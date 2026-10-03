"""Workflow projections: original rule facts are never overwritten."""
import datetime
import hashlib
import json

from optimisation.case_action_guard import case_action_guard
from optimisation.dispatch_repository import case_workflows, save_case_workflow, load_run, recent_runs


def boundary_reasons(event, spec, assessment=None):
    reasons = []
    if assessment:
        if not assessment["coverage_complete"]:
            reasons.append("incomplete_temperature_coverage")
        if len(assessment["windows"]) > 1:
            reasons.append("multiple_excursion_windows")
        if event.temperature_context.window_id is None:
            reasons.append("whole_observation_not_rule_assessed")
        if any(w["kind"] == "cold" and not (spec.freeze_sensitive and w["min_c"] <= 0) for w in assessment["windows"]):
            reasons.append("cold_policy_gap")
    if event.excursion_temp_c is not None and event.excursion_temp_c < spec.storage_min_c:
        if not (spec.freeze_sensitive and event.excursion_temp_c <= 0):
            reasons.append("cold_policy_gap")
    if getattr(event, "review_requested", False):
        reasons.append("operator_requested")
    return list(dict.fromkeys(reasons))


def projection(record, workflow):
    reviews = workflow.get("review_history", [])
    latest = reviews[-1] if reviews else None
    required = bool(record.get("review_required"))
    disposition = latest["disposition"] if latest else None if required else record["disposition"]
    pending = (required and latest is None) or (latest is not None and disposition in {"quarantine", "retest"})
    return {
        "review_required": required, "review_status": "pending" if pending else "resolved" if latest else "not_required",
        "review_history": reviews, "effective_disposition": disposition,
        "effective_reshipment_required": disposition == "scrap" if latest else False if pending else bool(record.get("reshipment_required")),
        "decision_source": "manual_review" if latest else "awaiting_review" if required else "automatic_rule",
        "execution_locked": bool(workflow.get("execution_locked")),
        "effective_destination_facility_id": (latest or {}).get("destination_facility_id") or record["event"].get("destination_facility_id"),
    }


def executable(record):
    if record.get("review_status") == "pending":
        raise ValueError("case requires completed human review before execution")
    return {**record, "disposition": record.get("effective_disposition", record.get("disposition", "scrap")),
            "reshipment_required": record.get("effective_reshipment_required", record.get("reshipment_required")),
            "event": {**record["event"], "destination_facility_id": record.get("effective_destination_facility_id") or record["event"].get("destination_facility_id")}}


def execution_exists(service, record):
    if record.get("execution_locked") or record.get("processing_status") == "closed":
        return True
    target = record["event"].get("dispatch_id") or record.get("handling_dispatch_id")
    ids = [target] if target else [r["dispatch_id"] for r in recent_runs(service.DISPATCH_DATABASE_URL, limit=200)]
    for did in ids:
        try:
            if f"RO-{record['run_id']}" in load_run(service.DISPATCH_DATABASE_URL, did).orders:
                return True
        except KeyError:
            continue
    return False


def review_case(service, run_id, req):
    with case_action_guard(service.DISPATCH_DATABASE_URL):
        record = service.find_run(run_id)
        if record is None:
            raise KeyError(run_id)
        digest = hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        workflow = case_workflows(service.DISPATCH_DATABASE_URL).get(run_id, {})
        for action in workflow.get("review_history", []):
            if action["command_id"] == req.command_id:
                if action["request_sha256"] != digest:
                    raise ValueError("review command_id belongs to a different request")
                return record
        if execution_exists(service, record) or record["processing_status"] in {"handled", "closed"}:
            raise ValueError("review is locked after execution or handling; original outcome cannot be rewritten")
        if record["workflow_version"] != req.expected_version:
            raise ValueError("case changed; reload before reviewing")
        destination = req.destination_facility_id or record["event"].get("destination_facility_id")
        if destination:
            nodes = {n["facility_id"]: n for n in service.read_network()["nodes"]}
            if destination not in nodes or nodes[destination]["role"] != "customer":
                raise ValueError("review destination must be a known hospital")
            if record["event"].get("order_id") and destination != record["event"].get("destination_facility_id"):
                raise ValueError("review cannot change the linked order destination")
        if req.disposition == "scrap" and not destination:
            raise ValueError("scrap review requires a reshipment destination hospital")
        action = {**req.model_dump(), "destination_facility_id": destination, "request_sha256": digest,
                  "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "reshipment_required": req.disposition == "scrap", "demo_self_declared_reviewer": True}
        save_case_workflow(service.DISPATCH_DATABASE_URL, run_id, {
            **workflow, "status": "pending", "review_history": [*workflow.get("review_history", []), action],
        }, expected_version=req.expected_version)
        return service.find_run(run_id)
