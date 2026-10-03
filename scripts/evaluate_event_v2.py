"""Fixed-budget mixed-background/temporal experiment, no serving promotion.

Generate ONLY train/validation before fitting. Freeze all models, thresholds
and review policies before generating five entirely new test cohorts.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from generate_event_dataset import canonical, digest
from evaluate_event_baselines import dump
from evaluate_event_gate import identities as prior_identities
from verify_event_dataset import read_predictors
from event_v2_data import TRAIN, VALIDATION, TEST, ROLE_CONFIG, create_role, load_role, verify_role
from ml.event_simulation import FEATURES
from ml.event_temporal import VERSION, TEMPORAL_FEATURES, make_temporal_pipeline, temporal_probabilities
from ml.event_baselines import (TARGETS, choose_thresholds, family_bootstrap, make_pipeline, metrics, probabilities, shuffle_family_sets)
from ml.event_gate import assess, fingerprint, screening_metrics, select_policy, train_envelope

PROBES = ("mixed_aggregate", "mixed_temporal", "shuffled_temporal", "frozen_v1")


def score_probe(name, model, base, temporal):
    return temporal_probabilities(model, temporal) if "temporal" in name else probabilities(model, base)


def scored(base, truth, labels, indices, scores, thresholds, review_policy):
    result = {"raw": metrics(truth, scores, thresholds, labels)}
    decisions = assess(base, scores, review_policy)
    result["screened"] = screening_metrics(truth, decisions, labels)
    families = {}
    for i, (label, index) in enumerate(zip(labels, indices)):
        if label["observationally_ambiguous"]: families.setdefault(index["family_id"], []).append(i)
    if any(len(rows) != 2 or not np.array_equal(scores[rows[0]], scores[rows[1]]) for rows in families.values()):
        raise ValueError("v2 violates observational twins")
    result["twin_pairs_identical_predictions"] = len(families)
    # Retain subset precision AND all-event multi recall, never just correct top1.
    power, fuel = TARGETS.index("power_outage"), TARGETS.index("generator_fuel_stockout")
    raw_sets = np.asarray([[scores[i,j] >= thresholds[j] for j in range(len(TARGETS))] for i in range(len(scores))])
    power_only = (truth[:,power] == 1) & (truth[:,fuel] == 0)
    fuel_only = (truth[:,fuel] == 1) & (truth[:,power] == 0)
    result["power_fuel_cross_claims"] = {
        "power_without_fuel_events": int(power_only.sum()), "fuel_claims_on_power_without_fuel": int(raw_sets[power_only,fuel].sum()),
        "fuel_without_power_events": int(fuel_only.sum()), "power_claims_on_fuel_without_power": int(raw_sets[fuel_only,power].sum()),
        "joint_truth_events": int(((truth[:,power] == 1) & (truth[:,fuel] == 1)).sum()),
        "scope": "injected-label conditional cross-claims, NOT causal or mutually exclusive class proof"}
    return result, decisions


def select_candidate(validation_reports, policies):
    eligible = ["mixed_aggregate", "mixed_temporal"]
    def key(name):
        groups = [validation_reports[role][name] for role in VALIDATION]
        enabled = policies[name]["enabled"]
        coverage = sum(g["screened"]["screen_passed"] for g in groups) if enabled else 0
        robust_f1 = float(np.mean([g["raw"]["macro_f1_11"] for g in groups]))
        return (-int(enabled), -coverage, -robust_f1, name)
    return sorted(eligible, key=key)[0]


def run(output, baseline, *, train_per_profile=3000, validation_per_profile=600, test_per_role=600, seed=20261014, bootstrap=300, prior_datasets=()):
    if output.exists() or output.resolve().is_relative_to(baseline.resolve()): raise ValueError("fresh separate v2 experiment required")
    if type(seed) is not int or not 0 <= seed < 2**32 or bootstrap < 1: raise ValueError("valid seed/bootstrap required")
    for count in [train_per_profile, validation_per_profile, test_per_role]:
        if type(count) is not int or not 20 <= count <= 20000: raise ValueError("20..20000 per-role budget required")
    selection = json.loads((baseline / "selection-frozen.json").read_text())
    base_protocol = json.loads((baseline / "protocol.json").read_text())
    base_model_path = baseline / "selected-experimental-model.joblib"
    if (digest(base_model_path) != selection["model_sha256"] or digest(baseline / "protocol.json") != selection["protocol_sha256"]
            or selection["selected"] != "full_hgb" or base_protocol["target_order"] != list(TARGETS)
            or base_protocol["features_by_view"]["full"] != list(FEATURES)):
        raise ValueError("original frozen full HGB contract required")
    import sklearn
    if base_protocol["versions"]["scikit-learn"] != sklearn.__version__: raise ValueError("compatible frozen model runtime required")
    source_paths = [Path(__file__), ROOT / "scripts/event_v2_data.py", ROOT / "src/ml/event_temporal.py",
        ROOT / "src/ml/event_simulation.py", ROOT / "scripts/generate_event_dataset.py", ROOT / "src/ml/event_baselines.py",
        ROOT / "src/ml/event_gate.py", ROOT / "src/temperature_monitoring.py", ROOT / "src/rule_engine/rules_config.json",
        ROOT / "scripts/evaluate_event_gate.py", ROOT / "scripts/verify_event_dataset.py"]
    prior_sets = [(path, prior_identities(path)) for path in prior_datasets]
    prior_hashes = {str(path):json.loads((path/"manifest.json").read_text())["file_sha256"] for path in prior_datasets}
    for path,files in prior_hashes.items():
        if any(digest(Path(path)/name)!=h for name,h in files.items()): raise ValueError("prior cohort integrity mismatch")
    protocol = {"schema": VERSION, "seed": seed, "features": list(TEMPORAL_FEATURES), "target_order": list(TARGETS),
        "train_profiles": {role: train_per_profile for role in TRAIN}, "validation_profiles": {role: validation_per_profile for role in VALIDATION},
        "test_roles": {role: test_per_role for role in TEST}, "base_role_schedules": ROLE_CONFIG,
        "backgrounds": {"nominal": {"ambient": [18,35], "noise": [.08,.35], "dropout": [.015,.08]},
            "stress": {"ambient": [40,48], "noise": [.6,1.2], "dropout": [.15,.30]},
            "extreme": {"ambient": [48,54], "noise": [1.2,1.6], "dropout": [.30,.40]}},
        "role_identity": "independent seed/virtual assets per ALL roles; validation/test nominal NOT same-device IID",
        "training_mixture": "50% nominal + 50% stress, engineered coverage NOT real-business prevalence",
        "physics_labels_unchanged": True, "all_label_kinds_retained": True, "no_serving_or_review_gate_changes": True,
        "probes": {"mixed_aggregate": "33 observations, mixed TRAIN", "mixed_temporal": "111 observations, same mixed TRAIN",
                   "shuffled_temporal": "same 111 inputs, TRAIN-family sets shuffled within product/family-size", "frozen_v1": "original frozen 33-feature HGB, no refit"},
        "fixed_fit": {"max_iter":100,"max_leaf_nodes":15,"learning_rate":.1,"l2_regularization":1,"early_stopping":False,"seed":42},
        "thresholds": "per-label pooled validation F1, existing fixed grid; no test threshold tuning",
        "review_policy_selection": "UNCHANGED v1 policy grid and evidence guard, >=30 supported, >=90% exact precision and <=5% normal supported false alarms on pooled validation",
        "candidate_selection": "validation-qualified policy first; max supported coverage, then equal-profile mean macro-F1, name tie break; only mixed aggregate/temporal eligible",
        "test_generation": "AFTER freezing model/threshold/policy artifacts; five independent roles, no generator retuning",
        "baseline_model_sha256": selection["model_sha256"], "baseline_selection_sha256": digest(baseline / "selection-frozen.json"),
        "prior_dataset_manifests": {str(path):digest(path/"manifest.json") for path in prior_datasets},
        "prior_file_sha256": prior_hashes,
        "versions": {"sklearn":sklearn.__version__,"numpy":np.__version__,"pandas":pd.__version__}, "bootstrap":bootstrap,
        "source_sha256": {str(p.relative_to(ROOT)):digest(p) for p in source_paths},
        "limitations": ["same uncalibrated simulator, not real-world validation; unknown types seen in training",
            "independent label-occurrence predictors, not clinical safety or unique causal attribution",
            "observationally masked secondary faults kept; no promised identifiability or automatic action",
            "pooled validation qualification can mask subgroup weakness; report every profile separately",
            "one training seed, fixed small budget; conditional family bootstrap excludes training/selection uncertainty",
            "v2 artifact incompatible with deployed 33-field event runtime; experimental only"]}
    output.mkdir(parents=True)
    dump(output / "protocol.json", protocol)
    data = output / "data"; summaries, audits, identity_sets = {}, {}, {}
    def build(role, count):
        summaries[role] = create_role(data, role, count, seed)
        audits[role], identity_sets[role] = verify_role(data, role, summaries[role])
        for prior, sets in identity_sets.items():
            if prior != role and any(a & b for a,b in zip(identity_sets[role], sets)):
                raise ValueError("v2 cross-role family/asset/exact-profile overlap; no resampling")
        base_profiles = {fingerprint(row) for row in read_predictors(data/role)}
        for path,sets in prior_sets:
            if any(a & b for a,b in zip((identity_sets[role][0],identity_sets[role][1],base_profiles),sets)):
                raise ValueError("v2 overlaps a previously inspected cohort; no resampling")
    for role in TRAIN: build(role, train_per_profile)
    for role in VALIDATION: build(role, validation_per_profile)
    train_parts = [load_role(data, role) for role in TRAIN]
    val_parts = {role:load_role(data,role) for role in VALIDATION}
    train_base = pd.concat([p[0] for p in train_parts], ignore_index=True)
    train_temporal = pd.concat([p[1] for p in train_parts], ignore_index=True)
    train_truth = np.concatenate([p[2] for p in train_parts])
    train_indices = [{**index,"product_id":part[0].iloc[i].product_id} for part in train_parts for i,index in enumerate(part[4])]
    val_base = pd.concat([p[0] for p in val_parts.values()], ignore_index=True)
    val_truth = np.concatenate([p[2] for p in val_parts.values()]); val_labels = sum([p[3] for p in val_parts.values()], [])
    envelope = train_envelope(train_base)
    models = {"mixed_aggregate":make_pipeline("full","hgb"), "mixed_temporal":make_temporal_pipeline(),
              "shuffled_temporal":make_temporal_pipeline(), "frozen_v1":joblib.load(base_model_path)}
    thresholds, policies, searches, validation, training = {}, {}, {}, {r:{} for r in VALIDATION}, {}
    with threadpool_limits(limits=1):
        for name, model in models.items():
            print("v2 fitting " + name, flush=True)
            if name != "frozen_v1":
                y = shuffle_family_sets(train_truth, train_indices) if name == "shuffled_temporal" else train_truth
                model.fit(train_temporal if "temporal" in name else train_base, y)
            val_scores = np.concatenate([score_probe(name,model,p[0],p[1]) for p in val_parts.values()])
            threshold = selection["thresholds"][selection["selected"]] if name == "frozen_v1" else choose_thresholds(val_truth,val_scores).tolist()
            policies[name], searches[name] = select_policy(val_base,val_scores,val_truth,val_labels,envelope,threshold)
            thresholds[name] = threshold
            for role,part in val_parts.items():
                validation[role][name],_ = scored(part[0],part[2],part[3],part[4],score_probe(name,model,part[0],part[1]),threshold,policies[name])
            train_scores = score_probe(name,model,train_base,train_temporal)
            training[name] = metrics(train_truth,train_scores,threshold,sum([p[3] for p in train_parts],[]))
        selected = select_candidate(validation,policies)
        model_files = {}
        for name,model in models.items():
            path = output / (name + ".joblib"); joblib.dump(model,path); model_files[name] = digest(path)
        frozen = {"schema":VERSION,"selected":selected,"validation":validation,"policies":policies,"policy_searches":searches,
                  "thresholds":thresholds,"model_sha256":model_files,"protocol_sha256":digest(output/"protocol.json"),"promotion":False}
        dump(output / "selection-frozen.json",frozen); frozen_sha = digest(output / "selection-frozen.json")
        print("v2 selection frozen; now generating NEW tests",flush=True)
        test = {}
        for role in TEST:
            build(role,test_per_role)
            base,temporal,truth,labels,indices = load_role(data,role)
            test[role] = {}
            for name,model in models.items():
                scores = score_probe(name,model,base,temporal)
                test[role][name],decisions = scored(base,truth,labels,indices,scores,thresholds[name],policies[name])
                if name == selected:
                    test[role][name]["family_bootstrap"] = family_bootstrap(truth,scores,thresholds[name],
                        [i["family_id"] for i in indices],repetitions=bootstrap)
                with (output/(role+"-"+name+".jsonl")).open("x",encoding="utf-8") as stream:
                    for index,label,result in zip(indices,labels,decisions):
                        stream.write(canonical({"event_id":index["event_id"],"family_id":index["family_id"],"truth":label["injected_causes"],
                                               "observationally_ambiguous":label["observationally_ambiguous"],**result})+"\n")
        if digest(output/"selection-frozen.json") != frozen_sha or any(digest(ROOT/p)!=h for p,h in protocol["source_sha256"].items()):
            raise ValueError("v2 source/selection changed while scoring")
        for name,h in model_files.items():
            if digest(output/(name+".joblib"))!=h: raise ValueError("v2 frozen model changed")
        for role,summary in summaries.items():
            if any(digest(data/role/name)!=h for name,h in summary["file_sha256"].items()): raise ValueError("v2 dataset changed")
        if any(digest(Path(path)/"manifest.json")!=h for path,h in protocol["prior_dataset_manifests"].items()):
            raise ValueError("prior dataset manifest changed")
        if any(digest(Path(path)/name)!=h for path,files in prior_hashes.items() for name,h in files.items()):
            raise ValueError("prior cohort file changed")
        if digest(base_model_path)!=protocol["baseline_model_sha256"] or digest(baseline/"selection-frozen.json")!=protocol["baseline_selection_sha256"]:
            raise ValueError("original baseline changed")
        dump(data/"manifest.json",{"schema":VERSION,"status":"complete","roles":summaries,"audits":audits,
            "all_role_family_asset_profile_overlaps":0,"prior_cohort_overlaps":0 if prior_sets else "not_checked",
            "seed":seed,"features":list(TEMPORAL_FEATURES),"physics_source_sha256":protocol["source_sha256"]})
        report = {"status":"complete","schema":VERSION,"selected":selected,"selection_sha256":frozen_sha,"protocol":protocol,
            "dataset_manifest_sha256":digest(data/"manifest.json"),"training":training,"validation":validation,"test":test,
            "promotion":False,"all_events_human_review_required":True,"serving_contract_unchanged":True}
        dump(output/"report.json",report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--seed",type=int,default=20261014)
    parser.add_argument("--train-per-profile",type=int,default=3000)
    parser.add_argument("--validation-per-profile",type=int,default=600)
    parser.add_argument("--test-per-role",type=int,default=600)
    parser.add_argument("--bootstrap",type=int,default=300)
    parser.add_argument("--prior-dataset",type=Path,action="append",default=[])
    args = parser.parse_args()
    report = run(args.output,args.baseline,seed=args.seed,train_per_profile=args.train_per_profile,
                 validation_per_profile=args.validation_per_profile,test_per_role=args.test_per_role,bootstrap=args.bootstrap,prior_datasets=args.prior_dataset)
    print(json.dumps({"status":report["status"],"selected":report["selected"],"test_macro_f1":{r:p[report["selected"]]["raw"]["macro_f1_11"] for r,p in report["test"].items()}}))


if __name__ == "__main__": main()
