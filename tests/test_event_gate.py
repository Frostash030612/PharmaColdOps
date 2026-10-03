"""Refusal is not safety; candidates cannot bypass durable human workflow."""
import copy
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from threadpoolctl import threadpool_limits

from api import service, case_audit
from api.main import app
from ml import event_runtime
from ml.event_baselines import TARGETS, make_pipeline
from ml.event_gate import (VERSION, assess, fingerprint, policy, screening_metrics, select_policy,
                           train_envelope, validate_policy)
from ml.event_simulation import CHANNELS, FEATURES, VERSION as OBS_VERSION, temperature_series
from optimisation.case_repository import registered_records
from temperature_monitoring import analyse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate_event_gate as evaluation

client = TestClient(app)


def features():
    row = {key: 0.0 for key in FEATURES if key != "product_id"}
    row.update(product_id="vaccine_2_8", planned_duration_min=180., observed_duration_min=120., sample_cadence_min=5.,
               temperature_coverage_ratio=1., auxiliary_coverage_ratio=1.)
    return pd.DataFrame([row], columns=FEATURES)


def screen_policy():
    envelope = {"products": list(service.ENGINE.specs), "ranges": {k: [-10000., 10000.] for k in FEATURES if k != "product_id"}}
    return policy(envelope, [.5] * len(TARGETS))


def scores(*codes, p=.99):
    result = np.full((1, len(TARGETS)), .001)
    for code in codes:
        result[0, TARGETS.index(code)] = p
    return result


def observation(product="vaccine_2_8"):
    spec = service.ENGINE.specs[product]
    temp = spec.storage_max_c + 5
    records = []
    for start in range(0, 60, 5):
        row = {key: 0. for key in CHANNELS}
        row.update(start_min=start, end_min=start + 5, product_temp_c=temp, air_temp_c=temp, ambient_temp_c=25.,
                   mains_available=1., airflow_fraction=.9, humidity_pct=60.)
        records.append(row)
    return {"schema": OBS_VERSION, "source": "simulated", "event_id": "EV-GATE-TEST", "product_id": product,
            "planned_duration_min": 180, "observation_end_min": 60, "sample_cadence_min": 5, "records": records}


def request(obs=None, **extra):
    obs = obs or observation()
    series = temperature_series(obs, service.ENGINE.specs)
    window = analyse(series, service.ENGINE.specs[obs["product_id"]])["windows"][0]
    return {"product_id": obs["product_id"], "packaging": "intact", "registration_id": "gate-case",
            **window["event"], "temperature_context": {"series": series.model_dump(), "window_id": window["window_id"]},
            "event_context": {"observation": obs}, **extra}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("EVENT_GATE_DIR", raising=False)
    event_runtime._cache.clear()
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "cases.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "cases.jsonl")
    monkeypatch.setattr(service, "write_case", lambda r: True)
    monkeypatch.setattr(service, "evidence_snapshot", lambda n: {"status": "not_verified"})
    monkeypatch.setattr(case_audit, "audit_cases", lambda records, states: {"status": "unavailable", "cases": [{"run_id": records[0]["run_id"]}]})


def test_screened_candidate_is_still_uncalibrated_and_requires_human():
    result = assess(features(), scores("power_outage"), screen_policy())[0]
    assert result["status"] == "candidate_only" and result["supported_candidate"] == "power_outage"
    assert result["review_required"] and result["automatic_actions_allowed"] is False and result["scores_uncalibrated"]


@pytest.mark.parametrize("code", ["door_left_open", "staff_error", "thermostat_failure", "ice_pack_not_conditioned"])
def test_semantically_shared_mechanism_never_yields_single_confirmed_cause(code):
    result = assess(features(), scores(code), screen_policy())[0]
    assert result["status"] == "abstained" and result["supported_candidate"] is None
    assert "shared_mechanism_semantic_ambiguity" in result["reasons"]
    assert "staff_error" in result["candidates"] and len(result["candidates"]) >= 2


