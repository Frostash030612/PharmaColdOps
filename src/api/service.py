"""Decision-service business logic: a thin, import-safe layer over the engine.

Built on one module-level ``RuleEngine`` (the engine re-reads
``rules_config.json`` per construction, so a singleton avoids re-loading on
every request). Sandbox overrides are honoured by resolving a per-request
``ProductSpec`` and evaluating with an engine that carries just that product
overridden — the base config is never mutated.

``classify_evidence`` / ``risk_score`` mirror the demo's ``renderEvidence`` /
``riskInfo`` so the *same* semantics are available over HTTP; wording stays on
the client.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
import copy
import math
import hashlib
import uuid
import sys
from dataclasses import asdict
from pathlib import Path

# uvicorn wires handlers onto its own loggers, so this line appears on the
# console next to the access log — a live "audit trail" proving each front-end
# change really round-trips to the Python engine (drag a slider and watch).
log = logging.getLogger("uvicorn.error")

ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:  # Minimal test environments may omit this optional loader.
    pass
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rule_engine.engine import RuleEngine  # noqa: E402
from rule_engine.models import ExcursionEvent, ProductSpec  # noqa: E402

from knowledge_graph.writer import write_case, evidence_snapshot  # noqa: E402
from knowledge_graph import qa as kg_qa  # noqa: E402
from optimisation.reshipment import (  # noqa: E402
    build_delivery_order,
    build_reshipment_order,
    plan_reshipment_route,
)
from optimisation.singapore_export import (  # noqa: E402
    leg_geojson, routes_geojson, sequence_distance_m, sequence_geojson, sequences_geojson,
)
from optimisation.tracking import (  # noqa: E402
    LOADING_MIN, advance_clock, make_clock, schedule_origin, simulated_now, vehicle_track,
    watched_now,
)
from optimisation.singapore_loader import read_network  # noqa: E402
from optimisation.dispatch_models import (  # noqa: E402
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
)
from optimisation.dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders  # noqa: E402
from optimisation.dispatch_state import (  # noqa: E402
    accept_plan, deliver_next, depart, next_stop, planned_stops, state_to_dict,
)
from optimisation.dispatch_repository import (  # noqa: E402
    create_run, latest_dispatch_id, latest_open_dispatch_id, load_context, load_run,
    recent_runs, update_context, update_run, create_successor,
    case_workflows, save_case_workflow,
)
from optimisation.daily_orders import (  # noqa: E402
    ASSUMPTIONS as DAILY_PLAN_ASSUMPTIONS,
    FLEET_LIMIT, MAX_STOPS_PER_VEHICLE, daily_delivery_batch,
)
from optimisation.simulated_orders import SimulationConfig, generate_simulated_batch  # noqa: E402
from optimisation.parking_policy import warehouse_ids, validate_terminals, validate_end_node  # noqa: E402
from optimisation.case_repository import (  # noqa: E402
    RegistrationConflict, lookup_registration, register_once, registered_records,
    claim_graph_records, finish_graph_claim, graph_sync_status,
)
from optimisation.dynamic_problem import (  # noqa: E402
    DEFAULT_POLICY, accept_emergency_order, preview_emergency_order,
)
from optimisation.failure_rescue import (  # noqa: E402
    accept_vehicle_failure, preview_vehicle_failure,
)
from optimisation.execution import execution_view, checkpoint, install_schedule  # noqa: E402
from optimisation.dispatch_constraints import price_work  # noqa: E402
from optimisation.delay_monitor import (  # noqa: E402
    accept_delay_replan, preview_delay_risks,
)
from .schemas import (  # noqa: E402
    DelayAcceptIn, DelayPreviewIn,
    DispatchCreateIn, DispatchPlanIn, EmergencyAcceptIn, EmergencyPreviewIn, EventIn,
    GridIn, QAIn, RouteIn, SpecOverride, VehicleFailureAcceptIn, VehicleFailurePreviewIn,
    OvernightRunPreviewIn, OvernightRunAcceptIn, NextDayIn,
)

# Loaded once; used both as the source of stock thresholds and to keep the
# per-request override engines cheap (dict copy, no disk I/O).
ENGINE = RuleEngine()

# Append-only run history: one JSON line per *closed* inbound case
# (/api/case_close). Live /api/decide previews are never archived. A runtime
# artifact (gitignored via `data/audit/`), served newest-first over GET /api/runs.
# Tests monkeypatch RUNS_FILE to a temp path so pytest never writes into the repo.
RUNS_FILE = Path(os.environ.get("CASE_RUNS_FILE", str(ROOT / "data" / "audit" / "runs.jsonl")))
DISPATCH_DATABASE_URL = os.environ.get(
    "DATABASE_URL", str(ROOT / "data" / "audit" / "dispatch.sqlite3")
)


def valid_product_ids() -> list:
    return sorted(ENGINE.specs)


def resolve_spec(product_id: str, override: SpecOverride | None) -> ProductSpec:
    """Product thresholds with the demo sandbox's overrides merged in."""
    try:
        base = ENGINE.specs[product_id]
    except KeyError:
        raise KeyError(product_id)  # surfaced by main as HTTP 422
    if override is None:
        return base
    return ProductSpec(
        product_id=base.product_id,
        storage_min_c=base.storage_min_c,
        storage_max_c=base.storage_max_c,
        allowable_duration_min=(
            override.allowable_duration_min
            if override.allowable_duration_min is not None else base.allowable_duration_min),
        mkt_threshold_c=(override.mkt_threshold_c
                         if override.mkt_threshold_c is not None else base.mkt_threshold_c),
        retestable=override.retestable if override.retestable is not None else base.retestable,
        freeze_sensitive=base.freeze_sensitive,
    )


def _engine_for(spec: ProductSpec) -> RuleEngine:
    """Engine evaluating ``spec`` in place of the product's stock thresholds."""
    return RuleEngine(specs={**ENGINE.specs, spec.product_id: spec})


def _as_event(product_id: str, temp_c: float, duration_min: float, mkt_c: float,
              packaging: str, stage: str, scenario_id: str) -> ExcursionEvent:
    return ExcursionEvent(
        scenario_id=scenario_id,
        product_id=product_id,
        excursion_temp_c=temp_c,
        duration_min=duration_min,  # int for decide/batch, float mid-point for grid
        mkt_c=mkt_c,
        packaging=packaging,
        stage=stage,
    )


def classify_evidence(spec: ProductSpec, event: EventIn) -> dict:
    """Mirror of the demo's evidence chips — level per input, keyed by row.

    ``freeze`` appears only for freeze-sensitive products, exactly as in the UI.
    """
    lvl: dict = {}
    ev = event.model_dump()
    temp_c = ev["excursion_temp_c"]
    A, T = spec.allowable_duration_min, spec.mkt_threshold_c

    lvl["packaging"] = "breach" if ev["packaging"] == "compromised" else "ok"
    lvl["temp"] = "breach" if temp_c > spec.storage_max_c else "ok"
    if spec.freeze_sensitive:
        lvl["freeze"] = "severe" if temp_c <= 0.0 else "ok"

    if ev["duration_min"] >= 2 * A:
        lvl["duration"] = "severe"
    elif ev["duration_min"] > A:
        lvl["duration"] = "breach"
    elif ev["duration_min"] >= 0.8 * A:
        lvl["duration"] = "near"
    else:
        lvl["duration"] = "ok"

    if ev["mkt_c"] >= T + 3.0:
        lvl["mkt"] = "severe"
    elif ev["mkt_c"] > T:
        lvl["mkt"] = "breach"
    elif ev["mkt_c"] >= T - 0.5:
        lvl["mkt"] = "near"
    else:
        lvl["mkt"] = "ok"
    return lvl


def risk_score(spec: ProductSpec, event: EventIn) -> dict:
    """Deterministic severity score + a machine-readable top-cause code.

    A faithful port of the demo's ``riskInfo`` (same weights, same pins) but
    returning a stable ``cause_code`` the client localises — the client's ZH
    causes are Chinese and must not live in Python.
    """
    ev = event.model_dump()
    temp_c = ev["excursion_temp_c"]
    band = max(1e-6, spec.storage_max_c - spec.storage_min_c)
    frozen = spec.freeze_sensitive and temp_c <= 0.0

    if frozen:
        t_score, t_label = 1.6, "frozen"
    elif temp_c > spec.storage_max_c:
        t_score = min(1.5, (temp_c - spec.storage_max_c) / band)
        t_label = "above max"
    elif temp_c < spec.storage_min_c and spec.freeze_sensitive:
        t_score = min(1.2, (spec.storage_min_c - temp_c) / band)
        t_label = "below min"
    else:
        t_score, t_label = 0.0, "in band"

    d_score = min(1.5, ev["duration_min"] / spec.allowable_duration_min)
    m_score = max(0.0, min(1.5, (ev["mkt_c"] - spec.mkt_threshold_c) / band))
    p_breach = ev["packaging"] == "compromised" and temp_c > spec.storage_max_c

    raw = 0.50 * t_score + 0.28 * d_score + 0.12 * m_score + (0.10 if p_breach else 0.0)
    if frozen:
        raw = max(raw, 0.95)
    if p_breach:
        raw = max(raw, 0.72)

    # priority order mirrors riskInfo's causes[] so top-cause is identical
    if frozen:
        cause_code = "frozen"
    elif p_breach:
        cause_code = "packaging"
    elif temp_c > spec.storage_max_c + band * 0.5:
        cause_code = "overtemp"
    elif (not frozen) and ev["duration_min"] > spec.allowable_duration_min:
        cause_code = "duration"
    elif ev["mkt_c"] > spec.mkt_threshold_c:
        cause_code = "mkt"
    elif (ev["duration_min"] >= 0.8 * spec.allowable_duration_min
          or ev["mkt_c"] >= spec.mkt_threshold_c - 0.5):
        cause_code = "near"
    else:
        cause_code = "inband" if t_label == "in band" else "minor"

    score = max(3, min(99, round(raw * 100)))
    return {"score": score, "cause_code": cause_code}


def _spec_dict(spec: ProductSpec) -> dict:
    return {
        "product_id": spec.product_id,
        "storage_min_c": spec.storage_min_c,
        "storage_max_c": spec.storage_max_c,
        "allowable_duration_min": spec.allowable_duration_min,
        "mkt_threshold_c": spec.mkt_threshold_c,
        "retestable": spec.retestable,
        "freeze_sensitive": spec.freeze_sensitive,
    }


def _audit(kind: str, ev, spec=None, decision=None) -> None:
    """One readable console line per request: what came in and what was decided."""
    fields = [f"{kind} {ev.product_id} {ev.excursion_temp_c:g}°C/{ev.duration_min:g}min "
              f"MKT {ev.mkt_c:g}°C {ev.packaging}/{ev.stage}"]
    if spec is not None:
        fields.append(f"spec A={spec.allowable_duration_min:g}min "
                      f"T={spec.mkt_threshold_c:g}°C retest={spec.retestable}")
    if decision is not None:
        fields.append(f"→ {decision.disposition.value} (rule {decision.rule_no})")
    log.info("[audit] " + " ".join(fields))


def _new_run_id() -> str:
    """Readable unique-ish id for one archived case (timestamp, µs resolution)."""
    return "R" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8]


def _record_run(view: dict, *, started_at: str | None = None,
                remark: str | None = None, persist: bool = True) -> dict:
    """Build an immutable assessment record, optionally mirror it for legacy callers.

    Registration commits the returned record to the DB first (persist=False),
    then writes the advisory JSONL mirror only for the winning new registration.
    """
    now = datetime.datetime.now()
    record = {
        "run_id": _new_run_id(),
        "created_at": now.isoformat(timespec="seconds"),
        "started_at": started_at or now.isoformat(timespec="seconds"),
        **view,
    }
    if remark:
        record["remark"] = remark
    if persist:
        _mirror_record(record)
    return record


