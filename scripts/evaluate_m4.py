"""Formal, nested M4 experiments with no writes to deployment or case storage.

All fitting, model/calibration selection and thresholds stay inside outer-train.
Use a FRESH output directory. The default is a five-fold full-data experiment,
not a deployment promotion or clinical-validation procedure.
"""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data/processed/.mpl-cache"))
os.environ.setdefault("MPLBACKEND", "Agg")
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

import train_m4_models as training
from ml.contracts import FEATURES, CAUSE_CATEGORICAL, normalize_features
from ml.formal import Dataset, CAUSE_CONTEXT, outer_splits, inner_splits, evaluate_fold, summarize, reliability


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(task):
    df, ids, target, files = training.data_frame(task)
    x = df[FEATURES[task]].copy()
    if task == "cause":
        for key in CAUSE_CATEGORICAL: x[key] = x[key].astype(str)
    groups = (df.facility_level.astype(str) + ":" + df.facility_id.astype(str)).to_numpy() if task == "cause" else None
    months = (df.year * 12 + df.month).to_numpy() if task == "cause" else None
    data = Dataset(task, x.reset_index(drop=True), df[target].to_numpy(), ids, groups, months)
    validity = contract_validity(data)
    xhash = pd.util.hash_pandas_object(x, index=False)
    audit = {"rows": len(df), "target": target, "classes": {str(c): int(n) for c, n in pd.Series(data.y).value_counts().items()},
        "features": FEATURES[task], "missing": {k: int(v) for k, v in x.isna().sum().items()},
        "duplicate_predictor_rows": int(x.duplicated().sum()),
        "contract_valid_rows": int(validity.sum()), "contract_invalid_rows": int((~validity).sum()),
        "offline_imputation_is_not_online_missing_input_acceptance": True,
        "predictor_profiles_with_multiple_target_labels": int(pd.DataFrame({"profile": xhash.to_numpy(), "target": data.y}).groupby("profile").target.nunique().gt(1).sum()),
        "source_hashes": {str(p.relative_to(ROOT)): digest(p) for p in files},
        "synthetic_scope": "risk suspected synthetic; cause declared synthetic; not operational effectiveness"}
    if task == "risk":
        audit.update(time_split="unavailable_no_timestamp", facility_split="unavailable_no_facility_identity",
                     feature_timing="whole-shipment summaries; retrospective classification, not future 30/60-minute warning")
    else:
        audit.update(facility_groups=int(len(np.unique(groups))), calendar_months=int(len(np.unique(months))),
            calendar_range=[int(months.min()), int(months.max())],
            duplicate_facility_month_vaccine_rows=int(df.duplicated(["facility_level", "facility_id", "year", "month", "vaccine_name"]).sum()),
            facility_groups_with_multiple_equipment_types=int(df.assign(group=groups).groupby("group").equipment_type.nunique().gt(1).sum()),
            grouping_scope="namespaced provided IDs; synthetic identity stress test, not verified real-facility generalization",
            feature_timing="monthly contexts lack incident timestamp; no proof all features precede an event",
            cohort="heat/freeze flag present and non-not_applicable cause; post-excursion monthly cohort")
    return data, audit


def contract_validity(data):
    valid = []
    for _, row in data.x.iterrows():
        values = {k: v.item() if isinstance(v,np.generic) else v for k,v in row.to_dict().items()}
        try:
            normalize_features(data.task, values); valid.append(True)
        except ValueError:
            valid.append(False)
    return np.asarray(valid, dtype=bool)


