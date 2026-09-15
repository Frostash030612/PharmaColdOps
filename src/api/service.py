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
from optimisation.singapore_export import routes_geojson, sequences_geojson  # noqa: E402
from optimisation.tracking import LOADING_MIN, make_clock, simulated_now, vehicle_track  # noqa: E402
from optimisation.singapore_loader import read_network  # noqa: E402
from optimisation.dispatch_models import DeliveryOrder, DispatchVehicle, InventoryLot  # noqa: E402
from optimisation.dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders  # noqa: E402
from optimisation.dispatch_state import accept_plan, deliver_next, depart, state_to_dict  # noqa: E402
from optimisation.dispatch_repository import (  # noqa: E402
    create_run, latest_dispatch_id, list_dispatch_ids, load_context, load_run,
    update_context, update_run,
)
from optimisation.daily_orders import ASSUMPTIONS as DAILY_PLAN_ASSUMPTIONS  # noqa: E402
from optimisation.daily_orders import daily_delivery_batch  # noqa: E402
from optimisation.dynamic_problem import accept_emergency_order, preview_emergency_order  # noqa: E402
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
        orders, inventory, vehicles, algorithm=req.algorithm
    )
    return _dispatch_plan_response(plan, requested_algorithm=req.algorithm)


def _dispatch_plan_response(plan, *, requested_algorithm: str) -> dict:
    """Serialise one already-computed plan; never invokes a solver again."""
    network = read_network()
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
            })
        zone_views.append({
            "temperature_zone": zone_plan.temperature_zone,
            "feasible": result.feasible,
            "target_orders": sum(len(ids) for ids in zone_plan.order_ids_by_node.values()),
            "target_facilities": len(zone_plan.order_ids_by_node),
            "served_facilities": result.metrics.served_customers,
            "unserved_customer_ids": list(result.metrics.unserved_customer_ids),
            "total_distance": result.metrics.total_distance,
            "routes": routes,
            "geojson": routes_geojson(network, result),
        })
    return {
        "algorithm": requested_algorithm,
        "preview": True,
        "feasible": plan.feasible,
        "order_count": plan.order_count,
        "zones": zone_views,
    }


def _dispatch_inputs(req: DispatchPlanIn):
    return (
        tuple(DeliveryOrder(**item.model_dump()) for item in req.orders),
        tuple(InventoryLot(**item.model_dump()) for item in req.inventory),
        tuple(DispatchVehicle(**item.model_dump()) for item in req.vehicles),
    )


