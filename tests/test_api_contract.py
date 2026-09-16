"""HTTP contract tests for the FastAPI decision service (src/api).

These pin the wire format the demo front-end consumes: semantic decision
fields + localized-by-code risk/evidence, plus grid/batch shapes and the
spec-override sandbox. Parity checks assert API responses equal a direct
engine call for the gold scenario bank.
"""
import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from rule_engine.engine import RuleEngine
from rule_engine.models import ExcursionEvent

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data" / "scenarios" / "scenarios.csv"

VALID = {"vaccine_2_8", "frozen_m20", "insulin_2_8", "mrna_ultracold"}
client = TestClient(app)
engine = RuleEngine()


@pytest.fixture(autouse=True)
def isolated_runs_file(tmp_path, monkeypatch):
    """Point the runs log at a throwaway file so tests never write data/audit/,
    and no-op the KG writer so tests never touch the dev Neo4j graph."""
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(service, "write_case", lambda rec: True)


def _decide_payload(pid, temp, dur, mkt, packaging="intact", stage="transit"):
    return {
        "product_id": pid,
        "excursion_temp_c": temp,
        "duration_min": dur,
        "mkt_c": mkt,
        "packaging": packaging,
        "stage": stage,
    }


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["module"] == "rule_engine"
    assert VALID.issubset(set(body["products"]))


def test_decide_scrap_gold_shape():
    r = client.post("/api/decide", json=_decide_payload("vaccine_2_8", 20.0, 90, 19.0))
    assert r.status_code == 200
    d = r.json()
    assert d["disposition"] == "scrap"
    assert d["reshipment_required"] is True
    assert 1 <= d["rule_no"] <= 6
    assert d["reason"]
    assert d["regulation"]
    assert d["event"]["product_id"] == "vaccine_2_8"
    # evidence chip levels mirror renderEvidence
    ev = d["evidence"]
    assert ev["packaging"] == "ok"
    assert ev["temp"] == "breach"
    assert ev["freeze"] == "ok"
    assert ev["duration"] == "severe"      # 90 >= 2*30
    assert ev["mkt"] == "severe"           # 19 >= 10+3
    risk = d["risk"]
    assert isinstance(risk["score"], int) and 3 <= risk["score"] <= 99
    assert risk["cause_code"] in {"frozen", "packaging", "overtemp",
                                  "duration", "mkt", "near", "inband", "minor"}


def test_decide_unknown_product_is_422():
    r = client.post("/api/decide", json=_decide_payload("not_a_product", 10.0, 5, 9.0))
    assert r.status_code == 422
    assert "unknown product_id" in r.json()["detail"]


def test_decide_sandbox_override_honoured():
    # stock thresholds → retest (mkt 9.5 == threshold − 0.5); relaxed + non-retestable → release
    payload = _decide_payload("vaccine_2_8", 10.0, 20, 9.5)
    stock = client.post("/api/decide", json=payload).json()
    assert stock["disposition"] == "retest"
    payload["spec_override"] = {"allowable_duration_min": 60,
                                "mkt_threshold_c": 12.0, "retestable": False}
    relaxed = client.post("/api/decide", json=payload).json()
    assert relaxed["disposition"] == "release"
    assert relaxed["spec"]["allowable_duration_min"] == 60


def test_grid_shape_and_values():
    durations = [5.0, 60.0, 75.0]       # ascending x-axis mid-points
    mkts = [13.0, 10.0, 9.0]            # descending, top row first
    r = client.post("/api/grid", json={
        "product_id": "vaccine_2_8",
        "excursion_temp_c": 8.0,          # spec.max — matches the UI's cell events
        "packaging": "intact",
        "stage": "transit",
        "durations": durations,
        "mkts": mkts,
    })
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 3
    for row in rows:
        assert len(row) == 3
        for disp in row:
            assert disp in {"release", "retest", "quarantine", "scrap"}
    # top row (MKT 13.0 = threshold + 3) → scrap everywhere (rule 3)
    assert rows[0] == ["scrap", "scrap", "scrap"]


def test_batch_returns_one_trimmed_decision_per_event():
    events = [
        _decide_payload("vaccine_2_8", 20.0, 90, 19.0),
        _decide_payload("vaccine_2_8", 6.0, 10, 5.0),
        _decide_payload("frozen_m20", -30.0, 5, -28.0),
    ]
    r = client.post("/api/decide_batch", json={"events": events})
    assert r.status_code == 200
    decisions = r.json()["decisions"]
    assert len(decisions) == 3
    assert [d["disposition"] for d in decisions] == ["scrap", "release", "release"]
    assert all({"disposition", "rule_no", "reshipment_required"} <= set(d.keys())
               for d in decisions)


def test_decide_matches_engine_on_gold_bank():
    with SCENARIOS.open(newline="", encoding="utf-8") as f:
        for row in list(csv.DictReader(f))[:5]:
            api = client.post("/api/decide", json=_decide_payload(
                row["product_id"], float(row["excursion_temp_c"]), int(row["duration_min"]),
                float(row["mkt_c"]), row["packaging"], row["stage"])).json()
            direct = engine.evaluate(ExcursionEvent(
                scenario_id=row["scenario_id"],
                product_id=row["product_id"],
                excursion_temp_c=float(row["excursion_temp_c"]),
                duration_min=int(row["duration_min"]),
                mkt_c=float(row["mkt_c"]),
                packaging=row["packaging"],
                stage=row["stage"],
            ))
            assert api["disposition"] == direct.disposition.value, row["scenario_id"]
            assert api["rule_no"] == direct.rule_no, row["scenario_id"]
            assert api["reshipment_required"] == direct.reshipment_required


