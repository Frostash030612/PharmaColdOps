"""Fresh cause-data learnability diagnostics, never update serving models/data.

Exploratory reuse of an already evaluated public synthetic cohort. Fixed probes
and budgets are written before fitting. Results guide research effort, not a
new independent medical-performance claim or automated deployment promotion.
"""
import argparse
import csv
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
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from evaluate_m4 import load
from train_m4_models import data_frame
from ml.formal import CAUSE_CONTEXT
from ml.learnability import (associations, baselines, diagnostic_splits, fixed_probes, fit_probe,
                            nested_subset, profile_audit, shuffle_within, subset_sha)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def summarize(rows):
    result = {}
    for mode in sorted({r["mode"] for r in rows}):
        result[mode] = {}
        for name in sorted({r["probe"] for r in rows}):
            full = [r for r in rows if r["mode"] == mode and r["probe"] == name and r["fraction"] == 1]
            if not full:
                continue
            result[mode][name] = {section: {metric: {"mean": float(np.mean([r[section][metric] for r in full])),
                                                      "sd": float(np.std([r[section][metric] for r in full], ddof=1)) if len(full) > 1 else None}
                                         for metric in ["top1", "macro_f1", "top3"]} for section in ["train", "validation"]}
            result[mode][name]["macro_f1_gap_mean"] = float(np.mean([r["train"]["macro_f1"] - r["validation"]["macro_f1"] for r in full]))
            result[mode][name]["paired_baseline_gains"] = {
                metric: float(np.mean([r["validation"][metric] - max(b[metric] for b in r["baselines"].values()) for r in full]))
                for metric in ["top1", "macro_f1", "top3"]}
    return result


def allocation_decision(summary, rows):
    # Budget heuristics declared in protocol, NOT clinical or statistical cutoffs.
    gains = {mode: max(values["paired_baseline_gains"]["macro_f1"] for values in probes.values())
             for mode, probes in summary.items()}
    capacity_gaps = [probes["extra_trees_capacity"]["macro_f1_gap_mean"] for probes in summary.values()]
    growth = {}
    for mode in summary:
        differences = []
        for name in ["hgb_fixed_budget"]:
            for repetition in sorted({r["repetition"] for r in rows}):
                matched = {r["fraction"]: r for r in rows if r["mode"] == mode and r["probe"] == name and r["repetition"] == repetition}
                if .25 in matched and 1 in matched:
                    differences.append(matched[1]["validation"]["macro_f1"] - matched[.25]["validation"]["macro_f1"])
        growth[mode] = float(np.mean(differences)) if differences else None
    weak_gain = all(v < .03 for v in gains.values())
    memorization = all(v > .30 for v in capacity_gaps)
    flat_growth = all(v is not None and v < .02 for v in growth.values())
    priority = "event_level_simulation_data_first" if weak_gain and memorization and flat_growth else "bounded_followup_before_large_tuning_or_new_data"
    return {"priority": priority, "best_exploratory_macro_f1_gain_by_mode": gains,
            "capacity_train_validation_gaps": capacity_gaps, "hgb_growth_25pct_to_full_by_mode": growth,
            "budget_heuristics": {"weak_gain_below": .03, "memorization_gap_above": .30, "flat_growth_below": .02},
            "conditions": {"weak_gain_all_modes": weak_gain, "memorization_all_modes": memorization, "flat_growth_all_modes": flat_growth},
            "scope": "research effort triage, not a Bayes ceiling, random-label proof, medical threshold or deployment selection"}


def semantic_cooccurrences(data):
    frame = data.x.copy()
    frame["label"] = data.y
    rows = []
    for target, field, value in [("power_outage", "power_outage_hours_last_month", 0),
                                 ("no_monitoring_device", "monitoring_device_present", "1"),
                                 ("equipment_breakdown", "equipment_functional", "1")]:
        selected = frame[frame.label == target]
        count = int((selected[field] == value).sum())
        rows.append({"target": target, "field": field, "value": value, "support": len(selected),
                     "cooccurrences": count, "fraction": count / len(selected)})
    return {"rows": rows, "scope": "descriptive cooccurrence only; monthly/last-month timing and measurement semantics unknown; NOT mislabel counts"}


