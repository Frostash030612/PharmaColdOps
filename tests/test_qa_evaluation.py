"""Evaluation storage and cleanup cannot pollute or erase normal operations."""
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from api import service
from api.schemas import EventIn
from optimisation.case_repository import read_case_originals

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate_qa as evaluation


@pytest.fixture
def harness(tmp_path, monkeypatch):
    native_db, native_log = tmp_path / "native.sqlite3", tmp_path / "native.jsonl"
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(native_db))
    monkeypatch.setattr(service, "RUNS_FILE", native_log)
    graph = {}
    def write(record):
        graph[record["run_id"]] = record
        return True
    monkeypatch.setattr(service, "write_case", write)
    native = service.close_case(EventIn(product_id="vaccine_2_8", excursion_temp_c=20,
        duration_min=90, mkt_c=19, packaging="intact"), None, registration_id="user-case")
    before = (native_db.read_bytes(), native_log.read_bytes())
    def qa(req):
        if req.question_type == "product_requirements":
            p = next(p for p in json.loads(evaluation.CONFIG.read_text())["products"] if p["product_id"] == req.product_id)
            ids = set(evaluation.PRODUCT_RULES["common"]) | (set(evaluation.PRODUCT_RULES["freeze_sensitive"]) if p["freeze_sensitive"] else set())
            return {"status": "ok", "answer": f"{float(p['storage_min_c'])} {p['allowable_duration_min']}",
                    "evidence": [{"node_type": "Regulation", "node_id": rid} for rid in ids]}
        if req.question_type == "not_a_supported_intent":
            return {"status": "unsupported", "evidence": []}
        r = graph.get(req.run_id)
        if not r:
            return {"status": "no_case", "evidence": []}
        evidence = [{"node_type": "ExcursionEvent", "node_id": r["run_id"]},
                    {"node_type": "Disposition", "node_id": r["disposition"]}]
        evidence += [{"node_type": "Regulation", "node_id": rid} for rid in evaluation.RULE_TO_REGULATIONS[r["rule_no"]]]
        evidence += [{"node_type": "SOP", "node_id": sid} for sid in evaluation.RULE_TO_SOPS[r["rule_no"]]]
        return {"status": "ok", "evidence": evidence,
                "answer": f"{r['disposition'].upper()} {r['reason']} {r['event']['excursion_temp_c']} {r['event']['stage']}"}
    monkeypatch.setattr(service, "qa_view", qa)
    @contextmanager
    def fake_graph(args, info):
        info["mode"] = "fake_for_unit_test"
        info["configured_requested"] = args.configured_test_graph
        yield object()
    monkeypatch.setattr(evaluation, "_graph", fake_graph)
    def delete(driver, rid, prefix):
        assert rid.startswith(prefix)
        graph.pop(rid, None)
    monkeypatch.setattr(evaluation, "_delete_case", delete)
    return native_db, native_log, graph, native, before


def assert_native_unchanged(h):
    db, log, graph, native, before = h
    assert (db.read_bytes(), log.read_bytes()) == before
    assert native["run_id"] in graph
    assert service.DISPATCH_DATABASE_URL == str(db) and service.RUNS_FILE == log


