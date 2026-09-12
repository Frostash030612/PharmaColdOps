"""Pure, auditable state transitions for an accepted dispatch plan."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .dispatch_models import DeliveryOrder, InventoryLot
from .dispatch_planner import DISPATCH_ORIGIN, DispatchPlan


@dataclass(frozen=True)
class OrderProgress:
    order_id: str
    product_id: str
    destination_facility_id: str
    quantity: int
    vehicle_id: str
    status: str = "planned"


@dataclass(frozen=True)
class VehicleProgress:
    vehicle_id: str
    current_facility_id: str
    remaining_order_ids: tuple[str, ...]
    delivered_order_ids: tuple[str, ...] = ()
    status: str = "reserved"


@dataclass(frozen=True)
class DispatchState:
    version: int
    status: str
    orders: dict[str, OrderProgress]
    vehicles: dict[str, VehicleProgress]
    available_by_lot: dict[str, int]
    reserved_by_order: dict[str, tuple[tuple[str, int], ...]]
    applied_commands: tuple[str, ...] = ()


def accept_plan(
    plan: DispatchPlan,
    orders: tuple[DeliveryOrder, ...],
    inventory: tuple[InventoryLot, ...],
    *,
    command_id: str,
) -> DispatchState:
    """Reserve stock and vehicles once a feasible preview is accepted."""
    if not command_id:
        raise ValueError("command_id is required")
    if not plan.feasible:
        raise ValueError("cannot accept an infeasible dispatch plan")
    by_order = {order.order_id: order for order in orders}
    assignments: dict[str, str] = {}
    sequences: dict[str, list[str]] = {}
    for zone_plan in plan.zone_plans:
        for route in zone_plan.result.routes:
            vehicle_id = zone_plan.vehicle_ids[route.vehicle_id - 1]
            sequence = sequences.setdefault(vehicle_id, [])
            for node_id in route.customer_ids:
                for order_id in zone_plan.order_ids_by_node[node_id]:
                    assignments[order_id] = vehicle_id
                    sequence.append(order_id)
    if set(assignments) != set(by_order):
        missing = sorted(set(by_order) - set(assignments))
        raise ValueError(f"plan leaves orders unassigned: {missing}")

    available = {lot.lot_id: lot.available_quantity for lot in inventory}
    reservations: dict[str, tuple[tuple[str, int], ...]] = {}
    for order in orders:
        needed = order.quantity
        allocations = []
        for lot in inventory:
            if (lot.status != "available" or lot.facility_id != DISPATCH_ORIGIN
                    or lot.product_id != order.product_id
                    or lot.temperature_zone != order.temperature_zone):
                continue
            take = min(needed, available[lot.lot_id])
            if take:
                available[lot.lot_id] -= take
                needed -= take
                allocations.append((lot.lot_id, take))
            if needed == 0:
                break
        if needed:
            raise ValueError(f"inventory changed before accepting order {order.order_id}")
        reservations[order.order_id] = tuple(allocations)

    order_states = {
        order_id: OrderProgress(
            order_id, order.product_id, order.destination_facility_id,
            order.quantity, assignments[order_id],
        ) for order_id, order in by_order.items()
    }
    vehicle_states = {
        vehicle_id: VehicleProgress(vehicle_id, DISPATCH_ORIGIN, tuple(sequence))
        for vehicle_id, sequence in sequences.items()
    }
    return DispatchState(1, "accepted", order_states, vehicle_states,
                         available, reservations, (command_id,))


def depart(state: DispatchState, *, command_id: str) -> DispatchState:
    if command_id in state.applied_commands:
        return state
    if state.status != "accepted":
        raise ValueError("dispatch must be accepted before departure")
    vehicles = {key: replace(value, status="in_transit") for key, value in state.vehicles.items()}
    orders = {key: replace(value, status="in_transit") for key, value in state.orders.items()}
    return replace(state, version=state.version + 1, status="in_transit",
                   vehicles=vehicles, orders=orders,
                   applied_commands=(*state.applied_commands, command_id))


def deliver_next(state: DispatchState, vehicle_id: str, *, command_id: str) -> DispatchState:
    """Deliver exactly the next assigned order; duplicate commands are harmless."""
    if command_id in state.applied_commands:
        return state
    if state.status != "in_transit":
        raise ValueError("dispatch is not in transit")
    try:
        vehicle = state.vehicles[vehicle_id]
    except KeyError as exc:
        raise ValueError(f"unknown vehicle {vehicle_id!r}") from exc
    if not vehicle.remaining_order_ids:
        raise ValueError(f"vehicle {vehicle_id!r} has no remaining orders")
    order_id = vehicle.remaining_order_ids[0]
    order = state.orders[order_id]
    updated_vehicle = replace(
        vehicle,
        current_facility_id=order.destination_facility_id,
        remaining_order_ids=vehicle.remaining_order_ids[1:],
        delivered_order_ids=(*vehicle.delivered_order_ids, order_id),
        status="completed" if len(vehicle.remaining_order_ids) == 1 else "in_transit",
    )
    vehicles = {**state.vehicles, vehicle_id: updated_vehicle}
    orders = {**state.orders, order_id: replace(order, status="delivered")}
    complete = all(not item.remaining_order_ids for item in vehicles.values())
    return replace(state, version=state.version + 1,
                   status="completed" if complete else state.status,
                   vehicles=vehicles, orders=orders,
                   applied_commands=(*state.applied_commands, command_id))
