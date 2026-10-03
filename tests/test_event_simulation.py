"""Latent mechanism data must preserve time, ambiguity and feature isolation."""
import copy
import csv
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from ml.event_simulation import (Asset, CAUSES, CHANNELS, FEATURES, Fault, Plan, VERSION,
                                extract_features, hidden_labels, simulate, temperature_series,
                                twin, validate_observation)
from rule_engine.engine import RuleEngine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_event_dataset as generation
import verify_event_dataset as verification

SPECS = RuleEngine().specs


def plan(code="equipment_breakdown", *, cutoff=160, product="vaccine_2_8", seed=42):
    return Plan("FAMILY-test", "EV-test", product, Asset("ASSET-test", .004, 2, 12, .9, 0),
                seed, 180, cutoff, 5, "sustained", "nominal", 30, .05, .2,
                () if code is None else (Fault(code, 30, 60, 1),))


@pytest.mark.parametrize("product", sorted(SPECS))
@pytest.mark.parametrize("code", list(CAUSES) + ["external_heat", "sensor_bias", None])
def test_all_products_and_mechanisms_are_reproducible_m2_compatible_and_prefix_bounded(product, code):
    value = plan(code, product=product)
    observed = simulate(value, SPECS)
    assert observed == simulate(value, SPECS)
    assert observed != simulate(replace(value, seed=43), SPECS)
    validate_observation(observed, SPECS)
    series = temperature_series(observed, SPECS)
    assert series.source == "simulated" and series.observation_end_min == 160
    assert all(row["end_min"] <= 160 for row in observed["records"])
    assert set(extract_features(observed, SPECS)) == set(FEATURES)
    assert hidden_labels(value)["injected_causes"] == ([] if code is None else [code if code in CAUSES else "unmodeled_disturbance"])


def test_future_only_changes_cannot_change_past_observation_features_or_targets():
    value = plan(None, cutoff=73.25)
    future = replace(value, faults=(Fault("thermostat_failure", 100, 40, 1, -1),))
    first = simulate(value, SPECS)
    second = simulate(future, SPECS)
    assert first == second and extract_features(first, SPECS) == extract_features(second, SPECS)
    assert hidden_labels(future)["injected_causes"] == []


def test_explicit_observation_twins_have_distinct_hidden_labels_and_stay_ambiguous():
    first = replace(plan("door_left_open"), ambiguity=True)
    second = twin(first)
    a, b = simulate(first, SPECS), simulate(second, SPECS)
    assert {k: v for k, v in a.items() if k != "event_id"} == {k: v for k, v in b.items() if k != "event_id"}
    assert extract_features(a, SPECS) == extract_features(b, SPECS)
    assert hidden_labels(first)["single_class_target"] == "door_left_open"
    assert hidden_labels(second)["single_class_target"] == "staff_error"
    assert hidden_labels(first)["observationally_ambiguous"] and hidden_labels(second)["observationally_ambiguous"]


def test_multiple_faults_and_unknowns_are_not_forced_into_one_certain_cause():
    value = replace(plan(), faults=(Fault("equipment_breakdown", 30, 60, 1), Fault("door_left_open", 40, 30, 1)))
    label = hidden_labels(value)
    assert label["label_kind"] == "multi" and label["single_class_target"] is None
    assert len(label["injected_causes"]) == 2
    assert hidden_labels(plan("sensor_bias"))["label_kind"] == "unknown"
    assert hidden_labels(plan(None))["single_class_target"] == "no_fault"


def test_hidden_label_is_not_changed_by_rewriting_observed_temperature():
    value = plan()
    label = hidden_labels(value)
    observed = simulate(value, SPECS)
    for row in observed["records"]:
        row["product_temp_c"] = 5.0
    features = extract_features(observed, SPECS)
    assert features["known_hot_min"] == features["known_cold_min"] == 0
    assert label == hidden_labels(value)
    assert "scrap" not in label and "disposition" not in label


def test_all_missing_temperature_remains_unknown_not_zero_or_safe_mkt():
    observed = simulate(plan(), SPECS)
    for row in observed["records"]:
        row["product_temp_c"] = None
    result = extract_features(observed, SPECS)
    assert result["temperature_coverage_ratio"] == 0
    for key in ["temperature_offset_mean_c", "temperature_offset_min_c", "temperature_offset_max_c",
                "known_hot_min", "known_cold_min", "known_only_mkt_offset_c", "max_rise_c_per_min"]:
        assert result[key] is None
    assert result["longest_temperature_gap_min"] == 160


def test_time_weighted_observation_summaries_and_known_plan_progress_use_no_future():
    observed = simulate(plan(None, cutoff=11), SPECS)
    rows = observed["records"]
    assert len(rows) == 3 and [r["end_min"] - r["start_min"] for r in rows] == [5, 5, 1]
    for row, temp in zip(rows, [5, 10, 20]):
        row["product_temp_c"] = temp
        row["route_progress"] = row["start_min"] / 180
    result = extract_features(observed, SPECS)
    assert result["temperature_offset_mean_c"] == pytest.approx((5 * 5 + 10 * 5 + 20) / 11 - 5, abs=1e-6)
    assert result["known_hot_min"] == 6
    assert result["progress_lag_mean_min"] == 0


