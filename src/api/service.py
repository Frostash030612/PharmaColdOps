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

from knowledge_graph.writer import write_case  # noqa: E402
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
from optimisation.dispatch_state import accept_plan, deliver_next, depart, state_to_dict  # noqa: E402
from optimisation.dispatch_repository import (  # noqa: E402
    create_run, latest_dispatch_id, latest_open_dispatch_id, load_context, load_run,
    recent_runs, update_context, update_run,
)
from optimisation.daily_orders import (  # noqa: E402
    ASSUMPTIONS as DAILY_PLAN_ASSUMPTIONS,
    FLEET_LIMIT, MAX_STOPS_PER_VEHICLE, daily_delivery_batch,
)
from optimisation.dynamic_problem import (  # noqa: E402
    DEFAULT_POLICY, accept_emergency_order, preview_emergency_order,
)
from .schemas import DispatchCreateIn, DispatchPlanIn, EmergencyAcceptIn, EmergencyPreviewIn, EventIn, GridIn, QAIn, RouteIn, SpecOverride  # noqa: E402

# Loaded once; used both as the source of stock thresholds and to keep the
# per-request override engines cheap (dict copy, no disk I/O).
ENGINE = RuleEngine()

# Append-only run history: one JSON line per *closed* inbound case
# (/api/case_close). Live /api/decide previews are never archived. A runtime
# artifact (gitignored via `data/audit/`), served newest-first over GET /api/runs.
# Tests monkeypatch RUNS_FILE to a temp path so pytest never writes into the repo.
RUNS_FILE = ROOT / "data" / "audit" / "runs.jsonl"
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
    return "R" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def _record_run(view: dict, *, started_at: str | None = None,
                remark: str | None = None) -> dict:
    """Append one closed case to the runs log and return the stored record.

    Best-effort on disk: an OSError must never take the close down with it —
    the caller still gets the record back (the log is advisory). Each line is
    the full semantic decision view plus run_id / created_at / started_at
    stamps and an optional remark.
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
    try:
        RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("could not append run record to %s", RUNS_FILE, exc_info=True)
    return record


def list_runs(limit: int = 200) -> dict:
    """Every archived decision, newest first (empty list when none recorded yet)."""
    if not RUNS_FILE.exists():
        return {"count": 0, "runs": []}
    records = []
    try:
        with RUNS_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        log.warning("could not read %s", RUNS_FILE, exc_info=True)
    records.reverse()
    return {"count": len(records), "runs": records[:limit]}


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
    for field in ("facility_id", "destination_facility_id"):
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
               started_at: str | None = None, remark: str | None = None) -> dict:
    """Close one inbound case: decide its current inputs and append ONE record.

    The disposition is recomputed from the posted inputs (deterministic, so it
    matches the live /api/decide preview the sandbox was showing). Appends the
    record to RUNS_FILE and returns it with the run_id / created_at stamps the
    front-end shows in the case history.
    """
    spec = resolve_spec(event.product_id, override)
    decision = _engine_for(spec).evaluate(_as_event(
        event.product_id, event.excursion_temp_c, event.duration_min,
        event.mkt_c, event.packaging, event.stage, scenario_id="case_close"))
    _audit("close", event, spec, decision)
    record = _record_run(_decision_view(event, spec, decision),
                         started_at=started_at, remark=remark)
    # Mirror the chain into the knowledge graph (best-effort: the runs log
    # stays authoritative; a down graph must never fail the close).
    write_case(record)
    return record


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
        (item for item in list_runs()["runs"] if item["run_id"] == run_id),
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
                "end_node_id": route.end_node_id,
                "end_facility_id": (
                    None if route.end_node_id is None
                    else id_by_node.get(route.end_node_id)
                ),
                "mileage_limit_violation": route.mileage_limit_violation,
            })
        zone_views.append({
            "temperature_zone": zone_plan.temperature_zone,
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


def create_dispatch(req: DispatchCreateIn) -> dict:
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
        vehicle for vehicle in vehicles if vehicle.vehicle_id in planned_vehicle_ids
    )
    state = accept_plan(plan, orders, inventory, command_id=req.command_id,
                        vehicles=accepted_vehicles)
    plan_view = _dispatch_plan_response(
        plan, requested_algorithm=req.algorithm,
        constraints=req.constraints.model_dump(),
    )
    context = {
        "plan": plan_view,
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
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version)
        # Departure starts the simulated clock at the operating-day minute the
        # vehicles roll, so positions are reproducible from the record alone.
        if not context.get("clock"):
            start = min((item["earliest_min"] for item in context["input"]["orders"]),
                        default=540)
            context["clock"] = make_clock(start, speed or DEFAULT_CLOCK_SPEED)
            update_context(DISPATCH_DATABASE_URL, dispatch_id, context)
    return {"dispatch_id": dispatch_id,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


def deliver_dispatch(dispatch_id: str, vehicle_id: str, command_id: str) -> dict:
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    new = deliver_next(old, vehicle_id, command_id=command_id)
    if new is not old:
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
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
        "destination_facility_id": order.destination_facility_id,
        "quantity": order.quantity, "earliest_min": order.earliest_min,
        "latest_min": order.latest_min, "temperature_zone": order.temperature_zone,
        "source_run_id": order.source_run_id,
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


def _route_legs(network: dict, stops: list[dict], end_node: int = 0) -> list[dict]:
    """Depot → every stop (delivered ones included) → end node, as separate legs."""
    sequence = [0, *[stop["node_id"] for stop in stops], end_node]
    return leg_geojson(network, sequence)


def _legs_with_progress(network: dict, stops: list[dict], track: dict | None,
                        end_node: int = 0) -> list[dict]:
    """The schedule's legs, each marked with whether the truck has DRIVEN it.

    ``delivered`` (the stop's order is recorded as delivered) is not the same
    question as "has the truck been here": the final leg back to the depot serves
    no order at all, so judging progress by deliveries left that leg looking
    "still ahead" for ever — the truck vanished at its last stop while a green
    line still ran home. Progress comes from the schedule instead: every leg
    before the one the truck is on is behind it, and the current leg counts once
    it is fully covered.
    """
    schedule = [0, *[stop["node_id"] for stop in stops], end_node]
    current = None
    if track:
        for index, (a, b) in enumerate(zip(schedule, schedule[1:])):
            if track.get("leg_from") == a and track.get("leg_to") == b:
                current = index
                break
    fraction = (track or {}).get("leg_fraction", 0.0)
    legs = []
    for index, (leg, (a, b)) in enumerate(zip(_route_legs(network, stops, end_node),
                                              zip(schedule, schedule[1:]))):
        end = index + 1
        legs.append({
            **leg,
            "node_id": stops[index]["node_id"] if index < len(stops) else 0,
            "order_id": stops[index]["order_id"] if index < len(stops) else None,
            "delivered": bool(index < len(stops) and stops[index]["delivered"]),
            "driven": bool(current is not None and (
                index < current or (index == current and fraction >= 1.0))),
            "schedule_index": end,
        })
    return legs


def dispatch_route_view(state, context: dict) -> dict:
    """What the live dispatch state looks like on the map.

    Built from the state's own vehicle queues — not from a re-solve — so the
    map, the stop lists and the order table can never disagree. Delivered stops
    stay in the sequence (flagged) because a route that silently drops what has
    already been served is unreadable as an operation record.
    """
    network = read_network()
    node_by_facility = {n["facility_id"]: n["node_id"] for n in network["nodes"]}
    distance = network["matrix"]["distance_m"]
    orders = {item["order_id"]: item for item in context["input"]["orders"]}

    sequences: dict[str, list[int]] = {}
    routes = []
    clock = context.get("clock")
    sim_now = watched_now(clock) if clock else None
    for vehicle_id, vehicle in sorted(state.vehicles.items()):
        pending, stops = [], []
        for order_id in (*vehicle.delivered_order_ids, *vehicle.remaining_order_ids):
            order = orders.get(order_id)
            if order is None:  # an order the context never recorded: skip, don't guess
                continue
            node_id = node_by_facility[order["destination_facility_id"]]
            delivered = order_id in vehicle.delivered_order_ids
            if not delivered:
                pending.append(node_id)
            stops.append({
                "node_id": node_id, "order_id": order_id,
                "quantity": order["quantity"], "delivered": delivered,
                "earliest_min": order["earliest_min"], "latest_min": order["latest_min"],
                "source_run_id": order.get("source_run_id"),
            })
        if not stops:
            continue
        # The schedule spans the WHOLE sequence, delivered stops included, and
        # runs from the minute the fleet rolled — not from whenever the speed was
        # last changed (see tracking.schedule_origin).
        # Where this run finishes: the depot for a closed route, the parking node
        # for an open one. It must be what the planner priced (2026-09-16).
        end_node = vehicle.end_node_id if vehicle.end_node_id is not None else 0
        whole = [stop["node_id"] for stop in stops]
        track = None
        if sim_now is not None:
            track = vehicle_track(network, whole,
                                  schedule_origin(clock) + LOADING_MIN, sim_now,
                                  end_node=end_node)
        schedule = (0, *whole, end_node)
        total = sum(distance[a][b] for a, b in zip(schedule, schedule[1:])) / 1000
        sequences[vehicle_id] = pending
        routes.append({
            "vehicle_id": vehicle_id, "status": vehicle.status,
            "customer_ids": list(whole),
            "stops": stops,
            # Legs, not one merged line: the map draws what has already been
            # driven separately from what is left, so a route in progress is
            # readable at a glance. Leg ``i`` ends at stop ``i``; the final leg
            # is the way home, which serves no order and is still DRIVEN.
            "legs": _legs_with_progress(network, stops, track, end_node=end_node),
            "track": track,
            "total_load": sum(stop["quantity"] for stop in stops
                              if not stop["delivered"]),
            "total_distance": round(total, 2),
        })
    return {
        "routes": routes,
        "clock": clock,
        "sim_now_min": None if sim_now is None else round(sim_now, 2),
        "geojson": sequences_geojson(network, sequences),
        "metrics": {
            "vehicles_used": len(routes),
            "total_distance": round(sum(r["total_distance"] for r in routes), 2),
            "orders_total": len(state.orders),
            "orders_delivered": sum(item.status == "delivered"
                                    for item in state.orders.values()),
            "stock_remaining": sum(state.available_by_lot.values()),
            # "All orders are delivered" is not "the fleet is back": the trucks
            # still have to drive home, and the map should show that rather than
            # making them disappear at the last stop.
            "still_returning": sum(1 for r in routes
                                   if r.get("track") and not r["track"]["finished"]),
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
    lot = InventoryLot(f"LOT-{order.order_id}", order.product_id, DISPATCH_ORIGIN,
                       order.quantity, order.temperature_zone)
    inventory = [*context["input"]["inventory"], _lot_dump(lot)]
    vehicles = list(context["input"]["vehicles"])
    if not any(item["temperature_zone"] == order.temperature_zone for item in vehicles):
        # A product in a zone the plan has no fleet for (e.g. the first frozen
        # case on a chilled-only plan) needs vehicles before it can ship.
        vehicles.extend(_vehicle_dump(v) for v in _zone_fleet(order.temperature_zone))
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


def reshipment_branch_plan(record: dict, *, policy: str = DEFAULT_POLICY) -> dict:
    """Every way this closed case could be served — read-only, nothing reserved.

    The operator looks at the options (which vehicle, how far, how late, who else
    is affected) and picks one; :func:`route_reshipment` then revalidates and
    applies exactly that choice. Deriving the order happens here too, so the UI
    never has to guess a destination or a quantity.
    """
    order = build_delivery_order(record)
    if order is None:
        raise ValueError(f"case {record['run_id']} does not require reshipment")
    dispatch_id, state = _require_plan()
    clock, next_day = _dispatch_clock(record, order)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    state, context, _ = _prepare_branch(state, context, order)
    if order.order_id in state.orders:  # already committed: show it, don't re-judge
        return {"dispatch_id": dispatch_id, "order_id": order.order_id,
                "already_committed": True, "scheduled_next_day": next_day,
                "order": _order_dump(order), "policy": policy, "candidates": [],
                "baselines": {}}
    preview = preview_emergency_order(state, context, order,
                                      current_time_min=clock, policy=policy)
    return {
        "dispatch_id": dispatch_id,
        "order_id": order.order_id,
        "already_committed": False,
        "scheduled_next_day": next_day,
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
    order = build_delivery_order(record)
    if order is None:
        raise ValueError(f"case {record['run_id']} does not require reshipment")
    clock, next_day = _dispatch_clock(record, order)
    dispatch_id, state = _require_plan()

    if order.order_id in state.orders:  # replaying the same case must not double-book
        context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
        return {"dispatch_id": dispatch_id, "inserted": False,
                "scheduled_next_day": next_day,
                "route_view": dispatch_route_view(state, context),
                **state_to_dict(state), **context}

    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    state, context, _ = _prepare_branch(state, context, order)
    if candidate_kind is None or vehicle_id is None:
        kind, carrier = _pick_candidate(state, context, order, clock, policy)
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
    )
    # Context carries the order for later previews: without it, the next case's
    # affected-order simulation cannot resolve this one's window.
    context["input"]["orders"].append(_order_dump(order))
    update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=state.version)
    update_context(DISPATCH_DATABASE_URL, dispatch_id, context)
    return {"dispatch_id": dispatch_id, "inserted": True,
            "candidate_kind": kind, "vehicle_id": carrier,
            "scheduled_next_day": next_day,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


def _pick_candidate(state, context: dict, order: DeliveryOrder, clock: int,
                    policy: str = DEFAULT_POLICY) -> tuple[str, str]:
    """The best on-time option the dispatch preview actually offers.

    Delegating to the preview means the capacity, temperature-zone, onboard-spare
    and knock-on-lateness rules are enforced here too — this bridge never invents
    a vehicle the optimiser would have rejected. Returns the candidate's kind as
    well: picking its vehicle but assuming a kind would apply the wrong state
    transition (a spare vehicle starts a new task; an in-transit one detours).
    """
    preview = preview_emergency_order(
        state, context, order, current_time_min=clock, policy=policy,
    )
    candidate = preview.get("selected_candidate")
    if candidate is None or not candidate["on_time"]:
        raise ValueError(
            f"no vehicle can deliver resupply {order.order_id} within its window "
            f"({preview.get('reason', 'no on-time candidate')})"
        )
    return candidate["kind"], candidate["vehicle_id"]


def emergency_dispatch_preview(dispatch_id: str, req: EmergencyPreviewIn) -> dict:
    state = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    preview = preview_emergency_order(
        state,
        context,
        DeliveryOrder(**req.order.model_dump()),
        current_time_min=req.current_time_min,
        policy=req.policy,
    )
    return _with_candidate_geometry(read_network(), preview)


def accept_emergency_dispatch(dispatch_id: str, req: EmergencyAcceptIn) -> dict:
    old = load_run(DISPATCH_DATABASE_URL, dispatch_id)
    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    order = DeliveryOrder(**req.order.model_dump())
    new = accept_emergency_order(
        old, context, order,
        current_time_min=req.current_time_min,
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
        update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=old.version)
        update_context(DISPATCH_DATABASE_URL, dispatch_id, context)
    return {"dispatch_id": dispatch_id,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


def recent_dispatch_runs(limit: int = 5) -> list[dict]:
    """Recent operations, newest first — what the console can replay."""
    return recent_runs(DISPATCH_DATABASE_URL, limit)


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
    update_context(DISPATCH_DATABASE_URL, dispatch_id, context)
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
    # Re-read progress each pass: delivering one order shifts the next one's
    # place in the queue, so a single pass could only ever land one arrival.
    for _ in range(64):
        due = None
        for vehicle_id, vehicle in sorted(state.vehicles.items()):
            if vehicle.status != "in_transit" or not vehicle.remaining_order_ids:
                continue
            sequence = [node_by_facility[state.orders[oid].destination_facility_id]
                        for oid in (*vehicle.delivered_order_ids, *vehicle.remaining_order_ids)]
            track = vehicle_track(network, sequence, schedule_origin(clock) + LOADING_MIN,
                                  sim_now)
            # Arrivals already recorded must not count again, or the next stop
            # would be delivered the moment the previous one was.
            if track["reached_stops"] > len(vehicle.delivered_order_ids):
                due = (vehicle_id, vehicle.remaining_order_ids[0])
                break
        if due is None:
            break
        vehicle_id, order_id = due
        state = deliver_next(state, vehicle_id, command_id=f"auto-{order_id}")
    if state.version != base_version:
        update_run(DISPATCH_DATABASE_URL, dispatch_id, state,
                   expected_version=base_version)
    # The advanced clock is part of the context: persisting it is what makes the
    # next tick resume from here rather than from the wall clock.
    update_context(DISPATCH_DATABASE_URL, dispatch_id, context)
    return {"dispatch_id": dispatch_id,
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
