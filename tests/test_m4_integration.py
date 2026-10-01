"""Learned advisory outputs cannot alter rules, dispatch or immutable history."""
import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from api import service
from api.main import app
from ml import runtime
from optimisation.case_repository import read_case_originals

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import train_m4_models as training


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp("m4-models")
    # Test artifacts use a fast real estimator, not fake probabilities; no
    # claims about its performance. Deployment training selects independently.
    original = training.candidates
    training.candidates = lambda task: ([("logistic_regression", LogisticRegression(max_iter=2000, random_state=42))], [])
    try:
        with threadpool_limits(limits=1):
            for task in ["risk", "cause"]: training.fit_task(task, root / task)
    finally:
        training.candidates = original
    return root


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, artifacts):
    monkeypatch.setenv("ML_MODEL_DIR", str(artifacts))
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "cases.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(service, "write_case", lambda r: True)


def context(task="risk"):
    _, meta = runtime.load_model(task)
    sample = meta["samples"][0]
    return {"task": task, "source": "dataset_sample", **copy.deepcopy(sample)}


def event(**extras):
    return {"product_id": "vaccine_2_8", "excursion_temp_c": 5, "duration_min": 0,
            "mkt_c": 5, "packaging": "intact", **extras}


def test_model_information_samples_and_real_predictions_are_readonly():
    with TestClient(app) as client:
        info = client.get("/api/ml/models").json()
        assert info["risk"]["status"] == info["cause"]["status"] == "ready"
        for task in ["risk", "cause"]:
            samples = client.get("/api/ml/samples/" + task).json()
            assert all("silent_failure" not in s["features"] and "excursion_cause" not in s["features"] for s in samples["samples"])
            response = client.post("/api/ml/predict", json=context(task))
            assert response.status_code == 200, response.text
            r = response.json()
            assert r["status"] == "predicted" and r["advisory_only"] and "disposition" not in r
            assert len(r["explanations"]) == 5
            if task == "risk": assert 0 <= r["failure_probability"] <= 1
            else: assert len(r["top_classes"]) == 3
        assert read_case_originals(service.DISPATCH_DATABASE_URL, legacy_file=service.RUNS_FILE) == ([], {})


def test_optional_models_do_not_replace_rules_or_heuristic_risk():
    with TestClient(app) as client:
        plain = client.post("/api/decide", json=event()).json()
        with_models = client.post("/api/decide", json=event(ml_contexts=[context(), context("cause")]))
        assert with_models.status_code == 200, with_models.text
        result = with_models.json()
        assert {k: v for k, v in result.items() if k not in {"ml_contexts", "ml_assessments"}} == plain
        assert result["disposition"] == "release" and result["reshipment_required"] is False
        assert len(result["ml_assessments"]) == 2


def test_registration_retries_keep_original_ml_snapshot_when_model_disappears(monkeypatch, tmp_path):
    body = event(registration_id="ml-stable", ml_contexts=[context()])
    with TestClient(app) as client:
        first = client.post("/api/case_close", json=body)
        assert first.status_code == 200, first.text
        saved = first.json()
        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path / "missing"))
        repeated = client.post("/api/case_close", json=body)
        assert repeated.status_code == 200 and repeated.json()["ml_assessments"] == saved["ml_assessments"]
        history = client.get("/api/runs").json()
        assert history["count"] == 1 and history["runs"][0]["ml_assessments"] == saved["ml_assessments"]
        changed = copy.deepcopy(body)
        changed["ml_contexts"][0]["source"] = "manual_simulated"
        changed["ml_contexts"][0].pop("sample_id")
        assert client.post("/api/case_close", json=changed).status_code == 409


def test_model_missing_fails_explicitly_but_legacy_rule_only_still_works(monkeypatch, tmp_path):
    model_context = context()
    monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path / "absent"))
    with TestClient(app) as client:
        assert client.get("/api/ml/models").json()["risk"]["status"] == "unavailable"
        assert client.post("/api/ml/predict", json=model_context).status_code == 503
        assert client.post("/api/decide", json=event(ml_contexts=[model_context])).status_code == 503
        assert client.post("/api/case_close", json=event(registration_id="missing", ml_contexts=[model_context])).status_code == 503
        assert client.post("/api/decide", json=event()).status_code == 200
        assert client.get("/api/runs").json()["count"] == 0


@pytest.mark.parametrize("bad", ["missing", "extra_target", "nan", "bool", "temperature_order", "duplicate_task", "invalid_source"])
def test_malformed_contexts_are_rejected_before_registration(bad):
    c = context(); body = event(registration_id="invalid", ml_contexts=[c])
    if bad == "missing": c["features"].pop("door_opens")
    if bad == "extra_target": c["features"]["silent_failure"] = 1
    if bad == "nan": c["features"]["temp_mean_c"] = "NaN"
    if bad == "bool": c["features"]["door_opens"] = True
    if bad == "temperature_order": c["features"]["temp_min_c"] = 90
    if bad == "duplicate_task": body["ml_contexts"].append(copy.deepcopy(c))
    if bad == "invalid_source": c["source"] = "gps_measured"
    with TestClient(app) as client:
        assert client.post("/api/case_close", json=body).status_code == 422
        assert client.get("/api/runs").json()["count"] == 0


def test_sample_identity_mismatch_cannot_be_claimed_as_dataset_observation():
    c = context(); c["features"]["door_opens"] += 1
    with TestClient(app) as client:
        assert client.post("/api/ml/predict", json=c).status_code == 422


def test_extreme_temperature_is_withheld_not_extrapolated_into_scrap_probability():
    c = context(); c.update(source="manual_simulated", sample_id=None)
    c["features"].update(temp_min_c=-80, temp_mean_c=-70, temp_max_c=-60)
    with TestClient(app) as client:
        r = client.post("/api/ml/predict", json=c).json()
        assert r["status"] == "out_of_domain" and "failure_probability" not in r


def test_artifact_integrity_is_checked_before_loading(tmp_path, monkeypatch, artifacts):
    import shutil
    directory = tmp_path / "altered"
    shutil.copytree(artifacts / "risk", directory / "risk")
    target = directory / "risk/model.joblib"
    with target.open("ab") as file: file.write(b"corrupt")
    monkeypatch.setenv("ML_MODEL_DIR", str(directory))
    with TestClient(app) as client:
        assert client.get("/api/ml/models").json()["risk"]["status"] == "unavailable"


def test_root_context_unknown_category_is_withheld():
    c = context("cause"); c.update(source="manual_simulated", sample_id=None)
    c["features"]["equipment_type"] = "unseen_equipment"
    with TestClient(app) as client:
        r = client.post("/api/ml/predict", json=c).json()
        assert r["status"] == "out_of_domain" and "top_classes" not in r