def create_dispatch(req: DispatchCreateIn) -> dict:
    """Plan, accept and atomically persist one dispatch run."""
    orders, inventory, vehicles = _dispatch_inputs(req)
    plan = plan_delivery_orders(orders, inventory, vehicles, algorithm=req.algorithm)
    state = accept_plan(plan, orders, inventory, command_id=req.command_id)
    plan_view = _dispatch_plan_response(plan, requested_algorithm=req.algorithm)
    context = {
        "plan": plan_view,
        "input": {
            "orders": [item.model_dump() for item in req.orders],
            "inventory": [item.model_dump() for item in req.inventory],
            "vehicles": [item.model_dump() for item in req.vehicles],
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
# Runs are numbered because a *completed* operation is history — the next
# resupply opens the next one rather than reopening a finished delivery.
RESHIPMENT_DISPATCH_PREFIX = "RESHIPMENTS"

#: Ids for "today's delivery plan" operations (doc §4.1).  Reshipments keep
#: their own prefix so the bootstrap rule below stays deterministic; this one
#: marks an operation planned from a batch of ordinary hospital orders.
DAILY_PLAN_DISPATCH_PREFIX = "PLAN"


def daily_plan_request(
    *, hospitals: int = 4, seed: int | None = None, temperature_zone: str = "chilled"
) -> dict:
    """A simulated order batch plus a ready-to-post planning body.

    Nothing is persisted: the client previews the batch through
    ``POST /api/dispatch/plan``, the operator looks at distance / vehicles /
    feasibility, and only ``POST /api/dispatch/runs`` creates the operation —
    the sequence doc §4.1 asks for ("操作员看方案 → 确认发车").
    """
    orders, inventory, vehicles = daily_delivery_batch(
        hospitals=hospitals, seed=seed, temperature_zone=temperature_zone
    )
    return {
        "note": DAILY_PLAN_ASSUMPTIONS,
        "seed": seed,
        "hospitals": hospitals,
        "temperature_zone": temperature_zone,
        # Exactly the body /api/dispatch/plan accepts; /runs additionally needs
        # dispatch_id + command_id, which the client generates (see the front-end
        # store) so two clients cannot collide on the same id.
        "plan": {
            "algorithm": "greedy",
            "orders": [_order_dump(order) for order in orders],
            "inventory": [_lot_dump(lot) for lot in inventory],
            "vehicles": [_vehicle_dump(vehicle) for vehicle in vehicles],
        },
    }


def _run_sequence(dispatch_id: str) -> int:
    tail = dispatch_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def active_reshipment_run() -> tuple[str, object | None]:
    """The live resupply operation, or the id the next one should take.

    Returns ``(dispatch_id, state)`` with ``state`` None when nothing is open,
    which is the signal to bootstrap rather than to insert.
    """
    known = list_dispatch_ids(DISPATCH_DATABASE_URL, RESHIPMENT_DISPATCH_PREFIX)
    if known:
        latest = max(known, key=_run_sequence)
        state = load_run(DISPATCH_DATABASE_URL, latest)
        if state.status != "completed":
            return latest, state
        return f"{RESHIPMENT_DISPATCH_PREFIX}-{_run_sequence(latest) + 1}", None
    return f"{RESHIPMENT_DISPATCH_PREFIX}-1", None


def get_active_reshipment_dispatch() -> dict:
    """The live operation for the front-end; KeyError when none is open."""
    dispatch_id, state = active_reshipment_run()
    if state is None:
        raise KeyError(dispatch_id)
    return get_dispatch(dispatch_id)


def get_active_dispatch() -> dict:
    """The live operation for the front-end, whichever pathway created it.

    ``get_active_reshipment_dispatch`` above deliberately only sees the
    ``RESHIPMENTS-`` stream, because that prefix rule is what makes reshipment
    bootstrapping deterministic.  The panel, however, must also be able to show
    a "today's delivery plan" built from a batch of ordinary orders
    (``PLAN-…`` via ``POST /api/dispatch/runs``) — without this, an operator
    could create a plan and the panel would keep saying "no active dispatch
    operation".  KeyError when nothing is open; a *completed* operation counts
    as nothing open, matching the reshipment rule.
    """
    latest = latest_dispatch_id(DISPATCH_DATABASE_URL)
    if latest is None:
        raise KeyError("no dispatch run has ever been created")
    state = load_run(DISPATCH_DATABASE_URL, latest)
    if state.status == "completed":
        raise KeyError(latest)
    return get_dispatch(latest)


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
        legs = (0, *[stop["node_id"] for stop in stops], 0)
        total = sum(distance[a][b] for a, b in zip(legs, legs[1:])) / 1000
        sequences[vehicle_id] = pending
        routes.append({
            "vehicle_id": vehicle_id, "status": vehicle.status,
            "customer_ids": [stop["node_id"] for stop in stops],
            "stops": stops,
            "total_load": sum(stop["quantity"] for stop in stops
                              if not stop["delivered"]),
            "total_distance": round(total, 2),
        })
    clock = context.get("clock")
    sim_now = simulated_now(clock) if clock else None
    if sim_now is not None:
        depart_min = clock["sim_start_min"]
        for route in routes:
            if route["status"] != "in_transit" or not route["stops"]:
                continue
            # The schedule must span the WHOLE sequence, delivered stops
            # included: timing the remainder as if the vehicle had just left
            # the depot would place it further along the road than it is.
            whole = [stop["node_id"] for stop in route["stops"]]
            route["track"] = vehicle_track(network, whole, depart_min + LOADING_MIN, sim_now)
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
        },
    }


# The demo fleet is deliberately larger than network.json's 3: each resupply
# currently takes its own spare (see docs/C_配送模块.md D1), so a short demo runs out
# of vehicles and starts consolidating before the operator meant it to.
FLEET_SIZE = 6

# One real second = one simulated minute. Real time (speed 1) stays available
# for honesty, but a 25-minute drive is unwatchable at 1x.
DEFAULT_CLOCK_SPEED = 60.0
ALLOWED_CLOCK_SPEEDS = (1.0, 60.0, 300.0)


def _bootstrap_fleet(zone: str) -> tuple[DispatchVehicle, ...]:
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


