"""Frozen offline baselines for event simulation; no serving model promotion."""
import argparse
import csv
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from generate_event_dataset import ROLES, digest
from verify_event_dataset import read_predictors, verify
from ml.event_baselines import (PROBES, TARGETS, THRESHOLDS, VIEWS, choose_thresholds, family_bootstrap,
    make_pipeline, metrics, probabilities, shuffle_family_sets, targets, validate_frame)


def dump(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def load_role(dataset, role):
    if role not in ROLES:
        raise ValueError("unsupported role")
    path = dataset / role
    frame = pd.DataFrame(read_predictors(path))
    validate_frame(frame)
    with (path / "labels.private.jsonl").open(encoding="utf-8") as stream:
        labels = [json.loads(line) for line in stream]
    with (path / "index.csv").open(encoding="utf-8", newline="") as stream:
        indices = list(csv.DictReader(stream))
    if not len(frame) == len(labels) == len(indices):
        raise ValueError("aligned source rows required")
    for number, (label, index) in enumerate(zip(labels, indices)):
        if index["event_id"] != label["event_id"] or int(index["row_index"]) != number or index["role"] != role:
            raise ValueError("identity alignment failed")
    return frame, targets(labels), labels, indices


def scoring(scores, thresholds, truth, labels, indices):
    report = metrics(truth, scores, thresholds, labels)
    families = {}
    for row, (label, index) in enumerate(zip(labels, indices)):
        if label["observationally_ambiguous"]:
            families.setdefault(index["family_id"], []).append(row)
    if any(len(rows) != 2 or not np.array_equal(scores[rows[0]], scores[rows[1]]) for rows in families.values()):
        raise ValueError("identical ambiguous evidence must receive identical candidate scores")
    report["ambiguous_pairs_identical_predictions"] = len(families)
    return report


def write_predictions(path, scores, thresholds, labels, indices):
    # Predictions and scores remain separate from private hidden plan data.
    with path.open("x", encoding="utf-8") as stream:
        for score, label, index in zip(scores, labels, indices):
            value = {"event_id": index["event_id"], "family_id": index["family_id"],
                     "truth": label["injected_causes"], "label_kind": label["label_kind"],
                     "observationally_ambiguous": label["observationally_ambiguous"],
                     "candidates": [name for name, p, t in zip(TARGETS, score, thresholds) if p >= t],
                     "scores": dict(zip(TARGETS, score.tolist()))}
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def run(dataset, output, *, bootstrap=300):
    if output.exists() or output.resolve().is_relative_to(dataset.resolve()):
        raise ValueError("fresh separate output directory required")
    if bootstrap < 1:
        raise ValueError("positive bootstrap count required")
    # Integrity checks may read all labels, but nothing here chooses a model.
    audit = verify(dataset, replay_per_role=2)
    manifest_sha = digest(dataset / "manifest.json")
    sources = [Path(__file__), ROOT / "src/ml/event_baselines.py", ROOT / "scripts/verify_event_dataset.py",
               ROOT / "src/ml/event_simulation.py", ROOT / "scripts/generate_event_dataset.py"]
    protocol = {"schema": "event-baselines-v1", "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dataset_manifest_sha256": manifest_sha, "seed": 42, "target_order": list(TARGETS),
        "features_by_view": {name: list(fields) for name, fields in VIEWS.items()},
        "probes": {name: {"view": view, "algorithm": algorithm, "eligible_for_selection": eligible,
                          "parameters": make_pipeline(view, algorithm).named_steps["classifier"].estimator.get_params()
                              if algorithm != "prior" else {"probability": "train marginal prevalence"}}
                   for name, (view, algorithm, eligible) in PROBES.items()},
        "threshold_grid": list(THRESHOLDS), "threshold_selection": "per-label validation F1; ties higher threshold; absent label .5; constant positive score adds its value to allow rare-prior fire choice",
        "model_selection": "validation macro-F1 over 11 labels; only full_logistic/full_hgb; ties name ascending; no train+validation refit",
        "roles": "fit train only, choose validation only, freeze selection artifact before opening test labels for scoring",
        "negative_control": "shuffle TRAIN family label-sets within product and family size, preserving paired twins; validation labels unchanged; seed42; descriptive not p-value",
        "bootstrap": {"repetitions": bootstrap, "unit": "event family", "scope": "selected model, four test roles separately"},
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "versions": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "scikit-learn", "scipy", "joblib"]},
        "limitations": ["synthetic mechanism labels, not real causal/medical/disposal truth",
            "unknown perturbation types also present in train; not open-set validation",
            "scenario holdout = unseen excitation, not unseen cause class", "single fixed training seed and one shuffled control",
            "all no-fault/multi/unknown/ambiguous events retained; no-fault does not mean safe",
            "context view includes measurement coverage: a missingness diagnostic, not identity input",
            "uncalibrated model scores; thresholds not medical or deployment cutoffs",
            "paired-family shuffle retains within-pair semantic ambiguity and some labels; not a complete independence null",
            "cannot compare these scores directly to old monthly cause task; no automatic promotion"]}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "protocol.json", protocol)
    dump(output / "integrity-before.json", audit)
    train_x, train_y, train_labels, train_indices = load_role(dataset, "train")
    val_x, val_y, val_labels, val_indices = load_role(dataset, "validation")
    shuffled_indices = [{**index, "product_id": train_x.iloc[row].product_id} for row, index in enumerate(train_indices)]
    shuffled_truth = shuffle_family_sets(train_y, shuffled_indices)
    models, thresholds, validation, training = {}, {}, {}, {}
    with threadpool_limits(limits=1):
        for name, (view, algorithm, _) in PROBES.items():
            print("fitting " + name, flush=True)
            if algorithm == "prior":
                model = train_y.mean(axis=0)
                train_scores = np.tile(model, (len(train_x), 1))
                scores = np.tile(model, (len(val_x), 1))
            else:
                model = make_pipeline(view, algorithm)
                fitted_truth = shuffled_truth if name.startswith("shuffled_") else train_y
                model.fit(train_x, fitted_truth)
                train_scores = probabilities(model, train_x)
                scores = probabilities(model, val_x)
            threshold = choose_thresholds(val_y, scores)
            models[name], thresholds[name] = model, threshold
            validation[name] = scoring(scores, threshold, val_y, val_labels, val_indices)
            training[name] = scoring(train_scores, threshold, train_y, train_labels, train_indices)
            write_predictions(output / ("validation-" + name + ".jsonl"), scores, threshold, val_labels, val_indices)
        eligible = [name for name, (_, _, allowed) in PROBES.items() if allowed]
        selected = sorted(eligible, key=lambda name: (-validation[name]["macro_f1_11"], name))[0]
        model_path = output / "selected-experimental-model.joblib"
        joblib.dump(models[selected], model_path)
        selection = {"selected": selected, "validation": validation,
                     "thresholds": {name: t.tolist() for name, t in thresholds.items()},
                     "dataset_manifest_sha256": manifest_sha, "protocol_sha256": digest(output / "protocol.json"),
                     "model_sha256": digest(model_path), "promotion": False}
        dump(output / "selection-frozen.json", selection)
        frozen_sha = digest(output / "selection-frozen.json")
        test = {}
        for role in ROLES:
            if not role.startswith("test_"):
                continue
            print("scoring frozen models: " + role, flush=True)
            frame, truth, labels, indices = load_role(dataset, role)
            test[role] = {}
            for name, model in models.items():
                scores = np.tile(model, (len(frame), 1)) if name == "train_prior" else probabilities(model, frame)
                test[role][name] = scoring(scores, thresholds[name], truth, labels, indices)
                if name == selected:
                    test[role][name]["family_bootstrap"] = family_bootstrap(truth, scores, thresholds[name],
                        [i["family_id"] for i in indices], repetitions=bootstrap)
                write_predictions(output / (role + "-" + name + ".jsonl"), scores, thresholds[name], labels, indices)
        # No mutation of selection, dataset or evaluator during scoring.
        if digest(output / "selection-frozen.json") != frozen_sha or digest(dataset / "manifest.json") != manifest_sha:
            raise ValueError("frozen protocol/selection or dataset mutated")
        for filename, fingerprint in json.loads((dataset / "manifest.json").read_text())["file_sha256"].items():
            if digest(dataset / filename) != fingerprint:
                raise ValueError("dataset file mutated during evaluation")
        if any(digest(ROOT / filename) != fingerprint for filename, fingerprint in protocol["source_sha256"].items()):
            raise ValueError("evaluation source changed during run")
        report = {"status": "complete", "selected": selected, "protocol": protocol, "selection_sha256": frozen_sha,
                  "training": training, "validation": validation, "test": test, "dataset_unchanged": True,
                  "shuffle_control": {"unchanged_train_label_sets": int(np.all(shuffled_truth == train_y, axis=1).sum()),
                                      "train_events": len(train_y), "preserved_marginal_counts": bool(np.array_equal(shuffled_truth.sum(axis=0), train_y.sum(axis=0)))},
                  "serving_integration": False, "artifact_scope": "offline experimental model only; no serving contract"}
        dump(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=300)
    args = parser.parse_args()
    report = run(args.dataset, args.output, bootstrap=args.bootstrap)
    print(json.dumps({"status": report["status"], "selected": report["selected"],
                      "test_macro_f1_11": {role: probes[report["selected"]]["macro_f1_11"] for role, probes in report["test"].items()}}))


if __name__ == "__main__":
    main()
