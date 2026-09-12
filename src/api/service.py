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

import datetime
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

# uvicorn wires handlers onto its own loggers, so this line appears on the
# console next to the access log — a live "audit trail" proving each front-end
# change really round-trips to the Python engine (drag a slider and watch).
log = logging.getLogger("uvicorn.error")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rule_engine.engine import RuleEngine  # noqa: E402
from rule_engine.models import ExcursionEvent, ProductSpec  # noqa: E402

from knowledge_graph.writer import write_case  # noqa: E402
from knowledge_graph import qa as kg_qa  # noqa: E402
from optimisation.reshipment import (  # noqa: E402
    build_reshipment_order,
    plan_reshipment_route,
)
from optimisation.singapore_export import routes_geojson  # noqa: E402
from optimisation.singapore_loader import read_network  # noqa: E402
from optimisation.dispatch_models import DeliveryOrder, DispatchVehicle, InventoryLot  # noqa: E402
from optimisation.dispatch_planner import plan_delivery_orders  # noqa: E402
from optimisation.dispatch_state import accept_plan, deliver_next, depart, state_to_dict  # noqa: E402
from optimisation.dispatch_repository import create_run, load_run, update_run  # noqa: E402
from .schemas import DispatchCreateIn, DispatchPlanIn, EventIn, GridIn, QAIn, RouteIn, SpecOverride  # noqa: E402

# Loaded once; used both as the source of stock thresholds and to keep the
# per-request override engines cheap (dict copy, no disk I/O).
ENGINE = RuleEngine()

# Append-only run history: one JSON line per *closed* inbound case
# (/api/case_close). Live /api/decide previews are never archived. A runtime
# artifact (gitignored via `data/audit/`), served newest-first over GET /api/runs.
# Tests monkeypatch RUNS_FILE to a temp path so pytest never writes into the repo.
RUNS_FILE = ROOT / "data" / "audit" / "runs.jsonl"
DISPATCH_DB = ROOT / "data" / "audit" / "dispatch.sqlite3"


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


def route_view(req: RouteIn) -> dict:
    """Find a closed case, derive its order, solve, and serialise the replan."""
    record = next(
        (item for item in list_runs()["runs"] if item["run_id"] == req.run_id),
        None,
    )
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
    orders = tuple(DeliveryOrder(**item.model_dump()) for item in req.orders)
    inventory = tuple(InventoryLot(**item.model_dump()) for item in req.inventory)
    vehicles = tuple(DispatchVehicle(**item.model_dump()) for item in req.vehicles)
    plan = plan_delivery_orders(
        orders, inventory, vehicles, algorithm=req.algorithm
    )
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
        "algorithm": req.algorithm,
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
    create_run(DISPATCH_DB, req.dispatch_id, state)
    return {"dispatch_id": req.dispatch_id, **state_to_dict(state)}


def get_dispatch(dispatch_id: str) -> dict:
    state = load_run(DISPATCH_DB, dispatch_id)
    return {"dispatch_id": dispatch_id, **state_to_dict(state)}


def depart_dispatch(dispatch_id: str, command_id: str) -> dict:
    old = load_run(DISPATCH_DB, dispatch_id)
    new = depart(old, command_id=command_id)
    if new is not old:
        update_run(DISPATCH_DB, dispatch_id, new, expected_version=old.version)
    return {"dispatch_id": dispatch_id, **state_to_dict(new)}


def deliver_dispatch(dispatch_id: str, vehicle_id: str, command_id: str) -> dict:
    old = load_run(DISPATCH_DB, dispatch_id)
    new = deliver_next(old, vehicle_id, command_id=command_id)
    if new is not old:
        update_run(DISPATCH_DB, dispatch_id, new, expected_version=old.version)
    return {"dispatch_id": dispatch_id, **state_to_dict(new)}


def qa_view(req: QAIn) -> dict:
    """Route one structured question to KG queries; hide DB/query failures."""
    try:
        if req.question_type == "why_disposition":
            return kg_qa.why_disposition(req.run_id)
        if req.question_type == "audit_chain":
            return kg_qa.audit_chain(req.run_id)
        if req.question_type == "product_requirements":
            return kg_qa.product_requirements(req.product_id)
        return kg_qa.disposition_stats()
    except Exception as exc:
        log.warning("qa query failed: %s", exc, exc_info=True)
        raise RuntimeError("knowledge graph unavailable") from exc