@pytest.mark.parametrize("field", ["label_kind", "seed", "hidden_plan", "template", "role", "injected_causes"])
def test_hidden_parameters_and_targets_refused_by_feature_extractor(field):
    observed = simulate(plan(), SPECS)
    observed[field] = "leak"
    with pytest.raises(ValueError, match="hidden labels"):
        extract_features(observed, SPECS)


def test_identity_is_not_a_predictor_and_forward_or_unknown_channels_fail_closed():
    observed = simulate(plan(), SPECS)
    first = extract_features(observed, SPECS)
    observed["event_id"] = "DIFFERENT-ID"
    assert extract_features(observed, SPECS) == first
    assert not {"asset_id", "family_id", "event_id", "role", "label"} & set(first)
    changed = copy.deepcopy(observed)
    changed["records"][-1]["end_min"] += 1
    with pytest.raises(ValueError):
        extract_features(changed, SPECS)
    observed["records"][0]["fault_active"] = 1
    with pytest.raises(ValueError, match="channel"):
        extract_features(observed, SPECS)


@pytest.mark.parametrize("fault", [Fault("invented", 10, 20, 1), Fault("power_outage", -1, 20, 1),
                                    Fault("door_left_open", 10, 0, 1), Fault("door_left_open", 10, 20, float("nan"))])
def test_invalid_faults_fail_before_generation(fault):
    with pytest.raises(ValueError):
        simulate(replace(plan(), faults=(fault,)), SPECS)


def test_equipment_loss_changes_shared_thermal_dynamics_not_a_label_only_column():
    normal = replace(plan(None), dropout=0, noise_c=0)
    failed = replace(normal, faults=(Fault("equipment_breakdown", 30, 60, 1.3),))
    a, b = simulate(normal, SPECS), simulate(failed, SPECS)
    assert extract_features(b, SPECS)["temperature_offset_mean_c"] > extract_features(a, SPECS)["temperature_offset_mean_c"] + 2


def test_small_dataset_is_replayable_aligned_split_safe_and_not_overwritten(tmp_path):
    output = tmp_path / "first"
    result = generation.create(output, events=180, seed=42)
    assert result["status"] == "complete" and result["split_audit"]["event_ids_unique"] == 180
    validated = verification.verify(output, replay_per_role=2)
    assert validated["status"] == "passed" and validated["events_checked"] == 180
    assert validated["observational_twin_pairs_checked"] > 0
    second = generation.create(tmp_path / "second", events=180, seed=42)
    assert result["file_sha256"] == second["file_sha256"]
    third = generation.create(tmp_path / "third", events=180, seed=43)
    assert result["file_sha256"] != third["file_sha256"]
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="fresh output"):
        generation.create(output, events=180)
    assert (output / "manifest.json").read_bytes() == before
    assert not set(result["forbidden_predictors"]) & set(FEATURES)


def test_predictor_loader_never_opens_private_labels_and_rejects_extra_columns(tmp_path):
    with (tmp_path / "features.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FEATURES)
        writer.writeheader()
        writer.writerow({key: "vaccine_2_8" if key == "product_id" else "" for key in FEATURES})
    result = verification.read_predictors(tmp_path)
    assert result[0]["temperature_offset_mean_c"] is None
    text = (tmp_path / "features.csv").read_text()
    (tmp_path / "features.csv").write_text(text.replace("product_id,", "event_id,product_id,"))
    with pytest.raises(ValueError, match="predictor columns"):
        verification.read_predictors(tmp_path)


def test_file_tampering_is_refused_before_scoring_or_replay(tmp_path):
    output = tmp_path / "data"
    generation.create(output, events=120)
    with (output / "train/features.csv").open("a") as stream:
        stream.write("tampered\n")
    with pytest.raises(ValueError, match="integrity"):
        verification.verify(output)


def test_family_asset_template_holdout_guards_are_not_row_random_splits():
    families = {role: {"F-" + role} for role in generation.ROLES}
    assets = {role: {"base"} for role in generation.ROLES}
    assets["test_facility"] = {"new"}
    templates = {role: {"pulse"} for role in generation.ROLES}
    templates["test_scenario"] = {"ramp"}
    assert generation.validate_role_sets(families, assets, templates)["status"] == "passed"
    bad = copy.deepcopy(families); bad["validation"] = bad["train"]
    with pytest.raises(ValueError, match="family"):
        generation.validate_role_sets(bad, assets, templates)
    bad = copy.deepcopy(assets); bad["test_facility"] = {"base"}
    with pytest.raises(ValueError, match="facility"):
        generation.validate_role_sets(families, bad, templates)
    bad = copy.deepcopy(templates); bad["test_scenario"] = {"pulse"}
    with pytest.raises(ValueError, match="template"):
        generation.validate_role_sets(families, assets, bad)


@pytest.mark.parametrize("events,seed", [(0, 42), (120.5, 42), (True, 42), (120, -1), (120, True)])
def test_invalid_generation_config_does_not_write_output(tmp_path, events, seed):
    output = tmp_path / "bad"
    with pytest.raises(ValueError):
        generation.create(output, events=events, seed=seed)
    assert not output.exists()