def route_reshipment(record: dict) -> dict:
    """Route ONE closed reshipment case through the live dispatch system.

    The first such case bootstraps the shared run; every later case is inserted
    into that same run as an emergency order, so a resupply is always checked
    against real stock and real vehicle capacity instead of being routed by a
    parallel preview that reserves nothing.
    """
    order = build_delivery_order(record)
    if order is None:
        raise ValueError(f"case {record['run_id']} does not require reshipment")
    clock, next_day = _dispatch_clock(record, order)
    lot = InventoryLot(f"LOT-{order.order_id}", order.product_id, DISPATCH_ORIGIN,
                       order.quantity, order.temperature_zone)
    dispatch_id, state = active_reshipment_run()

    if state is None:
        vehicles = _bootstrap_fleet(order.temperature_zone)
        plan = plan_delivery_orders((order,), (lot,), vehicles)
        state = accept_plan(plan, (order,), (lot,), command_id=f"reship-{order.order_id}")
        context = {
            "plan": _dispatch_plan_response(plan, requested_algorithm="greedy"),
            "input": {
                "orders": [_order_dump(order)], "inventory": [_lot_dump(lot)],
                "vehicles": [_vehicle_dump(v) for v in vehicles],
            },
        }
        create_run(DISPATCH_DATABASE_URL, dispatch_id, state, context=context)
        return {"dispatch_id": dispatch_id, "bootstrapped": True,
                "scheduled_next_day": next_day,
                "route_view": dispatch_route_view(state, context),
                **state_to_dict(state), **context}

    if order.order_id in state.orders:  # replaying the same case must not double-book
        context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
        return {"dispatch_id": dispatch_id, "bootstrapped": False,
                "scheduled_next_day": next_day,
                "route_view": dispatch_route_view(state, context),
                **state_to_dict(state), **context}

    context = load_context(DISPATCH_DATABASE_URL, dispatch_id)
    context["input"]["inventory"].append(_lot_dump(lot))
    if not any(v["temperature_zone"] == order.temperature_zone
               for v in context["input"]["vehicles"]):
        # A product in a zone the run has no fleet for (e.g. the first frozen
        # case on a chilled-only run) needs its own vehicles before it can ship.
        context["input"]["vehicles"].extend(
            _vehicle_dump(v) for v in _bootstrap_fleet(order.temperature_zone)
        )
    # The new lot is stock that did not exist when the run was accepted, so it
    # must enter the ledger before the emergency check reads availability.
    state = dataclasses.replace(
        state, available_by_lot={**state.available_by_lot, lot.lot_id: lot.available_quantity},
    )
    kind, vehicle_id = _pick_candidate(state, context, order, clock)
    new = accept_emergency_order(
        state, context, order,
        current_time_min=clock,
        candidate_kind=kind, vehicle_id=vehicle_id,
        command_id=f"reship-{order.order_id}",
    )
    # Context carries the order for later previews: without it, the next case's
    # affected-order simulation cannot resolve this one's window.
    context["input"]["orders"].append(_order_dump(order))
    update_run(DISPATCH_DATABASE_URL, dispatch_id, new, expected_version=state.version)
    update_context(DISPATCH_DATABASE_URL, dispatch_id, context)
    return {"dispatch_id": dispatch_id, "bootstrapped": False,
            "scheduled_next_day": next_day,
            "route_view": dispatch_route_view(new, context),
            **state_to_dict(new), **context}


def _pick_candidate(state, context: dict, order: DeliveryOrder,
                    clock: int) -> tuple[str, str]:
    """The best on-time option the dispatch preview actually offers.

    Delegating to the preview means the capacity, temperature-zone and
    knock-on-lateness rules are enforced here too — this bridge never invents a
    vehicle the optimiser would have rejected. Returns the candidate's kind as
    well: picking its vehicle but assuming a kind would apply the wrong state
    transition (a spare vehicle starts a new task; an in-transit one detours).
    """
    preview = preview_emergency_order(
        state, context, order, current_time_min=clock,
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
    return preview_emergency_order(
        state,
        context,
        DeliveryOrder(**req.order.model_dump()),
        current_time_min=req.current_time_min,
    )


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
    context["clock"] = make_clock(simulated_now(clock), speed)
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
    if clock is None or state.status != "in_transit":
        return {"dispatch_id": dispatch_id,
                "route_view": dispatch_route_view(state, context),
                **state_to_dict(state), **context}

    network = read_network()
    node_by_facility = {n["facility_id"]: n["node_id"] for n in network["nodes"]}
    sim_now = simulated_now(clock)
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
            track = vehicle_track(network, sequence, clock["sim_start_min"] + LOADING_MIN,
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
