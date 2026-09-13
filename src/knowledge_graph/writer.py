"""Per-case KG writer: one closed ``case_close`` run becomes its decision chain.

Follows ``docs/KG_SCHEMA_v1.md`` §2–§3: the event is keyed by ``run_id``
(idempotent MERGE — replaying a run overwrites its chain, schema 纪律 3);
disposition facts live on the ``EVENT_LEADS_TO_DISPOSITION`` edge (no
per-case Decision node); ``Cause`` is the deterministic API risk code;
regulations are cited by the disposition concept via the rule→regulation
map; SOPs hang off the event via ``FOLLOWS`` (schema ✚ EVENT_FOLLOWS_SOP,
added 2026-09-11, flagged for review). A ``ReshipmentOrder`` is only created
when the engine flagged ``reshipment_required`` (M3→M5 anchor). When the
case carries facility ids — optional, the case-input contract does not pin
them yet (A 9/12 review, C 9/21 order contract) — the event is additionally
linked to the facility where it occurred (``EVENT_OCCURRED_AT``) and the
reshipment order to its destination (``RESHIPS_TO``); the field names are
placeholders, documented in KG_SCHEMA §2/§3.

Best-effort by design: ``data/audit/runs.jsonl`` stays the source of truth.
If Neo4j is unreachable the writer logs and returns False — closing a case
must never fail because the graph is down.
"""
from __future__ import annotations

import logging

from .build_graph import RULE_TO_REGULATIONS, RULE_TO_SOPS
from .connect import get_driver

log = logging.getLogger("uvicorn.error")


def write_case(record: dict) -> bool:
    """Write one closed case (full close_case record, ``run_id`` included).

    Returns True when the chain was written, False on any failure — errors
    are logged, never raised.
    """
    run_id = record["run_id"]
    ev = record["event"]
    risk = record.get("risk") or {}
    disposition = record["disposition"]
    rule_no = record.get("rule_no") or 0
    cause_code = risk.get("cause_code", "inband")
    # Optional facility linkage (forward-compatible): the case-input
    # contract carries no facility fields yet — A's 9/12 review and C's
    # 9/21 order contract will pin the names; these are placeholders
    # (KG_SCHEMA §2/§3). When present, the event links to where it occurred
    # and the reshipment order to its destination; when absent, the chain
    # is written exactly as before.
    facility_id = ev.get("facility_id")
    dest_id = record.get("destination_facility_id") or ev.get("destination_facility_id")
    params = {
        "run_id": run_id,
        "product_id": ev["product_id"],
        "temp": ev["excursion_temp_c"],
        "duration": ev["duration_min"],
        "mkt": ev["mkt_c"],
        "packaging": ev["packaging"],
        "stage": ev["stage"],
        "created_at": record.get("created_at", ""),
        "disposition": disposition,
        # schema §2: concept node mirrors the engine's reshipment default
        "reship_default": disposition in ("scrap", "quarantine"),
        "rule_no": rule_no,
        "reason": record.get("reason", ""),
        "rule_path": record.get("rule_path", ""),
        "regulation": record.get("regulation", ""),
        "reship": bool(record.get("reshipment_required")),
        "score": risk.get("score"),
        "cause_code": cause_code,
        "decided_at": record.get("created_at", ""),
        "reg_ids": RULE_TO_REGULATIONS.get(rule_no, []),
        "sop_ids": RULE_TO_SOPS.get(rule_no, []),
        "order_id": f"RO-{run_id}",
    }
    try:
        driver = get_driver()
        # Pre-check facility ids once (for the warning); unknown ids must
        # not fail the write — the chain lands without the facility edge.
        known = set()
        if facility_id or dest_id:
            known = {r["fid"] for r in driver.execute_query(
                "MATCH (f:Facility) WHERE f.facility_id IN $ids RETURN f.facility_id AS fid",
                parameters_={"ids": [x for x in (facility_id, dest_id) if x]},
            ).records}
            for fid in (facility_id, dest_id):
                if fid and fid not in known:
                    log.warning("facility %s not in graph; facility edge skipped for run %s",
                                fid, run_id)
        with driver:
            driver.execute_query(
                """
                MERGE (e:ExcursionEvent {run_id: $run_id})
                SET e.product_id = $product_id, e.excursion_temp_c = $temp,
                    e.duration_min = $duration, e.mkt_c = $mkt,
                    e.packaging = $packaging, e.stage = $stage,
                    e.created_at = $created_at
                MERGE (dis:Disposition {disposition: $disposition})
                SET dis.reshipment_default = $reship_default
                MERGE (e)-[d:EVENT_LEADS_TO_DISPOSITION]->(dis)
                SET d.rule_no = $rule_no, d.reason = $reason, d.rule_path = $rule_path,
                    d.regulation = $regulation, d.reshipment_required = $reship,
                    d.risk_score = $score, d.cause_code = $cause_code,
                    d.decided_at = $decided_at
                MERGE (c:Cause {cause_code: $cause_code})
                MERGE (e)-[:EVENT_CAUSED_BY]->(c)
                FOREACH (rid IN $reg_ids |
                    MERGE (r:Regulation {clause_id: rid})
                    // Case-scoped on purpose: the citation belongs to THIS case's
                    // fired rule. Hanging it off the shared Disposition node made
                    // every case with the same disposition inherit each other's
                    // regulations (fixed 2026-09-13, see KG_SCHEMA §3).
                    MERGE (e)-[:CITES]->(r))
                FOREACH (sid IN $sop_ids |
                    MERGE (s:SOP {sop_id: sid})
                    MERGE (e)-[:FOLLOWS]->(s))
                """,
                parameters_=params,
            )
            if facility_id in known:
                driver.execute_query(
                    """
                    MATCH (e:ExcursionEvent {run_id: $run_id})
                    MATCH (f:Facility {facility_id: $fid})
                    MERGE (e)-[:EVENT_OCCURRED_AT]->(f)
                    """,
                    parameters_={"run_id": run_id, "fid": facility_id},
                )
            if params["reship"]:
                driver.execute_query(
                    """
                    MATCH (e:ExcursionEvent {run_id: $run_id})
                    MERGE (ro:ReshipmentOrder {order_id: $order_id})
                    MERGE (e)-[:TRIGGERS_RESHIPMENT]->(ro)
                    """,
                    parameters_={"run_id": run_id, "order_id": params["order_id"]},
                )
                if dest_id in known:
                    driver.execute_query(
                        """
                        MATCH (ro:ReshipmentOrder {order_id: $order_id})
                        MATCH (f:Facility {facility_id: $fid})
                        MERGE (ro)-[:RESHIPS_TO]->(f)
                        """,
                        parameters_={"order_id": params["order_id"], "fid": dest_id},
                    )
        return True
    except Exception:
        log.warning("KG write failed for run %s", run_id, exc_info=True)
        return False