def _mirror_record(record):
    """Advisory JSONL mirror. Committed DB records survive mirror failures."""
    try:
        RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("could not append run record to %s", RUNS_FILE, exc_info=True)


def list_runs(limit: int = 200) -> dict:
    """Every archived decision, newest first (empty list when none recorded yet)."""
    records = []
    try:
        with RUNS_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning("skipped incomplete legacy case mirror line")
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        log.warning("could not read %s", RUNS_FILE, exc_info=True)
    # Prefer immutable DB originals over the legacy mirror; count each run once.
    unique = {record["run_id"]: record for record in records}
    unique.update({record["run_id"]: record for record in _registered_records()})
    records = sorted(unique.values(), key=lambda r: (r.get("created_at", ""), r["run_id"]), reverse=True)
    workflows = case_workflows(DISPATCH_DATABASE_URL) if records else {}
    cache = {}
    return {"count": len(records), "runs": [
        _case_progress(record, workflows.get(record["run_id"], {}), cache)
        for record in records[:limit]]}


def _case_progress(record, workflow, cache):
    """Processing follows actual replacement delivery, never the scrap/release label."""
    status = workflow.get("status") or record.get("processing_status") or (
        "pending" if record.get("reshipment_required") else "handled")
    dispatch_id = record.get("event", {}).get("dispatch_id") or workflow.get("dispatch_id")
    replacement = None
    if record.get("reshipment_required") and status != "closed":
        if not dispatch_id:  # old unbound cases: find their actual replacement, not the latest day
            if "_legacy_case_dispatches" not in cache:
                legacy = {}
                for item in recent_runs(DISPATCH_DATABASE_URL, limit=200):
                    candidate = item["dispatch_id"]
                    if candidate not in cache:
                        cache[candidate] = load_run(DISPATCH_DATABASE_URL, candidate)
                    for oid in cache[candidate].orders:
                        if oid.startswith("RO-"):
                            legacy.setdefault(oid, candidate)
                cache["_legacy_case_dispatches"] = legacy
            dispatch_id = cache["_legacy_case_dispatches"].get(f"RO-{record['run_id']}")
        if dispatch_id:
            try:
                if dispatch_id not in cache:
                    cache[dispatch_id] = load_run(DISPATCH_DATABASE_URL, dispatch_id)
                state = cache[dispatch_id]
                replacement = state.orders.get(f"RO-{record['run_id']}")
                # Mechanical rescue can replace the case's replacement shipment too.
                seen = set()
                while replacement and replacement.status == "failed" and replacement.order_id not in seen:
                    seen.add(replacement.order_id)
                    successor = next((o for o in state.orders.values()
                                      if o.replaces_order_id == replacement.order_id), None)
                    if not successor:
                        break
                    replacement = successor
            except KeyError:
                replacement = None
        if replacement:
            status = ("handled" if replacement.status == "delivered" else
                      "pending" if replacement.status in {"failed", "scrapped"} else "processing")
    return {**record, "processing_status": status,
            "workflow_version": workflow.get("version", 0),
            "workflow_history": workflow.get("history", []),
            "handling_dispatch_id": dispatch_id,
            "replacement_status": replacement.status if replacement else None}


def update_case_progress(run_id, req):
    record = find_run(run_id)
    if record is None:
        raise KeyError(run_id)
    current = record["processing_status"]
    if record["workflow_version"] != req.expected_version:
        raise ValueError("incident workflow changed; reload before retrying")
    allowed = {"pending": {"processing", "handled"}, "processing": {"handled"},
               "handled": {"closed"}, "closed": set()}
    if req.status not in allowed[current]:
        raise ValueError(f"cannot change incident status from {current} to {req.status}")
    if req.status == "handled" and record.get("reshipment_required"):
        raise ValueError("reshipment must actually be delivered before the incident is handled")
    if req.status in {"handled", "closed"} and not req.remark.strip():
        raise ValueError("a handling/closure note is required")
    action = {"status": req.status, "remark": req.remark.strip(),
              "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save_case_workflow(DISPATCH_DATABASE_URL, run_id, {
        "status": req.status, "dispatch_id": record.get("handling_dispatch_id"),
        "history": [*record["workflow_history"], action]}, expected_version=req.expected_version)
    return find_run(run_id)


def _event_dump(event: EventIn) -> dict:
    """The excursion inputs only — never leaks spec_override / case meta.

    Optional facility fields pass through when the case contract carries
    them (placeholders for the KG writer's EVENT_OCCURRED_AT / RESHIPS_TO
    edges — A 9/12 review / C 9/21 contract will pin the names).
    """
    dump = {
        "product_id": event.product_id,
        "excursion_temp_c": event.excursion_temp_c,
        "duration_min": event.duration_min,
        "mkt_c": event.mkt_c,
        "packaging": event.packaging,
        "stage": event.stage,
    }
    for field in ("facility_id", "destination_facility_id", "order_id", "dispatch_id"):
        if getattr(event, field, None):
            dump[field] = getattr(event, field)
    return dump


def _decision_view(event: EventIn, spec: ProductSpec, decision) -> dict:
    """The full semantic decision the demo panels render (codes, not wording)."""
    return {
        "disposition": decision.disposition.value,
        "rule_no": decision.rule_no,
        "reason": decision.reason,
        "regulation": decision.regulation,
        "reshipment_required": decision.reshipment_required,
        "rule_path": decision.rule_path,
        "event": _event_dump(event),
        "spec": _spec_dict(spec),
        "evidence": classify_evidence(spec, event),
        "risk": risk_score(spec, event),
    }


def decide_view(event: EventIn, override: SpecOverride | None) -> dict:
    """One event → the full semantic decision the demo panels render.

    A live *preview* — it is NOT archived. Only an explicit close_case() writes
    a run record, so the history stays one line per completed inbound case.
    """
    spec = resolve_spec(event.product_id, override)
    decision = _engine_for(spec).evaluate(_as_event(
        event.product_id, event.excursion_temp_c, event.duration_min,
        event.mkt_c, event.packaging, event.stage, scenario_id="api"))
    _audit("decide", event, spec, decision)
    return _decision_view(event, spec, decision)


def close_case(event: EventIn, override: SpecOverride | None,
               started_at: str | None = None, remark: str | None = None,
               registration_id: str | None = None) -> dict:
    """Close one inbound case: decide its current inputs and append ONE record.

    The disposition is recomputed from the posted inputs (deterministic, so it
    matches the live /api/decide preview the sandbox was showing). Appends the
    record to RUNS_FILE and returns it with the run_id / created_at stamps the
    front-end shows in the case history.
    """
    key = registration_id or uuid.uuid4().hex  # legacy calls remain distinct without a client key
    canonical = {"event": {field: getattr(event, field) for field in EventIn.model_fields},
                 "override": override.model_dump(exclude_none=True) if override else {},
                 "started_at": started_at, "remark": remark.strip() if remark and remark.strip() else None}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, allow_nan=False).encode()).hexdigest()
    try:
        existing = lookup_registration(DISPATCH_DATABASE_URL, key, digest)
    except RegistrationConflict:
        raise
    except Exception as exc:
        raise RuntimeError("case registration storage unavailable; retry the same registration_id") from exc
    if existing is not None:
        return _registration_response(existing)
    event, linked_snapshot = _bind_case_order(event)
    spec = resolve_spec(event.product_id, override)
    decision = _engine_for(spec).evaluate(_as_event(
        event.product_id, event.excursion_temp_c, event.duration_min,
        event.mkt_c, event.packaging, event.stage, scenario_id="case_close"))
    _audit("close", event, spec, decision)
    view = _decision_view(event, spec, decision)
    view["processing_status"] = "pending"
    view["registration_id"] = key
    view["graph_evidence"] = evidence_snapshot(view["rule_no"])
    if linked_snapshot:
        view["linked_order"] = linked_snapshot
    record = _record_run(view,
                         started_at=started_at, remark=canonical["remark"], persist=False)
    try:
        record, created = register_once(DISPATCH_DATABASE_URL, key, digest, record)
    except RegistrationConflict:
        raise
    except Exception as exc:
        raise RuntimeError("case registration storage unavailable; retry the same registration_id") from exc
    # DB registration + outbox are authoritative; graph failures stay retryable.
    if created:
        _mirror_record(record)
        try:
            sync_case_graph(run_id=record["run_id"], limit=1)
        except Exception:
            log.warning("best-effort graph mirror failed for %s", record["run_id"], exc_info=True)
    return _registration_response(record)


def sync_case_graph(*, run_id=None, limit=50, force=False):
    results = {"synced": 0, "failed": 0}
    for claim in claim_graph_records(DISPATCH_DATABASE_URL, run_id=run_id, limit=limit, force=force):
        try:
            success = write_case(claim["record"]) is True
        except Exception:
            log.warning("graph mirror attempt failed for %s", claim["run_id"], exc_info=True)
            success = False
        finish_graph_claim(DISPATCH_DATABASE_URL, claim, success=success,
                           error=None if success else "Neo4j unavailable or required static evidence missing")
        results["synced" if success else "failed"] += 1
    return {**results, "queue": graph_sync_status(DISPATCH_DATABASE_URL)}


def _registered_records():
    try:
        return registered_records(DISPATCH_DATABASE_URL)
    except Exception as exc:
        raise RuntimeError("case registration storage unavailable") from exc


def _registration_response(record):
    try:
        workflow = case_workflows(DISPATCH_DATABASE_URL).get(record["run_id"], {})
        return _case_progress(record, workflow, {})
    except Exception as exc:
        raise RuntimeError("case registered but progress read unavailable; retry the same registration_id") from exc


def _bind_case_order(event: EventIn):
    """Persist an unambiguous simulation-run/order link, not just a daily ID."""
    nodes = {n["facility_id"]: n for n in read_network()["nodes"]}
    if event.facility_id and event.facility_id not in nodes:
        raise ValueError("unknown incident facility_id")
    if event.destination_facility_id and (
        event.destination_facility_id not in nodes
        or nodes[event.destination_facility_id]["role"] != "customer"
    ):
        raise ValueError("destination_facility_id must be a receiving hospital")
    if not event.order_id:
        if event.dispatch_id:
            raise ValueError("dispatch_id requires order_id")
        return event, None
    dispatch_id = event.dispatch_id
    if not dispatch_id:  # older API clients: capture the active run NOW, not at rescue time
        dispatch_id, _ = _require_plan()
    try:
        state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
        context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    except KeyError as exc:
        raise ValueError("unknown linked dispatch_id") from exc
    order = next((o for o in context["input"]["orders"] if o["order_id"] == event.order_id), None)
    if order is None or event.order_id not in state.orders:
        raise ValueError("linked order is not part of the selected dispatch")
    if order["product_id"] != event.product_id:
        raise ValueError("incident product does not match linked order")
    if event.destination_facility_id and event.destination_facility_id != order["destination_facility_id"]:
        raise ValueError("incident destination does not match linked order")
    return event.model_copy(update={"dispatch_id": dispatch_id,
        "destination_facility_id": order["destination_facility_id"]}), {
        **order, "dispatch_id": dispatch_id, "operating_date": context.get("operating_date"),
        "quantity_is_nominal": event.order_id in context.get("nominal_order_ids", ())}


def grid_view(req: GridIn) -> dict:
    """Decision matrix in the map's cell order: ``rows[row][col]``."""
    spec = resolve_spec(req.product_id, req.spec_override)
    engine = _engine_for(spec)
    rows = []
    for mkt_c in req.mkts:  # descending — row 0 is the top (highest MKT) row
        row = []
        for dur in req.durations:  # ascending along the x-axis
            decision = engine.evaluate(_as_event(
                req.product_id, req.excursion_temp_c, dur, mkt_c,
                req.packaging, req.stage, scenario_id="grid"))
            row.append(decision.disposition.value)
        rows.append(row)
    log.info("[audit] grid %s %d rows × %d cols (spec A=%gmin T=%g°C)",
             req.product_id, len(req.mkts), len(req.durations),
             spec.allowable_duration_min, spec.mkt_threshold_c)
    return {"rows": rows}


