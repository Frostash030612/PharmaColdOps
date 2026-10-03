"""Read-only structural, temporal, split and replay validation of generated data.

Replay checks generator consistency, NOT independent realism/medical validity
or model accuracy. Never read private labels into the feature extractor.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rule_engine.engine import RuleEngine
from ml.event_simulation import (Asset, Fault, Plan, VERSION, FEATURES, extract_features,
                                hidden_labels, simulate, temperature_series, validate_observation, validate_plan)
from generate_event_dataset import ROLES, canonical, digest, validate_role_sets


def restore_plan(value):
    return Plan(**{**value, "asset": Asset(**value["asset"]), "faults": tuple(Fault(**f) for f in value["faults"])})


def read_predictors(directory):
    """Future learner's allowlist loader. No identity/label file is opened."""
    with (directory / "features.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FEATURES):
            raise ValueError("unknown/missing/reordered predictor columns; metadata is not model input")
        rows = []
        for row in reader:
            rows.append({key: row[key] if key == "product_id" else None if row[key] == "" else float(row[key]) for key in FEATURES})
        return rows


def verify(directory, *, replay_per_role=10):
    if replay_per_role < 0:
        raise ValueError("nonnegative replay count required")
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema") != VERSION or manifest.get("status") != "complete":
        raise ValueError("complete supported dataset manifest required")
    expected = {f"{role}/{name}" for role in ROLES for name in ["index.csv", "features.csv", "observations.jsonl", "labels.private.jsonl"]}
    if set(manifest.get("file_sha256", {})) != expected:
        raise ValueError("manifest file allowlist mismatch")
    for name, fingerprint in manifest["file_sha256"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or digest(path) != fingerprint:
            raise ValueError("dataset integrity mismatch")
    specs = RuleEngine().specs
    families, assets, templates = {}, {}, {}
    all_ids = set()
    labels_count, feature_missings = Counter(), Counter()
    rows_checked = replays = twins_checked = prefixes_checked = 0
    for role in ROLES:
        path = directory / role
        predictions = read_predictors(path)
        with (path / "index.csv").open(encoding="utf-8", newline="") as stream:
            indices = list(csv.DictReader(stream))
        with (path / "observations.jsonl").open(encoding="utf-8") as stream:
            observed = [json.loads(line) for line in stream]
        with (path / "labels.private.jsonl").open(encoding="utf-8") as stream:
            private = [json.loads(line) for line in stream]
        if not len(indices) == len(observed) == len(private) == len(predictions) == manifest["role_counts"][role]:
            raise ValueError("aligned event/feature/label/identity counts required")
        families[role], assets[role], templates[role] = set(), set(), set()
        group_observations = defaultdict(list)
        for number, (index, observation, target, features) in enumerate(zip(indices, observed, private, predictions)):
            event_id = index["event_id"]
            if index["role"] != role or int(index["row_index"]) != number or not event_id == observation["event_id"] == target["event_id"] or event_id in all_ids:
                raise ValueError("event identity / role mismatch")
            all_ids.add(event_id)
            plan = restore_plan(target["hidden_plan"])
            validate_plan(plan, specs)
            if index["family_id"] != plan.family_id or index["asset_id"] != plan.asset.asset_id:
                raise ValueError("family/asset metadata mismatch")
            validate_observation(observation, specs)
            temperature_series(observation, specs)  # real M2 interval contract
            if features != extract_features(observation, specs):
                raise ValueError("features not derived solely from matching observed prefix")
            if canonical(target) != canonical(hidden_labels(plan)):
                raise ValueError("label does not match hidden schedule occurrence")
            if number < replay_per_role:
                if observation != simulate(plan, specs):
                    raise ValueError("deterministic observation replay differs")
                # Hidden faults AFTER this prefix must not change its inputs/labels.
                future = Fault("equipment_breakdown", plan.cutoff_min + .01, 20, 1)
                if future.onset_min < plan.horizon_min:
                    changed = replace(plan, faults=plan.faults + (future,))
                    if observation != simulate(changed, specs) or target["injected_causes"] != hidden_labels(changed)["injected_causes"]:
                        raise ValueError("future-only fault leaked into current evidence/labels")
                    prefixes_checked += 1
                replays += 1
            if plan.regime != ("challenging" if role == "test_parameter" else "nominal"):
                raise ValueError("parameter regime leaks across declared holdout")
            ranges = [(40, 48, plan.ambient_c), (.6, 1.2, plan.noise_c), (.15, .30, plan.dropout)] if role == "test_parameter" else [(18, 35, plan.ambient_c), (.08, .35, plan.noise_c), (.015, .08, plan.dropout)]
            if any(not lower <= value <= upper for lower, upper, value in ranges):
                raise ValueError("hidden background parameters violate predeclared holdout ranges")
            group_observations[plan.family_id].append((observation, target, features))
            families[role].add(plan.family_id); assets[role].add(plan.asset.asset_id); templates[role].add(plan.template)
            labels_count[target["label_kind"]] += 1
            feature_missings.update(key for key, value in features.items() if value is None)
            rows_checked += 1
        for group in group_observations.values():
            if any(target["observationally_ambiguous"] for _, target, _ in group):
                if len(group) != 2 or group[0][2] != group[1][2] or group[0][1]["single_class_target"] == group[1][1]["single_class_target"]:
                    raise ValueError("ambiguity family must keep two equivalent observations with distinct hidden targets")
                first = {k: v for k, v in group[0][0].items() if k != "event_id"}
                second = {k: v for k, v in group[1][0].items() if k != "event_id"}
                if first != second:
                    raise ValueError("observational twins differ")
                twins_checked += 1
    split = validate_role_sets(families, assets, templates)
    return {"status": "passed", "schema": VERSION, "events_checked": rows_checked,
            "deterministic_replays": replays, "future_fault_prefix_invariance_checks": prefixes_checked,
            "observational_twin_pairs_checked": twins_checked, "realized_label_kinds": dict(labels_count),
            "feature_missing_counts": dict(feature_missings), "split_audit": split,
            "manifest_sha256": digest(directory / "manifest.json"),
            "verification_code_sha256": digest(Path(__file__)),
            "scope": "integrity / generator consistency / feature isolation / chronology / split checks, NOT independent domain validity or model accuracy"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--replay-per-role", type=int, default=10)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("fresh report required")
    try:
        result = verify(args.dataset, replay_per_role=args.replay_per_role)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