def collect_failures(data, pooled, directory):
    indices, y, p, pred = [pooled[k] for k in ["indices", "y", "calibrated", "predicted"]]
    classes = np.unique(data.y)
    rows = pd.DataFrame({"sample_id": np.asarray(data.ids)[indices], "actual": classes[y], "predicted": classes[pred],
                         "confidence": p.max(axis=1), "correct": pred == y})
    if data.task == "risk":
        rows["error_kind"] = np.select([(y==1)&(pred==0), (y==0)&(pred==1)], ["false_negative", "false_positive"], default="correct")
        rows["failure_probability"] = p[:, 1]
        rows["missing_any_feature"] = data.x.iloc[indices].isna().any(axis=1).to_numpy()
        rows["transit_band"] = pd.cut(data.x.iloc[indices].transit_days, [0,1,3,7,np.inf], include_lowest=True).astype(str).to_numpy()
        rows["sensor_gap_band"] = pd.cut(data.x.iloc[indices].sensor_gap_hours, [-np.inf,0,6,np.inf]).astype(str).to_numpy()
        group_keys = ["error_kind", "transit_band", "sensor_gap_band", "missing_any_feature"]
    else:
        rows["facility_level"] = data.x.iloc[indices].facility_level.to_numpy()
        rows["equipment_type"] = data.x.iloc[indices].equipment_type.to_numpy()
        rows["true_class_in_top3"] = [a in b for a, b in zip(y, np.argsort(-p, axis=1)[:, :3])]
        group_keys = ["actual", "facility_level", "equipment_type"]
    rows.to_csv(directory / "predictions-and-failures.csv", index=False)
    grouped = {}
    for key in group_keys:
        grouped[key] = [{"group": str(g), "n": len(part), "errors": int((~part.correct).sum()), "error_rate": float((~part.correct).mean())}
                        for g, part in rows.groupby(key, observed=True)]
    wrong = np.flatnonzero(pred != y)
    ranked = wrong[np.argsort(-p[wrong].max(axis=1))][:12]
    examples = []
    for i in ranked:
        example = {**rows.iloc[int(i)].to_dict(), "features": data.x.iloc[int(indices[i])].where(pd.notna(data.x.iloc[int(indices[i])]), None).to_dict(),
                   "top3": [{"label": str(classes[k]), "probability": float(p[i, k])} for k in np.argsort(-p[i])[:3]]}
        # NaN is represented as null in diagnostic JSON, never silently filled.
        example["features"] = {k: None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for k,v in example["features"].items()}
        example = {k: v.item() if isinstance(v, np.generic) else v for k,v in example.items()}
        examples.append(example)
    pairs = rows.loc[~rows.correct].groupby(["actual", "predicted"]).size().sort_values(ascending=False).head(12)
    result = {"error_count": int((~rows.correct).sum()), "test_count": len(rows), "groups": grouped,
              "top_confusions": [{"actual": str(a), "predicted": str(b), "count": int(n)} for (a,b),n in pairs.items()],
              "high_confidence_wrong_examples": examples,
              "scope": "post-score held-out diagnostics; examples never select model, threshold or calibration"}
    dump(directory / "failure-analysis.json", result)
    return result