def batch_view(events: list) -> dict:
    """Preset scenarios → trimmed decisions (stock thresholds, no overrides)."""
    decisions = []
    for ev in events:
        decision = ENGINE.evaluate(_as_event(
            ev.product_id, ev.excursion_temp_c, ev.duration_min,
            ev.mkt_c, ev.packaging, ev.stage, scenario_id="batch"))
        decisions.append({
            "disposition": decision.disposition.value,
            "rule_no": decision.rule_no,
            "reshipment_required": decision.reshipment_required,
        })
        _audit("batch", ev, None, decision)
    return {"decisions": decisions}


def find_run(run_id: str) -> dict | None:
    """One archived case by id, or None when the id is unknown."""
    return next(
        (item for item in list_runs(limit=None)["runs"] if item["run_id"] == run_id),
        None,
    )


def route_view(req: RouteIn) -> dict:
    """Find a closed case, derive its order, solve, and serialise the replan."""
    record = find_run(req.run_id)
    if record is None:
        raise KeyError(req.run_id)
    order = build_reshipment_order(record)
    if order is None:
        raise ValueError(f"case {req.run_id} does not require reshipment")
    result = plan_reshipment_route(order, algorithm=req.algorithm)
    return {
        "order_id": order.order_id,
        "algorithm": result.algorithm,
        "vehicles_used": result.metrics.vehicles_used,
        "total_distance": result.metrics.total_distance,
        "on_time_rate": result.metrics.on_time_rate,
        "served_customers": result.metrics.served_customers,
        "target_customers": (
            result.metrics.served_customers
            + len(result.metrics.unserved_customer_ids)
        ),
        "time_window_violations": result.metrics.time_window_violations,
        "capacity_violations": result.metrics.capacity_violations,
        "depot_return_violations": result.metrics.depot_return_violations,
        "vehicle_limit_violations": result.metrics.vehicle_limit_violations,
        "routes": [
            {
                "vehicle_id": route.vehicle_id,
                "customer_ids": list(route.customer_ids),
                "stops": [asdict(stop) for stop in route.stops],
                "total_load": route.total_load,
                "total_distance": route.total_distance,
                "duration": route.duration,
            }
            for route in result.routes
        ],
        # The browser needs the road geometry for a newly solved sequence; the
        # static node table alone cannot reconstruct facility-to-facility legs.
        "geojson": routes_geojson(read_network(), result),
    }


def dispatch_plan_view(req: DispatchPlanIn) -> dict:
    """Preview an order-driven plan without mutating inventory or vehicles."""
    orders, inventory, vehicles = _dispatch_inputs(req)
    plan = plan_delivery_orders(
        orders, inventory, vehicles, algorithm=req.algorithm,
        constraints=_dispatch_constraints(req),
    )
    return _dispatch_plan_response(
        plan, requested_algorithm=req.algorithm,
        constraints=req.constraints.model_dump(),
    )


def _dispatch_plan_response(plan, *, requested_algorithm: str, constraints: dict | None = None) -> dict:
    """Serialise one already-computed plan; never invokes a solver again."""
    network = read_network()
    id_by_node = {n["node_id"]: n["facility_id"] for n in network["nodes"]}
    zone_views = []
    for zone_plan in plan.zone_plans:
        result = zone_plan.result
        routes = []
        for route in result.routes:
            vehicle_id = zone_plan.vehicle_ids[route.vehicle_id - 1]
            routes.append({
                "vehicle_id": vehicle_id,
                "customer_ids": list(route.customer_ids),
                "order_ids": [
                    order_id for node_id in route.customer_ids
                    for order_id in zone_plan.order_ids_by_node[node_id]
                ],
                "stops": [asdict(stop) for stop in route.stops],
                "total_load": route.total_load,
                "total_distance": route.total_distance,
                "duration": route.duration,
                # Where this vehicle finishes: ``None`` = drives back to the depot
                # (closed route), otherwise the parking node (open route).
                "start_node_id": route.start_node_id,
                "start_facility_id": id_by_node.get(route.start_node_id),
                "start_time_min": route.start_time_min,
                "end_time_min": route.end_time_min,
                "actual_end_facility_id": id_by_node.get(route.end_node_id if route.end_node_id is not None else route.start_node_id),
                "end_node_id": route.end_node_id,
                "end_facility_id": (
                    None if route.end_node_id is None
                    else id_by_node.get(route.end_node_id)
                ),
                "mileage_limit_violation": route.mileage_limit_violation,
            })
        zone_views.append({
            "temperature_zone": zone_plan.temperature_zone,
            # Where this group loads: the route starts here (B4). ``None`` in
            # pickup-delivery mode, where every order brings its own source.
            "origin_facility_id": zone_plan.origin_facility_id,
            # Which model produced this group, so the client says "one source per
            # truck" or "collect and deliver in one run" from data, not guesswork.
            "routing_model": zone_plan.routing_model,
            "feasible": result.feasible,
            "target_orders": sum(len(ids) for ids in zone_plan.order_ids_by_node.values()),
            "target_facilities": len(zone_plan.order_ids_by_node),
            "served_facilities": result.metrics.served_customers,
            "unserved_customer_ids": list(result.metrics.unserved_customer_ids),
            # Why each of them did not fit, measured by re-attempting the
            # insertion (B7). Codes are stable; the client localises them.
            "unserved": [
                {
                    "node_id": node_id,
                    "facility_id": id_by_node.get(node_id),
                    "order_ids": list(zone_plan.order_ids_by_node.get(node_id, ())),
                    "reasons": [dict(reason) for reason in
                                zone_plan.unserved_reasons.get(node_id, ())],
                }
                for node_id in result.metrics.unserved_customer_ids
            ],
            "total_distance": result.metrics.total_distance,
            "mileage_violations": result.metrics.mileage_violations,
            "terminal_facility_ids": list(zone_plan.terminal_facility_ids),
            "routes": routes,
            "geojson": routes_geojson(network, result),
        })
    return {
        "algorithm": requested_algorithm,
        "preview": True,
        "feasible": plan.feasible,
        "order_count": plan.order_count,
        "constraints": constraints or {},
        "zones": zone_views,
    }


def _dispatch_inputs(req: DispatchPlanIn):
    return (
        tuple(DeliveryOrder(**item.model_dump()) for item in req.orders),
        tuple(InventoryLot(**item.model_dump()) for item in req.inventory),
        tuple(DispatchVehicle(**item.model_dump()) for item in req.vehicles),
    )


def _dispatch_constraints(req: DispatchPlanIn) -> DispatchConstraints:
    return DispatchConstraints(**req.constraints.model_dump())


def overnight_plan_view(req) -> dict:
    """Serialise the overnight parking decision (B5).

    Returns the chosen node per truck plus the two numbers that make the choice
    arguable: what the repositioning drive costs today, and how much deadhead it
    removes from tomorrow's first leg. ``net_two_day_m`` is the honest balance
    (usually negative — repositioning is at least what it saves, by the triangle
    inequality; what it buys is an earlier start).
    """
    from optimisation.overnight import plan_overnight_parking

    orders, inventory, vehicles = _dispatch_inputs(req)
    plan = plan_overnight_parking(
        orders, inventory, vehicles, algorithm=req.algorithm,
        constraints=_dispatch_constraints(req),
        today_distance_m=req.today_distance_m,
    )
    return {
        "algorithm": plan.algorithm,
        "totals": {
            "reposition_m": plan.total_reposition_m,
            "deadhead_m": plan.total_deadhead_m,
            "stay_deadhead_m": plan.total_stay_deadhead_m,
            "saved_m": plan.total_saved_m,
            "net_two_day_m": plan.total_net_m,
        },
        "choices": [dataclasses.asdict(choice) for choice in plan.choices],
        "assumptions": list(plan.assumptions),
    }


def _prepare_dispatch(req: DispatchCreateIn):
    """Plan, accept and atomically persist one dispatch run."""
    orders, inventory, vehicles = _dispatch_inputs(req)
    plan = plan_delivery_orders(
        orders, inventory, vehicles, algorithm=req.algorithm,
        constraints=_dispatch_constraints(req),
    )
    planned_vehicle_ids = {
        vehicle_id for zone_plan in plan.zone_plans
        for vehicle_id in zone_plan.vehicle_ids
    }
    accepted_vehicles = tuple(
        vehicles
    )
    state = accept_plan(plan, orders, inventory, command_id=req.command_id,
                        vehicles=accepted_vehicles)
    if req.constraints.max_vehicles is not None:
        assigned = [v for v in accepted_vehicles if v.vehicle_id in state.vehicles]
        idle = [v for v in accepted_vehicles if v.vehicle_id not in state.vehicles]
        accepted_vehicles = tuple((assigned + idle)[:req.constraints.max_vehicles])
    plan_view = _dispatch_plan_response(
        plan, requested_algorithm=req.algorithm,
        constraints=req.constraints.model_dump(),
    )
    context = {
        "plan": plan_view,
        "fixed_daily_input": req.model_dump(exclude={"dispatch_id", "command_id"}),
        "input": {
            "orders": [item.model_dump() for item in req.orders],
            "inventory": [item.model_dump() for item in req.inventory],
            # Keep the persisted fleet identical to the solver's hard fleet
            # limit. Otherwise an excluded fourth vehicle could reappear later
            # as an emergency "spare" and silently bypass max_vehicles.
            "vehicles": [_vehicle_dump(vehicle) for vehicle in accepted_vehicles],
            "constraints": req.constraints.model_dump(),
        },
    }
    from zoneinfo import ZoneInfo
    context["fixed_daily_input"]["vehicles"] = context["input"]["vehicles"]
    context["operating_date"] = req.operating_date or datetime.datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat()
    if req.simulation:
        context["simulation"] = req.simulation
    return state, context


def create_dispatch(req: DispatchCreateIn) -> dict:
    state, context = _prepare_dispatch(req)
    create_run(DISPATCH_DATABASE_URL, req.dispatch_id, state, context=context)
    return {"dispatch_id": req.dispatch_id,
            "route_view": dispatch_route_view(state, context),
            **state_to_dict(state), **context}


def get_dispatch(dispatch_id: str) -> dict:
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    return {"dispatch_id": dispatch_id,
            "route_view": dispatch_route_view(state, context),
            **state_to_dict(state), **context}