@pytest.mark.parametrize("kind,reason", [("missing", "missing_predictors"), ("product", "outside_training_envelope"),
    ("range", "outside_training_envelope"), ("temp_coverage", "insufficient_observation_coverage"),
    ("aux_coverage", "insufficient_observation_coverage"), ("prefix", "short_observation_prefix")])
def test_bad_evidence_requires_refusal(kind, reason):
    frame, value = features(), screen_policy()
    if kind == "missing": frame.loc[0, "ambient_mean_c"] = np.nan
    elif kind == "product": frame.loc[0, "product_id"] = "unseen"
    elif kind == "range": value["envelope"]["ranges"]["ambient_mean_c"] = [10, 35]
    elif kind == "prefix": frame.loc[0, "observed_duration_min"] = 59
    else: frame.loc[0, "temperature_coverage_ratio" if kind == "temp_coverage" else "auxiliary_coverage_ratio"] = .79
    result = assess(frame, scores("power_outage"), value)[0]
    assert result["status"] == "abstained" and reason in result["reasons"]


@pytest.mark.parametrize("probabilities,reason", [(scores(), "no_supported_cause_not_proof_of_safety"),
    (scores("power_outage", p=.6), "low_model_score"), (scores("power_outage", "transport_delay"), "multiple_plausible_causes"),
    (scores("unmodeled_disturbance"), "possible_unmodeled_disturbance")])
def test_no_fault_unknown_multi_and_low_scores_are_not_safe_conclusions(probabilities, reason):
    result = assess(features(), probabilities, screen_policy())[0]
    assert result["status"] == "abstained" and reason in result["reasons"]


@pytest.mark.parametrize("field,value", [("review_required", False), ("automatic_actions_allowed", True),
    ("minimum_temperature_coverage", 0), ("score_floor", .3), ("enabled", "true")])
def test_policy_cannot_disable_mandatory_review(field, value):
    bad = {**screen_policy(), field: value}
    with pytest.raises(ValueError): validate_policy(bad)


def test_screening_rejections_not_counted_as_correct_and_all_denominators_retained():
    x = pd.concat([features()] * 3, ignore_index=True)
    probability = np.vstack([scores("power_outage"), scores("power_outage"), scores()])
    truth = np.zeros((3, 11), dtype=int); truth[0, 0] = 1
    labels = [{"observationally_ambiguous": False}] * 3
    result = screening_metrics(truth, assess(x, probability, screen_policy()), labels)
    assert result["events"] == 3 and result["screen_passed"] == 2
    assert result["supported_exact_precision"] == .5 and result["correct_supported_fraction_all_events"] == pytest.approx(1 / 3)
    assert result["normal_supported_false_alarm_rate"] == .5
    assert result["review_required_events"] == 3 and result["automatic_actions_allowed_events"] == 0


def test_validation_infeasible_refuses_all_not_a_zero_coverage_perfect_model():
    x = pd.concat([features()] * 10, ignore_index=True)
    truth = np.zeros((10, 11), dtype=int)
    value, rows = select_policy(x, np.vstack([scores()] * 10), truth,
        [{"observationally_ambiguous": False}] * 10, train_envelope(x), [.5] * 11)
    assert value["enabled"] is False and len(rows) == 10
    assert all("validation_screen_not_qualified" in r["reasons"] for r in assess(x, np.vstack([scores()] * 10), value))


def test_validation_can_select_feasible_policy_without_test_inputs():
    x = pd.concat([features()] * 50, ignore_index=True)
    truth = np.zeros((50, 11), dtype=int); truth[:40, 0] = 1
    probability = np.vstack([scores("power_outage")] * 40 + [scores()] * 10)
    value, rows = select_policy(x, probability, truth, [{"observationally_ambiguous": False}] * 50,
                              train_envelope(x), [.5] * 11)
    assert value["enabled"] and any(r["eligible"] for r in rows)
    assert screening_metrics(truth, assess(x, probability, value), [{"observationally_ambiguous": False}] * 50)["screen_passed"] == 40


def test_preview_unconfigured_model_is_honest_readonly_and_fail_closed():
    response = client.post("/api/ml/event/assess", json={"observation": observation()})
    assert response.status_code == 200 and response.json()["status"] == "unavailable"
    assert response.json()["review_required"] and response.json()["automatic_actions_allowed"] is False
    assert not Path(service.DISPATCH_DATABASE_URL).exists() and not service.RUNS_FILE.exists()


