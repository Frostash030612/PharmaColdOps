"""Knowledge-graph QA query tests (M6, W1-D "QA API / evidence check").

``qa.py`` is what ``/api/qa`` serves: four parameterised Cypher queries that
must return (a) *this case's* evidence and (b) evidence tied to the rule that
actually fired — not a generic pile of citations (proposal §6.5; risk table
§11 "问答引用无关或缺失证据"). The API-level tests in
``test_api_contract.py`` only exercise the routing with monkeypatched stubs,
so without this file the Cypher itself is never executed.

Cases are written through ``knowledge_graph.writer`` — the same path
``POST /api/case_close`` takes — so the queries read exactly the shapes
production writes. Every test here needs the dev Neo4j (``docker compose up -d``) and is
skipped when it is unreachable (``tests/conftest.py``); each test cleans up the
ExcursionEvent / ReshipmentOrder it created and leaves the static graph alone.

Known state covered as-is (W1 follow-up, not a bug): the "no case" answer is a
plain string and there is no machine-readable ``status`` yet — the "no case"
tests below pin today's behaviour so the planned
``ok | no_case | insufficient_evidence | unsupported`` field cannot land
silently.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from knowledge_graph import qa, writer
from knowledge_graph.build_graph import PRODUCT_RULES, RULE_TO_REGULATIONS, RULE_TO_SOPS

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "src" / "rule_engine" / "rules_config.json"

# Real facility ids from C's Singapore network.json (the same vocabulary the
# KG Facility nodes are built from, so a case carrying them gets real edges).
DEPOT = "W-KN-PIONEER"
DESTINATION = "H-NUH"


def _query(q: str, **params) -> list:
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        return [dict(r) for r in driver.execute_query(q, parameters_=params).records]
    finally:
        driver.close()


def _config_products() -> dict:
    return {
        p["product_id"]: p
        for p in json.loads(CONFIG.read_text(encoding="utf-8"))["products"]
    }


def _record(run_id: str, **overrides) -> dict:
    """A realistic close_case record: rule 4 → quarantine + reshipment."""
    rec = {
        "run_id": run_id,
        "created_at": "2026-09-13T10:00:00",
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


@pytest.fixture
def closed_case():
    """One closed case written via the writer; removed afterwards."""
    run_id = "RQATEST-" + uuid.uuid4().hex[:8]
    rec = _record(run_id)
    assert writer.write_case(rec) is True
    try:
        yield run_id, rec
    finally:
        _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=run_id)
        _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
               oid=f"RO-{run_id}")


def _with_facilities(run_id: str) -> dict:
    rec = _record(run_id)
    rec["event"]["facility_id"] = DEPOT
    rec["destination_facility_id"] = DESTINATION
    return rec


# --------------------------------------------------------------------------
# why_disposition — the "为何隔离" answer plus rule-level evidence
# --------------------------------------------------------------------------

@pytest.mark.needs_db
def test_why_disposition_answers_the_case_and_cites_the_fired_rule(closed_case):
    run_id, rec = closed_case

    why = qa.why_disposition(run_id)
    answer = why["answer"]
    assert why["status"] == "ok"

    assert "QUARANTINE" in answer
    assert rec["reason"] in answer
    assert "9.5" in answer and "30" in answer and "13.0" in answer

    # Evidence must match the rule that fired (RULE_TO_* maps are what the
    # writer used to build the edges), not every regulation in the graph.
    regs = {n["node_id"] for n in why["evidence"] if n["node_type"] == "Regulation"}
    sops = {n["node_id"] for n in why["evidence"] if n["node_type"] == "SOP"}
    assert regs == set(RULE_TO_REGULATIONS[4])
    assert sops == set(RULE_TO_SOPS[4])

    # The /api/qa contract the front-end renders: three non-empty strings.
    for item in why["evidence"]:
        assert set(item) == {"node_type", "node_id", "summary"}
        assert all(isinstance(item[k], str) and item[k] for k in item)


@pytest.mark.needs_db
def test_audit_chain_surfaces_the_occurrence_facility():
    run_id = "RQATEST-" + uuid.uuid4().hex[:8]
    assert writer.write_case(_with_facilities(run_id)) is True
    try:
        chain = qa.audit_chain(run_id)
        answer = chain["answer"]
        assert chain["status"] == "ok"

        # event → disposition → cause, with the occurrence facility named
        assert "QUARANTINE" in answer
        depot_name = _query(
            "MATCH (f:Facility {facility_id: $fid}) RETURN f.name AS name", fid=DEPOT
        )[0]["name"]
        assert depot_name in answer

        pairs = {(n["node_type"], n["node_id"]) for n in chain["evidence"]}
        assert ("ExcursionEvent", run_id) in pairs
        assert ("Disposition", "quarantine") in pairs
        assert ("Cause", "duration") in pairs
        assert ("Facility", DEPOT) in pairs
    finally:
        _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=run_id)
        _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
               oid=f"RO-{run_id}")


@pytest.mark.needs_db
def test_facility_edges_are_written_for_a_case_carrying_facility_ids():
    """The writer's facility edges, read back independently of qa.py."""
    run_id = "RQATEST-" + uuid.uuid4().hex[:8]
    assert writer.write_case(_with_facilities(run_id)) is True
    try:
        assert _query(
            "MATCH (:ExcursionEvent {run_id: $rid})-[:EVENT_OCCURRED_AT]->(f:Facility) "
            "RETURN f.facility_id AS fid", rid=run_id
        ) == [{"fid": DEPOT}]
        assert _query(
            "MATCH (:ReshipmentOrder {order_id: $oid})-[:RESHIPS_TO]->(f:Facility) "
            "RETURN f.facility_id AS fid", oid=f"RO-{run_id}"
        ) == [{"fid": DESTINATION}]
    finally:
        _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=run_id)
        _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
               oid=f"RO-{run_id}")