def depart_dispatch(dispatch_id: str, command_id: str, speed: float | None = None) -> dict:
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    new = depart(old, command_id=command_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    if new is not old:
        # Departure starts the simulated clock at the operating-day minute the
        # vehicles roll, so positions are reproducible from the record alone.
        if not context.get("clock"):
            start = min((item["earliest_min"] for item in context["input"]["orders"]),
                        default=540)
            start = min([start, *(v.ready_from_min for v in new.vehicles.values() if v.ready_from_min is not None)])
            context["clock"] = make_clock(start, DEFAULT_CLOCK_SPEED if speed is None else speed)
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version, context=context)
    return {"dispatch_id": dispatch_id,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


def deliver_dispatch(dispatch_id: str, vehicle_id: str, command_id: str) -> dict:
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    new = deliver_next(old, vehicle_id, command_id=command_id)
    if new is not old:
        if context.get("clock"):
            vehicle = old.vehicles[vehicle_id]
            view = execution_view(vehicle, old, context)
            oid = vehicle.remaining_order_ids[0]
            index = next(i for i, stop in enumerate(view["stops"]) if stop["order_id"] == oid and stop["kind"] == "delivery")
            minute = max(watched_now(context["clock"]), view["track"]["service_starts"][index])
            context["clock"] = make_clock(minute, context["clock"]["speed"],
                started_real=datetime.datetime.now().isoformat(), depart_min=schedule_origin(context["clock"]))
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version, context=context)
    return {"dispatch_id": dispatch_id,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


# One shared operation: every disposition-triggered resupply lands in the live
# run so the map, the order list and the stock ledger always describe the same
# thing. Two parallel routing stories were exactly the problem this removes.
#
# 2026-09-15 (docs/C_配送模块.md §4.4-2): a resupply is a BRANCH of the day's
# delivery plan, not an operation of its own. The old code bootstrapped a
# one-order run out of a closed case the moment there was nothing to attach to,
# which is precisely how the multi-stop planner got reduced to a one-order
# vehicle dispatcher (§3.2). There is no bootstrap any more: no open plan means
# the branch is refused and the operator is told to create today's plan first.

#: Ids for "today's delivery plan" operations (doc §4.1) — the main line that
#: branch events attach to.
DAILY_PLAN_DISPATCH_PREFIX = "PLAN"


class NoActiveDeliveryPlan(ValueError):
    """A branch event arrived with no open daily plan to attach it to.

    Separate from a plain ``ValueError`` so the API can answer 409 (a state
    conflict the operator can fix) instead of 422 (a malformed request).
    """


def _resolve_daily_seed(seed: int | str | None) -> int | None:
    """``None`` → the fixed demo set; ``"today"`` → today's date; else the integer.

    ``"today"`` is the offline stand-in for a company's daily delivery feed: the
    batch is reproducible within the day (so a rehearsal or the report can replay
    it) and changes by itself tomorrow (so the demo does not show the same numbers
    forever).  Nothing here reaches out to a real order source — there is none in
    an offline prototype, and pretending otherwise would be the kind of claim this
    project's rules forbid.
    """
    if seed is None:
        return None
    if isinstance(seed, str):
        text = seed.strip().lower()
        if text in {"", "none"}:
            return None
        if text == "today":
            return int(datetime.date.today().strftime("%Y%m%d"))
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(
                f"seed must be an integer or 'today', got {seed!r}"
            ) from exc
    return int(seed)


def daily_plan_request(
    *, hospitals: int = 4, seed: int | str | None = None, temperature_zone: str = "chilled"
) -> dict:
    """A simulated order batch plus a ready-to-post planning body.

    Nothing is persisted: the client previews the batch through
    ``POST /api/dispatch/plan``, the operator looks at distance / vehicles /
    feasibility, and only ``POST /api/dispatch/runs`` creates the operation —
    the sequence doc §4.1 asks for ("操作员看方案 → 确认发车").
    """
    resolved_seed = _resolve_daily_seed(seed)
    orders, inventory, vehicles = daily_delivery_batch(
        hospitals=hospitals, seed=resolved_seed, temperature_zone=temperature_zone
    )
    return {
        "note": DAILY_PLAN_ASSUMPTIONS,
        "seed": resolved_seed,
        "hospitals": hospitals,
        "temperature_zone": temperature_zone,
        # Exactly the body /api/dispatch/plan accepts; /runs additionally needs
        # dispatch_id + command_id, which the client generates (see the front-end
        # store) so two clients cannot collide on the same id.
        "plan": {
            "algorithm": "greedy",
            # Dumped from the model rather than spelled out, so a new constraint
            # field can never be missing from the batch the operator is handed
            # (2026-09-16: mileage_limit_m / terminal_facility_ids were).
            "constraints": dataclasses.asdict(
                DispatchConstraints(
                    max_vehicles=FLEET_LIMIT,
                    max_stops_per_vehicle=MAX_STOPS_PER_VEHICLE,
                )
            ),
            "orders": [_order_dump(order) for order in orders],
            "inventory": [_lot_dump(lot) for lot in inventory],
            "vehicles": [_vehicle_dump(vehicle) for vehicle in vehicles],
        },
    }


def simulated_plan_request(req) -> dict:
    """Generate only; the existing plan/create endpoints decide feasibility."""
    values = req.model_dump()
    for field in ("product_ids", "origin_facility_ids"):
        if values[field] is not None:
            values[field] = tuple(values[field])
    batch = generate_simulated_batch(SimulationConfig(**values))
    return {
        "note": batch.metadata["assumptions"], "metadata": batch.metadata,
        "seed": batch.metadata["config"]["seed"], "scenario": req.scenario,
        "hospitals": len(batch.orders),
        "plan": {"algorithm": "greedy", "operating_date": batch.metadata["config"]["operating_date"],
            "simulation": batch.metadata, "constraints": dataclasses.asdict(batch.constraints),
            "orders": [_order_dump(o) for o in batch.orders],
            "inventory": [_lot_dump(lot) for lot in batch.inventory],
            "vehicles": [_vehicle_dump(vehicle) for vehicle in batch.vehicles]},
    }


def active_plan_run() -> tuple[str | None, object | None]:
    """The open daily delivery plan — the main line branch events attach to.

    Returns ``(dispatch_id, state)``, or ``(None, None)`` when there is nothing
    to attach to: either no plan was ever created, or every plan has already
    completed (a finished operation is history, not something to reopen). There
    is deliberately no "start a one-order operation instead" fallback — that
    fallback is what turned the multi-stop planner into a one-order vehicle
    dispatcher (``docs/C_配送模块.md`` §3.2, §4.4-2).

    "Open" is decided by ``updated_at`` in the repository, so it is the same
    operation the panel shows as active — not whichever id sorts highest, which
    is how a branch event once attached itself to a stale finished plan.
    """
    found = latest_open_dispatch_id(DISPATCH_DATABASE_URL, DAILY_PLAN_DISPATCH_PREFIX)
    return found if found is not None else (None, None)


def _require_plan() -> tuple[str, object]:
    dispatch_id, state = active_plan_run()
    if state is None:
        raise NoActiveDeliveryPlan(
            "no daily delivery plan is open: create today's delivery plan before "
            "routing a branch event (see POST /api/dispatch/daily-orders and "
            "POST /api/dispatch/runs)"
        )
    return dispatch_id, state


def get_active_dispatch() -> dict:
    """The live operation for the front-end, whichever pathway created it.

    ``get_active_reshipment_dispatch`` above deliberately only saw the
    ``RESHIPMENTS-`` stream, because that prefix rule is what made reshipment
    bootstrapping deterministic.  The panel, however, must also be able to show
    a "today's delivery plan" built from a batch of ordinary orders
    (``PLAN-…`` via ``POST /api/dispatch/runs``) — without this, an operator
    could create a plan and the panel would keep saying "no active dispatch
    operation".  KeyError when nothing is open.

    "Open" means *anything is still happening*: an operation whose orders are all
    delivered is NOT over while its trucks are still driving home, and treating it
    as over made the panel drop the operation (and the map lose the vehicle) at
    the exact moment the last order was delivered.
    """
    latest = latest_dispatch_id(DISPATCH_DATABASE_URL)
    if latest is None:
        raise KeyError("no dispatch run has ever been created")
    view = get_dispatch(latest)
    if view["status"] == "completed" and not view["route_view"]["metrics"]["still_returning"]:
        raise KeyError(latest)
    return view


def _order_dump(order: DeliveryOrder) -> dict:
    return {
        "order_id": order.order_id, "product_id": order.product_id,
        # The pickup point travels with the order: dropping it here is how a
        # distribution-point order silently turned into a warehouse order (B1b).
        "origin_facility_id": order.origin_facility_id,
        "destination_facility_id": order.destination_facility_id,
        "quantity": order.quantity, "earliest_min": order.earliest_min,
        "latest_min": order.latest_min, "temperature_zone": order.temperature_zone,
        "source_run_id": order.source_run_id,
        "replaces_order_id": order.replaces_order_id,
    }


def _lot_dump(lot: InventoryLot) -> dict:
    return {
        "lot_id": lot.lot_id, "product_id": lot.product_id,
        "facility_id": lot.facility_id, "available_quantity": lot.available_quantity,
        "temperature_zone": lot.temperature_zone, "status": lot.status,
    }


def _vehicle_dump(vehicle: DispatchVehicle) -> dict:
    return {
        "vehicle_id": vehicle.vehicle_id, "capacity": vehicle.capacity,
        "temperature_zone": vehicle.temperature_zone,
        "start_facility_id": vehicle.start_facility_id,
        "available_from_min": vehicle.available_from_min, "status": vehicle.status,
        # Spare stock the vehicle carries beyond its assigned orders. It is a
        # load assumption, not a depot lot, so it never enters the ledger.
        "onboard_spare": [
            {"product_id": product_id, "temperature_zone": zone, "quantity": quantity}
            for product_id, zone, quantity in vehicle.onboard_spare
        ],
    }


def _minute_of_day(timestamp: str | None) -> int:
    """Case timestamp → minutes since midnight (the dispatch clock).

    Falls back to the depot's opening minute rather than inventing "now", so a
    replayed or imported record routes deterministically.
    """
    try:
        moment = datetime.datetime.fromisoformat(timestamp or "")
    except (TypeError, ValueError):
        return 540
    return moment.hour * 60 + moment.minute


def _dispatch_clock(record: dict, order: DeliveryOrder) -> tuple[int, bool]:
    """The minute-of-day to plan from, and whether that means the next day.

    A case raised after the destination's receiving window has closed cannot be
    delivered today. Reporting "no vehicle can deliver this" would be wrong —
    vehicles exist, the day ended — so the resupply is planned from the next
    opening instead, and the caller is told that is what happened. The model
    carries minutes-of-day only, so a next-day delivery is expressed as that
    day's window rather than an absolute timestamp.
    """
    now = _minute_of_day(record.get("created_at"))
    if now <= order.latest_min:
        return now, False
    return order.earliest_min, True




def dispatch_route_view(state, context: dict) -> dict:
    """Draw the same per-vehicle schedule that the tick settles."""
    network = read_network()
    by_node = {n["node_id"]: n for n in network["nodes"]}
    orders = {o["order_id"]: o for o in context["input"]["orders"]}
    clock = context.get("clock")
    now = watched_now(clock) if clock else None
    routes, features = [], []
    for vehicle_id, vehicle in sorted(state.vehicles.items()):
        view = execution_view(vehicle, state, context, network=network, now=now)
        stops = view["stops"]
        present = {stop["order_id"] for stop in stops if stop["kind"] == "delivery"}
        history = []
        for oid in vehicle.delivered_order_ids:
            if oid in present:
                continue
            order = orders[oid]
            node = next(n for n in network["nodes"] if n["facility_id"] == order["destination_facility_id"])
            history.append({"node_id": node["node_id"], "kind": "delivery", "order_id": oid,
                            "quantity": order["quantity"], "delivered": True,
                            "earliest_min": order["earliest_min"], "latest_min": order["latest_min"]})
        stops = history + stops
        track = view["track"]
        if track and history:
            track = {**track, "reached_stops": track["reached_stops"] + len(history)}
        legs = [{**leg, "driven": True} for leg in vehicle.historical_legs] + view["legs"]
        if track and track.get("approaching_checkpoint") and vehicle.historical_legs:
            legs[len(vehicle.historical_legs) - 1]["driven"] = False
        coords = []
        for leg in legs:
            coords.extend(leg["coords"] if not coords else leg["coords"][1:])
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                         "properties": {"vehicle_id": vehicle_id, "node_order": view["node_sequence"]}})
        routes.append({
            "vehicle_id": vehicle_id, "status": vehicle.status,
            "start_node_id": view["start_node_id"], "start_facility_id": view["start_facility_id"],
            "end_node_id": view["end_node_id"], "end_facility_id": by_node[view["end_node_id"]]["facility_id"],
            "customer_ids": [stop["node_id"] for stop in stops], "stops": stops,
            "legs": legs, "track": track,
            "total_load": sum(state.orders[oid].quantity for oid in vehicle.remaining_order_ids),
            "total_distance": round(view["total_distance_m"] / 1000, 2),
            "distance_driven_m": round(view["distance_driven_m"], 2),
            "schedule_start_min": view["started_min"],
        })
    return {
        "routes": routes, "clock": clock,
        "sim_now_min": None if now is None else round(now, 2),
        "geojson": {"type": "FeatureCollection", "features": features,
                    "attribution": network.get("provenance", {}).get("attribution", "")},
        "metrics": {
            "vehicles_used": len(routes),
            "total_distance": round(sum(r["total_distance"] for r in routes), 2),
            "orders_total": len(state.orders),
            "orders_delivered": sum(o.status == "delivered" for o in state.orders.values()),
            "orders_scrapped": sum(o.status == "scrapped" for o in state.orders.values()),
            "orders_failed": sum(o.status == "failed" for o in state.orders.values()),
            "stock_remaining": sum(state.available_by_lot.values()),
            "still_returning": sum(bool(r["track"] and not r["track"]["finished"]) for r in routes),
        },
    }


