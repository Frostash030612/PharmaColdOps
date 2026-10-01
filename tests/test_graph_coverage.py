"""Coverage cannot be inferred from an old successful queue acknowledgement."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from knowledge_graph.coverage import audit_cases, compare_case
from optimisation import case_repository as repo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_case_graph import main as check_main


def record():
    return {"run_id": "COVERAGE", "created_at": "2026-10-01T09:00:00", "disposition": "scrap",
        "rule_no": 3, "reason": "severe excursion", "rule_path": "severe->scrap", "regulation": "demo principle",
        "reshipment_required": True, "graph_evidence": {"regulation_ids": ["REG"], "sop_ids": ["SOP"]},
        "risk": {"score": 99, "cause_code": "overtemp"},
        "event": {"product_id": "vaccine_2_8", "excursion_temp_c": 20, "duration_min": 90, "mkt_c": 19,
                  "packaging": "intact", "stage": "transit", "facility_id": "D-NORTHPOINT", "destination_facility_id": "H-NUH"}}


def static():
    return {"Product": {"vaccine_2_8"}, "Regulation": {"REG"}, "SOP": {"SOP"}, "Facility": {"D-NORTHPOINT", "H-NUH"}}


def actual():
    r = record()
    return {"event": {**r["event"], "created_at": r["created_at"]},
        "decisions": [{"disposition": "scrap", "facts": {"rule_no": 3, "reason": r["reason"],
            "rule_path": r["rule_path"], "regulation": r["regulation"], "reshipment_required": True,
            "risk_score": 99, "cause_code": "overtemp", "decided_at": r["created_at"]}}],
        "regulations": ["REG"], "sops": ["SOP"], "causes": ["overtemp"], "locations": ["D-NORTHPOINT"],
        "orders": ["RO-COVERAGE"], "destinations": ["H-NUH"]}


def test_synced_marker_does_not_hide_a_missing_event():
    result = compare_case(record(), None, static(), "synced")
    assert result["coverage"] == "missing" and result["repairable"]
    assert result["queue_status"] == "synced"


def test_healthy_case_has_no_missing_or_conflicting_evidence():
    result = compare_case(record(), actual(), static(), "synced")
    assert result["coverage"] == "complete" and result["issues"] == [] and not result["repairable"]


def test_duplicate_events_cannot_be_hidden_by_row_deduplication():
    a = actual()
    a["duplicate_event"] = True
    result = compare_case(record(), a, static())
    assert result["coverage"] == "conflict" and not result["repairable"]


@pytest.mark.parametrize("field", ["regulations", "sops", "causes", "locations", "orders", "destinations"])
def test_each_required_evidence_edge_is_checked(field):
    a = actual()
    a[field] = []
    result = compare_case(record(), a, static())
    assert result["coverage"] == "incomplete" and result["repairable"]
    assert {"code": "missing_edges", "field": field} in result["issues"]


@pytest.mark.parametrize("change", ["decision", "event", "extra_edge", "duplicate_edge"])
def test_conflicts_are_reported_and_never_automatically_repaired(change):
    a = actual()
    if change == "decision": a["decisions"][0]["disposition"] = "release"
    if change == "event": a["event"]["product_id"] = "frozen_m20"
    if change == "extra_edge": a["regulations"].append("UNRELATED")
    if change == "duplicate_edge": a["sops"].append("SOP")
    result = compare_case(record(), a, static())
    assert result["coverage"] == "conflict" and not result["repairable"]


def test_missing_static_source_is_not_masked_by_replay():
    s = static()
    s["Regulation"] = set()
    result = compare_case(record(), actual(), s)
    assert result["coverage"] == "incomplete" and not result["repairable"]


def test_read_only_inventory_does_not_create_db_or_migrate_tables(tmp_path):
    path = tmp_path / "nonexistent.sqlite3"
    assert repo.read_case_originals(path) == ([], {})
    assert not path.exists()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE dispatch_runs (id TEXT)")
    before = path.read_bytes()
    assert repo.read_case_originals(path) == ([], {})
    assert path.read_bytes() == before


def test_relational_original_wins_over_mirror_and_bad_legacy_refused(tmp_path):
    path = tmp_path / "db.sqlite3"
    r = record()
    repo.register_once(path, "reg", "digest", r)
    legacy = tmp_path / "old.jsonl"
    legacy.write_text(json.dumps({**r, "disposition": "release"}) + "\n")
    originals, states = repo.read_case_originals(path, legacy_file=legacy)
    assert originals[0]["disposition"] == "scrap" and states == {"COVERAGE": "pending"}
    legacy.write_text("{incomplete\n")
    with pytest.raises(json.JSONDecodeError): repo.read_case_originals(path, legacy_file=legacy)


def test_selective_requeue_does_not_touch_unrelated_records_or_live_claims(tmp_path):
    path = tmp_path / "db.sqlite3"
    repo.enqueue_graph_records(path, [record(), {**record(), "run_id": "OTHER"}, {**record(), "run_id": "LIVE"}])
    claims = repo.claim_graph_records(path)
    for c in claims:
        if c["run_id"] != "LIVE": repo.finish_graph_claim(path, c, success=True)
    assert repo.requeue_graph_records(path, run_ids=["COVERAGE", "LIVE"]) == 1
    assert repo.graph_sync_status(path, "OTHER")["status"] == "synced"
    assert repo.graph_sync_status(path, "LIVE")["status"] == "processing"


def test_cli_unavailable_fails_without_a_fake_zero_count(monkeypatch, tmp_path):
    import check_case_graph
    monkeypatch.setattr(check_case_graph, "read_case_originals", lambda *a, **k: ([], {}))
    monkeypatch.setattr(check_case_graph, "audit_cases", lambda *a, **k: (_ for _ in ()).throw(OSError("graph unreachable")))
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["check_case_graph", "--report", str(report)])
    assert check_main() == 1
    result = json.loads(report.read_text())
    assert result["status"] == "unavailable" and "case_count" not in result
    with pytest.raises(SystemExit): check_main()  # cannot overwrite the report


@pytest.mark.parametrize("legacy_only", [False, True])
def test_missing_graph_of_known_case_is_503_not_no_case(tmp_path, monkeypatch, legacy_only):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "db.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(service, "write_case", lambda r: True)
    monkeypatch.setattr(service.kg_qa, "audit_chain", lambda rid: {"status": "no_case", "answer": "no case", "evidence": []})
    if legacy_only:
        service.RUNS_FILE.write_text(json.dumps(record()) + "\n")
        rid = "COVERAGE"
    else:
        with TestClient(app) as client:
            rid = client.post("/api/case_close", json={"registration_id": "qa-gap", **record()["event"]}).json()["run_id"]
    with TestClient(app) as client:
        response = client.post("/api/qa", json={"question_type": "audit_chain", "run_id": rid})
        assert response.status_code == 503 and "chain missing" in response.text
        unknown = client.post("/api/qa", json={"question_type": "audit_chain", "run_id": "TRULY-UNKNOWN"})
        assert unknown.status_code == 200 and unknown.json()["status"] == "no_case"


@pytest.mark.needs_db
def test_live_readonly_audit_detects_loss_and_repairs_only_missing_chain(tmp_path, monkeypatch):
    from knowledge_graph.connect import get_driver
    from knowledge_graph.writer import write_case
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "db.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "cases.jsonl")
    monkeypatch.setattr(service, "write_case", write_case)
    with TestClient(app) as client:
        r = client.post("/api/case_close", json={"registration_id": "live-coverage", **record()["event"]}).json()
    rid = r["run_id"]
    try:
        originals, states = repo.read_case_originals(service.DISPATCH_DATABASE_URL, legacy_file=service.RUNS_FILE)
        assert audit_cases(originals, states)["status"] == "passed"
        before = Path(service.DISPATCH_DATABASE_URL).read_bytes()
        audit_cases(originals, states)
        assert Path(service.DISPATCH_DATABASE_URL).read_bytes() == before
        with get_driver() as d:
            d.execute_query("MATCH (e:ExcursionEvent {run_id:$rid})-[l:EVENT_OCCURRED_AT]->() DELETE l", rid=rid)
        result = audit_cases(originals, states)
        assert result["coverage"]["incomplete"] == 1 and result["repairable_count"] == 1
        monkeypatch.setattr(sys, "argv", ["check_case_graph", "--repair"])
        assert check_main() == 0
        with get_driver() as d:
            d.execute_query("MATCH (e:ExcursionEvent {run_id:$rid}) DETACH DELETE e", rid=rid)
        assert audit_cases(originals, states)["coverage"]["missing"] == 1
        assert check_main() == 0
        # Wrong extra facts must not be deleted under the guise of recovery.
        with get_driver() as d:
            d.execute_query("MATCH (e:ExcursionEvent {run_id:$rid}) MERGE (d:Disposition {disposition:'release'}) MERGE (e)-[:EVENT_LEADS_TO_DISPOSITION]->(d)", rid=rid)
        assert check_main() == 1
        assert audit_cases(originals, states)["coverage"]["conflict"] == 1
    finally:
        with get_driver() as d:
            d.execute_query("MATCH (e:ExcursionEvent {run_id:$rid}) DETACH DELETE e", rid=rid)
            d.execute_query("MATCH (r:ReshipmentOrder {order_id:$id}) DETACH DELETE r", id="RO-" + rid)
