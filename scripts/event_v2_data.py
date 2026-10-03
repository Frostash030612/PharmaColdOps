"""Independent v2 role construction using unchanged v1 simulator/label logic."""
from collections import Counter
from contextlib import ExitStack
from dataclasses import replace
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
import pandas as pd

from generate_event_dataset import canonical, digest, plan_families
from verify_event_dataset import read_predictors, restore_plan
from ml.event_simulation import (FEATURES, Fault, extract_features, hidden_labels, simulate, stable_seed,
                                validate_observation, validate_plan)
from ml.event_temporal import VERSION, TEMPORAL_FEATURES, extract_temporal, validate_temporal
from ml.event_baselines import targets, validate_frame
from rule_engine.engine import RuleEngine

TRAIN = ("train_nominal", "train_stress")
VALIDATION = ("validation_nominal", "validation_stress")
TEST = ("test_nominal", "test_device", "test_scenario", "test_stress", "test_extreme")
ROLE_CONFIG = {
    "train_nominal": ("train", "nominal"), "train_stress": ("test_parameter", "stress"),
    "validation_nominal": ("validation", "nominal"), "validation_stress": ("test_parameter", "stress"),
    "test_nominal": ("test_iid", "nominal"), "test_device": ("test_facility", "nominal"),
    "test_scenario": ("test_scenario", "nominal"), "test_stress": ("test_parameter", "stress"),
    "test_extreme": ("test_parameter", "extreme"),
}


def create_role(root, role, count, seed):
    if role not in ROLE_CONFIG or type(count) is not int or not 20 <= count <= 20000 or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("supported role, 20..20000 events and uint32 seed required")
    directory = root / role
    if directory.exists(): raise ValueError("fresh role directory required")
    directory.mkdir(parents=True)
    source_role, profile = ROLE_CONFIG[role]
    role_seed = stable_seed(VERSION, seed, role) % 2**32
    specs = RuleEngine().specs
    kinds, support = Counter(), Counter()
    with ExitStack() as stack:
        observed_file = stack.enter_context((directory / "observations.jsonl").open("x", encoding="utf-8"))
        labels_file = stack.enter_context((directory / "labels.private.jsonl").open("x", encoding="utf-8"))
        writers = {}
        for filename, fields in [("features.csv", FEATURES), ("temporal.csv", TEMPORAL_FEATURES),
                                 ("index.csv", ["row_index", "event_id", "family_id", "asset_id", "role"])]:
            writer = csv.DictWriter(stack.enter_context((directory / filename).open("x", encoding="utf-8", newline="")), fieldnames=fields)
            writer.writeheader(); writers[filename] = writer
        row_index = 0
        for family, _ in plan_families(role_seed, source_role, count, specs):
            # v2 extreme background only: same equations, noise channels,
            # occurrence labels and ambiguity twins. No label-conditioned fix.
            if profile == "extreme":
                rng = np.random.default_rng(stable_seed(VERSION, family[0].family_id, "extreme-background"))
                params = {"ambient_c": float(rng.uniform(48, 54)), "noise_c": float(rng.uniform(1.2, 1.6)), "dropout": float(rng.uniform(.30, .40))}
                family = [replace(plan, **params) for plan in family]
            for plan in family:
                observation = simulate(plan, specs)
                label = hidden_labels(plan)
                observed_file.write(canonical(observation) + "\n"); labels_file.write(canonical(label) + "\n")
                writers["features.csv"].writerow(extract_features(observation, specs))
                writers["temporal.csv"].writerow(extract_temporal(observation, specs))
                writers["index.csv"].writerow({"row_index": row_index, "event_id": plan.event_id, "family_id": plan.family_id,
                                            "asset_id": plan.asset.asset_id, "role": role})
                kinds[label["label_kind"]] += 1; support.update(label["injected_causes"])
                row_index += 1
    if row_index != count: raise ValueError("role count drift")
    print(f"generated v2 {role}: {count}", flush=True)
    return {"events": count, "source_role_schedule": source_role, "parameter_profile": profile, "seed": role_seed,
            "label_kinds": dict(kinds), "fault_support": dict(support),
            "file_sha256": {p.name: digest(p) for p in sorted(directory.iterdir())}}