@pytest.mark.needs_db
def test_audit_chain_surfaces_the_reshipment_destination():
    """The real ``RESHIPS_TO`` edge reaches both the evidence list and the answer."""
    run_id = "RQATEST-" + uuid.uuid4().hex[:8]
    assert writer.write_case(_with_facilities(run_id)) is True
    try:
        chain = qa.audit_chain(run_id)
        assert chain["status"] == "ok"

        pairs = {(n["node_type"], n["node_id"]) for n in chain["evidence"]}
        assert ("Facility", DESTINATION) in pairs
        assert ("ReshipmentOrder", f"RO-{run_id}") in pairs

        dest_name = _query(
            "MATCH (f:Facility {facility_id: $fid}) RETURN f.name AS name", fid=DESTINATION
        )[0]["name"]
        assert dest_name in chain["answer"]
    finally:
        _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=run_id)
        _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
               oid=f"RO-{run_id}")


@pytest.mark.needs_db
def test_why_disposition_without_citations_is_insufficient_evidence():
    """A case whose fired rule maps to no citation answers "no evidence".

    KG_SCHEMA §4 promises 无证据不回答; borrowing unrelated regulations would
    fake support, so the status must say so instead.
    """
    run_id = "RQATEST-" + uuid.uuid4().hex[:8]
    rec = _record(run_id, rule_no=0, reason="unmapped rule (no citations)")
    assert writer.write_case(rec) is True
    try:
        why = qa.why_disposition(run_id)
        assert why["status"] == "insufficient_evidence"
        assert why["evidence"] == []
        # The case itself is still described — only the citations are missing.
        assert run_id in why["answer"]
    finally:
        _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=run_id)
        _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
               oid=f"RO-{run_id}")


@pytest.mark.needs_db
def test_why_disposition_unknown_run_answers_no_case_without_evidence():
    why = qa.why_disposition("RQATEST-" + uuid.uuid4().hex)
    assert why["evidence"] == []
    assert why["status"] == "no_case"
    assert "no decision recorded" in why["answer"]


@pytest.mark.needs_db
def test_audit_chain_unknown_run_answers_no_case_without_evidence():
    chain = qa.audit_chain("RQATEST-" + uuid.uuid4().hex)
    assert chain["evidence"] == []
    assert chain["status"] == "no_case"
    assert "no decision recorded" in chain["answer"]


# --------------------------------------------------------------------------
# product_requirements — thresholds + governing clauses per product
# --------------------------------------------------------------------------

@pytest.mark.needs_db
def test_product_requirements_thresholds_match_rules_config():
    common = set(PRODUCT_RULES["common"])

    for product_id, cfg in _config_products().items():
        got = qa.product_requirements(product_id)
        answer = got["answer"]

        # The KG node is built from A's config, so the answer must show the
        # config's numbers — a drift guard, same spirit as test_config_sync.
        assert str(float(cfg["storage_min_c"])) in answer
        assert str(float(cfg["storage_max_c"])) in answer
        assert str(cfg["allowable_duration_min"]) in answer
        assert str(float(cfg["mkt_threshold_c"])) in answer
        assert f"freeze-sensitive: {cfg['freeze_sensitive']}" in answer

        expected = set(common)
        if cfg["freeze_sensitive"]:
            expected |= set(PRODUCT_RULES["freeze_sensitive"])
        cited = {n["node_id"] for n in got["evidence"]}
        assert cited == expected
        assert all(n["node_type"] == "Regulation" for n in got["evidence"])
        assert got["status"] == "ok"