# The demo fleet is deliberately larger than network.json's 3: each resupply
# currently takes its own spare (see docs/C_配送模块.md D1), so a short demo runs out
# of vehicles and starts consolidating before the operator meant it to.
FLEET_SIZE = 6

# One real second = one simulated minute. Real time (speed 1) stays available
# for honesty, but a 25-minute drive is unwatchable at 1x.
#: 0 freezes simulated time (a real pause for the transport view). It is a
#: genuine freeze, not a stopped refresh: simulated time is derived from the
#: wall clock times the speed, so nothing advances while it is 0, and resuming
#: re-bases the clock on the frozen minute instead of jumping forward.
DEFAULT_CLOCK_SPEED = 60.0
ALLOWED_CLOCK_SPEEDS = (0.0, 1.0, 60.0, 300.0)


def _zone_fleet(zone: str) -> tuple[DispatchVehicle, ...]:
    """The demo fleet for one temperature zone, sized from the committed network.

    Fleet size and capacity come from ``network.json`` (the same numbers the
    Solomon-style demo instance already documents as simulated) rather than
    invented constants. Sizing a vehicle to one order's quantity would leave
    zero free capacity, so the next resupply could never join the run.
    """
    network = read_network()
    return tuple(
        DispatchVehicle(f"VEH-{zone}-{index}", network["capacity"], zone, DISPATCH_ORIGIN)
        for index in range(1, FLEET_SIZE + 1)
    )


def _prepare_branch(state, context: dict, order: DeliveryOrder):
    """Add a case's replacement stock — and a fleet if its zone has none — in memory.

    A closed case's replacement stock is NEW stock: it did not exist when the
    plan was accepted, so it must enter the ledger before any candidate is
    judged, or every option would be refused for "insufficient inventory". Both
    the read-only preview and the committing call run through here, so what the
    operator was shown and what is then applied cannot disagree.
    """
    lot = InventoryLot(f"LOT-{order.order_id}", order.product_id, order.origin_facility_id or DISPATCH_ORIGIN,
                       order.quantity, order.temperature_zone)
    inventory = [*context["input"]["inventory"], _lot_dump(lot)]
    vehicles = list(context["input"]["vehicles"])
    if not any(item["temperature_zone"] == order.temperature_zone for item in vehicles):
        # A product in a zone the plan has no fleet for (e.g. the first frozen
        # case on a chilled-only plan) needs vehicles before it can ship.
        limit = context["input"].get("constraints", {}).get("max_vehicles")
        room = FLEET_SIZE if limit is None else max(0, limit - len(vehicles))
        vehicles.extend(_vehicle_dump(v) for v in _zone_fleet(order.temperature_zone)[:room])
    context = {
        **context,
        "input": {**context["input"], "inventory": inventory, "vehicles": vehicles},
    }
    state = dataclasses.replace(
        state,
        available_by_lot={**state.available_by_lot, lot.lot_id: lot.available_quantity},
    )
    return state, context, lot


def _with_candidate_geometry(network: dict, preview: dict) -> dict:
    """Attach drawable geometry — and the extra distance — to every option.

    "改道前 vs 改道后" is the figure this module exists to produce
    (``docs/C_配送模块.md`` §4.3), and it cannot be drawn from ETAs alone. Each
    candidate gets the line its vehicle would drive (``route_geojson``) and how
    much further that is than simply continuing (``added_distance_m``); the
    vehicle's current line comes back once per vehicle under ``baselines``.
    """
    baselines = preview.get("baselines", {})
    for vehicle_id, baseline in baselines.items():
        sequence = baseline.get("node_sequence") or []
        baseline["route_geojson"] = sequence_geojson(
            network, sequence, kind="baseline", vehicle_id=vehicle_id)
        baseline["distance_m"] = round(sequence_distance_m(network, sequence), 1)
    for item in preview.get("candidates", []):
        sequence = item.get("node_sequence") or []
        item["route_geojson"] = sequence_geojson(
            network, sequence, kind=item["kind"], vehicle_id=item["vehicle_id"])
        item["sequence_distance_m"] = round(sequence_distance_m(network, sequence), 1)
        baseline = baselines.get(item["vehicle_id"], {}).get("node_sequence")
        item["added_distance_m"] = round(
            item["sequence_distance_m"]
            - (sequence_distance_m(network, baseline) if baseline else 0.0), 1)
    return preview


def _order_source(linked) -> str:
    """Where the rescue order's product/hospital/quantity came from."""
    return "linked_order" if linked is not None else "event_fallback"


def _linked_order(record: dict, state) -> object | None:
    """The transport order this excursion concerns, when the input named one.

    The simulated excursion carries ``event.order_id`` (2026-09-16), so the
    rescue reads the product, the receiving hospital and the quantity straight
    off that order instead of guessing from a dropdown and a node's demo demand.
    Naming an order that is not in the running operation is an error, not a
    silent fallback: the whole point is that the link is real.
    """
    order_id = (record.get("event") or {}).get("order_id")
    if not order_id:
        return None
    order = state.orders.get(order_id)
    if order is None:
        raise ValueError(
            f"case {record['run_id']} is linked to order {order_id!r}, which is not "
            "part of the running operation"
        )
    return order


def _case_operation(record):
    dispatch_id = record.get("event", {}).get("dispatch_id") or record.get("handling_dispatch_id")
    if not dispatch_id:
        return _require_plan()  # compatibility for previously unbound demo cases
    try:
        return dispatch_id, load_run(DISPATCH_DATABASE_URL, dispatch_id)
    except KeyError as exc:
        raise ValueError("the incident's linked dispatch no longer exists") from exc


def _live_minute(context: dict, requested: float) -> float:
    return max(float(requested), watched_now(context["clock"])) if context.get("clock") else float(requested)


def reshipment_branch_plan(record: dict, *, policy: str = DEFAULT_POLICY) -> dict:
    """Every way this closed case could be served — read-only, nothing reserved.

    The operator looks at the options (which vehicle, how far, how late, who else
    is affected) and picks one; :func:`route_reshipment` then revalidates and
    applies exactly that choice. Deriving the order happens here too, so the UI
    never has to guess a destination or a quantity.
    """
    # Case-level refusal first: "this needs no reshipment" is a fact about the
    # case, and must not be masked by "no plan is open".
    if not record.get("reshipment_required"):
        raise ValueError(f"case {record['run_id']} does not require reshipment")
    dispatch_id, state = _case_operation(record)
    linked = _linked_order(record, state)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    source = next((o for o in context["input"]["orders"] if linked and o["order_id"] == linked.order_id), None)
    order = build_delivery_order(record, linked_order=linked, linked_input=source)
    if order is None:  # pragma: no cover - guarded just above
        raise ValueError(f"case {record['run_id']} does not require reshipment")
    clock, next_day = _dispatch_clock(record, order)
    # The case is about this shipment: if its goods are still in a truck, adopting
    # a plan has to scrap them rather than deliver them (B6, 2026-09-16).
    spoiled_id = linked.order_id if linked is not None else None
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    if context.get("clock"):
        clock = watched_now(context["clock"])
        next_day = clock > order.latest_min
    if linked and linked.order_id in context.get("nominal_order_ids", ()):
        context = {**context, "nominal_order_ids": [*context["nominal_order_ids"], order.order_id]}
    state, context, _ = _prepare_branch(state, context, order)
    if order.order_id in state.orders:  # already committed: show it, don't re-judge
        return {"dispatch_id": dispatch_id, "order_id": order.order_id,
                "already_committed": True, "scheduled_next_day": next_day,
                "order_source": _order_source(linked),
                "spoiled_order_id": spoiled_id,
                "order": _order_dump(order), "policy": policy, "candidates": [],
                "baselines": {}}
    if state.status == "completed" or context.get("next_day_dispatch_id"):
        raise ValueError("the incident's operating day is completed; it cannot be inserted into another day")
    preview = ({"feasible": False, "reason": "receiving_window_closed_today",
                "candidates": [], "baselines": {}, "current_time_min": clock}
               if next_day and context.get("clock") else
               preview_emergency_order(state, context, order, current_time_min=clock,
                                       policy=policy, spoiled_order_id=spoiled_id))
    return {
        "dispatch_id": dispatch_id,
        "order_id": order.order_id,
        "already_committed": False,
        "scheduled_next_day": next_day,
        "order_source": _order_source(linked),
        "spoiled_order_id": spoiled_id,
        "order": _order_dump(order),
        **_with_candidate_geometry(read_network(), preview),
    }