def run_protocol(data, mode, output, estimators, folds=5, seed=42):
    output.mkdir()
    reports, predictions, partitions = [], [], []
    representative = None
    for n, (outer_train, test) in enumerate(outer_splits(data, mode, folds, seed), 1):
        fit, calibration, selection = inner_splits(data, outer_train, mode, seed+n)
        parts = (fit, calibration, selection, test)
        record, predictor, predicted = evaluate_fold(data, parts, estimators, mode)
        record["fold"] = n; reports.append(record); predictions.append(predicted)
        record["inner_seed"] = seed+n
        for role, part in zip(["fit", "calibration", "selection", "test"], parts):
            for i in part:
                partitions.append({"fold": n, "role": role, "row": int(i), "sample_id": data.ids[i],
                    "group": str(data.groups[i]) if data.groups is not None else None,
                    "month": int(data.months[i]) if data.months is not None else None})
        if n == 1:
            representative = (predictor, parts)
            joblib.dump(predictor, output / "representative-fold-1.joblib")
        print(data.task, mode, n, record["algorithm"], record["calibration"], record["calibrated_metrics"], flush=True)
    pd.DataFrame(partitions).to_csv(output / "partitions.csv", index=False)
    pooled = {key: np.concatenate([p[key] for p in predictions]) for key in predictions[0]}
    if len(set(pooled["indices"])) != len(pooled["indices"]): raise ValueError("outer test rows scored more than once")
    np.savez_compressed(output / "out-of-fold.npz", **pooled)
    failures = collect_failures(data, pooled, output)
    from sklearn.metrics import classification_report, confusion_matrix
    classes = np.unique(data.y)
    result = {"task": data.task, "mode": mode, "features": list(data.x.columns), "folds": reports,
              "fold_summary": summarize(reports), "test_rows": len(pooled["indices"]), "dataset_rows": len(data.y),
              "test_coverage": len(pooled["indices"])/len(data.y), "seed": seed,
              "fold_sd_not_confidence_interval": True, "selection_never_uses_outer_test": True,
              "classification_report_pooled": classification_report(pooled["y"], pooled["predicted"], labels=np.arange(len(classes)), target_names=[str(c) for c in classes], output_dict=True, zero_division=0),
              "confusion_pooled": confusion_matrix(pooled["y"], pooled["predicted"], labels=np.arange(len(classes))).tolist(),
              "failure_analysis": failures}
    result["algorithm_comparison"] = {name: {k: {"mean": float(np.mean([f["candidate_test_metrics"][name][k] for f in reports])),
                                                   "std": float(np.std([f["candidate_test_metrics"][name][k] for f in reports], ddof=1))}
                                      for k in reports[0]["candidate_test_metrics"][name]} for name,_ in estimators}
    result["calibration_comparison"] = {name: {k: {"mean": float(np.mean([f["calibration_test_metrics"][name][k] for f in reports])),
                                                     "std": float(np.std([f["calibration_test_metrics"][name][k] for f in reports], ddof=1))}
                                        for k in reports[0]["calibration_test_metrics"][name]} for name in reports[0]["calibration_test_metrics"]}
    dump(output / "report.json", result)
    plot_protocol(data, result, pooled, output)
    return result, representative


