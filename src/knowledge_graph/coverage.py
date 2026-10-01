"""Read-only per-case graph coverage against immutable relational/JSONL originals.

An acknowledged outbox is not proof a later graph rebuild retained its events.
Missing edges may be safely replayed; contradictory facts/extra edges require
review instead of silently deleting someone else's graph data.
"""
from .connect import get_driver
from .writer import evidence_snapshot

CASE_QUERY = """
UNWIND $ids AS rid
OPTIONAL MATCH (e:ExcursionEvent {run_id:rid})
RETURN rid, properties(e) AS event,
 [(e)-[d:EVENT_LEADS_TO_DISPOSITION]->(v:Disposition) |
  {disposition:v.disposition, facts:properties(d)}] AS decisions,
 [(e)-[:EVENT_CAUSED_BY]->(c:Cause) | c.cause_code] AS causes,
 [(e)-[:CITES]->(r:Regulation) | r.clause_id] AS regulations,
 [(e)-[:FOLLOWS]->(s:SOP) | s.sop_id] AS sops,
 [(e)-[:EVENT_OCCURRED_AT]->(f:Facility) | f.facility_id] AS locations,
 [(e)-[:TRIGGERS_RESHIPMENT]->(ro:ReshipmentOrder) | ro.order_id] AS orders,
 [(e)-[:TRIGGERS_RESHIPMENT]->(:ReshipmentOrder)-[:RESHIPS_TO]->(f:Facility) |
  f.facility_id] AS destinations
"""


def compare_case(record, actual, static, queue_status=None):
    issues = []
    def issue(code, field=None):
        issues.append({"code": code, **({"field": field} if field else {})})
    ev = record["event"]
    evidence = record.get("graph_evidence") or evidence_snapshot(record.get("rule_no") or 0)
    expected_sets = {
        "regulations": set(evidence["regulation_ids"]), "sops": set(evidence["sop_ids"]),
        "causes": {(record.get("risk") or {}).get("cause_code", "inband")},
        "locations": {ev["facility_id"]} if ev.get("facility_id") else set(),
        "orders": {"RO-" + record["run_id"]} if record.get("reshipment_required") else set(),
        "destinations": set(),
    }
    destination = record.get("destination_facility_id") or ev.get("destination_facility_id")
    if record.get("reshipment_required") and destination:
        expected_sets["destinations"].add(destination)
    dependencies = {"Product": {ev["product_id"]}, "Regulation": expected_sets["regulations"],
                    "SOP": expected_sets["sops"], "Facility": expected_sets["locations"] | expected_sets["destinations"]}
    for label, ids in dependencies.items():
        if ids - static[label]:
            issue("missing_static_evidence", label)
    if not actual or actual["event"] is None:
        issue("missing_event")
    else:
        if actual.get("duplicate_event"):
            issue("conflicting_duplicate_event")
        expected_event = {key: ev.get(key) for key in ["product_id", "excursion_temp_c", "duration_min", "mkt_c", "packaging", "stage", "dispatch_id", "order_id"]}
        expected_event["created_at"] = record.get("created_at", "")
        for key, value in expected_event.items():
            got = actual["event"].get(key)
            if got != value:
                issue("missing_event_field" if got is None else "conflicting_event_field", key)
        decisions = actual["decisions"] or []
        if not decisions:
            issue("missing_decision")
        elif len(decisions) != 1 or decisions[0]["disposition"] != record["disposition"]:
            issue("conflicting_decision")
        else:
            expected = {"rule_no": record.get("rule_no") or 0, "reason": record.get("reason", ""),
                "rule_path": record.get("rule_path", ""), "regulation": record.get("regulation", ""),
                "reshipment_required": bool(record.get("reshipment_required")),
                "risk_score": (record.get("risk") or {}).get("score"),
                "cause_code": (record.get("risk") or {}).get("cause_code", "inband"),
                "decided_at": record.get("created_at", "")}
            for key, value in expected.items():
                got = decisions[0]["facts"].get(key)
                if got != value:
                    issue("missing_decision_field" if got is None else "conflicting_decision_field", key)
        for field, expected in expected_sets.items():
            values = actual[field] or []
            found = set(values)
            if expected - found:
                issue("missing_edges", field)
            if found - expected or len(values) != len(found):
                issue("conflicting_edges", field)
    conflict = any(i["code"].startswith("conflicting") for i in issues)
    state = "conflict" if conflict else "missing" if any(i["code"] == "missing_event" for i in issues) else "incomplete" if issues else "complete"
    return {"run_id": record["run_id"], "coverage": state, "queue_status": queue_status,
        "repairable": bool(issues) and not conflict and not any(i["code"] == "missing_static_evidence" for i in issues),
        "legacy_citation_mapping": "graph_evidence" not in record, "issues": issues}


def audit_cases(records, queue_states=None):
    queue_states = queue_states or {}
    results = []
    with get_driver() as driver:
        static = {}
        for label, key in [("Product", "product_id"), ("Regulation", "clause_id"), ("SOP", "sop_id"), ("Facility", "facility_id")]:
            static[label] = {r["id"] for r in driver.execute_query(f"MATCH (n:{label}) RETURN n.{key} AS id").records}
        for offset in range(0, len(records), 100):
            chunk = records[offset:offset + 100]
            rows = {}
            for row in driver.execute_query(CASE_QUERY, ids=[r["run_id"] for r in chunk]).records:
                rid = row["rid"]
                if rid in rows:
                    rows[rid]["duplicate_event"] = True
                else:
                    rows[rid] = dict(row)
            results.extend(compare_case(r, rows.get(r["run_id"]), static, queue_states.get(r["run_id"])) for r in chunk)
    counts = {key: sum(r["coverage"] == key for r in results) for key in ["complete", "missing", "incomplete", "conflict"]}
    unconfirmed = sum(r["queue_status"] in {"pending", "processing"} for r in results)
    return {"status": "empty" if not records else "passed" if counts["complete"] == len(records) and not unconfirmed else "failed",
            "case_count": len(records), "coverage": counts,
            "queue_unconfirmed_count": unconfirmed,
            "repairable_count": sum(r["repairable"] for r in results), "cases": results}
