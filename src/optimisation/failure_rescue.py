"""Mechanical vehicle-failure rescue for an active grouped dispatch run.

The model deliberately does *not* invent a vehicle-to-vehicle or cold-storage
transfer path.  A failed truck's undelivered cargo becomes unavailable; each
affected demand is therefore replaced from available stock and loaded onto an
unassigned, compatible spare vehicle.  If stock, a spare vehicle, or a legal
one-origin route is absent, the preview says so instead of presenting a fake
rescue option.
"""
from __future__ import annotations

from dataclasses import replace

from .dispatch_models import DeliveryOrder, normalise_onboard_spare
from .dispatch_planner import DISPATCH_ORIGIN
from .dispatch_state import DispatchState, OrderProgress, VehicleProgress
from .singapore_loader import read_network
from .dispatch_constraints import price_work
from .execution import execution_view, install_schedule


FAILURE_CANDIDATE_KIND = "replacement_vehicle"
LOADING_MIN = 15


def _reject_paired_run(state: DispatchState) -> None:
    paired = sorted(vehicle_id for vehicle_id, vehicle in state.vehicles.items()
                    if vehicle.drive_plan)
    if paired:
        raise ValueError(
            "mechanical failure rescue is not available for a pickup-delivery run yet: "
            "replacement routing currently assumes a single pickup source. Re-plan "
            "today's batch with routing_model='grouped' first "
            f"(paired vehicles: {', '.join(paired)})"
        )


def _replacement_orders(
    state: DispatchState, context: dict, failed_vehicle_id: str,
) -> tuple[VehicleProgress, tuple[DeliveryOrder, ...], tuple[str, ...]]:
    try:
        failed = state.vehicles[failed_vehicle_id]
    except KeyError as exc:
        raise ValueError(f"unknown failed vehicle {failed_vehicle_id!r}") from exc
    if failed.status != "in_transit":
        raise ValueError("only an in-transit vehicle can fail in this rescue flow")
    if not failed.remaining_order_ids:
        raise ValueError(f"vehicle {failed_vehicle_id!r} has no undelivered orders")

    by_id = {item["order_id"]: item for item in context.get("input", {}).get("orders", ())}
    missing = [order_id for order_id in failed.remaining_order_ids if order_id not in by_id]
    if missing:
        raise ValueError(f"dispatch context is missing failed orders: {missing}")

    originals = tuple(by_id[order_id] for order_id in failed.remaining_order_ids)
    origins = {item.get("origin_facility_id") or DISPATCH_ORIGIN for item in originals}
    zones = {item["temperature_zone"] for item in originals}
    if len(origins) != 1 or len(zones) != 1:
        raise ValueError(
            "mechanical failure rescue currently requires a grouped run with one "
            "pickup source and one temperature zone"
        )

    replacements = tuple(
        DeliveryOrder(
            order_id=f"FR-{failed_vehicle_id}-{item['order_id']}",
            product_id=item["product_id"],
            origin_facility_id=item.get("origin_facility_id") or DISPATCH_ORIGIN,
            destination_facility_id=item["destination_facility_id"],
            quantity=item["quantity"],
            earliest_min=item["earliest_min"],
            latest_min=item["latest_min"],
            temperature_zone=item["temperature_zone"],
            replaces_order_id=item["order_id"],
        )
        for item in originals
    )
    return failed, replacements, tuple(item["order_id"] for item in originals)


def _allocate_replacements(
    state: DispatchState, context: dict, orders: tuple[DeliveryOrder, ...],
) -> tuple[dict[str, tuple[tuple[str, int], ...]], dict[str, int]] | None:
    """Reserve only genuinely available replacement stock in a local copy."""
    available = dict(state.available_by_lot)
    lots = {item["lot_id"]: item for item in context.get("input", {}).get("inventory", ())}
    allocations: dict[str, tuple[tuple[str, int], ...]] = {}
    for order in orders:
        needed = order.quantity
        allocation: list[tuple[str, int]] = []
        source = order.origin_facility_id or DISPATCH_ORIGIN
        for lot_id, lot in lots.items():
            if (lot.get("status", "available") != "available"
                    or lot["facility_id"] != source
                    or lot["product_id"] != order.product_id
                    or lot["temperature_zone"] != order.temperature_zone):
                continue
            take = min(needed, available.get(lot_id, 0))
            if take:
                available[lot_id] -= take
                needed -= take
                allocation.append((lot_id, take))
            if needed == 0:
                break
        if needed:
            return None
        allocations[order.order_id] = tuple(allocation)
    return allocations, available