def plot(output, rows, association):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, mode in zip(axes, ["random", "facility", "time"]):
        for name in fixed_probes():
            for section, style in [("train", "--"), ("validation", "-")]:
                group = [r for r in rows if r["mode"] == mode and r["probe"] == name]
                xs = sorted({r["fraction"] for r in group})
                ys = [np.mean([r[section]["macro_f1"] for r in group if r["fraction"] == f]) for f in xs]
                ax.plot(xs, ys, style, marker="o", label=name + ":" + section, linewidth=1)
        ax.set(title=mode, xlabel="Training pool fraction", ylabel="10-class macro-F1", ylim=(0, 1.03))
    axes[-1].legend(fontsize=6, loc="upper left", bbox_to_anchor=(1.02, 1))
    fig.suptitle("Exploratory cause learning curves; same cohort reused, not clinical validation")
    fig.tight_layout(); fig.savefig(output / "learning-curves.png", dpi=140); plt.close(fig)
    values = sorted(association["rows"], key=lambda r: r["mi_above_null_mean"])
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh([r["feature"] for r in values], [r["mi_above_null_mean"] for r in values])
    ax.set(xlabel="Marginal MI minus row-shuffle null mean (nats)", title="Descriptive signal; dependence/exchangeability not established")
    fig.tight_layout(); fig.savefig(output / "marginal-signal.png", dpi=140); plt.close(fig)


