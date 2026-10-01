"""Per-case KG writer: one closed ``case_close`` run becomes its decision chain.

Follows ``docs/KG_SCHEMA_v1.md`` §2–§3: the event is keyed by ``run_id``
(idempotent MERGE — replaying a run overwrites its chain, schema 纪律 3);
disposition facts live on the ``EVENT_LEADS_TO_DISPOSITION`` edge (no
per-case Decision node); ``Cause`` is the deterministic API risk code;
regulations are cited by the disposition concept via the rule→regulation
map; SOPs hang off the event via ``FOLLOWS`` (schema ✚ EVENT_FOLLOWS_SOP,
added 2026-09-11, flagged for review). A ``ReshipmentOrder`` is only created
when the engine flagged ``reshipment_required`` (M3→M5 anchor). When the
case carries facility ids — optional, validated by the case-input contract — the event is additionally
linked to the facility where it occurred (``EVENT_OCCURRED_AT``) and the
reshipment order to its destination (``RESHIPS_TO``); the field names are
defined in KG_SCHEMA §2/§3.

The relational registration and outbox are authoritative. One Neo4j transaction
writes the complete chain; missing static dependencies or unavailable graphs
return False so the outbox remains pending rather than claiming partial success.
"""
from __future__ import annotations

import logging

from .build_graph import RULE_TO_REGULATIONS, RULE_TO_SOPS
from .connect import get_driver

log = logging.getLogger("uvicorn.error")


def evidence_snapshot(rule_no):
    return {"regulation_ids": list(RULE_TO_REGULATIONS.get(rule_no, [])),
            "sop_ids": list(RULE_TO_SOPS.get(rule_no, []))}


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
    facility_id = ev.get("facility_id")
    dest_id = record.get("destination_facility_id") or ev.get("destination_facility_id")
    evidence = record.get("graph_evidence") or evidence_snapshot(rule_no)
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
        "reg_ids": evidence["regulation_ids"],
        "sop_ids": evidence["sop_ids"],
        "order_id": f"RO-{run_id}",
        "facility_id": facility_id,
        "destination_id": dest_id,
        "dispatch_id": ev.get("dispatch_id"),
        "source_order_id": ev.get("order_id"),
        "simulated": True,
    }
    try:
        with get_driver() as driver, driver.session() as session:
            session.execute_write(_write_chain, params)
        return True
    except Exception:
        log.warning("KG write failed for run %s", run_id, exc_info=True)
        return False


def _write_chain(tx, params):
    dependencies = {"Product": ("product_id", [params["product_id"]]),
                    "Regulation": ("clause_id", params["reg_ids"]), "SOP": ("sop_id", params["sop_ids"]),
                    "Facility": ("facility_id", [f for f in [params["facility_id"],
                        params["destination_id"] if params["reship"] else None] if f])}
    for label, (key, ids) in dependencies.items():
        found = {r["id"] for r in tx.run(f"MATCH (n:{label}) WHERE n.{key} IN $ids RETURN n.{key} AS id", ids=ids)}
        if set(ids) - found:
            raise ValueError(f"missing static {label} evidence: {sorted(set(ids) - found)}")
    tx.run(
                """
                MERGE (e:ExcursionEvent {run_id: $run_id})
                SET e.product_id = $product_id, e.excursion_temp_c = $temp,
                    e.duration_min = $duration, e.mkt_c = $mkt,
                    e.packaging = $packaging, e.stage = $stage,
                    e.created_at = $created_at, e.dispatch_id = $dispatch_id,
                    e.order_id = $source_order_id, e.simulated = $simulated
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
                **params,
            ).consume()
    if params["facility_id"]:
        tx.run(
                    """
                    MATCH (e:ExcursionEvent {run_id: $run_id})
                    MATCH (f:Facility {facility_id: $fid})
                    MERGE (e)-[:EVENT_OCCURRED_AT]->(f)
                    """,
                    run_id=params["run_id"], fid=params["facility_id"],
                ).consume()
    if params["reship"]:
        tx.run(
                    """
                    MATCH (e:ExcursionEvent {run_id: $run_id})
                    MERGE (ro:ReshipmentOrder {order_id: $order_id})
                    MERGE (e)-[:TRIGGERS_RESHIPMENT]->(ro)
                    """,
                    run_id=params["run_id"], order_id=params["order_id"],
                ).consume()
        if params["destination_id"]:
            tx.run(
                        """
                        MATCH (ro:ReshipmentOrder {order_id: $order_id})
                        MATCH (f:Facility {facility_id: $fid})
                        MERGE (ro)-[:RESHIPS_TO]->(f)
                        """,
                        order_id=params["order_id"], fid=params["destination_id"],
                    ).consume()