def test_route_plans_closed_reshipment_case():
    closed = client.post(
        "/api/case_close",
        json={**_decide_payload("vaccine_2_8", 20.0, 90, 19.0),
              "destination_facility_id": "H-NUH"},
    ).json()
    response = client.post("/api/route", json={"run_id": closed["run_id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == f"RO-{closed['run_id']}"
    assert body["algorithm"] == "greedy-nearest-insertion"
    assert body["vehicles_used"] >= 1
    assert body["on_time_rate"] == 1.0
    assert body["served_customers"] >= 0
    assert body["target_customers"] == 1
    assert body["served_customers"] == 1
    # Resolve the node id by facility instead of pinning it: node order changed
    # on 2026-09-16 when the supply points were added (H-NUH moved 2 -> 3).
    network = json.loads((ROOT / "data" / "optimisation" / "singapore" / "network.json").read_text())
    h_nuh = next(n["node_id"] for n in network["nodes"] if n["facility_id"] == "H-NUH")
    assert body["routes"][0]["customer_ids"] == [h_nuh]  # H-NUH network node
    assert {
        "time_window_violations", "capacity_violations",
        "depot_return_violations", "vehicle_limit_violations",
    } <= body.keys()
    assert body["routes"] and body["routes"][0]["stops"]
    assert body["geojson"]["type"] == "FeatureCollection"
    assert len(body["geojson"]["features"]) == body["vehicles_used"]


def test_route_rejects_case_that_does_not_need_reshipment():
    closed = client.post(
        "/api/case_close",
        json=_decide_payload("vaccine_2_8", 6.0, 10, 5.0),
    ).json()
    response = client.post("/api/route", json={"run_id": closed["run_id"]})
    assert response.status_code == 422
    assert "does not require reshipment" in response.json()["detail"]


def test_route_unknown_run_is_404():
    response = client.post("/api/route", json={"run_id": "R-NOT-FOUND"})
    assert response.status_code == 404


def test_qa_routes_structured_question(monkeypatch):
    expected = {"status": "ok", "answer": "release: 2", "evidence": []}
    monkeypatch.setattr(service.kg_qa, "disposition_stats", lambda: expected)
    response = client.post("/api/qa", json={"question_type": "disposition_stats"})
    assert response.status_code == 200
    assert response.json() == expected


def test_qa_unsupported_type_returns_structured_status():
    # An intent outside the four supported ones is *answered*, not rejected, so
    # the front-end can render one localised notice per outcome class
    # (proposal §6.5). Needs no graph: the router short-circuits.
    response = client.post("/api/qa", json={"question_type": "what_is_the_weather"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported"
    assert body["evidence"] == []
    assert "unsupported question type" in body["answer"]


def test_qa_requires_identifier_for_question_type():
    response = client.post("/api/qa", json={"question_type": "audit_chain"})
    assert response.status_code == 422


def test_qa_returns_503_when_graph_is_unavailable(monkeypatch):
    def unavailable():
        raise OSError("connection refused")

    monkeypatch.setattr(service.kg_qa, "disposition_stats", unavailable)
    response = client.post("/api/qa", json={"question_type": "disposition_stats"})
    assert response.status_code == 503
    assert response.json()["detail"] == "knowledge graph unavailable"


def test_decide_is_preview_only_never_archives():
    # Live sandbox previews must NOT grow the case history.
    client.post("/api/decide", json=_decide_payload("vaccine_2_8", 20.0, 90, 19.0))
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "runs": []}


def test_case_close_appends_one_record_and_runs_is_newest_first():
    close = {**_decide_payload("vaccine_2_8", 20.0, 90, 19.0), "started_at": "2026-09-09T10:00:00"}
    r1 = client.post("/api/case_close", json=close)                       # scrap
    assert r1.status_code == 200
    rec = r1.json()
    body = client.get("/api/runs").json()
    assert body["count"] == 1
    assert body["runs"][0]["run_id"] == rec["run_id"]
    # archived record = decision + case stamps; event holds only the six inputs
    assert {"run_id", "created_at", "started_at", "disposition", "rule_no",
            "reshipment_required", "rule_path", "event", "spec", "evidence",
            "risk"} <= set(rec)
    assert rec["started_at"] == "2026-09-09T10:00:00"
    assert rec["disposition"] == "scrap" and rec["rule_no"] == 3
    assert rec["event"] == {"product_id": "vaccine_2_8", "excursion_temp_c": 20.0,
                            "duration_min": 90, "mkt_c": 19.0,
                            "packaging": "intact", "stage": "transit"}
    assert "remark" not in rec
    # a second close archives a second, newest-first line
    client.post("/api/case_close", json=_decide_payload("vaccine_2_8", 6.0, 10, 5.0))  # release
    body = client.get("/api/runs").json()
    assert body["count"] == 2
    assert body["runs"][0]["disposition"] == "release"
    assert body["runs"][1]["disposition"] == "scrap"
    assert body["count"] == len(body["runs"])


def test_case_close_stores_optional_remark():
    close = {**_decide_payload("vaccine_2_8", 6.0, 10, 5.0), "remark": "batch 2026-0901" }
    rec = client.post("/api/case_close", json=close).json()
    assert rec["remark"] == "batch 2026-0901"
    assert client.get("/api/runs").json()["runs"][0]["remark"] == "batch 2026-0901"


def test_runs_empty_when_nothing_closed_yet():
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "runs": []}
