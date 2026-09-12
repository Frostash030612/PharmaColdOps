"""Build auditable emergency-order candidates from persisted dispatch state."""
from __future__ import annotations

from .dispatch_models import DeliveryOrder
from .dispatch_planner import DISPATCH_ORIGIN
from dataclasses import replace

from .dispatch_state import DispatchState, OrderProgress, VehicleProgress
from .singapore_loader import read_network


def preview_emergency_order(
    state: DispatchState,
    context: dict,
    order: DeliveryOrder,
    *,
    current_time_min: int,
    loading_min: int = 15,
) -> dict:
    """Compare spare-vehicle and return-to-depot options without changing state."""
    if state.status not in {"accepted", "in_transit"}:
        raise ValueError("emergency orders require an active dispatch")
    if order.order_id in state.orders:
        raise ValueError(f"order {order.order_id!r} already exists")

    network = read_network()
    nodes = {node["facility_id"]: node["node_id"] for node in network["nodes"]}
    if order.destination_facility_id not in nodes:
        raise ValueError(f"unknown destination {order.destination_facility_id!r}")
    matrix = network["matrix"]

    def leg(origin: str, destination: str) -> tuple[float, float]:
        try:
            i, j = nodes[origin], nodes[destination]
        except KeyError as exc:
            raise ValueError(f"unknown facility {exc.args[0]!r}") from exc
        return matrix["distance_m"][i][j], matrix["duration_s"][i][j] / 60.0

    input_data = context.get("input", {})
    lots = {item["lot_id"]: item for item in input_data.get("inventory", [])}
    stock = sum(
        state.available_by_lot.get(lot_id, 0)
        for lot_id, lot in lots.items()
        if lot["product_id"] == order.product_id
        and lot["temperature_zone"] == order.temperature_zone
        and lot["facility_id"] == DISPATCH_ORIGIN
        and lot.get("status", "available") == "available"
    )
    if stock < order.quantity:
        return {
            "feasible": False,
            "order_id": order.order_id,
            "reason": "insufficient_available_inventory",
            "required_quantity": order.quantity,
            "available_quantity": stock,
            "candidates": [],
        }

    vehicles = {item["vehicle_id"]: item for item in input_data.get("vehicles", [])}
    candidates = []
    for vehicle_id, vehicle in vehicles.items():
        if vehicle["temperature_zone"] != order.temperature_zone or vehicle["capacity"] < order.quantity:
            continue
        progress = state.vehicles.get(vehicle_id)
        if progress is None and vehicle.get("status", "available") == "available":
            distance, travel = leg(DISPATCH_ORIGIN, order.destination_facility_id)
            depart_at = max(current_time_min, vehicle.get("available_from_min", 0)) + loading_min
            eta = depart_at + travel
            candidates.append(_candidate("spare_vehicle", vehicle_id, eta, distance, order))
        elif progress is not None and progress.status == "in_transit":
            to_depot_distance, to_depot_time = leg(progress.current_facility_id, DISPATCH_ORIGIN)
            delivery_distance, delivery_time = leg(DISPATCH_ORIGIN, order.destination_facility_id)
            eta = current_time_min + to_depot_time + loading_min + delivery_time
            item = _candidate(
                "return_to_depot", vehicle_id, eta,
                to_depot_distance + delivery_distance, order,
            )
            item["affected_order_ids"] = list(progress.remaining_order_ids)
            candidates.append(item)

    candidates.sort(key=lambda item: (
        not item["on_time"], len(item["affected_order_ids"]),
        item["eta_min"], item["distance_m"],
    ))
    return {
        "feasible": any(item["on_time"] for item in candidates),
        "order_id": order.order_id,
        "current_time_min": current_time_min,
        "available_quantity": stock,
        "selected_candidate": candidates[0] if candidates else None,
        "candidates": candidates,
        "limitations": [
            "preview_only",
            "free_flow_travel_time",
            "in_transit_vehicle_must_return_to_depot_because_no_unassigned_onboard_stock_is_recorded",
        ],
    }


def _candidate(kind: str, vehicle_id: str, eta: float, distance: float, order: DeliveryOrder) -> dict:
    arrival = max(eta, order.earliest_min)
    return {
        "kind": kind,
        "vehicle_id": vehicle_id,
        "eta_min": round(arrival, 2),
        "on_time": arrival <= order.latest_min,
        "lateness_min": round(max(0.0, arrival - order.latest_min), 2),
        "distance_m": round(distance, 2),
        "affected_order_ids": [],
    }


def accept_emergency_order(
    state: DispatchState,
    context: dict,
    order: DeliveryOrder,
    *,
    current_time_min: int,
    candidate_kind: str,
    vehicle_id: str,
    command_id: str,
) -> DispatchState:
    """Revalidate and apply one previewed emergency option exactly once."""
    if command_id in state.applied_commands:
        return state
    preview = preview_emergency_order(
        state, context, order, current_time_min=current_time_min
    )
    candidate = next((item for item in preview["candidates"] if (
        item["kind"] == candidate_kind and item["vehicle_id"] == vehicle_id
    )), None)
    if candidate is None or not candidate["on_time"]:
        raise ValueError("selected emergency candidate is unavailable or late")

    lots = {item["lot_id"]: item for item in context["input"]["inventory"]}
    available = dict(state.available_by_lot)
    needed = order.quantity
    allocations = []
    for lot_id, lot in lots.items():
        if (lot["product_id"] != order.product_id
                or lot["temperature_zone"] != order.temperature_zone
                or lot["facility_id"] != DISPATCH_ORIGIN
                or lot.get("status", "available") != "available"):
            continue
        take = min(needed, available.get(lot_id, 0))
        if take:
            available[lot_id] -= take
            needed -= take
            allocations.append((lot_id, take))
        if needed == 0:
            break
    if needed:
        raise ValueError("inventory changed after emergency preview")

    vehicles = dict(state.vehicles)
    if candidate_kind == "spare_vehicle":
        vehicles[vehicle_id] = VehicleProgress(
            vehicle_id, DISPATCH_ORIGIN, (order.order_id,), status="in_transit"
        )
    else:
        vehicle = vehicles[vehicle_id]
        vehicles[vehicle_id] = replace(
            vehicle, remaining_order_ids=(order.order_id, *vehicle.remaining_order_ids)
        )
    orders = {**state.orders, order.order_id: OrderProgress(
        order.order_id, order.product_id, order.destination_facility_id,
        order.quantity, vehicle_id, "in_transit",
    )}
    return replace(
        state,
        version=state.version + 1,
        status="in_transit",
        orders=orders,
        vehicles=vehicles,
        available_by_lot=available,
        reserved_by_order={
            **state.reserved_by_order, order.order_id: tuple(allocations)
        },
        applied_commands=(*state.applied_commands, command_id),
    )