@pytest.mark.needs_db
def test_product_requirements_unknown_product_is_empty():
    got = qa.product_requirements("not_a_product")
    assert got["evidence"] == []
    assert got["status"] == "no_case"
    assert "unknown product" in got["answer"]


# --------------------------------------------------------------------------
# disposition_stats — aggregate over every closed case
# --------------------------------------------------------------------------

@pytest.mark.needs_db
def test_disposition_stats_matches_an_independent_count():
    rows = _query(
        """
        MATCH (:ExcursionEvent)-[:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
        RETURN dis.disposition AS disposition, count(*) AS n
        ORDER BY disposition
        """
    )
    got = qa.disposition_stats()
    assert got["evidence"] == []
    if rows:
        expected = "; ".join(f"{r['disposition']}: {r['n']}" for r in rows)
        assert got["status"] == "ok"
        assert got["answer"] == expected
    else:
        # An empty graph is "no case", not "insufficient evidence".
        assert got["status"] == "no_case"


@pytest.mark.needs_db
def test_disposition_stats_counts_a_newly_closed_case(closed_case):
    run_id, rec = closed_case

    rows = _query(
        """
        MATCH (:ExcursionEvent)-[:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
        RETURN dis.disposition AS disposition, count(*) AS n
        ORDER BY disposition
        """
    )
    counted = {r["disposition"]: r["n"] for r in rows}
    assert counted.get("quarantine", 0) >= 1

    got = qa.disposition_stats()
    assert got["status"] == "ok"
    assert "quarantine:" in got["answer"]
    assert str(counted["quarantine"]) in got["answer"]


@pytest.mark.needs_db
def test_cause_context_aggregates_the_cases_own_cause(closed_case):
    """「该原因最常见场景」: the cause comes from the case, the split from real edges."""
    run_id, rec = closed_case
    cause = rec["risk"]["cause_code"]

    got = qa.cause_context(run_id)
    assert got["status"] == "ok"
    assert cause in got["answer"]

    # The aggregation must agree with an independent count of the same edges.
    total = _query(
        """
        MATCH (e:ExcursionEvent)-[:EVENT_CAUSED_BY]->(c:Cause {cause_code: $code})
        RETURN count(e) AS n
        """,
        code=cause,
    )[0]["n"]
    assert f"{total} closed case(s)" in got["answer"]

    pairs = {(e["node_type"], e["node_id"]) for e in got["evidence"]}
    assert ("Cause", cause) in pairs
    assert pairs <= {("Cause", cause)} | {
        ("ExcursionEvent", r) for r in
        {e["node_id"] for e in got["evidence"] if e["node_type"] == "ExcursionEvent"}
    }
    assert run_id in {e["node_id"] for e in got["evidence"]}


@pytest.mark.needs_db
def test_cause_context_unknown_run_or_code_is_no_case():
    # explicit code that no case carries
    by_code = qa.cause_context(cause_code="not_a_recorded_cause")
    assert by_code["status"] == "no_case" and by_code["evidence"] == []
    # a run_id whose case (and therefore cause) does not exist
    by_run = qa.cause_context(run_id="RQATEST-" + uuid.uuid4().hex)
    assert by_run["status"] == "no_case" and by_run["evidence"] == []


@pytest.mark.needs_db
def test_evidence_is_not_shared_between_cases_with_the_same_disposition():
    """Regression guard for the 2026-09-13 CITES scoping fix.

    Citations used to hang off the shared ``Disposition`` node, so a case whose
    rule cited one clause inherited every clause any other case with the same
    disposition had ever cited. Two quarantine cases on rules 3 and 4 must now
    report only their own rule's citations.
    """
    rows = {3: "RQATEST-" + uuid.uuid4().hex[:8], 4: "RQATEST-" + uuid.uuid4().hex[:8]}
    records = {
        rule: _record(
            run_id,
            disposition="quarantine",
            rule_no=rule,
            reason=f"rule {rule} quarantine",
            reshipment_required=True,
        )
        for rule, run_id in rows.items()
    }
    for rec in records.values():
        assert writer.write_case(rec) is True
    try:
        cited = {}
        for rule, run_id in rows.items():
            why = qa.why_disposition(run_id)
            assert why["status"] == "ok"
            cited[rule] = {
                n["node_id"] for n in why["evidence"] if n["node_type"] == "Regulation"
            }

        assert cited[3] == set(RULE_TO_REGULATIONS[3])
        assert cited[4] == set(RULE_TO_REGULATIONS[4])
        # The whole point: the two cases share a disposition but not evidence.
        assert cited[3] != cited[4]
        assert "R-EU-GDP-1.2" not in cited[3], "rule 3 inherited rule 4's citation"
    finally:
        for run_id in rows.values():
            _query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e", rid=run_id)
            _query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
                   oid=f"RO-{run_id}")