@pytest.mark.parametrize("extra", [{"scores": {"power_outage": 1}}, {"model_path": "/tmp/model"},
    {"review_required": False}, {"label": "power_outage"}])
def test_clients_cannot_supply_scores_paths_labels_or_gate_result(extra):
    assert client.post("/api/ml/event/assess", json={"observation": observation(), **extra}).status_code == 422


@pytest.mark.parametrize("change", ["hidden", "bool_time", "nan", "string_channel", "cadence", "cadence_mismatch", "many_rows"])
def test_malformed_or_hidden_observations_are_rejected(change):
    obs = observation()
    if change == "hidden": obs["hidden_plan"] = {"faults": []}
    elif change == "bool_time": obs["planned_duration_min"] = True
    elif change == "nan": obs["records"][0]["humidity_pct"] = float("inf")
    elif change == "string_channel": obs["records"][0]["door_open"] = "one"
    elif change == "cadence": obs["sample_cadence_min"] = 0
    elif change == "cadence_mismatch": obs["sample_cadence_min"] = 4
    else: obs["records"] *= 121
    # stdlib-backed TestClient refuses infinity at JSON encoding; submit text.
    response = client.post("/api/ml/event/assess", content=json.dumps({"observation": obs}), headers={"Content-Type": "application/json"})
    assert response.status_code == 422


@pytest.mark.parametrize("change", ["no_temperature", "changed_temperature", "product"])
def test_context_cannot_attach_to_unrelated_product_or_temperature_case(change):
    body = request()
    if change == "no_temperature": body.pop("temperature_context")
    elif change == "changed_temperature": body["temperature_context"]["series"]["intervals"][0]["temp_c"] += 1
    else: body["event_context"]["observation"]["product_id"] = "insulin_2_8"
    assert client.post("/api/case_close", json=body).status_code == 422
    assert registered_records(service.DISPATCH_DATABASE_URL) == []


def test_registration_freezes_full_evidence_and_model_snapshot_retry_does_not_reassess(monkeypatch):
    body = request()
    closed = client.post("/api/case_close", json=body)
    assert closed.status_code == 200, closed.text
    original = closed.json()
    assert original["review_status"] == "pending" and original["effective_disposition"] is None
    assert original["event_assessment"]["status"] == "unavailable"
    monkeypatch.setattr(event_runtime, "evaluate", lambda *a: pytest.fail("registration retry must not reassess changed model"))
    assert client.post("/api/case_close", json=body).json() == original
    changed = copy.deepcopy(body)
    changed["event_context"]["observation"]["records"][0]["humidity_pct"] = 61
    assert client.post("/api/case_close", json=changed).status_code == 409


def test_even_screen_passed_model_cannot_change_original_rule_or_bypass_review(monkeypatch):
    body = request()
    baseline = service.decide_view(__import__("api.schemas", fromlist=["DecideIn"]).DecideIn(**{k:v for k,v in body.items() if k != "event_context"}), None)
    monkeypatch.setattr(event_runtime, "evaluate", lambda *a: {"status": "candidate_only", "screen_passed": True,
        "supported_candidate": "power_outage", "review_required": False, "automatic_actions_allowed": True, "reasons": []})
    record = client.post("/api/case_close", json={**body, "review_required": False}).json()
    assert record["disposition"] == baseline["disposition"] and record["risk"] == baseline["risk"]
    assert record["review_status"] == "pending" and "event_model_human_confirmation_required" in record["review_reasons"]
    assert client.post("/api/dispatch/reshipments/preview", json={"run_id": record["run_id"]}).status_code == 422
    assert client.post(f"/api/runs/{record['run_id']}/workflow", json={"status": "handled", "expected_version": 0, "remark": "try bypass"}).status_code == 409