def read_temporal(directory):
    with (directory / "temporal.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(TEMPORAL_FEATURES): raise ValueError("exact v2 predictor allowlist required")
        rows = [{k: row[k] if k == "product_id" else None if row[k] == "" else float(row[k]) for k in TEMPORAL_FEATURES} for row in reader]
    frame = pd.DataFrame(rows, columns=TEMPORAL_FEATURES)
    validate_temporal(frame)
    return frame


def load_role(root, role):
    if role not in ROLE_CONFIG: raise ValueError("unsupported v2 role")
    directory = root / role
    base = pd.DataFrame(read_predictors(directory), columns=FEATURES); validate_frame(base)
    temporal = read_temporal(directory)
    with (directory / "labels.private.jsonl").open(encoding="utf-8") as stream:
        labels = [json.loads(line) for line in stream]
    with (directory / "index.csv").open(encoding="utf-8", newline="") as stream:
        indices = list(csv.DictReader(stream))
    if not len(base) == len(temporal) == len(labels) == len(indices): raise ValueError("aligned v2 rows required")
    for number, (label, index) in enumerate(zip(labels, indices)):
        if index["role"] != role or int(index["row_index"]) != number or index["event_id"] != label["event_id"]:
            raise ValueError("v2 row identity mismatch")
    return base, temporal, targets(labels), labels, indices


def verify_role(root, role, summary, replays=2):
    directory = root / role
    for name, h in summary["file_sha256"].items():
        if directory.joinpath(name).is_symlink() or digest(directory / name) != h: raise ValueError("v2 data hash mismatch")
    base, temporal, _, labels, indices = load_role(root, role)
    if len(base) != summary["events"]: raise ValueError("v2 declared count mismatch")
    with (directory / "observations.jsonl").open(encoding="utf-8") as stream:
        observations = [json.loads(line) for line in stream]
    if len(observations) != len(base): raise ValueError("observations not aligned")
    specs = RuleEngine().specs
    base_rows, temporal_rows = base.to_dict("records"), temporal.to_dict("records")
    twins, families, assets, profiles = {}, set(), set(), set()
    replay_count = prefixes = 0
    for i, (observation, label, index) in enumerate(zip(observations, labels, indices)):
        validate_observation(observation, specs)
        plan = restore_plan(label["hidden_plan"]); validate_plan(plan, specs)
        profile = ROLE_CONFIG[role][1]
        ranges = [(18, 35, plan.ambient_c), (.08, .35, plan.noise_c), (.015, .08, plan.dropout)] if profile == "nominal" else (
            [(40, 48, plan.ambient_c), (.6, 1.2, plan.noise_c), (.15, .30, plan.dropout)] if profile == "stress" else
            [(48, 54, plan.ambient_c), (1.2, 1.6, plan.noise_c), (.30, .40, plan.dropout)])
        if any(not a <= v <= b for a,b,v in ranges) or plan.regime != ("nominal" if profile == "nominal" else "challenging"):
            raise ValueError("role background contract mismatch")
        if (observation["event_id"] != index["event_id"] or plan.family_id != index["family_id"] or plan.asset.asset_id != index["asset_id"]
                or canonical(label) != canonical(hidden_labels(plan))): raise ValueError("v2 observation/plan/target identity mismatch")
        expected = extract_temporal(observation, specs)
        actual = {k: None if pd.isna(temporal_rows[i][k]) else temporal_rows[i][k] for k in TEMPORAL_FEATURES}
        if expected != actual or extract_features(observation, specs) != {k: None if pd.isna(base_rows[i][k]) else base_rows[i][k] for k in FEATURES}:
            raise ValueError("v2 inputs not observation-only")
        if i < replays:
            if observation != simulate(plan, specs): raise ValueError("v2 replay differs")
            replay_count += 1
            if plan.cutoff_min + .01 < plan.horizon_min:
                future = replace(plan, faults=plan.faults + (Fault("equipment_breakdown", plan.cutoff_min + .01, 10, 1),))
                if observation != simulate(future, specs) or label["injected_causes"] != hidden_labels(future)["injected_causes"]:
                    raise ValueError("future fault leaked")
                prefixes += 1
        features_key = canonical(expected); profiles.add(features_key)
        if label["observationally_ambiguous"]: twins.setdefault(index["family_id"], []).append((features_key, label["single_class_target"]))
        families.add(index["family_id"]); assets.add(index["asset_id"])
    if any(len(pair) != 2 or pair[0][0] != pair[1][0] or pair[0][1] == pair[1][1] for pair in twins.values()):
        raise ValueError("v2 observational ambiguity was lost")
    return {"events": len(base), "replays": replay_count, "future_prefix_checks": prefixes, "twin_pairs": len(twins)}, (families, assets, profiles)
