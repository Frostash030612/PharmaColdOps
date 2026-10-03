"""Train and persist advisory M4 risk/candidate-cause models, never scrap labels.

Fresh output only. Model choice uses validation PR-AUC (risk) / macro-F1 (cause).
The untouched test split is scored after selection. No anonymous IDs, quantity
or warehouse stock features. Default runtime artifacts are regenerable/ignored.
"""
import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ml.contracts import FEATURES, RISK_FIELDS, CAUSE_CATEGORICAL, CAUSE_NUMERIC, INTEGER_FIELDS, normalize_features
from ml.evaluate import balanced_weights, best_f1_threshold, binary_metrics, multi_metrics
from ml.training import make_pipeline


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidates(task):
    models = [("logistic_regression", LogisticRegression(max_iter=2000, random_state=42)),
              ("hist_gradient_boosting", HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=15,
                  learning_rate=.08, random_state=42))]
    skipped = []
    if task == "risk":
        for package, cls in [("lightgbm", "LGBMClassifier"), ("xgboost", "XGBClassifier")]:
            try:
                mod = importlib.import_module(package)
                params = dict(n_estimators=200, max_depth=5, learning_rate=.05, random_state=42, n_jobs=1)
                if package == "lightgbm": params["verbose"] = -1
                else: params["eval_metric"] = "logloss"
                models.append((package, getattr(mod, cls)(**params)))
            except Exception as exc:  # optional native packages can raise their own load errors
                skipped.append({"model": package, "reason": type(exc).__name__})
    return models, skipped


def data_frame(task):
    if task == "risk":
        files = [ROOT / "data/ml/cold-chain-silent-failure/shipment-sensor-dataset.csv"]
        df = pd.read_csv(files[0]); target = "silent_failure"
        ids = df["shipment_id"].astype(str).tolist()
    else:
        base = ROOT / "data/ml/electricsheepafrica__vaccine-cold-chain"
        files = [base / f"vaccine_coldchain_{name}.csv" for name in ["district_hospital", "regional_vaccine_store", "rural_health_post"]]
        df = pd.concat([pd.read_csv(p) for p in files], ignore_index=True)
        df["sample_id"] = [f"CAUSE-{i:05d}" for i in range(len(df))]
        df = df[(df.heat_excursion_detected == 1) | (df.freeze_excursion_detected == 1)].copy()
        target = "excursion_cause"
        df = df[df[target].notna() & (df[target] != "not_applicable")].reset_index(drop=True)
        ids = df["sample_id"].tolist()
    return df, ids, target, files


def data_for(task):
    df, ids, target, files = data_frame(task)
    x = df[FEATURES[task]].copy()
    if task == "cause":
        for key in CAUSE_CATEGORICAL: x[key] = x[key].astype(str)
    return x, df[target].to_numpy(), ids, target, {str(p.relative_to(ROOT)): digest(p) for p in files}