def test_gate_blocks_linked_delivery_until_human_and_preserves_audit(day_plan):
    did = day_plan("PLAN-GATE-HUMAN", hospitals=1)
    order = service.get_dispatch(did)["input"]["orders"][0]
    body = request(observation(order["product_id"]), order_id=order["order_id"], dispatch_id=did,
                   destination_facility_id=order["destination_facility_id"])
    result = client.post("/api/case_close", json=body)
    assert result.status_code == 200, result.text
    record = result.json()
    originals = copy.deepcopy(registered_records(service.DISPATCH_DATABASE_URL))
    service.depart_dispatch(did, "depart", speed=0)
    vehicle = next(k for k,v in service.get_dispatch(did)["vehicles"].items() if order["order_id"] in v["remaining_order_ids"])
    with pytest.raises(ValueError, match="held"):
        service.deliver_dispatch(did, vehicle, "not-reviewed")
    with pytest.raises(ValueError, match="hold"):
        service.set_dispatch_speed(did, 60)
    review = client.post(f"/api/runs/{record['run_id']}/review", json={"command_id": "gate-human", "expected_version": record["workflow_version"],
        "disposition": "release", "reviewer": "Demo reviewer", "reason": "Checked evidence independently; candidate is not a rule verdict"})
    assert review.status_code == 200 and review.json()["decision_source"] == "manual_review"
    assert registered_records(service.DISPATCH_DATABASE_URL) == originals
    service.deliver_dispatch(did, vehicle, "reviewed-release")
    exported = client.get(f"/api/runs/{record['run_id']}/audit?format=json").json()
    assert exported["original_registration"]["event_assessment"] == record["event_assessment"]
    assert exported["effective_assessment"]["effective_disposition"] == "release"
    assert len(exported["review_history"]) == 1


def test_bundle_hash_and_policy_validation_precede_unpickling(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"; bundle.mkdir()
    (bundle / "model.joblib").write_bytes(b"not a pickle")
    metadata = {"schema": VERSION, "features": list(FEATURES), "targets": list(TARGETS), "shadow_only": True,
                "model_sha256": "wrong", "policy": screen_policy(), "policy_sha256": fingerprint(screen_policy())}
    (bundle / "metadata.json").write_text(json.dumps(metadata))
    monkeypatch.setenv("EVENT_GATE_DIR", str(bundle))
    monkeypatch.setattr(joblib, "load", lambda *a: pytest.fail("invalid hash must fail before unpickle"))
    result = event_runtime.evaluate(observation(), service.ENGINE.specs)
    assert result["status"] == "unavailable" and result["review_required"]


def test_real_bundle_runtime_contract_and_api_workflow_smoke(tmp_path, monkeypatch):
    x = pd.concat([features()] * 40, ignore_index=True)
    for key in FEATURES[1:]: x[key] += np.linspace(0, .01, 40)
    y = np.zeros((40, 11), dtype=int)
    for i in range(11): y[:, i] = (np.arange(40) % (i + 2) == 0)
    model = make_pipeline("full", "logistic")
    with threadpool_limits(limits=1): model.fit(x, y)
    bundle = tmp_path / "bundle"; bundle.mkdir()
    joblib.dump(model, bundle / "model.joblib")
    import sklearn
    metadata = {"schema": VERSION, "features": list(FEATURES), "targets": list(TARGETS), "shadow_only": True,
                "sklearn_version": sklearn.__version__, "model_sha256": event_runtime.digest(bundle / "model.joblib"),
                "policy": screen_policy(), "policy_sha256": fingerprint(screen_policy())}
    (bundle / "metadata.json").write_text(json.dumps(metadata))
    monkeypatch.setenv("EVENT_GATE_DIR", str(bundle))
    result = event_runtime.evaluate(observation(), service.ENGINE.specs)
    assert result["status"] in {"candidate_only", "abstained"} and result["model_sha256"] == metadata["model_sha256"]
    assert evaluation.workflow_smoke(observation(), bundle)["status"] == "passed"
    metadata["policy"]["review_required"] = False
    metadata["policy_sha256"] = fingerprint(metadata["policy"])
    (bundle / "metadata.json").write_text(json.dumps(metadata))
    assert event_runtime.evaluate(observation(), service.ENGINE.specs)["status"] == "unavailable"