def plot_protocol(data, report, pooled, output):
    import matplotlib.pyplot as plt
    y = pooled["y"]
    fig, ax = plt.subplots(figsize=(6,5))
    for name in ["raw", "calibrated"]:
        p = pooled[name]
        curve = reliability(y, p[:, 1]) if data.task == "risk" else reliability((p.argmax(axis=1)==y).astype(int), p.max(axis=1))
        bins = curve["bins"]
        ax.plot([r["mean_probability"] for r in bins], [r["observed_frequency"] for r in bins], 'o-', label=name)
    ax.plot([0,1],[0,1],'--',color='grey'); ax.legend(); ax.set(xlabel='Mean probability', ylabel='Observed frequency', title=f'{data.task}: {report["mode"]} held-out reliability')
    fig.tight_layout(); fig.savefig(output / "reliability.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9,7))
    matrix = np.asarray(report["confusion_pooled"]); normalized = matrix / matrix.sum(axis=1, keepdims=True)
    ax.imshow(normalized, vmin=0,vmax=1,cmap='Blues')
    classes = [str(c) for c in np.unique(data.y)]
    ax.set_xticks(range(len(classes)), classes, rotation=70,ha='right'); ax.set_yticks(range(len(classes)), classes)
    for i in range(len(classes)):
        for j in range(len(classes)): ax.text(j,i,str(matrix[i,j]),ha='center',va='center',fontsize=7)
    ax.set(xlabel='Predicted',ylabel='Actual',title=f'{data.task}: {report["mode"]} OOF confusion (counts)')
    fig.tight_layout(); fig.savefig(output / "confusion.png",dpi=150); plt.close(fig)


def shap_explanation(model, data, fit, test, output, identity, rows=12, background=12, nsamples=128, seed=42):
    import shap
    import matplotlib.pyplot as plt
    output.mkdir()
    rng = np.random.RandomState(seed)
    complete = contract_validity(data)
    fit, test = np.asarray(fit)[complete[fit]], np.asarray(test)[complete[test]]
    if not len(fit) or not len(test): raise ValueError("no complete train-background / held-out SHAP samples")
    bg = rng.choice(fit, min(background,len(fit)), replace=False)
    explained = rng.choice(test, min(rows,len(test)), replace=False)
    columns = list(data.x.columns)
    def predict(values):
        x = pd.DataFrame(values, columns=columns)
        for c in columns:
            if data.task == "cause" and c in CAUSE_CATEGORICAL: x[c] = x[c].astype(str)
            else: x[c] = pd.to_numeric(x[c])
        return model.predict_proba(x)
    # Offline marginal probability-space SHAP; hybrid feature combinations may
    # violate real sensor/context dependencies. Not a causal intervention.
    explainer = shap.KernelExplainer(predict, data.x.iloc[bg].to_numpy(), link="identity", feature_names=columns)
    state = np.random.get_state()
    try:
        np.random.seed(seed)
        values = np.asarray(explainer.shap_values(data.x.iloc[explained].to_numpy(), nsamples=nsamples, l1_reg=0, silent=True))
    finally: np.random.set_state(state)
    probabilities = predict(data.x.iloc[explained].to_numpy())
    expected = np.asarray(explainer.expected_value)
    if values.shape != (len(explained),len(columns),len(model.classes_)): raise ValueError("unexpected SHAP class/feature axes")
    residual = float(np.max(np.abs(expected + values.sum(axis=1) - probabilities)))
    if residual > 1e-6 or not np.isfinite(values).all(): raise ValueError("SHAP local additivity check failed")
    effects = np.mean(np.abs(values[:,:,1]),axis=0) if data.task == "risk" else np.mean(np.abs(values),axis=(0,2))
    order = np.argsort(effects)
    fig, ax = plt.subplots(figsize=(8,5)); ax.barh(np.asarray(columns)[order],effects[order]); ax.set_xlabel('Mean |SHAP| (probability units)')
    ax.set_title(f'{data.task}: {identity["scope"]}, {len(explained)} held-out rows')
    fig.tight_layout(); fig.savefig(output / "shap.png",dpi=150); plt.close(fig)
    np.savez_compressed(output / "values.npz",values=values,expected=expected,probabilities=probabilities,explained_indices=explained,background_indices=bg)
    result = {**identity, "method": "KernelSHAP_marginal_approximation", "link": "identity_probability_units", "features": columns,
        "classes": [str(c) for c in model.classes_], "background_sample_ids": [data.ids[i] for i in bg],
        "held_out_sample_ids": [data.ids[i] for i in explained], "seed": seed, "nsamples": nsamples,
        "local_additivity_max_residual": residual, "shap_version": shap.__version__,
        "feature_effects": dict(zip(columns,effects.tolist())), "not_global_importance_or_causality": True,
        "hybrid_background_inputs_not_guaranteed_physically_valid": True,
        "online_reference_replacement_unchanged_not_SHAP": True}
    dump(output / "explanation.json",result)
    return result


def deployment_shap(data, output, args):
    from ml.runtime import load_model
    model, meta = load_model(data.task)
    fit, test = training.train_test_split(np.arange(len(data.y)),stratify=data.y,test_size=.15,random_state=42)
    fit, validation = training.train_test_split(fit,stratify=data.y[fit],test_size=.1765,random_state=42)
    reconstructed = hashlib.sha256(json.dumps([fit.tolist(),validation.tolist(),test.tolist()]).encode()).hexdigest()
    if reconstructed != meta["split"]["sha256"] or meta["source_hashes"] != load(data.task)[1]["source_hashes"]:
        raise ValueError("cannot establish deployed model's original held-out/background partitions")
    return shap_explanation(model,data,fit,test,output,
        {"scope":"current_deployed_uncalibrated_model", "model_id":meta["model_id"], "model_sha256":meta["model_sha256"],
         "original_partition_sha256":reconstructed},args.shap_rows,args.shap_background,args.shap_samples)


def feature_manifest():
    # Labels, discard/wastage quantities and post-excursion findings are never
    # fitted. Cohort flags filter the descriptive cause task, not its features.
    return {
        "risk": {key: {"role":"transport_summary", "availability":"whole-trip retrospective summary; no prediction timestamp"} for key in FEATURES['risk']},
        "cause": {key: {"context7":key in CAUSE_CONTEXT,
                         "availability":"plausibly prior context if recorded before event; not established by monthly row" if key in CAUSE_CONTEXT else
                         "monthly/function/power/monitoring/calendar context; not established as pre-incident"} for key in FEATURES['cause']},
        "forbidden_risk":['shipment_id','silent_failure','feature_x1','feature_x2','feature_x3','product_volume_l','fill_ratio','carrier_id','origin_zone','dest_zone'],
        "forbidden_cause":['facility_id','id','excursion_cause','heat_excursion_detected','freeze_excursion_detected','temp_in_range_pct','min_temp_recorded_C',
            'max_temp_recorded_C','vvm_stage','shake_test_done','vaccines_discarded_freeze','wastage_rate_pct','doses_wasted_last_quarter','wastage_cause_primary'],
        "facility_id_grouping_only_not_a_model_feature":True,
        "year_month_features_present_only_in_full15":True,
        "identifiers_not_shared_business_order_ids":True,
    }


def markdown(report):
    lines = ['# M4 formal experiments', '', f'Generated UTC: {report["generated_at"]}',
             '', 'No deployment promotion. All data is suspected/declared synthetic. No potency, scrap or prospective warning claim.',
             '', '## Selected models: outer-fold mean ± SD', '', '| protocol | n test | F1/macro-F1 | AUC/top-1 | PR-AUC/top-3 | Brier raw → selected | log loss raw → selected |', '|---|---:|---:|---:|---:|---:|---:|']
    def cell(section,key): return f'{section[key]["mean"]:.4f} ± {section[key]["std"]:.4f}'
    for key, r in report['protocols'].items():
        s=r['fold_summary']; c=s['calibrated_metrics']; raw=s['raw_metrics']; risk=r['task']=='risk'
        lines.append(f'| {key} | {r["test_rows"]} | {cell(c,"f1" if risk else "macro_f1")} | {cell(c,"auc" if risk else "top1")} | {cell(c,"prauc" if risk else "top3")} | {raw["brier"]["mean"]:.4f} → {c["brier"]["mean"]:.4f} | {raw["log_loss"]["mean"]:.4f} → {c["log_loss"]["mean"]:.4f} |')
    lines += ['', 'Time-forward protocols exclude the first warm-up months. Different evaluation populations are not interchangeable.',
              'SD is variation across folds, not a confidence interval. Lower Brier/log loss is not proof of better calibration alone.',
              '', '## Dataset audit', '', '```json', json.dumps(report['data_audit'],ensure_ascii=False,indent=2), '```',
              '', '## Reproducibility / model boundaries', '', '```json', json.dumps(report['config'],ensure_ascii=False,indent=2), '```',
              '', 'Current deployment artifacts and online inference remain unchanged. New calibrators are offline experiment candidates.',
              'SHAP folders distinguish deployed artifacts from independent representative fold-1 models; original train/test partitions and hashes are verified.',
              'Kernel SHAP uses marginal hybrid inputs and a small deterministic sample, not global feature importance, actual causal diagnosis or clinical validation.',
              'Baseline means empirical training priors / majority prediction. Cause context7 excludes dynamic monthly monitoring/power/function fields; it is not proven event-time feature availability.']
    lines += ['', '## Fixed algorithm comparison (raw, outer-fold mean ± SD)', '',
              '| protocol | algorithm | F1/macro-F1 | PR-AUC/top-3 | Brier |', '|---|---|---:|---:|---:|']
    for key,r in report['protocols'].items():
        for name,s in r['algorithm_comparison'].items():
            lines.append(f'| {key} | {name} | {cell(s,"f1" if r["task"]=="risk" else "macro_f1")} | {cell(s,"prauc" if r["task"]=="risk" else "top3")} | {cell(s,"brier")} |')
    lines += ['', '## Calibration comparison (fixed methods; selection never uses these test results)', '',
              '| protocol | method | Brier | log loss | ECE-10 |', '|---|---|---:|---:|---:|']
    for key,r in report['protocols'].items():
        for name,s in r['calibration_comparison'].items():
            lines.append(f'| {key} | {name} | {cell(s,"brier")} | {cell(s,"log_loss")} | {cell(s,"ece_10")} |')
    return '\n'.join(lines)+'\n'


def summary_tables(report, output):
    selected, candidates, calibration = [], [], []
    for protocol, result in report['protocols'].items():
        for kind, summary in result['fold_summary'].items():
            for metric, values in summary.items():
                selected.append({'protocol':protocol,'kind':kind,'metric':metric,**values})
        for name, summary in result['algorithm_comparison'].items():
            for metric, values in summary.items():
                candidates.append({'protocol':protocol,'algorithm':name,'metric':metric,**values})
        for name, summary in result['calibration_comparison'].items():
            for metric, values in summary.items():
                calibration.append({'protocol':protocol,'calibration':name,'metric':metric,**values})
    for name, rows in [('summary-metrics',selected),('algorithm-comparison',candidates),('calibration-comparison',calibration)]:
        pd.DataFrame(rows).to_csv(output/f'{name}.csv',index=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/processed/m4-formal')
    parser.add_argument('--folds',type=int,default=5)
    parser.add_argument('--shap-rows',type=int,default=12)
    parser.add_argument('--shap-background',type=int,default=12)
    parser.add_argument('--shap-samples',type=int,default=128)
    args=parser.parse_args()
    if args.output.exists(): parser.error('fresh output required; existing results cannot be overwritten')
    if args.folds<2 or min(args.shap_rows,args.shap_background)<1 or args.shap_samples<32: parser.error('invalid experiment size')
    args.output.mkdir(parents=True)
    versions={name:importlib.metadata.version(name) for name in ['scikit-learn','numpy','pandas','scipy','joblib','shap','matplotlib']}
    report={'schema':'m4-formal-experiment-v1','generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'config':{'folds':args.folds,'seed':42,'inner_roles':'fit60_calibration20_selection20; time roles strictly ordered',
                  'outer_test_never_selects_models_calibration_or_thresholds':True,'risk_time_split':'unavailable_no_timestamp',
                  'inner_seed_formula':'42 + outer_fold_number',
                  'versions':versions,'code_hashes':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/'src/ml/formal.py',ROOT/'src/ml/training.py',ROOT/'scripts/train_m4_models.py',ROOT/'src/ml/contracts.py']},
                  'shap_rows':args.shap_rows,'shap_background':args.shap_background,'shap_samples':args.shap_samples,
                  'calibration_selection':'risk minimum selection Brier; cause minimum selection log-loss; none included'},
        'data_audit':{},'feature_manifest':feature_manifest(),'protocols':{},'shap':{},'unavailable_models':{}}
    started=time.perf_counter()
    with threadpool_limits(limits=1):
        for task in ['risk','cause']:
            data,audit=load(task); report['data_audit'][task]=audit
            estimators,skipped=training.candidates(task); report['unavailable_models'][task]=skipped
            for mode in ['random'] if task=='risk' else ['random','facility','time']:
                for variant in ['full'] if task=='risk' else ['full','context7']:
                    subset=data if variant=='full' else Dataset(task,data.x[CAUSE_CONTEXT],data.y,data.ids,data.groups,data.months)
                    key=f'{task}-{variant}-{mode}'
                    result,representative=run_protocol(subset,mode,args.output/key,estimators,args.folds)
                    report['protocols'][key]=result
                    dump(args.output/'report.json',report)
                    if variant=='full' and mode=='random':
                        model,parts=representative
                        report['shap'][f'{task}-formal']=shap_explanation(model,subset,parts[0],parts[-1],args.output/f'{task}-formal-shap',
                            {'scope':'independent_formal_fold1_selected_calibration','model_sha256':digest(args.output/key/'representative-fold-1.joblib')},
                            args.shap_rows,args.shap_background,args.shap_samples)
            from ml.runtime import ModelUnavailable
            try:
                report['shap'][f'{task}-deployment']=deployment_shap(data,args.output/f'{task}-deployment-shap',args)
            except ModelUnavailable:
                report['shap'][f'{task}-deployment']={'status':'unavailable','reason':'trusted deployment artifacts absent; formal-fold SHAP remains independent'}
            dump(args.output/'report.json',report)  # retain completed protocols if a later one fails
    report['elapsed_seconds']=time.perf_counter()-started
    dump(args.output/'report.json',report)
    summary_tables(report,args.output)
    (args.output/'report.md').write_text(markdown(report),encoding='utf-8')
    print('Formal artifacts:',args.output,flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