def run(output, *, repetitions=3, permutations=20, association_permutations=99):
    if output.exists():
        raise ValueError("fresh output directory required")
    if permutations < 1 or association_permutations < 1:
        raise ValueError("positive control counts required")
    data, audit = load("cause")
    splits = diagnostic_splits(data, repetitions)
    probes = fixed_probes()
    fractions = [.10, .25, .50, 1.0]
    files = [Path(__file__), ROOT / "src/ml/learnability.py", ROOT / "src/ml/training.py",
             ROOT / "scripts/evaluate_m4.py", ROOT / "scripts/train_m4_models.py", ROOT / "src/ml/contracts.py"]
    protocol = {"schema": "cause-learnability-audit-v1", "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "repetitions": repetitions, "fractions": fractions, "association_permutations": association_permutations,
                "model_permutations_per_scope_per_mode": permutations, "seed": 42,
                "probes": {name: {"parameters": estimator.get_params(), "balanced_weights": weighted} for name, (estimator, weighted) in probes.items()},
                "features": list(data.x.columns), "metric_class_order": np.unique(data.y).tolist(),
                "split_protocol": "random/group 25% diagnostic holdout; three distinct last-six-month rolling blocks; prior-only learning-curve subsampling",
                "negative_controls": "first repetition in each mode, balanced/natural HGB; global and within-facility-level TRAIN labels shuffled, validation labels fixed",
                "followup_rationale": "initial exploratory audit showed source-level priors and automatic-early-stopping confounding; followup adds source-conditional baselines and fixed-budget HGB, not a blind independent test",
                "baselines": ["empirical_prior", "stratified_random", "uniform_random", "facility_level_prior", "facility_level_balanced_prior", "facility_level_random_prior"],
                "omitted_context_candidates_descriptive_only": ["has_epi_officer", "cold_chain_staff_trained", "requires_reconstitution"],
                "budget_heuristics": {"weak_gain_below": .03, "memorization_gap_above": .30, "flat_growth_below": .02},
                "source_hashes": {str(p.relative_to(ROOT)): digest(p) for p in files}, "dataset_hashes": audit["source_hashes"],
                "versions": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "scikit-learn", "scipy"]},
                "no_model_or_gold_or_data_changes": True,
                "limitations": ["already inspected public synthetic data; NOT a new untouched independent test",
                                "random/group repetitions overlap; SD is not confidence interval; time blocks are different cohorts",
                                "fixed capacity probes not a hyperparameter search; no automatic promotion",
                                "negative controls exploratory; exchangeability/time dependence not established",
                                "new event simulation would need separate latent-mechanism data and unseen scenarios; not real-business validation"]}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "protocol.json", protocol)
    report = {"status": "running", "protocol": protocol, "dataset_audit": audit, "curves": [], "model_controls": []}
    dump(output / "report.json", report)
    report["profiles"] = {"full15": profile_audit(data.x, data.y), "context7": profile_audit(data.x[CAUSE_CONTEXT], data.y)}
    report["semantic_cooccurrences"] = semantic_cooccurrences(data)
    report["associations"] = associations(data.x, data.y, permutations=association_permutations, strata=data.x.facility_level)
    raw, raw_ids, target, _ = data_frame("cause")
    if raw_ids != data.ids or not np.array_equal(raw[target].to_numpy(), data.y):
        raise ValueError("omitted context rows do not align with source identities")
    extra = protocol["omitted_context_candidates_descriptive_only"]
    report["omitted_context_associations"] = associations(raw[extra].astype(str), data.y,
        permutations=association_permutations, strata=data.x.facility_level)
    report["omitted_context_associations"]["timing_scope"] = "not approved online inputs; no incident timestamp proves pre-event availability; association only, never fitted in probes"
    report["source_aliases"] = [key for key in data.x.columns if key != "facility_level" and data.x[key].nunique() > 1
                                and data.x.groupby("facility_level")[key].nunique().max() == 1]
    classes = np.unique(data.y)
    with (output / "split-identities.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["mode", "repetition", "role", "sample_id", "index", "facility_group", "month_index"])
        writer.writeheader()
        for mode, repetition, train, validation in splits:
            for role, indices in [("train_pool", train), ("diagnostic_validation", validation)]:
                writer.writerows({"mode": mode, "repetition": repetition, "role": role, "sample_id": data.ids[i], "index": int(i),
                                 "facility_group": data.groups[i], "month_index": int(data.months[i])} for i in indices)
    with threadpool_limits(limits=1):
        for mode, repetition, pool, validation in splits:
            for fraction in fractions:
                train = nested_subset(data, pool, fraction, 100 + repetition, mode)
                reference = baselines(data.y[train], data.y[validation], classes, 200 + repetition,
                                      data.x.facility_level.iloc[train].to_numpy(), data.x.facility_level.iloc[validation].to_numpy())
                for name, (estimator, weighted) in probes.items():
                    start = time.monotonic()
                    scores = fit_probe(data, train, validation, estimator, weighted)
                    row = {"mode": mode, "repetition": repetition, "fraction": fraction, "probe": name,
                           "train_n": len(train), "validation_n": len(validation), "training_indices_sha256": subset_sha(train),
                           "validation_indices_sha256": subset_sha(validation), "training_sample_ids": np.asarray(data.ids)[train].tolist(),
                           "baselines": reference, **scores, "fit_and_score_seconds": time.monotonic() - start}
                    report["curves"].append(row); dump(output / "report.json", report)
                    print(f"curve {mode}/{repetition} {fraction} {name} train={scores['train']['macro_f1']:.4f} val={scores['validation']['macro_f1']:.4f}", flush=True)
        for mode, repetition, train, validation in splits:
            if repetition != 0:
                continue
            for name in ["hgb_balanced", "hgb_natural"]:
                estimator, weighted = probes[name]
                real = next(r["validation"] for r in report["curves"] if r["mode"] == mode and r["repetition"] == 0 and r["fraction"] == 1 and r["probe"] == name)
                for scope in ["global", "within_facility_level"]:
                    null = []
                    for number in range(permutations):
                        seed = 1000 + number
                        labels = np.random.default_rng(seed).permutation(data.y[train]) if scope == "global" else shuffle_within(data.y[train], data.x.facility_level.iloc[train], seed)
                        scores = fit_probe(data, train, validation, estimator, weighted, labels)
                        null.append(scores["validation"])
                    record = {"mode": mode, "probe": name, "scope": scope, "real": real, "repetitions": permutations,
                              "null_scores": null, "comparison": {key: {"null_mean": float(np.mean([r[key] for r in null])),
                                   "null_p95": float(np.quantile([r[key] for r in null], .95)),
                                   "observed_minus_null_mean": real[key] - float(np.mean([r[key] for r in null])),
                                   "exploratory_tail_fraction": float((1 + sum(r[key] >= real[key] for r in null)) / (len(null) + 1))}
                                   for key in ["top1", "macro_f1", "top3"]}}
                    report["model_controls"].append(record); dump(output / "report.json", report)
                    print(f"control {mode} {name} {scope} {permutations} fits complete", flush=True)
    report["summary"] = summarize(report["curves"])
    report["allocation_decision"] = allocation_decision(report["summary"], report["curves"])
    omitted = max(max(0, r["conditional_mi_above_null_mean"]) / report["omitted_context_associations"]["target_entropy_nats"]
                  for r in report["omitted_context_associations"]["rows"])
    report["allocation_decision"]["omitted_context_max_conditional_entropy_fraction"] = omitted
    report["allocation_decision"]["omitted_context_followup_budget_threshold"] = .01
    if omitted >= .01:
        report["allocation_decision"]["priority"] = "bounded_feature_availability_validation_first"
    report["status"] = "complete"
    dump(output / "report.json", report)
    plot(output, report["curves"], report["associations"])
    rows = [{k: row[k] for k in ["mode", "repetition", "fraction", "probe", "train_n", "validation_n"]} |
            {f"{section}_{metric}": row[section][metric] for section in ["train", "validation"] for metric in ["top1", "macro_f1", "top3"]}
            for row in report["curves"]]
    pd.DataFrame(rows).to_csv(output / "learning-curves.csv", index=False)
    pd.DataFrame(report["associations"]["rows"]).to_csv(output / "feature-associations.csv", index=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--permutations", type=int, default=20)
    parser.add_argument("--association-permutations", type=int, default=99)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("fresh output required")
    result = run(args.output, repetitions=args.repetitions, permutations=args.permutations,
                 association_permutations=args.association_permutations)
    print(json.dumps({"status": result["status"], "curve_fits": len(result["curves"]),
                      "control_fits": sum(r["repetitions"] for r in result["model_controls"]),
                      "allocation_decision": result["allocation_decision"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
