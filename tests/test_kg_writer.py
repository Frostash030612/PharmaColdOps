"""Per-case KG writer tests (M6).

Two layers:

- **graceful failure**: an unreachable graph must never break a case_close —
  the writer logs and returns False (runs always, no DB needed);
- **chain correctness**: one closed case becomes its schema-faithful chain
  (ExcursionEvent → Disposition via ``EVENT_LEADS_TO_DISPOSITION`` edge
  facts, Cause, cited Regulations, followed SOPs, a ReshipmentOrder only
  when flagged), idempotent under replay — skipped when the dev Neo4j
  container (``pharmaneo``) is unreachable.
"""
from __future__ import annotations

import os

import pytest
from neo4j import GraphDatabase

from knowledge_graph import connect, qa, writer

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")

RUN_ID = "RTEST-1"


def _record(run_id: str = RUN_ID, **overrides) -> dict:
    """A realistic close_case record (the shape service._record_run produces).

    Rule 4 cites R-WHO-TRS961-EXCURSION + R-EU-GDP-1.2 and follows
    SOP-GDP-001 + SOP-GDP-003 (RULE_TO_* maps in build_graph).
    """
    rec = {
        "run_id": run_id,
        "created_at": "2026-09-11T10:00:00",
        "disposition": "quarantine",
        "rule_no": 4,
        "reason": "MKT exceeds threshold; quarantine pending assessment.",
        "regulation": "WHO TRS 961 Annex 9: hold for assessment.",
        "reshipment_required": True,
        "rule_path": "temp_ok -> mkt_breach -> rule_4",
        "event": {
            "product_id": "vaccine_2_8",
            "excursion_temp_c": 9.5,
            "duration_min": 30,
            "mkt_c": 13.0,
            "packaging": "intact",
            "stage": "transit",
        },
        "risk": {"score": 55, "cause_code": "duration"},
    }
    rec.update(overrides)
    return rec


def _query(q: str, **params) -> list:
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        return [dict(r) for r in driver.execute_query(q, parameters_=params).records]
    finally:
        driver.close()


def test_write_case_returns_false_when_db_unreachable(monkeypatch):
    # Point at a port nothing listens on; the writer must swallow the error
    # (case_close keeps working while the graph is down).
    monkeypatch.setattr(connect, "URI", "neo4j://localhost:1")
    assert writer.write_case(_record()) is False


@pytest.mark.needs_db
def test_write_case_builds_schema_chain_and_is_idempotent():
    assert writer.write_case(_record()) is True
    assert writer.write_case(_record()) is True  # replay: same chain, no duplicates

    events = _query(
        "MATCH (e:ExcursionEvent {run_id: $rid}) RETURN e", rid=RUN_ID
    )
    assert len(events) == 1
    e = events[0]["e"]
    assert e["product_id"] == "vaccine_2_8"
    assert e["excursion_temp_c"] == 9.5
    assert e["duration_min"] == 30 and e["mkt_c"] == 13.0
    assert e["packaging"] == "intact" and e["stage"] == "transit"

    chain = _query(
        """
        MATCH (e:ExcursionEvent {run_id: $rid})-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
        RETURN d, dis
        """,
        rid=RUN_ID,
    )
    assert len(chain) == 1
    d, dis = chain[0]["d"], chain[0]["dis"]
    assert dis["disposition"] == "quarantine"
    assert d["rule_no"] == 4
    assert d["reshipment_required"] is True
    assert d["risk_score"] == 55
    assert d["cause_code"] == "duration"

    cited = _query(
        """
        MATCH (:ExcursionEvent {run_id: $rid})-[:EVENT_LEADS_TO_DISPOSITION]->()
              <-[:CITES]-(r:Regulation)
        RETURN r.clause_id AS cid
        """,
        rid=RUN_ID,
    )
    assert {r["cid"] for r in cited} == {"R-WHO-TRS961-EXCURSION", "R-EU-GDP-1.2"}

    sops = _query(
        "MATCH (:ExcursionEvent {run_id: $rid})-[:FOLLOWS]->(s:SOP) RETURN s.sop_id AS sid",
        rid=RUN_ID,
    )
    assert {r["sid"] for r in sops} == {"SOP-GDP-001", "SOP-GDP-003"}

    causes = _query(
        """
        MATCH (:ExcursionEvent {run_id: $rid})-[:EVENT_CAUSED_BY]->(c:Cause)
        RETURN c.cause_code AS code
        """,
        rid=RUN_ID,
    )
    assert [r["code"] for r in causes] == ["duration"]

    orders = _query(
        """
        MATCH (:ExcursionEvent {run_id: $rid})-[:TRIGGERS_RESHIPMENT]->(ro:ReshipmentOrder)
        RETURN ro.order_id AS oid
        """,
        rid=RUN_ID,
    )
    assert [r["oid"] for r in orders] == [f"RO-{RUN_ID}"]

    # qa.py reads the same chain (the /api/qa layer consumes these shapes)
    why = qa.why_disposition(RUN_ID)
    assert "QUARANTINE" in why["answer"]
    assert {"R-WHO-TRS961-EXCURSION", "R-EU-GDP-1.2"} <= {
        n["node_id"] for n in why["evidence"]
    }

    audit = qa.audit_chain(RUN_ID)
    assert "QUARANTINE" in audit["answer"]
    node_types = {n["node_type"] for n in audit["evidence"]}
    assert {"ExcursionEvent", "Disposition", "Cause", "Regulation", "SOP"} <= node_types

    # cleanup: remove the test event and its order (concept nodes stay)
    _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=RUN_ID)
    _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
           oid=f"RO-{RUN_ID}")


