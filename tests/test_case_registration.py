"""Registration identity, durable first outcome, concurrent workers and retry recovery."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.case_repository import registered_records

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    writes = []
    monkeypatch.setattr(service, "write_case", lambda record: writes.append(record["run_id"]))
    return writes


def body(key="reg-1", **changes):
    return {"registration_id": key, "product_id": "vaccine_2_8", "excursion_temp_c": 20,
            "duration_min": 90, "mkt_c": 19, "packaging": "intact", "stage": "transit",
            "started_at": "2026-10-01T09:00:00+08:00", **changes}


def test_retry_keeps_one_record_and_one_graph_mirror(isolated):
    first = client.post("/api/case_close", json=body())
    second = client.post("/api/case_close", json=body())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert client.get("/api/runs").json()["count"] == 1
    assert len(service.RUNS_FILE.read_text().splitlines()) == 1
    assert isolated == [first.json()["run_id"]]


@pytest.mark.parametrize("changes", [{"duration_min": 91}, {"remark": "another event"},
    {"started_at": "2026-10-01T10:00:00+08:00"}, {"spec_override": {"allowable_duration_min": 60}}])
def test_reusing_identity_for_changed_inputs_is_a_conflict(changes):
    assert client.post("/api/case_close", json=body()).status_code == 200
    response = client.post("/api/case_close", json=body(**changes))
    assert response.status_code == 409
    assert client.get("/api/runs").json()["count"] == 1


def test_identical_incidents_with_different_keys_are_not_merged():
    first = client.post("/api/case_close", json=body("reg-1")).json()
    second = client.post("/api/case_close", json=body("reg-2")).json()
    assert first["run_id"] != second["run_id"]
    assert client.get("/api/runs").json()["count"] == 2


def test_legacy_clients_without_key_remain_distinct():
    payload = body()
    payload.pop("registration_id")
    assert client.post("/api/case_close", json=payload).status_code == 200
    assert client.post("/api/case_close", json=payload).status_code == 200
    assert client.get("/api/runs").json()["count"] == 2


def test_parallel_workers_return_the_same_committed_record(isolated):
    def register(_):
        with TestClient(app) as worker:
            result = worker.post("/api/case_close", json=body())
            assert result.status_code == 200, result.text
            return result.json()["run_id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        run_ids = list(pool.map(register, range(16)))
    assert len(set(run_ids)) == 1
    assert len(registered_records(service.DISPATCH_DATABASE_URL)) == 1
    assert len(isolated) == 1


def test_successful_snapshot_is_not_recomputed_when_rules_change(monkeypatch):
    first = client.post("/api/case_close", json=body()).json()
    monkeypatch.setattr(service, "resolve_spec", lambda *args: (_ for _ in ()).throw(AssertionError("must not recompute")))
    second = client.post("/api/case_close", json=body())
    assert second.status_code == 200
    assert first == second.json()


def test_missing_json_mirror_does_not_hide_committed_registration(monkeypatch):
    monkeypatch.setattr(service, "RUNS_FILE", service.RUNS_FILE / "missing" / "mirror.jsonl")
    monkeypatch.setattr(service, "_mirror_record", lambda record: None)
    first = client.post("/api/case_close", json=body()).json()
    assert not service.RUNS_FILE.exists()
    history = client.get("/api/runs").json()
    assert history["count"] == 1 and history["runs"][0]["run_id"] == first["run_id"]


def test_database_failure_before_commit_does_not_report_registration_success(monkeypatch):
    original = service.register_once
    monkeypatch.setattr(service, "register_once", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
    response = client.post("/api/case_close", json=body())
    assert response.status_code == 503
    assert not registered_records(service.DISPATCH_DATABASE_URL)
    assert not service.RUNS_FILE.exists()
    monkeypatch.setattr(service, "register_once", original)
    assert client.post("/api/case_close", json=body()).status_code == 200


def test_failure_after_commit_replays_without_duplicate(monkeypatch):
    original = service._registration_response
    monkeypatch.setattr(service, "_registration_response", lambda record: (_ for _ in ()).throw(RuntimeError("response unavailable")))
    assert client.post("/api/case_close", json=body()).status_code == 503
    assert len(registered_records(service.DISPATCH_DATABASE_URL)) == 1
    monkeypatch.setattr(service, "_registration_response", original)
    assert client.post("/api/case_close", json=body()).status_code == 200
    assert client.get("/api/runs").json()["count"] == 1


def test_legacy_json_and_database_mirror_are_deduplicated_and_bad_lines_skipped():
    first = client.post("/api/case_close", json=body()).json()
    with service.RUNS_FILE.open("a") as handle:
        handle.write("{incomplete\n")
        handle.write(json.dumps({**first, "run_id": "LEGACY", "created_at": "2026-09-01T09:00:00"}) + "\n")
    result = client.get("/api/runs").json()
    assert result["count"] == 2
    assert {record["run_id"] for record in result["runs"]} == {first["run_id"], "LEGACY"}


def test_graph_failure_never_erases_a_durable_registration(monkeypatch):
    monkeypatch.setattr(service, "write_case", lambda record: (_ for _ in ()).throw(OSError("graph down")))
    response = client.post("/api/case_close", json=body())
    assert response.status_code == 200
    assert client.get("/api/runs").json()["count"] == 1


def test_validation_refusal_does_not_claim_the_key():
    assert client.post("/api/case_close", json=body(product_id="missing")).status_code == 422
    assert not registered_records(service.DISPATCH_DATABASE_URL)
    assert client.post("/api/case_close", json=body()).status_code == 200
