"""Build versioned event-mechanism DATA, not a serving model or clinical gold.

Observation/feature files contain no hidden fault/scenario parameters. Label
sidecars and split metadata are separate, checksummed and never used as inputs.
Default 6,000 events; six explicitly different diagnostic evaluation roles.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict, replace
import datetime
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
from rule_engine.engine import RuleEngine, CONFIG_PATH
from ml.event_simulation import (VERSION, CAUSES, CHANNELS, FEATURES, TEMPLATES, UNSEEN_TEMPLATES,
                                Fault, Plan, extract_features, hidden_labels, make_asset,
                                opaque_id, simulate, stable_seed, twin)

ROLES = ("train", "validation", "test_iid", "test_facility", "test_scenario", "test_parameter")
MODES = ("single", "multi", "no_fault", "unknown", "ambiguous_pair")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def role_counts(events):
    if not isinstance(events, int) or isinstance(events, bool) or not 120 <= events <= 50000:
        raise ValueError("120..50000 events required")
    count = events // 10
    return {role: count if role != "train" else events - count * 5 for role in ROLES}


def plan_families(seed, role, count, specs):
    if role not in ROLES:
        raise ValueError("unknown split role")
    rng = np.random.default_rng(stable_seed(seed, role, "family-schedule"))
    products = sorted(specs)
    base_assets = [opaque_id("ASSET", seed, "base", n) for n in range(32)]
    held_assets = [opaque_id("ASSET", seed, "heldout", n) for n in range(8)]
    assets = held_assets if role == "test_facility" else base_assets
    templates = UNSEEN_TEMPLATES if role == "test_scenario" else TEMPLATES
    regime = "challenging" if role == "test_parameter" else "nominal"
    index = 0
    while index < count:
        # Mode shares are designed coverage, NOT estimated real-business priors.
        mode = str(rng.choice(MODES, p=[.59, .15, .10, .10, .06]))
        if mode == "ambiguous_pair" and count - index == 1:
            mode = "single"
        family = opaque_id("FAMILY", VERSION, seed, role, index)
        event = opaque_id("EV", VERSION, seed, role, index)
        asset_id = str(rng.choice(assets))
        asset = make_asset(asset_id, seed)
        horizon = int(rng.integers(180, 361))
        cutoff = round(float(rng.uniform(.65, 1) * horizon), 3)
        template = str(rng.choice(templates))
        product = str(rng.choice(products))
        if mode == "single":
            codes = [str(rng.choice(CAUSES))]
        elif mode == "multi":
            codes = rng.choice(CAUSES, size=int(rng.integers(2, 4)), replace=False).tolist()
        elif mode == "unknown":
            codes = [str(rng.choice(["external_heat", "sensor_bias"]))]
        elif mode == "ambiguous_pair":
            codes = ["door_left_open"]
        else:
            codes = []
        faults = []
        for code in codes:
            onset = float(rng.uniform(.2, .45 if mode == "ambiguous_pair" else .85) * horizon)
            duration = float(rng.uniform(.1, .35) * horizon)
            subtype = str(rng.choice(["door", "setpoint", "buffer"])) if code == "staff_error" else "default"
            faults.append(Fault(code, onset, duration, float(rng.uniform(.6, 1.4)), int(rng.choice([-1, 1])), subtype))
        ambient = float(rng.uniform(40, 48) if regime == "challenging" else rng.uniform(18, 35))
        dropout = float(rng.uniform(.15, .30) if regime == "challenging" else rng.uniform(.015, .08))
        noise = float(rng.uniform(.6, 1.2) if regime == "challenging" else rng.uniform(.08, .35))
        plan = Plan(family, event, product, asset, stable_seed(seed, family, "observed-process"), horizon, cutoff,
                    5, template, regime, ambient, dropout, noise, tuple(faults), mode == "ambiguous_pair")
        family_plans = [plan, twin(plan)] if mode == "ambiguous_pair" else [plan]
        yield family_plans, mode
        index += len(family_plans)


def create(output, *, events=6000, seed=42):
    if output.exists():
        raise ValueError("fresh output directory required")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("valid integer seed required")
    counts = role_counts(events)
    specs = RuleEngine().specs  # read product ranges only; never evaluate a disposition
    output.mkdir(parents=True, exist_ok=False)
    source_paths = [Path(__file__), ROOT / "src/ml/event_simulation.py", ROOT / "src/temperature_monitoring.py", CONFIG_PATH]
    protocol = {"schema": VERSION, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "seed": seed, "events": events, "role_counts": counts,
                "observed_channels": list(CHANNELS), "model_features": list(FEATURES),
                "forbidden_predictors": ["event_id", "family_id", "asset_id", "role", "seed", "template", "regime",
                                         "faults", "injected_causes", "label_kind", "single_class_target", "hidden_plan", "observationally_ambiguous"],
                "known_mechanism_codes": list(CAUSES), "unknown_mechanisms": ["external_heat", "sensor_bias"],
                "designed_mode_probabilities": dict(zip(MODES, [.59, .15, .10, .10, .06])),
                "split_policy": {"shared_base_roles": ["train", "validation", "test_iid", "test_scenario", "test_parameter"],
                                 "facility_holdout": "8 virtual assets distinct from 32 base assets",
                                 "scenario_holdout": "ramp/two_pulses, absent from all other roles; NOT unseen cause classes",
                                 "parameter_holdout": "ambient40..48C/noise0.6..1.2C/dropout0.15..0.30, nominal ranges disjoint",
                                 "family_policy": "all observational twins stay in one role; no fault/event seed reused across roles"},
                "physics_scope": "uncalibrated engineering thermal/cooling/door/power/airflow model; no manufacturer stability or clinical labels",
                "measurement_scope": "1-minute process, 5-minute noisy sample values explicitly held constant until next sample; null stays unknown",
                "task_scope": "latent injected fault occurrence within observed prefix, not unique attribution to excursion or confirmed investigation",
                "label_policy": "hidden schedule first, observations second; no labels derived from M3 or feature thresholds; multi target null; normal/unknown retained",
                "missing_policy": "no zero filling; known-only durations/MKT labelled and coverage exposed; observed sensor errors/benign anomalies overlap faults",
                "privacy_scope": "synthetic-only; private suffix means separation from model inputs, not human annotation or cryptographic secrecy",
                "next_steps": "do not inspect holdout accuracy to tune generator; train/validate separately later, report control/multi/unknown/ambiguity denominators",
                "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in source_paths},
                "numpy_version": np.__version__, "status": "generating"}
    (output / "manifest.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    summaries = {}
    families_by_role, assets_by_role, templates_by_role = {}, {}, {}
    features_by_role = defaultdict(set)
    feature_frequency = Counter()
    all_ids, all_seeds = set(), set()
    for role, count in counts.items():
        directory = output / role
        directory.mkdir()
        label_counts, mode_counts, cause_counts = Counter(), Counter(), Counter()
        families, assets_seen, templates_seen = set(), set(), set()
        coverage = []
        row_index = 0
        with ExitStack() as stack:
            observations = stack.enter_context((directory / "observations.jsonl").open("x", encoding="utf-8"))
            labels = stack.enter_context((directory / "labels.private.jsonl").open("x", encoding="utf-8"))
            feature_file = stack.enter_context((directory / "features.csv").open("x", encoding="utf-8", newline=""))
            index_file = stack.enter_context((directory / "index.csv").open("x", encoding="utf-8", newline=""))
            feature_writer = csv.DictWriter(feature_file, fieldnames=FEATURES)
            index_writer = csv.DictWriter(index_file, fieldnames=["row_index", "event_id", "family_id", "asset_id", "role"])
            feature_writer.writeheader(); index_writer.writeheader()
            for family_plans, mode in plan_families(seed, role, count, specs):
                family = family_plans[0].family_id
                process_seed = family_plans[0].seed
                if process_seed in all_seeds:
                    raise ValueError("process seed reused across event families")
                all_seeds.add(process_seed)
                families.add(family)
                twin_profile = None
                for plan in family_plans:
                    if plan.event_id in all_ids:
                        raise ValueError("event identity collision")
                    all_ids.add(plan.event_id)
                    observation = simulate(plan, specs)
                    features = extract_features(observation, specs)
                    hidden = hidden_labels(plan)
                    feature_hash = hashlib.sha256(canonical(features).encode()).hexdigest()
                    if mode == "ambiguous_pair":
                        if twin_profile is not None and feature_hash != twin_profile:
                            raise ValueError("declared ambiguity twins differ in model inputs")
                        twin_profile = feature_hash
                    features_by_role[role].add(feature_hash); feature_frequency[feature_hash] += 1
                    assets_seen.add(plan.asset.asset_id); templates_seen.add(plan.template)
                    observations.write(canonical(observation) + "\n")
                    labels.write(canonical(hidden) + "\n")
                    feature_writer.writerow(features)
                    index_writer.writerow({"row_index": row_index, "event_id": plan.event_id, "family_id": family,
                                           "asset_id": plan.asset.asset_id, "role": role})
                    row_index += 1
                    label_counts[hidden["label_kind"]] += 1; mode_counts[mode] += 1
                    cause_counts.update(hidden["injected_causes"])
                    coverage.append(features["temperature_coverage_ratio"])
        if row_index != count:
            raise ValueError("role row count differs from declared split")
        families_by_role[role], assets_by_role[role], templates_by_role[role] = families, assets_seen, templates_seen
        summaries[role] = {"rows": row_index, "families": len(families), "virtual_assets": len(assets_seen),
                           "realized_label_kinds": dict(label_counts), "designed_family_modes": dict(mode_counts),
                           "injected_cause_occurrences": dict(cause_counts), "temperature_coverage_mean": float(np.mean(coverage)),
                           "zero_temperature_coverage_events": sum(v == 0 for v in coverage)}
        print(f"generated {role}: {row_index} events, {len(families)} families", flush=True)
    checks = validate_role_sets(families_by_role, assets_by_role, templates_by_role)
    overlaps = []
    for i, first in enumerate(ROLES):
        for second in ROLES[:i]:
            count = len(features_by_role[first] & features_by_role[second])
            if count:
                overlaps.append({"roles": [first, second], "feature_profiles": count})
    if overlaps:
        raise ValueError("identical model-input profiles cross roles; split audit refused, no resampling to hide failure")
    protocol.update(status="complete", role_summaries=summaries)
    protocol["split_audit"] = {**checks, "event_ids_unique": len(all_ids), "process_family_seeds_unique": len(all_seeds),
                               "cross_role_identical_feature_profiles": overlaps,
                               "within_role_repeated_feature_profiles": sum(v > 1 for v in feature_frequency.values())}
    files = sorted(output.glob("*/*"))
    protocol["file_sha256"] = {str(p.relative_to(output)): digest(p) for p in files}
    (output / "manifest.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return protocol


def validate_role_sets(families, assets, templates):
    if set(families) != set(ROLES) or set(assets) != set(ROLES) or set(templates) != set(ROLES):
        raise ValueError("all six roles required")
    for i, first in enumerate(ROLES):
        for second in ROLES[:i]:
            if families[first] & families[second]:
                raise ValueError("event family crosses training/evaluation roles")
    base_assets = set().union(*(values for role, values in assets.items() if role != "test_facility"))
    if assets["test_facility"] & base_assets:
        raise ValueError("facility holdout identity leakage")
    base_templates = set().union(*(values for role, values in templates.items() if role != "test_scenario"))
    if templates["test_scenario"] & base_templates:
        raise ValueError("excitation-template holdout leakage")
    return {"status": "passed", "family_role_overlap": 0, "heldout_asset_overlap": 0, "heldout_template_overlap": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--events", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("fresh output required")
    result = create(args.output, events=args.events, seed=args.seed)
    print(json.dumps({"status": result["status"], "events": result["events"], "split_audit": result["split_audit"]}))


if __name__ == "__main__":
    main()