def fit_task(task, directory):
    x, y, ids, target, sources = data_for(task)
    train, test = train_test_split(np.arange(len(x)), stratify=y, test_size=.15, random_state=42)
    train, validation = train_test_split(train, stratify=y[train], test_size=.1765, random_state=42)
    models, skipped = candidates(task)
    results, winner = [], None
    for name, estimator in models:
        pipeline = make_pipeline(task, estimator)
        pipeline.fit(x.iloc[train], y[train], classifier__sample_weight=balanced_weights(y[train]))
        probabilities = pipeline.predict_proba(x.iloc[validation])
        if task == "risk":
            threshold = best_f1_threshold(y[validation], probabilities[:, 1])
            metrics = binary_metrics(y[validation], probabilities[:, 1], threshold)
            score = metrics["prauc"]
        else:
            threshold = None
            from sklearn.preprocessing import LabelEncoder
            labels = LabelEncoder().fit(pipeline.classes_)
            metrics = multi_metrics(labels.transform(y[validation]), probabilities)
            score = metrics["macro_f1"]
        results.append({"algorithm": name, "validation": metrics})
        if winner is None or score > winner[0]: winner = (score, name, pipeline, threshold)
    _, algorithm, model, threshold = winner
    ptest = model.predict_proba(x.iloc[test])
    if task == "risk": metrics = binary_metrics(y[test], ptest[:, 1], threshold)
    else:
        from sklearn.preprocessing import LabelEncoder
        metrics = multi_metrics(LabelEncoder().fit(model.classes_).transform(y[test]), ptest)
    fields, references = [], {}
    for key in FEATURES[task]:
        if task == "cause" and key in CAUSE_CATEGORICAL:
            options = sorted(x.iloc[train][key].unique().tolist())
            reference = x.iloc[train][key].mode().iloc[0]
            fields.append({"key": key, "kind": "category", "options": options})
        else:
            reference = float(x.iloc[train][key].median())
            fields.append({"key": key, "kind": "integer" if key in INTEGER_FIELDS else "number",
                "bounds": list((RISK_FIELDS if task == "risk" else CAUSE_NUMERIC)[key]),
                "training_range": [float(x.iloc[train][key].min()), float(x.iloc[train][key].max())]})
        references[key] = reference
    # Public demo samples are from the held-out partition; NO target label is
    # exposed and no sample is automatically claimed to belong to an incident.
    ranked = np.argsort(ptest[:, 1] if task == "risk" else ptest.max(axis=1))
    eligible = []
    for i in ranked:
        row = x.iloc[test[i]].to_dict()
        row = {k: v.item() if isinstance(v, np.generic) else v for k, v in row.items()}
        try:
            row = normalize_features(task, row)
        except ValueError:
            continue
        supported = all(row[f["key"]] in f["options"] if f["kind"] == "category" else
                        f["training_range"][0] <= row[f["key"]] <= f["training_range"][1] for f in fields)
        if supported: eligible.append(int(i))
    if not eligible: raise ValueError("no complete, in-domain held-out demonstration samples")
    selected = [eligible[i] for i in np.linspace(0, len(eligible)-1, min(8, len(eligible))).astype(int)]
    samples = []
    for i in selected:
        row = x.iloc[test[i]].to_dict()
        for k, v in row.items():
            if isinstance(v, np.generic): row[k] = v.item()
        samples.append({"sample_id": ids[test[i]], "features": row})
    directory.mkdir()
    joblib.dump(model, directory / "model.joblib")
    model_sha = digest(directory / "model.joblib")
    metadata = {"schema_version": 1, "task": task, "target": target,
        "model_id": f"{task}-v1-{algorithm}-{model_sha[:12]}", "algorithm": algorithm,
        "model_sha256": model_sha, "sklearn_version": sklearn.__version__,
        "seed": 42, "split": {"method": "random_stratified_not_temporal_or_facility_grouped",
            "train": len(train), "validation": len(validation), "test": len(test),
            "sha256": hashlib.sha256(json.dumps([train.tolist(), validation.tolist(), test.tolist()]).encode()).hexdigest()},
        "selection": "validation_pr_auc" if task == "risk" else "validation_macro_f1",
        "candidates": results, "unavailable_candidates": skipped, "test_metrics": metrics,
        "threshold": threshold, "features": FEATURES[task], "fields": fields,
        "references": references, "classes": model.classes_.tolist(), "samples": samples,
        "source_hashes": sources, "data_suspected_or_declared_synthetic": True, "probabilities_uncalibrated": True,
        "scope": "retrospective benchmark association; not scrap, potency, prospective warning or confirmed causal diagnosis"}
    (directory / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(task, algorithm, json.dumps(metrics), flush=True)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/m4")
    args = parser.parse_args()
    if args.output.exists(): parser.error("output already exists; choose a new directory, then configure ML_MODEL_DIR")
    args.output.mkdir(parents=True)
    with threadpool_limits(limits=1):
        metadata = {task: fit_task(task, args.output / task) for task in ["risk", "cause"]}
    (args.output / "training-report.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Model artifacts:", args.output)
    return 0


if __name__ == "__main__": raise SystemExit(main())