@pytest.mark.needs_db
def test_release_case_creates_no_reshipment_order():
    assert writer.write_case(_record(
        run_id="RTEST-2", disposition="release", rule_no=1,
        reason="freeze-sensitive product stayed above 0 °C",
        reshipment_required=False,
    )) is True
    assert _query(
        "MATCH (ro:ReshipmentOrder {order_id: 'RO-RTEST-2'}) RETURN ro"
    ) == []
    _query("MATCH (e:ExcursionEvent {run_id: 'RTEST-2'}) DETACH DELETE e")


@pytest.mark.needs_db
def test_facility_edges_when_case_carries_facility_ids():
    # placeholders awaiting A's 9/12 review / C's 9/21 contract: when the
    # case carries the ids, the writer links event→facility and
    # order→destination; unknown ids must never fail the write.
    rec = _record(run_id="RTEST-3")
    rec["event"]["facility_id"] = "W-KN-PIONEER"
    rec["destination_facility_id"] = "H-NUH"
    assert writer.write_case(rec) is True

    loc = _query(
        "MATCH (:ExcursionEvent {run_id: 'RTEST-3'})-[:EVENT_OCCURRED_AT]->(f:Facility) "
        "RETURN f.facility_id AS fid"
    )
    assert [r["fid"] for r in loc] == ["W-KN-PIONEER"]

    dest = _query(
        "MATCH (:ReshipmentOrder {order_id: 'RO-RTEST-3'})-[:RESHIPS_TO]->(f:Facility) "
        "RETURN f.facility_id AS fid"
    )
    assert [r["fid"] for r in dest] == ["H-NUH"]

    # audit_chain surfaces the occurrence facility
    audit = qa.audit_chain("RTEST-3")
    assert "Kuehne" in audit["answer"] or "PIONEER" in audit["answer"]
    assert ("Facility", "W-KN-PIONEER") in {
        (n["node_type"], n["node_id"]) for n in audit["evidence"]
    }

    # unknown facility id → no edge, but the write still succeeds
    rec2 = _record(run_id="RTEST-4")
    rec2["event"]["facility_id"] = "NOT-A-FACILITY"
    assert writer.write_case(rec2) is True
    assert _query(
        "MATCH (:ExcursionEvent {run_id: 'RTEST-4'})-[:EVENT_OCCURRED_AT]->() RETURN 1"
    ) == []

    for rid in ("RTEST-3", "RTEST-4"):
        _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=rid)
        _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
               oid=f"RO-{rid}")