def route_reshipment(record: dict, *, candidate_kind: str | None = None,
                     vehicle_id: str | None = None,
                     policy: str = DEFAULT_POLICY) -> dict:
    """Attach ONE closed reshipment case to the day's plan as a branch event.

    The case becomes a real ``DeliveryOrder`` and is inserted into the operation
    that is already running, so a resupply is always checked against real stock,
    real capacity and the orders already on board. With no open plan there is
    nothing to branch from: the case is refused rather than quietly promoted into
    an operation of its own (``docs/C_配送模块.md`` §4.4-2).
    """
    if not record.get("reshipment_required"):
        raise ValueError(f"case {record['run_id']} does not require reshipment")
    dispatch_id, state = _case_operation(record)
    linked = _linked_order(record, state)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    source = next((o for o in context["input"]["orders"] if linked and o["order_id"] == linked.order_id), None)
    order = build_delivery_order(record, linked_order=linked, linked_input=source)
    if order is None:  # pragma: no cover - guarded just above
        raise ValueError(f"case {record['run_id']} does not require reshipment")
    clock, next_day = _dispatch_clock(record, order)
    # If the case names the shipment it is about and that shipment is still in a
    # truck, adopting a plan must scrap it instead of delivering it.
    spoiled_id = linked.order_id if linked is not None else None

    if order.order_id in state.orders:  # replaying the same case must not double-book
        context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
        return {"dispatch_id": dispatch_id, "inserted": False,
                "scheduled_next_day": next_day,
                "route_view": dispatch_route_view(state, context),
                **state_to_dict(state), **context}

    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    if state.status == "completed" or context.get("next_day_dispatch_id"):
        raise ValueError("the incident's operating day is completed; it cannot be inserted into another day")
    if context.get("clock"):
        clock = watched_now(context["clock"])
        next_day = clock > order.latest_min
        if next_day:
            raise ValueError("receiving window is closed today; start the next operating day before applying this reshipment")
    if linked and linked.order_id in context.get("nominal_order_ids", ()):
        context = {**context, "nominal_order_ids": [*context["nominal_order_ids"], order.order_id]}
    state, context, _ = _prepare_branch(state, context, order)
    if candidate_kind is None or vehicle_id is None:
        kind, carrier = _pick_candidate(state, context, order, clock, policy,
                                        spoiled_order_id=spoiled_id)
    else:
        # An explicit choice from the comparison card: revalidated by
        # accept_emergency_order, never trusted as given.
        kind, carrier = candidate_kind, vehicle_id
    new = accept_emergency_order(
        state, context, order,
        current_time_min=clock,
        candidate_kind=kind, vehicle_id=carrier,
        command_id=f"reship-{order.order_id}",
        policy=policy,
        spoiled_order_id=spoiled_id,
    )
    # Context carries the order for later previews: without it, the next case's
    # affected-order simulation cannot resolve this one's window.
    context["input"]["orders"].append(_order_dump(order))
    update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=state.version, context=context)
    scrapped = [oid for oid, item in new.orders.items() if item.status == "scrapped"]
    return {"dispatch_id": dispatch_id, "inserted": True,
            "candidate_kind": kind, "vehicle_id": carrier,
            "scheduled_next_day": next_day,
            # Which shipments this action scrapped, so the caller (and the audit
            # trail) can tell "delivered" from "written off" (B6).
            "scrapped_order_ids": scrapped,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


def _pick_candidate(state, context: dict, order: DeliveryOrder, clock: int,
                    policy: str = DEFAULT_POLICY,
                    spoiled_order_id: str | None = None) -> tuple[str, str]:
    """The best on-time option the dispatch preview actually offers.

    Delegating to the preview means the capacity, temperature-zone, onboard-spare
    and knock-on-lateness rules are enforced here too — this bridge never invents
    a vehicle the optimiser would have rejected. Returns the candidate's kind as
    well: picking its vehicle but assuming a kind would apply the wrong state
    transition (a spare vehicle starts a new task; an in-transit one detours).
    """
    preview = preview_emergency_order(
        state, context, order, current_time_min=clock, policy=policy,
        spoiled_order_id=spoiled_order_id,
    )
    candidate = preview.get("selected_candidate")
    if candidate is None or not candidate["on_time"]:
        raise ValueError(
            f"no vehicle can deliver resupply {order.order_id} within its window "
            f"({preview.get('reason', 'no on-time candidate')})"
        )
    return candidate["kind"], candidate["vehicle_id"]


def urgent_options():
    """Capabilities, not warehouse balances. The comparison warehouse can park only."""
    from optimisation.catalog import read_catalog, read_supply_points, supplies_product
    catalog, points = read_catalog(), read_supply_points()
    network = read_network()
    by_point = {p.facility_id: p for p in points}
    return {"products": [dataclasses.asdict(p) for p in catalog],
        "warehouses": [{"facility_id": n["facility_id"], "name": n["name"],
            "product_ids": [p.product_id for p in catalog if n["facility_id"] in by_point
                            and supplies_product(by_point[n["facility_id"]], p.product_id)]}
            for n in network["nodes"] if n["facility_id"] in warehouse_ids(network)],
        "destinations": [{key: n[key] for key in ("facility_id", "name", "earliest_min", "latest_min")}
                         for n in network["nodes"] if n["role"] == "customer"],
        "resource_mode": "demo_nominal", "note": "No real order quantities or warehouse balances are required."}


def _urgent_payload(req):
    return {key: getattr(req, key) for key in (
        "request_id", "product_id", "origin_facility_id", "destination_facility_id",
        "earliest_min", "latest_min", "policy")}


def _prepare_urgent(state, context, req):
    from optimisation.catalog import product_zones, read_supply_points, supplies_product
    zones = product_zones()
    if req.product_id not in zones:
        raise ValueError("unknown urgent product_id")
    point = next((p for p in read_supply_points() if p.facility_id == req.origin_facility_id), None)
    if point is None or not supplies_product(point, req.product_id):
        raise ValueError("selected pickup warehouse cannot supply this product")
    network = read_network()
    destination = next((n for n in network["nodes"] if n["facility_id"] == req.destination_facility_id
                        and n["role"] == "customer"), None)
    if destination is None:
        raise ValueError("urgent destination must be a receiving hospital")
    validate_terminals(network, context["input"].get("constraints", {}).get("terminal_facility_ids"))
    if state.status not in {"accepted", "in_transit"} or context.get("overnight"):
        raise ValueError("urgent order needs an open delivery day; create or start the next day first")
    now = watched_now(context["clock"]) if context.get("clock") else min(
        o["earliest_min"] for o in context["input"]["orders"])
    if req.current_time_min is not None:
        now = max(now, req.current_time_min)
    earliest = max(destination["earliest_min"], math.ceil(now), req.earliest_min or 0)
    if req.latest_min < earliest:
        raise ValueError("urgent deadline has passed or is before the receiving window")
    if req.latest_min > destination["latest_min"]:
        raise ValueError("urgent deadline must be within the hospital receiving window")
    order_id = f"URG-{req.request_id}"
    if order_id in state.orders:
        raise ValueError("urgent order ID already exists")
    order = DeliveryOrder(order_id, req.product_id, req.destination_facility_id, 1,
                          earliest, req.latest_min, zones[req.product_id], origin_facility_id=req.origin_facility_id)
    # One compatibility token, not a box count or a replenishment of real stock.
    lot = InventoryLot(f"DEMO-{order_id}", order.product_id, req.origin_facility_id, 1, order.temperature_zone)
    staged = copy.deepcopy(context)
    staged.setdefault("nominal_order_ids", []).append(order_id)
    staged["input"]["inventory"].append(_lot_dump(lot))
    state = dataclasses.replace(state, available_by_lot={**state.available_by_lot, lot.lot_id: 1})
    return state, staged, order, now


def preview_urgent_dispatch(dispatch_id, req):
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    previous = context.get("urgent_requests", {}).get(req.request_id)
    if previous:
        if previous["payload"] != _urgent_payload(req):
            raise ValueError("request_id already belongs to a different urgent order")
        return {"dispatch_id": dispatch_id, "state_version": state.version, "already_committed": True,
                "order": previous["order"], "candidates": [], "resource_mode": "demo_nominal"}
    staged, context, order, now = _prepare_urgent(state, context, req)
    preview = preview_emergency_order(staged, context, order, current_time_min=now, policy=req.policy)
    return {"dispatch_id": dispatch_id, "state_version": state.version, "request_id": req.request_id,
            "order": _order_dump(order), "already_committed": False, "resource_mode": "demo_nominal",
            **_with_candidate_geometry(read_network(), preview)}


def accept_urgent_dispatch(dispatch_id, req):
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    previous = context.get("urgent_requests", {}).get(req.request_id)
    choice = {"candidate_kind": req.candidate_kind, "vehicle_id": req.vehicle_id, "command_id": req.command_id}
    if previous:
        if previous["payload"] != _urgent_payload(req) or previous["choice"] != choice:
            raise ValueError("request_id already belongs to another urgent order or choice")
        return {**get_dispatch(dispatch_id), "urgent_result": {"already_committed": True, "order_id": previous["order"]["order_id"]}}
    if old.version != req.expected_version:
        raise ValueError("dispatch changed after urgent preview; preview again")
    if req.command_id in old.applied_commands:
        raise ValueError("command_id is already in use")
    staged, context, order, now = _prepare_urgent(old, context, req)
    new = accept_emergency_order(staged, context, order, current_time_min=now,
        candidate_kind=req.candidate_kind, vehicle_id=req.vehicle_id, command_id=req.command_id, policy=req.policy)
    context["input"]["orders"].append(_order_dump(order))
    if req.candidate_kind == "add_stop_in_transit":
        token = f"DEMO-{order.order_id}"
        new = dataclasses.replace(new, available_by_lot={k: v for k, v in new.available_by_lot.items() if k != token})
        context["input"]["inventory"] = [lot for lot in context["input"]["inventory"] if lot["lot_id"] != token]
    context.setdefault("urgent_requests", {})[req.request_id] = {"payload": _urgent_payload(req), "choice": choice,
        "order": _order_dump(order), "resource_mode": "demo_nominal", "accepted_at_min": now}
    update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version, context=context)
    return {**get_dispatch(dispatch_id), "urgent_result": {"already_committed": False, "order_id": order.order_id}}


def emergency_dispatch_preview(dispatch_id: str, req: EmergencyPreviewIn) -> dict:
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    preview = preview_emergency_order(
        state,
        context,
        DeliveryOrder(**req.order.model_dump()),
        current_time_min=_live_minute(context, req.current_time_min),
        policy=req.policy,
    )
    return _with_candidate_geometry(read_network(), preview)


def accept_emergency_dispatch(dispatch_id: str, req: EmergencyAcceptIn) -> dict:
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    order = DeliveryOrder(**req.order.model_dump())
    new = accept_emergency_order(
        old, context, order,
        current_time_min=_live_minute(context, req.current_time_min),
        candidate_kind=req.candidate_kind,
        vehicle_id=req.vehicle_id,
        command_id=req.command_id,
        policy=req.policy,
    )
    if new is not old:
        # The accepted order must join the context, not just the state: the
        # next emergency preview simulates every remaining order's arrival by
        # looking its window up here, and would fail on an order it cannot see.
        known = {item["order_id"] for item in context["input"]["orders"]}
        if order.order_id not in known:
            context["input"]["orders"].append(_order_dump(order))
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version, context=context)
    return {"dispatch_id": dispatch_id,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


def _with_failure_geometry(preview: dict) -> dict:
    """Attach a drawable route to every mechanical-failure candidate."""
    network = read_network()
    for item in preview.get("candidates", []):
        item["route_geojson"] = sequence_geojson(
            network, item["node_sequence"], kind="mechanical_failure",
            vehicle_id=item["vehicle_id"],
        )
    return preview


def vehicle_failure_preview(dispatch_id: str, req: VehicleFailurePreviewIn) -> dict:
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    return _with_failure_geometry(preview_vehicle_failure(
        state, context, failed_vehicle_id=req.failed_vehicle_id,
        current_time_min=_live_minute(context, req.current_time_min),
    ))


def accept_vehicle_failure_dispatch(dispatch_id: str, req: VehicleFailureAcceptIn) -> dict:
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    new, outcome = accept_vehicle_failure(
        old, context,
        failed_vehicle_id=req.failed_vehicle_id,
        replacement_vehicle_id=req.replacement_vehicle_id,
        current_time_min=_live_minute(context, req.current_time_min),
        command_id=req.command_id,
    )
    if new is not old:
        replacement_ids = set(outcome["replacement_order_ids"])
        known = {item["order_id"] for item in context["input"]["orders"]}
        for order in new.orders.values():
            if order.order_id not in replacement_ids or order.order_id in known:
                continue
            context["input"]["orders"].append({
                "order_id": order.order_id,
                "product_id": order.product_id,
                "destination_facility_id": order.destination_facility_id,
                "quantity": order.quantity,
                "earliest_min": next(
                    item["earliest_min"] for item in context["input"]["orders"]
                    if item["order_id"] == order.replaces_order_id
                ),
                "latest_min": next(
                    item["latest_min"] for item in context["input"]["orders"]
                    if item["order_id"] == order.replaces_order_id
                ),
                "temperature_zone": next(
                    item["temperature_zone"] for item in context["input"]["orders"]
                    if item["order_id"] == order.replaces_order_id
                ),
                "origin_facility_id": next(
                    item.get("origin_facility_id") for item in context["input"]["orders"]
                    if item["order_id"] == order.replaces_order_id
                ),
                "replaces_order_id": order.replaces_order_id,
                "source_run_id": None,
            })
        context.setdefault("mechanical_failures", []).append({
            "failed_vehicle_id": req.failed_vehicle_id,
            "failed_order_ids": outcome["failed_order_ids"],
            "replacement_order_ids": outcome["replacement_order_ids"],
            "replacement_vehicle_id": req.replacement_vehicle_id,
            "recovery_mode": "replacement_delivery",
            "transfer_facility_id": None,
        })
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version, context=context)
    return {
        "dispatch_id": dispatch_id,
        "failure": outcome,
        "route_view": dispatch_route_view(new, context),
        **state_to_dict(new), **context,
    }