def _route_candidate(
    vehicle: dict,
    orders: tuple[DeliveryOrder, ...],
    *,
    failed_vehicle_id: str,
    failed_order_ids: tuple[str, ...],
    current_time_min: int,
    node_by_facility: dict[str, int],
    distance_m: list[list[float]],
    duration_s: list[list[float]],
) -> dict:
    """Build a single-source replacement route, preserving every time window."""
    start = vehicle.get("start_facility_id") or DISPATCH_ORIGIN
    pickup = orders[0].origin_facility_id or DISPATCH_ORIGIN

    def leg(a: str, b: str) -> tuple[float, float]:
        return (distance_m[node_by_facility[a]][node_by_facility[b]],
                duration_s[node_by_facility[a]][node_by_facility[b]] / 60.0)

    sequence = [start]
    now = float(current_time_min)
    total_distance = 0.0
    if start != pickup:
        distance, minutes = leg(start, pickup)
        total_distance += distance
        now += minutes
        sequence.append(pickup)
    now += LOADING_MIN

    pending = list(orders)
    delivered: list[DeliveryOrder] = []
    arrivals: dict[str, float] = {}
    current = pickup
    while pending:
        def score(order: DeliveryOrder) -> tuple:
            distance, minutes = leg(current, order.destination_facility_id)
            eta = max(now + minutes, order.earliest_min)
            return (eta > order.latest_min, eta, distance, order.order_id)

        order = min(pending, key=score)
        pending.remove(order)
        distance, minutes = leg(current, order.destination_facility_id)
        total_distance += distance
        now = max(now + minutes, order.earliest_min)
        arrivals[order.order_id] = now
        sequence.append(order.destination_facility_id)
        delivered.append(order)
        current = order.destination_facility_id

    if current != DISPATCH_ORIGIN:
        distance, _ = leg(current, DISPATCH_ORIGIN)
        total_distance += distance
        sequence.append(DISPATCH_ORIGIN)

    latest_arrival = max(arrivals.values(), default=float(current_time_min))
    lateness = max(
        (max(0.0, arrivals[order.order_id] - order.latest_min) for order in delivered),
        default=0.0,
    )
    return {
        "kind": FAILURE_CANDIDATE_KIND,
        "vehicle_id": vehicle["vehicle_id"],
        "failed_vehicle_id": failed_vehicle_id,
        "failed_order_ids": list(failed_order_ids),
        "replacement_order_ids": [order.order_id for order in delivered],
        "pickup_facility_id": pickup,
        "transfer_facility_id": None,
        "recovery_mode": "replacement_delivery",
        "limitations": [
            "The failed vehicle's cargo is treated as unavailable.",
            "No vehicle-to-vehicle or cold-storage transfer is modeled.",
        ],
        "arrivals": {key: round(value, 2) for key, value in arrivals.items()},
        "eta_min": round(latest_arrival, 2),
        "on_time": lateness == 0,
        "lateness_min": round(lateness, 2),
        "distance_m": round(total_distance, 2),
        "starts_new_vehicle": True,
        "affected_order_ids": [],
        "affected_orders": [],
        "node_sequence": [node_by_facility[item] for item in sequence],
    }


def preview_vehicle_failure(
    state: DispatchState,
    context: dict,
    *,
    failed_vehicle_id: str,
    current_time_min: int,
) -> dict:
    """Assess replacement-vehicle rescue without changing dispatch state."""
    if state.status != "in_transit":
        raise ValueError("mechanical failure rescue requires an in-transit dispatch")
    _reject_paired_run(state)
    _, replacements, failed_order_ids = _replacement_orders(
        state, context, failed_vehicle_id)
    allocation = _allocate_replacements(state, context, replacements)
    base = {
        "failed_vehicle_id": failed_vehicle_id,
        "failed_order_ids": list(failed_order_ids),
        "replacement_order_ids": [order.order_id for order in replacements],
        "recovery_mode": "replacement_delivery",
        "transfer_facility_id": None,
    }
    if allocation is None:
        return {
            **base,
            "feasible": False,
            "reason": "insufficient_replacement_inventory",
            "candidates": [],
        }

    network = read_network()
    node_by_facility = {node["facility_id"]: node["node_id"] for node in network["nodes"]}
    unknown = sorted({
        facility for order in replacements
        for facility in (order.origin_facility_id, order.destination_facility_id)
        if facility not in node_by_facility
    })
    if unknown:
        raise ValueError(f"unknown rescue facilities: {unknown}")
    zone = replacements[0].temperature_zone
    required_capacity = sum(order.quantity for order in replacements)
    candidates = []
    for vehicle in context.get("input", {}).get("vehicles", ()):
        vehicle_id = vehicle["vehicle_id"]
        if vehicle_id in state.vehicles or vehicle.get("status", "available") != "available":
            continue
        if vehicle["temperature_zone"] != zone:
            continue
        spare_load = sum(quantity for _, _, quantity in normalise_onboard_spare(
            vehicle.get("onboard_spare", ())
        ))
        if vehicle["capacity"] - spare_load < required_capacity:
            continue
        candidate = _route_candidate(
            vehicle, replacements,
            failed_vehicle_id=failed_vehicle_id,
            failed_order_ids=failed_order_ids,
            current_time_min=current_time_min,
            node_by_facility=node_by_facility,
            distance_m=network["matrix"]["distance_m"],
            duration_s=network["matrix"]["duration_s"],
        )
        priced = price_work(state, context, vehicle_id=vehicle_id,
            order_ids=tuple(candidate["replacement_order_ids"]), current_time_min=current_time_min,
            orders={order.order_id: vars(order) for order in replacements},
            pickup_facility_id=candidate["pickup_facility_id"], starts_new_vehicle=True)
        candidate.update(priced)
        candidate["eta_min"] = round(max(priced["arrivals"].values()), 2)
        candidate["lateness_min"] = round(max(
            max(0, priced["arrivals"][order.order_id] - order.latest_min) for order in replacements), 2)
        candidates.append(candidate)
    candidates.sort(key=lambda item: (
        not item["on_time"], item["lateness_min"], item["distance_m"], item["vehicle_id"]
    ))
    if not candidates:
        return {
            **base,
            "feasible": False,
            "reason": "no_compatible_spare_vehicle",
            "required_capacity": required_capacity,
            "temperature_zone": zone,
            "candidates": [],
        }
    return {
        **base,
        "feasible": any(item["feasible"] for item in candidates),
        "reason": None if any(item["feasible"] for item in candidates) else "no_feasible_replacement_schedule",
        "candidates": candidates,
        "selected_candidate": candidates[0],
    }


