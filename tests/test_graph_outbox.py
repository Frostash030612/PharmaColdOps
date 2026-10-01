"""Durable at-least-once graph delivery, immutable payloads and leased claims."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation import case_repository as repo


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "cases.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(service, "write_case", lambda record: False)


def register():
    with TestClient(app) as client:
        return client.post("/api/case_close", json={"registration_id": "outbox-case",
            "product_id": "vaccine_2_8", "excursion_temp_c": 20, "duration_min": 90,
            "mkt_c": 19, "packaging": "intact", "facility_id": "D-NORTHPOINT",
            "destination_facility_id": "H-NUH"}).json()


def test_failed_mirror_is_durable_and_recovers_original_without_reassessment(monkeypatch):
    case = register()
    status = repo.graph_sync_status(service.DISPATCH_DATABASE_URL, case["run_id"])
    assert status["status"] == "pending" and status["attempts"] == 1
    with TestClient(app) as client:
        assert client.post("/api/qa", json={"question_type": "audit_chain", "run_id": case["run_id"]}).status_code == 503
        assert client.get("/api/graph-sync").json()["pending"] == 1
    seen = []
    def write(record):
        seen.append(record)
        return True
    monkeypatch.setattr(service, "write_case", write)
    monkeypatch.setattr(service, "resolve_spec", lambda *a: pytest.fail("must not re-evaluate"))
    assert service.sync_case_graph(force=True)["synced"] == 1
    assert seen[0]["event"] == case["event"] and seen[0]["disposition"] == case["disposition"]
    assert service.sync_case_graph(force=True)["synced"] == 0
    assert len(seen) == 1
    assert repo.graph_sync_status(service.DISPATCH_DATABASE_URL, case["run_id"])["status"] == "synced"


def test_registration_and_queue_commit_atomically(monkeypatch):
    original = service.sync_case_graph
    monkeypatch.setattr(service, "sync_case_graph", lambda **kw: (_ for _ in ()).throw(RuntimeError("process crash")))
    case = register()
    assert repo.graph_sync_status(service.DISPATCH_DATABASE_URL, case["run_id"])["status"] == "pending"
    assert len(repo.registered_records(service.DISPATCH_DATABASE_URL)) == 1
    monkeypatch.setattr(service, "sync_case_graph", original)
    monkeypatch.setattr(service, "write_case", lambda r: True)
    assert service.sync_case_graph()["synced"] == 1


def test_first_registration_freezes_citation_ids(monkeypatch):
    from knowledge_graph import writer
    case = register()
    original = repo.registered_records(service.DISPATCH_DATABASE_URL)[0]
    assert original["graph_evidence"]["regulation_ids"]
    monkeypatch.setattr(writer, "RULE_TO_REGULATIONS", {})
    monkeypatch.setattr(writer, "RULE_TO_SOPS", {})
    captured = []
    monkeypatch.setattr(service, "write_case", lambda r: captured.append(r) or True)
    assert service.sync_case_graph(force=True)["synced"] == 1
    assert captured[0]["graph_evidence"] == original["graph_evidence"]
    assert captured[0]["run_id"] == case["run_id"]


def test_opt_in_api_worker_starts_and_stops(monkeypatch):
    from threading import Event
    called = Event()
    monkeypatch.setenv("KG_SYNC_ENABLED", "1")
    monkeypatch.setattr(service, "sync_case_graph", lambda: called.set())
    with TestClient(app):
        assert called.wait(2)


def test_failed_attempt_backs_off_and_success_is_monotonic(monkeypatch):
    case = register()
    assert service.sync_case_graph()["failed"] == 0  # not due yet
    monkeypatch.setattr(service, "write_case", lambda r: True)
    assert service.sync_case_graph(force=True)["synced"] == 1
    assert repo.graph_sync_status(service.DISPATCH_DATABASE_URL, case["run_id"])["attempts"] == 2


def test_parallel_workers_claim_only_once_and_expired_claim_cannot_overwrite(monkeypatch):
    case = register()
    db = service.DISPATCH_DATABASE_URL
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = [claim for batch in pool.map(lambda _: repo.claim_graph_records(db, force=True), range(16)) for claim in batch]
    assert len(claims) == 1
    assert repo.claim_graph_records(db, force=True) == []
    now = repo.time.time()
    monkeypatch.setattr(repo.time, "time", lambda: now + 61)
    new = repo.claim_graph_records(db)[0]
    assert new["token"] != claims[0]["token"]
    assert repo.finish_graph_claim(db, new, success=True)
    assert not repo.finish_graph_claim(db, claims[0], success=False)
    assert repo.graph_sync_status(db, case["run_id"])["status"] == "synced"


def test_existing_registration_migrates_and_legacy_backfill_deduplicates(tmp_path):
    db = tmp_path / "old.sqlite3"
    record = {"run_id": "OLD", "event": {}, "disposition": "scrap"}
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE case_registrations (registration_id TEXT PRIMARY KEY, request_sha256 TEXT, run_id TEXT UNIQUE, record_json TEXT)")
        connection.execute("INSERT INTO case_registrations VALUES (?,?,?,?)", ("old", "hash", "OLD", json.dumps(record)))
    assert repo.graph_sync_status(db)["pending"] == 1
    repo.enqueue_graph_records(db, [{**record, "disposition": "release"}, {**record, "run_id": "LEGACY"}])
    claims = repo.claim_graph_records(db)
    assert len(claims) == 2
    assert next(c for c in claims if c["run_id"] == "OLD")["record"]["disposition"] == "scrap"
    for claim in claims:
        repo.finish_graph_claim(db, claim, success=True)
    assert repo.requeue_graph_records(db) == 2
    assert repo.graph_sync_status(db)["pending"] == 2


@pytest.mark.needs_db
def test_live_graph_outage_recovery_full_evidence_and_transaction_rollback(monkeypatch):
    from knowledge_graph import writer, qa
    from knowledge_graph.connect import get_driver
    original = writer.get_driver
    monkeypatch.setattr(service, "write_case", writer.write_case)
    monkeypatch.setattr(writer, "get_driver", lambda: (_ for _ in ()).throw(OSError("simulated outage")))
    case = register()
    monkeypatch.setattr(writer, "get_driver", original)
    rid = case["run_id"]
    try:
        assert service.sync_case_graph(force=True)["synced"] == 1
        assert qa.why_disposition(rid)["status"] == "ok"
        chain = qa.audit_chain(rid)
        assert chain["status"] == "ok"
        evidence = {(e["node_type"], e["node_id"]) for e in chain["evidence"]}
        assert {("Facility", "D-NORTHPOINT"), ("Facility", "H-NUH"), ("ReshipmentOrder", f"RO-{rid}")} <= evidence
        assert repo.requeue_graph_records(service.DISPATCH_DATABASE_URL) == 1
        assert service.sync_case_graph(force=True)["synced"] == 1
        with get_driver() as driver:
            assert driver.execute_query("MATCH (e:ExcursionEvent {run_id:$id}) RETURN count(e) AS n", id=rid).records[0]["n"] == 1
        original_chain = writer._write_chain
        def fail_after_chain(tx, params):
            original_chain(tx, params)
            raise ValueError("late write failure must roll back whole transaction")
        monkeypatch.setattr(writer, "_write_chain", fail_after_chain)
        assert not writer.write_case({**case, "run_id": rid + "-ROLLBACK"})
        with get_driver() as driver:
            assert driver.execute_query("MATCH (e:ExcursionEvent {run_id:$id}) RETURN count(e) AS n", id=rid + "-ROLLBACK").records[0]["n"] == 0
    finally:
        with get_driver() as driver:
            driver.execute_query("MATCH (e:ExcursionEvent {run_id:$id}) DETACH DELETE e", id=rid)
            driver.execute_query("MATCH (r:ReshipmentOrder {order_id:$id}) DETACH DELETE r", id=f"RO-{rid}")