def _delay_inspection_min(context: dict, requested: float | None) -> float:
    """Use the live operation clock unless an integration supplied its own time."""
    if requested is not None:
        return float(requested)
    clock = context.get("clock")
    if clock is None:
        raise ValueError(
            "delay inspection needs a departed dispatch clock or current_time_min"
        )
    return watched_now(clock)


def delay_dispatch_preview(dispatch_id: str, req: DelayPreviewIn) -> dict:
    """Read-only forecast of current delivery-window risk and queue remedies."""
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    current_time = _delay_inspection_min(context, req.current_time_min)
    preview = preview_delay_risks(
        state, context, current_time_min=current_time, delay_min=req.delay_min,
    )
    return {
        "dispatch_id": dispatch_id,
        **_with_candidate_geometry(read_network(), preview),
    }


def accept_delay_dispatch(dispatch_id: str, req: DelayAcceptIn) -> dict:
    """Persist one independently previewed delay recovery, with an audit record."""
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    duplicate = req.command_id in old.applied_commands
    if not duplicate and old.version != req.expected_version:
        raise ValueError("dispatch changed after delay preview; inspect again")
    current_time = _delay_inspection_min(context, req.current_time_min)
    if context.get("clock"):
        current_time = max(current_time, watched_now(context["clock"]))
    new, outcome = accept_delay_replan(
        old, context, vehicle_id=req.vehicle_id, current_time_min=current_time,
        delay_min=req.delay_min, command_id=req.command_id,
    )
    if new is not old:
        candidate = outcome["candidate"]
        if candidate["remaining_order_ids_after"] != req.remaining_order_ids_after:
            raise ValueError("delay candidate changed after preview; inspect again")
        # Retain just the business decision, not a render-only GeoJSON duplicate.
        context.setdefault("delay_replans", []).append({
            "vehicle_id": req.vehicle_id,
            "inspected_at_min": candidate["inspected_at_min"],
            "delay_min": req.delay_min,
            "original_order_ids": candidate["original_order_ids"],
            "remaining_order_ids_after": candidate["remaining_order_ids_after"],
            "baseline": candidate["baseline"],
            "replanned": candidate["replanned"],
            "search_method": candidate["search_method"],
        })
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new,
                   expected_version=old.version, context=context)
    return {
        "dispatch_id": dispatch_id,
        "delay_replan": outcome,
        "route_view": dispatch_route_view(new, context),
        **state_to_dict(new), **context,
    }


def recent_dispatch_runs(limit: int = 5) -> list[dict]:
    """Recent operations, newest first — what the console can replay."""
    return recent_runs(DISPATCH_DATABASE_URL, limit)


def _overnight_run_preview(state, context, req):
    from optimisation.overnight import plan_overnight_parking
    network = read_network()
    by_node = {n["node_id"]: n for n in network["nodes"]}
    by_facility = {n["facility_id"]: n for n in network["nodes"]}
    if state.status != "completed" or not context.get("clock"):
        raise ValueError("finish today's deliveries and return/parking legs before overnight confirmation")
    now = watched_now(context["clock"])
    if any(view["track"] and not view["track"]["finished"] for view in (
        execution_view(v, state, context, network=network, now=now)
        for v in state.vehicles.values() if v.status != "failed")):
        raise ValueError("vehicles are still driving; finish today's closing legs first")
    source = req.tomorrow.model_dump() if req.tomorrow else {
        **(context.get("fixed_daily_input") or context["input"]),
        "algorithm": context.get("plan", {}).get("algorithm", "greedy")}
    source = DispatchPlanIn(**source).model_dump()
    current_day = datetime.date.fromisoformat(context.get("operating_date") or
        datetime.datetime.fromisoformat(context["clock"]["started_real"]).date().isoformat())
    next_operating_date = (current_day + datetime.timedelta(days=1)).isoformat()
    if req.tomorrow and req.tomorrow.operating_date and req.tomorrow.operating_date != next_operating_date:
        raise ValueError("tomorrow's operating_date must be the next day of this dispatch")
    source["operating_date"] = next_operating_date
    if source.get("simulation"):
        source["simulation"] = {**source["simulation"], "carried_forward_to": next_operating_date,
                                "note": "Fixed simulated batch carried forward; not newly generated orders."}
    from optimisation.catalog import product_zones, read_supply_points, supplies_product
    carried = [{**lot, "available_quantity": state.available_by_lot.get(lot["lot_id"], 0)}
               for lot in context["input"]["inventory"] if lot.get("status", "available") == "available"]
    lot_ids = {lot["lot_id"] for lot in context["input"]["inventory"]}
    points = {p.facility_id: p for p in read_supply_points()}
    zones = product_zones()
    additions = []
    for lot in req.replenishments:
        if lot.lot_id in lot_ids:
            raise ValueError(f"replenishment lot {lot.lot_id!r} already exists")
        if lot.status != "available" or lot.available_quantity <= 0:
            raise ValueError("replenishments must be available positive quantities")
        point = points.get(lot.facility_id)
        if point is None or not supplies_product(point, lot.product_id) or zones.get(lot.product_id) != lot.temperature_zone:
            raise ValueError(f"invalid replenishment source/product/temperature for {lot.lot_id!r}")
        lot_ids.add(lot.lot_id)
        additions.append(lot.model_dump())
    if req.demo_replenish:
        # Route demo: product supply is a capability, not a real warehouse balance.
        demand = {}
        available = {}
        for lot in (*carried, *additions):
            key = (lot["facility_id"], lot["product_id"], lot["temperature_zone"])
            available[key] = available.get(key, 0) + lot["available_quantity"]
        for order in source["orders"]:
            if order.get("source_run_id") or order.get("replaces_order_id") or order["order_id"] in context.get("nominal_order_ids", ()):
                continue
            key = (order.get("origin_facility_id") or DISPATCH_ORIGIN, order["product_id"], order["temperature_zone"])
            demand[key] = demand.get(key, 0) + order["quantity"]
        for index, ((origin, product, zone), needed) in enumerate(sorted(demand.items())):
            shortfall = max(0, needed - available.get((origin, product, zone), 0))
            if shortfall:
                token = f"DEMO-NEXT-{next_operating_date}-{origin}-{product}"
                while token in lot_ids:
                    token += "-new"
                lot_ids.add(token)
                additions.append(_lot_dump(InventoryLot(token, product, origin, shortfall, zone)))
    source["inventory"] = carried + additions
    source["orders"] = [o for o in source["orders"] if not o.get("source_run_id") and not o.get("replaces_order_id")
                        and o["order_id"] not in context.get("nominal_order_ids", ())]
    if not source["orders"]:
        raise ValueError("the next day needs at least one fixed delivery order")
    declared = {v["vehicle_id"]: v for v in context["input"]["vehicles"]}
    current_vehicles, distance_today = [], {}
    for requested in source["vehicles"]:
        vehicle_id = requested["vehicle_id"]
        if vehicle_id not in declared:
            raise ValueError(f"vehicle {vehicle_id!r} is not in today's declared fleet")
        progress = state.vehicles.get(vehicle_id)
        if progress and progress.status == "failed":
            continue
        vehicle = {**declared[vehicle_id], "status": "available"}
        if progress:
            vehicle["onboard_spare"] = [{"product_id": p, "temperature_zone": z, "quantity": q}
                                        for p, z, q in progress.onboard_spare]
            view = execution_view(progress, state, context, network=network, now=now)
            vehicle["start_facility_id"] = by_node[view["end_node_id"]]["facility_id"]
            distance_today[vehicle_id] = view["distance_driven_m"]
        else:
            distance_today[vehicle_id] = 0
        current_vehicles.append(vehicle)
    source["vehicles"] = current_vehicles
    unknown = set(req.parking_overrides) - {v["vehicle_id"] for v in current_vehicles}
    if unknown:
        raise ValueError(f"unknown parking vehicles: {sorted(unknown)}")
    future_request = DispatchPlanIn(**source)
    orders, inventory, fleet = _dispatch_inputs(future_request)
    suggested = plan_overnight_parking(orders, inventory, fleet,
        algorithm=future_request.algorithm, constraints=_dispatch_constraints(future_request),
        today_distance_m=distance_today)
    choices = []
    terminals = source["constraints"].get("terminal_facility_ids") or []
    for choice in suggested.choices:
        park = req.parking_overrides.get(choice.vehicle_id, choice.park_facility_id)
        if park not in by_facility:
            raise ValueError(f"unknown parking facility {park!r}")
        validate_terminals(network, (park,))
        if terminals and park not in terminals:
            raise ValueError(f"parking facility {park!r} is not an allowed terminal")
        progress = state.vehicles.get(choice.vehicle_id)
        if progress is None:
            from optimisation.dispatch_state import VehicleProgress
            progress = VehicleProgress(choice.vehicle_id, choice.from_facility_id, (),
                status="completed", start_facility_id=choice.from_facility_id,
                schedule_start_facility_id=choice.from_facility_id, schedule_start_min=now)
        parking_state = dataclasses.replace(state, vehicles={**state.vehicles, choice.vehicle_id: progress})
        parking_context = {**context, "input": {**context["input"], "constraints": {
            **context["input"].get("constraints", {}), "terminal_facility_ids": [park]}}}
        work = price_work(parking_state, parking_context, vehicle_id=choice.vehicle_id,
                          order_ids=(), current_time_min=now)
        if park == choice.from_facility_id:
            work["blocked_by"] = [r for r in work["blocked_by"] if r["code"] != "closing_window_exceeded"]
            work["feasible"] = not work["blocked_by"]
        choices.append({**dataclasses.asdict(choice), "park_facility_id": park,
                        "reposition_m": round(work["distance_m"], 2),
                        "today_distance_m": round(distance_today[choice.vehicle_id], 2), **work})
        next(v for v in source["vehicles"] if v["vehicle_id"] == choice.vehicle_id)["start_facility_id"] = park
    future = dispatch_plan_view(DispatchPlanIn(**source))
    first_sources = {}
    for zone in future["zones"]:
        for route in zone["routes"]:
            pickup = next((stop["node_id"] for stop in route["stops"] if stop["kind"] == "pickup"), None)
            first_sources[route["vehicle_id"]] = (by_node[pickup]["facility_id"] if pickup is not None
                                                  else zone["origin_facility_id"])
    for choice in choices:
        origin = first_sources.get(choice["vehicle_id"])
        choice["tomorrow_origin_facility_id"] = origin
        if origin:
            pickup = by_facility[origin]["node_id"]
            at = by_facility[choice["from_facility_id"]]["node_id"]
            park = by_facility[choice["park_facility_id"]]["node_id"]
            distance = network["matrix"]["distance_m"]
            choice["deadhead_m"] = round(distance[park][pickup], 2)
            choice["stay_deadhead_m"] = round(distance[at][pickup], 2)
            choice["saved_m"] = round(choice["stay_deadhead_m"] - choice["deadhead_m"], 2)
            choice["net_m"] = round(choice["saved_m"] - choice["reposition_m"], 2)
    date = datetime.date.fromisoformat(context.get("operating_date") or
        datetime.datetime.fromisoformat(context["clock"]["started_real"]).date().isoformat())
    return {"state_version": state.version, "preview": True,
            "operating_date": date.isoformat(), "next_operating_date": (date + datetime.timedelta(days=1)).isoformat(),
            "choices": choices, "tomorrow": source, "next_day_plan": future,
            "feasible": all(c["feasible"] for c in choices) and future["feasible"],
            "replenishments": additions,
            "inventory_note": ("Demo supply is automatically assumed; numbers are compatibility markers, not real warehouse balances. Consumed lots are not restored."
                               if req.demo_replenish else
                               "Next-day inventory carries today's remaining available lots plus explicitly declared replenishment lots; consumed stock is never restored.")}