def accept_vehicle_failure(
    state: DispatchState,
    context: dict,
    *,
    failed_vehicle_id: str,
    replacement_vehicle_id: str,
    current_time_min: int,
    command_id: str,
) -> tuple[DispatchState, dict]:
    """Mark one truck failed and send replacement stock in a spare vehicle."""
    if command_id in state.applied_commands:
        return state, {"idempotent": True}
    preview = preview_vehicle_failure(
        state, context, failed_vehicle_id=failed_vehicle_id,
        current_time_min=current_time_min,
    )
    candidate = next((item for item in preview.get("candidates", ())
                      if item["vehicle_id"] == replacement_vehicle_id), None)
    if candidate is None or not candidate["on_time"]:
        raise ValueError("selected mechanical-failure rescue is unavailable or late")
    _, replacements, failed_order_ids = _replacement_orders(
        state, context, failed_vehicle_id)
    allocation = _allocate_replacements(state, context, replacements)
    if allocation is None:  # state may have changed after preview
        raise ValueError("replacement inventory changed after failure preview")
    reservations, available = allocation

    vehicles = dict(state.vehicles)
    failed = vehicles[failed_vehicle_id]
    view = execution_view(failed, state, context)
    position = (view["track"] or {}).get("position")
    if position is None:
        facility = next(n for n in read_network()["nodes"] if n["facility_id"] == failed.current_facility_id)
        position = [facility["lon"], facility["lat"]]
    vehicles[failed_vehicle_id] = replace(
        failed, status="failed", remaining_order_ids=(), pickup_facility_ids=(),
        drive_plan=(), schedule_stops=(), replan_order_ids=(), replan_started_min=None,
        schedule_start_facility_id=failed.current_facility_id, schedule_start_min=current_time_min,
        end_node_id=next(n["node_id"] for n in read_network()["nodes"] if n["facility_id"] == failed.current_facility_id),
        distance_before_schedule_m=view["distance_driven_m"], failed_position=tuple(position),
        historical_legs=(*failed.historical_legs, *(leg for leg in view["legs"] if leg["driven"])),
        approach_from_facility_id=None, approach_depart_min=None,
    )
    vehicle_input = next(
        item for item in context["input"]["vehicles"]
        if item["vehicle_id"] == replacement_vehicle_id
    )
    start = vehicle_input.get("start_facility_id") or DISPATCH_ORIGIN
    pickup = candidate["pickup_facility_id"]
    vehicles[replacement_vehicle_id] = VehicleProgress(
        replacement_vehicle_id,
        start,
        tuple(candidate["replacement_order_ids"]),
        status="in_transit",
        onboard_spare=normalise_onboard_spare(vehicle_input.get("onboard_spare", ())),
        pickup_facility_ids=(() if pickup == start else (pickup,)),
        start_facility_id=start,
        end_node_id=candidate["end_node_id"],
    )
    vehicles[replacement_vehicle_id] = install_schedule(vehicles[replacement_vehicle_id], candidate)

    orders = dict(state.orders)
    for order_id in failed_order_ids:
        orders[order_id] = replace(orders[order_id], status="failed")
    for order in replacements:
        orders[order.order_id] = OrderProgress(
            order.order_id, order.product_id, order.destination_facility_id,
            order.quantity, replacement_vehicle_id, "in_transit",
            replaces_order_id=order.replaces_order_id,
        )
    new = replace(
        state,
        version=state.version + 1,
        orders=orders,
        vehicles=vehicles,
        available_by_lot=available,
        reserved_by_order={**state.reserved_by_order, **reservations},
        applied_commands=(*state.applied_commands, command_id),
    )
    return new, {
        "idempotent": False,
        "failed_order_ids": list(failed_order_ids),
        "replacement_order_ids": [order.order_id for order in replacements],
        "candidate": candidate,
    }