def test_connection_factory_is_shared(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(evaluation.connect, "get_driver", lambda: sentinel)
    assert evaluation._driver() is sentinel


def test_default_cleans_graph_registration_outbox_and_archive(harness, tmp_path):
    out = tmp_path / "eval"
    assert evaluation.main(["evaluate", "--limit", "3", "--workdir", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["checks_run"] == 34 and report["checks_failed"] == 0
    assert report["cleanup"] == {"status": "complete", "cases_removed": 3, "sql_outbox_archive_cleared": True}
    assert report["graph"]["configured_requested"] is False
    assert read_case_originals(out / "cases.sqlite3", legacy_file=out / "runs.jsonl") == ([], {})
    assert len(json.loads((out / "cases.manifest.json").read_text())) == 3
    assert len(harness[2]) == 1
    assert_native_unchanged(harness)


def test_keep_retains_only_isolated_evaluation_data(harness, tmp_path):
    out = tmp_path / "keep"
    assert evaluation.main(["evaluate", "--limit", "2", "--keep", "--workdir", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["cleanup"]["status"] == "retained"
    records, states = read_case_originals(out / "cases.sqlite3", legacy_file=out / "runs.jsonl")
    assert len(records) == len(states) == 2
    assert all(r["run_id"].startswith(report["evaluation_prefix"]) for r in records)
    assert_native_unchanged(harness)


def test_runtime_failure_still_cleans_owned_records(harness, tmp_path, monkeypatch):
    out = tmp_path / "failed"
    monkeypatch.setattr(service, "qa_view", lambda req: (_ for _ in ()).throw(RuntimeError("query failed")))
    assert evaluation.main(["evaluate", "--limit", "2", "--workdir", str(out)]) == 2
    report = json.loads((out / "report.json").read_text())
    assert report["status"] == "error" and report["cleanup"]["cases_removed"] == 1
    assert len(report["created_cases"]) == 1
    assert len(json.loads((out / "cases.manifest.json").read_text())) == 1
    assert read_case_originals(out / "cases.sqlite3", legacy_file=out / "runs.jsonl") == ([], {})
    assert_native_unchanged(harness)


def test_cleanup_failure_preserves_local_recovery_source(harness, tmp_path, monkeypatch):
    out = tmp_path / "cleanup-error"
    monkeypatch.setattr(evaluation, "_delete_case", lambda *a: (_ for _ in ()).throw(OSError("cannot delete graph")))
    assert evaluation.main(["evaluate", "--limit", "1", "--workdir", str(out)]) == 2
    report = json.loads((out / "report.json").read_text())
    assert report["status"] == "error" and report["cleanup"]["status"] == "incomplete_or_no_graph"
    records, states = read_case_originals(out / "cases.sqlite3", legacy_file=out / "runs.jsonl")
    assert len(records) == len(states) == 1
    assert_native_unchanged(harness)


def test_unavailable_graph_is_not_a_zero_case_pass(harness, tmp_path, monkeypatch):
    @contextmanager
    def unavailable(*args):
        raise RuntimeError("not reachable")
        yield  # pragma: no cover
    monkeypatch.setattr(evaluation, "_graph", unavailable)
    out = tmp_path / "unavailable"
    assert evaluation.main(["evaluate", "--workdir", str(out)]) == 2
    report = json.loads((out / "report.json").read_text())
    assert report["status"] == "error" and report["checks_run"] == 0
    assert_native_unchanged(harness)


@pytest.mark.parametrize("argument", ["--workdir", "--report"])
def test_existing_evidence_is_not_overwritten(harness, tmp_path, argument):
    old = tmp_path / "old"
    old.write_text("retain this")
    with pytest.raises(SystemExit): evaluation.main(["evaluate", argument, str(old)])
    assert old.read_text() == "retain this"
    assert_native_unchanged(harness)


def test_zero_limit_is_rejected(harness):
    with pytest.raises(SystemExit): evaluation.main(["evaluate", "--limit", "0"])
    assert_native_unchanged(harness)


def test_graph_cleanup_refuses_another_namespace():
    with pytest.raises(ValueError): evaluation._delete_case(None, "USER-CASE", "RQAEVAL-owned-")


@pytest.mark.needs_db
def test_live_configured_evaluation_preserves_foreign_case_and_never_rebuilds(tmp_path, monkeypatch):
    from knowledge_graph.connect import get_driver
    from knowledge_graph import writer
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "native.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "native.jsonl")
    monkeypatch.setattr(service, "write_case", writer.write_case)
    native = service.close_case(EventIn(product_id="vaccine_2_8", excursion_temp_c=20,
        duration_min=90, mkt_c=19, packaging="intact"), None, registration_id="native-sentinel")
    before = (Path(service.DISPATCH_DATABASE_URL).read_bytes(), service.RUNS_FILE.read_bytes())
    monkeypatch.setattr(evaluation, "load_static", lambda *a: pytest.fail("never rebuild configured graph"))
    out = tmp_path / "live"
    try:
        assert evaluation.main(["evaluate", "--configured-test-graph", "--limit", "3", "--workdir", str(out)]) == 0
        report = json.loads((out / "report.json").read_text())
        with get_driver() as d:
            assert d.execute_query("MATCH (e:ExcursionEvent) WHERE e.run_id STARTS WITH $prefix RETURN count(e) AS n", prefix=report["evaluation_prefix"]).records[0]["n"] == 0
            assert d.execute_query("MATCH (e:ExcursionEvent {run_id:$rid}) RETURN count(e) AS n", rid=native["run_id"]).records[0]["n"] == 1
        assert (Path(service.DISPATCH_DATABASE_URL).read_bytes(), service.RUNS_FILE.read_bytes()) == before
        assert read_case_originals(out / "cases.sqlite3", legacy_file=out / "runs.jsonl") == ([], {})
    finally:
        with get_driver() as d:
            d.execute_query("MATCH (e:ExcursionEvent {run_id:$rid}) DETACH DELETE e", rid=native["run_id"])
            d.execute_query("MATCH (r:ReshipmentOrder {order_id:$rid}) DETACH DELETE r", rid="RO-" + native["run_id"])