def overnight_dispatch_preview(dispatch_id: str, req: OvernightRunPreviewIn):
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    if context.get("overnight", {}).get("status") in {"repositioning", "parked", "next_day_created"}:
        raise ValueError("overnight parking is already confirmed for this day")
    return {"dispatch_id": dispatch_id, **_overnight_run_preview(state, context, req)}


def accept_overnight_dispatch(dispatch_id: str, req: OvernightRunAcceptIn):
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    if req.command_id in old.applied_commands:
        return get_dispatch(dispatch_id)
    if old.version != req.expected_version:
        raise ValueError("dispatch changed after parking preview; preview again")
    if context.get("overnight"):
        raise ValueError("overnight parking is already confirmed")
    preview = _overnight_run_preview(old, context, req)
    if not preview["feasible"]:
        raise ValueError("parking or the next day's delivery plan violates its constraints")
    from optimisation.dispatch_state import VehicleProgress
    vehicles = dict(old.vehicles)
    choices = {}
    for choice in preview["choices"]:
        vehicle_id = choice["vehicle_id"]
        vehicle = vehicles.get(vehicle_id) or VehicleProgress(vehicle_id, choice["from_facility_id"], ())
        vehicle = dataclasses.replace(vehicle, current_facility_id=choice["from_facility_id"],
            status="completed" if choice["reposition_m"] else "parked", remaining_order_ids=(),
            pickup_facility_ids=(), drive_plan=(), replan_order_ids=(), replan_started_min=None,
            end_node_id=choice["end_node_id"])
        vehicles[vehicle_id] = install_schedule(vehicle, choice)
        choices[vehicle_id] = {"from_facility_id": choice["from_facility_id"],
            "park_facility_id": choice["park_facility_id"], "reposition_m": choice["reposition_m"],
            "today_distance_m": choice["today_distance_m"]}
    context["overnight"] = {"status": "repositioning" if any(c["reposition_m"] for c in choices.values()) else "parked",
        "choices": choices, "tomorrow": preview["tomorrow"], "next_operating_date": preview["next_operating_date"],
        "replenishments": preview["replenishments"],
        "inventory_note": preview["inventory_note"], "command_id": req.command_id}
    context["operating_date"] = preview["operating_date"]
    new = dataclasses.replace(old, version=old.version + 1, vehicles=vehicles,
                              applied_commands=(*old.applied_commands, req.command_id))
    update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version, context=context)
    return get_dispatch(dispatch_id)


def create_next_day(dispatch_id: str, req: NextDayIn):
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    parking = context.get("overnight") or {}
    if parking.get("next_dispatch_id"):
        if parking.get("next_day_command_id") == req.command_id:
            return get_dispatch(parking["next_dispatch_id"])
        raise ValueError(f"the next day already exists: {parking['next_dispatch_id']}")
    if old.version != req.expected_version:
        raise ValueError("dispatch changed; refresh before creating the next day")
    if parking.get("status") != "parked":
        raise ValueError("complete the confirmed parking moves before creating the next day")
    if req.speed not in ALLOWED_CLOCK_SPEEDS:
        raise ValueError(f"speed must be one of {ALLOWED_CLOCK_SPEEDS}")
    batch = DispatchCreateIn(**parking["tomorrow"], dispatch_id=req.dispatch_id, command_id=req.command_id)
    new, new_context = _prepare_dispatch(batch)
    new_context.update({"previous_dispatch_id": dispatch_id, "operating_date": parking["next_operating_date"],
                        "inventory_snapshot_note": parking["inventory_note"]})
    if req.depart:
        new = depart(new, command_id=f"depart-{req.command_id}")
        start = min(o["earliest_min"] for o in new_context["input"]["orders"])
        start = min([start, *(v.ready_from_min for v in new.vehicles.values() if v.ready_from_min is not None)])
        new_context["clock"] = make_clock(start, req.speed)
    parking.update({"status": "next_day_created", "next_dispatch_id": req.dispatch_id,
                    "next_day_command_id": req.command_id})
    parent = dataclasses.replace(old, version=old.version + 1,
                                 applied_commands=(*old.applied_commands, req.command_id))
    create_successor(DISPATCH_DATABASE_URL, dispatch_id, parent, context,
        expected_version=old.version, successor_id=req.dispatch_id, successor_state=new, successor_context=new_context)
    return get_dispatch(req.dispatch_id)


def replay_dispatch(dispatch_id: str, *, speed: float | None = None,
                    new_dispatch_id: str | None = None) -> dict:
    """Run the SAME plan again from the beginning, as a new operation.

    Replaying is not time travel: the finished operation is kept as history and
    the identical batch (orders, stock, fleet — read back from the stored input)
    is planned and dispatched afresh, so a demo can be watched again end to end
    without inventing new data. The new run departs immediately at ``speed``
    (its clock starts at the first receiving window, exactly as when the
    operator pressed depart).
    """
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    source = context.get("input") or {}
    if not source.get("orders"):
        raise ValueError(f"dispatch {dispatch_id!r} has no stored input to replay")
    batch = DispatchCreateIn(
        dispatch_id=new_dispatch_id or (
            f"{DAILY_PLAN_DISPATCH_PREFIX}-{int(datetime.datetime.now().timestamp())}"),
        command_id=f"replay-{dispatch_id}",
        algorithm=(context.get("plan") or {}).get("algorithm", "greedy"),
        orders=source["orders"], inventory=source["inventory"], vehicles=source["vehicles"],
        constraints=source.get("constraints", {}),
    )
    created = create_dispatch(batch)
    departed = depart_dispatch(created["dispatch_id"], f"replay-go-{dispatch_id}", speed=speed)
    return {**departed, "replayed_from": dispatch_id}


def set_dispatch_speed(dispatch_id: str, speed: float) -> dict:
    """Change how fast simulated time runs, without moving the vehicles.

    The clock is re-based on the current simulated minute, so switching from
    60x to 1x continues from where the trucks are instead of teleporting them
    back to the departure time.
    """
    if speed not in ALLOWED_CLOCK_SPEEDS:
        raise ValueError(f"speed must be one of {ALLOWED_CLOCK_SPEEDS}")
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    clock = context.get("clock")
    if clock is None:
        raise ValueError("the operation has not departed yet")
    context["clock"] = make_clock(watched_now(clock), speed,
                                  depart_min=schedule_origin(clock))
    state = dataclasses.replace(state, version=state.version + 1)
    update_run(DISPATCH_DATABASE_URL, dispatch_id, state, expected_version=state.version - 1, context=context)
    return {"dispatch_id": dispatch_id,
            "route_view": dispatch_route_view(state, context),
            **state_to_dict(state), **context}


def tick_dispatch(dispatch_id: str) -> dict:
    """Apply the deliveries the simulated clock says have already happened.

    The clock decides *when*; the audited state machine still decides *what* —
    each arrival becomes a normal deliver_next command, keyed by its order so
    repeated ticks are idempotent. Polling this is therefore safe.
    """
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    clock = context.get("clock")
    if clock is None:
        return {"dispatch_id": dispatch_id,
                "route_view": dispatch_route_view(state, context),
                **state_to_dict(state), **context}
    # A finished operation is still ticked: all orders may be delivered while the
    # trucks are still driving home, and the map should keep moving them until
    # they are back. There is nothing left to deliver, so the loop below simply
    # finds no arrival to apply.

    network = read_network()
    node_by_facility = {n["facility_id"]: n["node_id"] for n in network["nodes"]}
    # Charge this tick only for the time somebody was actually watching, so an
    # operation nobody is looking at waits instead of racing to the end of the
    # day (tracking.advance_clock).
    context["clock"] = advance_clock(clock)
    sim_now = simulated_now(context["clock"])
    base_version = state.version          # several arrivals may land in one tick
    for _ in range(128):
        due = None
        for vehicle_id, vehicle in sorted(state.vehicles.items()):
            if vehicle.status != "in_transit" or not vehicle.remaining_order_ids:
                continue
            view = execution_view(vehicle, state, context, network=network, now=sim_now)
            track = view["track"]
            if not track or track.get("approaching_checkpoint"):
                continue
            oid = vehicle.remaining_order_ids[0]
            index = next((i for i, stop in enumerate(view["stops"])
                          if stop["kind"] == "delivery" and stop["order_id"] == oid), None)
            if index is not None and sim_now >= track["service_starts"][index]:
                due = (vehicle_id, oid)
                break
        if due is None:
            break
        vehicle_id, order_id = due
        state = deliver_next(state, vehicle_id, command_id=f"auto-{order_id}")
    parking = context.get("overnight")
    if parking and parking["status"] == "repositioning":
        finished = True
        vehicles = dict(state.vehicles)
        for vehicle_id, choice in parking["choices"].items():
            vehicle = vehicles[vehicle_id]
            view = execution_view(vehicle, state, context, network=network, now=sim_now)
            if view["track"] and view["track"]["finished"]:
                vehicles[vehicle_id] = dataclasses.replace(vehicle,
                    current_facility_id=choice["park_facility_id"], status="parked")
            else:
                finished = False
        if vehicles != state.vehicles:
            state = dataclasses.replace(state, version=state.version + 1, vehicles=vehicles)
        if finished:
            parking["status"] = "parked"
    # The advanced clock is part of the context: persisting it is what makes the
    # next tick resume from here rather than from the wall clock. Commit it with
    # the state version even on an arrival-free tick: an older poll must not
    # overwrite a re-plan's audit context after a concurrent acceptance.
    update_run(DISPATCH_DATABASE_URL, dispatch_id, state,
               expected_version=base_version, context=context)
    inspection = None
    if state.status == "in_transit":
        try:
            inspection = preview_delay_risks(
                state, context, current_time_min=sim_now, optimise=False)
        except ValueError as exc:
            inspection = {"status": "unsupported", "reason": str(exc)}
    return {"dispatch_id": dispatch_id,
            "delay_inspection": inspection,
            "route_view": dispatch_route_view(state, context),
            **state_to_dict(state), **context}


def qa_view(req: QAIn) -> dict:
    """Route one structured question to KG queries; hide DB/query failures.

    An intent outside :data:`knowledge_graph.qa.QUESTION_TYPES` is answered with
    ``status="unsupported"`` instead of a 4xx, so the front-end renders one
    localised notice per outcome class (proposal §6.5: no case / insufficient
    evidence / unsupported question / database failure). A graph failure is
    raised as ``RuntimeError`` and becomes HTTP 503.
    """
    if req.run_id and req.question_type in {"why_disposition", "audit_chain", "cause_context"}:
        try:
            sync = graph_sync_status(DISPATCH_DATABASE_URL, req.run_id)
        except Exception as exc:
            raise RuntimeError("case registration storage unavailable") from exc
        if sync and sync["status"] != "synced":
            raise RuntimeError("case graph synchronization pending; retry after graph recovery")
    try:
        if req.question_type == "why_disposition":
            return kg_qa.why_disposition(req.run_id)
        if req.question_type == "audit_chain":
            return kg_qa.audit_chain(req.run_id)
        if req.question_type == "product_requirements":
            return kg_qa.product_requirements(req.product_id)
        if req.question_type == "cause_context":
            return kg_qa.cause_context(req.run_id, req.cause_code)
        if req.question_type == "disposition_stats":
            return kg_qa.disposition_stats()
        return kg_qa.unsupported_response(req.question_type)
    except Exception as exc:
        log.warning("qa query failed: %s", exc, exc_info=True)
        raise RuntimeError("knowledge graph unavailable") from exc
