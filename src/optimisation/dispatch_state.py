"""Pure, auditable state transitions for an accepted dispatch plan."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .dispatch_models import DeliveryOrder, DispatchVehicle, InventoryLot
from .dispatch_planner import DISPATCH_ORIGIN, DispatchPlan


@dataclass(frozen=True)
class OrderProgress:
    order_id: str
    product_id: str
    destination_facility_id: str
    quantity: int
    vehicle_id: str
    status: str = "planned"
    replaces_order_id: str | None = None


@dataclass(frozen=True)
class PlannedStop:
    """One stop a vehicle still has to drive, in order (2026-09-16, PDPTW).

    The order queue alone cannot describe a pickup-delivery route: the truck may
    collect order A, collect order B, then deliver B and A. A pickup carries the
    facility it happens at; a delivery is the order's own destination.
    """

    kind: str                      # "pickup" | "delivery"
    order_id: str
    facility_id: str | None = None  # pickups only
    service_min: float = 0.0

    @property
    def is_pickup(self) -> bool:
        return self.kind == "pickup"


@dataclass(frozen=True)
class VehicleProgress:
    vehicle_id: str
    current_facility_id: str
    remaining_order_ids: tuple[str, ...]
    delivered_order_ids: tuple[str, ...] = ()
    status: str = "reserved"
    #: Spare stock still on board, as ``(product_id, temperature_zone, quantity)``.
    #: Consumed by the ``add_stop_in_transit`` candidate so an in-transit vehicle
    #: can serve a branch event without returning to the depot.
    onboard_spare: tuple[tuple[str, str, int], ...] = ()
    #: Network node this vehicle finishes at. ``None`` = the depot (closed route);
    #: a parking node makes the route open, and the map must draw the final leg to
    #: it instead of home (2026-09-16).
    end_node_id: int | None = None
    #: Supply points this vehicle must visit **before** its remaining deliveries
    #: (2026-09-16, B6). A rescue whose goods are not on board sends the truck to a
    #: pickup point first; keeping that leg in the state is what lets the clock,
    #: the map and the ledger agree instead of the truck appearing to teleport.
    #: Superseded by ``drive_plan`` when that is set (pickup-delivery routes).
    pickup_facility_ids: tuple[str, ...] = ()
    #: The full planned stop sequence when pickups and deliveries interleave
    #: (2026-09-16, PDPTW). Empty ⇒ the legacy derivation: the leading pickups
    #: above, then the remaining orders in queue order. The plan is never pruned —
    #: the truck's position is computed from the whole run — and ``stops_done``
    #: says how much of it has happened.
    drive_plan: tuple[PlannedStop, ...] = ()
    #: A delay remedy starts a new *remaining-route* schedule at the last
    #: audited facility.  The original plan is retained for audit/map history;
    #: these fields let the live tracker avoid replaying already driven legs
    #: after an operator accepts a re-sequence (B2, 2026-09-30).
    replan_started_min: float | None = None
    replan_start_facility_id: str | None = None
    replan_order_ids: tuple[str, ...] = ()
    start_facility_id: str | None = None
    schedule_start_min: float | None = None
    schedule_start_facility_id: str | None = None
    schedule_stops: tuple[PlannedStop, ...] = ()
    distance_before_schedule_m: float = 0.0
    historical_legs: tuple[dict, ...] = ()
    approach_from_facility_id: str | None = None
    approach_depart_min: float | None = None
    failed_position: tuple[float, float] | None = None
    ready_from_min: float | None = None


@dataclass(frozen=True)
class DispatchState:
    version: int
    status: str
    orders: dict[str, OrderProgress]
    vehicles: dict[str, VehicleProgress]
    available_by_lot: dict[str, int]
    reserved_by_order: dict[str, tuple[tuple[str, int], ...]]
    applied_commands: tuple[str, ...] = ()


def state_to_dict(state: DispatchState) -> dict:
    """JSON-safe representation used by the runtime repository and API."""
    return {
        "version": state.version, "status": state.status,
        "orders": {key: vars(value) for key, value in state.orders.items()},
        "vehicles": {key: {
            **vars(value),
            "remaining_order_ids": list(value.remaining_order_ids),
            "delivered_order_ids": list(value.delivered_order_ids),
            "onboard_spare": [list(part) for part in value.onboard_spare],
            # The driven sequence travels as plain data: it is what the client
            # draws and what a replay reads back (2026-09-16, PDPTW step 4).
            "drive_plan": [
                {"kind": stop.kind, "order_id": stop.order_id,
                 "facility_id": stop.facility_id, "service_min": stop.service_min}
                for stop in value.drive_plan
            ],
            "replan_order_ids": list(value.replan_order_ids),
            "schedule_stops": [vars(stop) for stop in value.schedule_stops],
            "historical_legs": list(value.historical_legs),
        } for key, value in state.vehicles.items()},
        "available_by_lot": state.available_by_lot,
        "reserved_by_order": {
            key: [list(part) for part in value]
            for key, value in state.reserved_by_order.items()
        },
        "applied_commands": list(state.applied_commands),
    }


def state_from_dict(raw: dict) -> DispatchState:
    """Rehydrate a persisted state without replaying side effects."""
    return DispatchState(
        version=raw["version"], status=raw["status"],
        orders={key: OrderProgress(**value) for key, value in raw["orders"].items()},
        vehicles={key: VehicleProgress(
            **{**value,
               "remaining_order_ids": tuple(value["remaining_order_ids"]),
               "delivered_order_ids": tuple(value["delivered_order_ids"]),
               # Absent in states persisted before onboard spare existed: default
               # to "carries nothing extra" rather than failing the reload.
               "onboard_spare": tuple(
                   tuple(part) for part in value.get("onboard_spare", ())
               ),
               "drive_plan": tuple(
                   PlannedStop(**stop)
                   for stop in value.get("drive_plan", ())
               ),
               "replan_order_ids": tuple(value.get("replan_order_ids", ())),
               "schedule_stops": tuple(PlannedStop(**stop) for stop in value.get("schedule_stops", ())),
               "historical_legs": tuple(value.get("historical_legs", ())),
               "failed_position": tuple(value["failed_position"]) if value.get("failed_position") else None}
        ) for key, value in raw["vehicles"].items()},
        available_by_lot=dict(raw["available_by_lot"]),
        reserved_by_order={
            key: tuple((part[0], part[1]) for part in value)
            for key, value in raw["reserved_by_order"].items()
        },
        applied_commands=tuple(raw["applied_commands"]),
    )


def accept_plan(
    plan: DispatchPlan,
    orders: tuple[DeliveryOrder, ...],
    inventory: tuple[InventoryLot, ...],
    *,
    command_id: str,
    vehicles: tuple[DispatchVehicle, ...] = (),
) -> DispatchState:
    """Reserve stock and vehicles once a feasible preview is accepted.

    ``vehicles`` is optional so existing callers keep working; when given, each
    dispatched vehicle carries its onboard spare stock into the state, which is
    what lets a later branch event be served without a depot return.
    """
    if not command_id:
        raise ValueError("command_id is required")
    if not plan.feasible:
        raise ValueError("cannot accept an infeasible dispatch plan")
    by_order = {order.order_id: order for order in orders}
    assignments: dict[str, str] = {}
    sequences: dict[str, list[str]] = {}
    end_nodes: dict[str, int] = {}
    drive_plans: dict[str, list[PlannedStop]] = {}
    starts, start_times, pickups = {}, {}, {}
    declared = {vehicle.vehicle_id: vehicle for vehicle in vehicles}
    for zone_plan in plan.zone_plans:
        for route in zone_plan.result.routes:
            if not route.customer_ids:
                continue
            vehicle_id = zone_plan.vehicle_ids[route.vehicle_id - 1]
            starts[vehicle_id] = (declared[vehicle_id].start_facility_id if vehicle_id in declared
                                 else zone_plan.origin_facility_id or DISPATCH_ORIGIN)
            start_times[vehicle_id] = route.start_time_min
            if zone_plan.routing_model == "grouped" and starts[vehicle_id] != zone_plan.origin_facility_id:
                pickups[vehicle_id] = (zone_plan.origin_facility_id,)
            sequence = sequences.setdefault(vehicle_id, [])
            if route.end_node_id is not None:
                end_nodes[vehicle_id] = route.end_node_id
            stop_plan = zone_plan.stop_plan_by_vehicle.get(route.vehicle_id, ())
            if stop_plan:
                # A pickup-delivery route: the plan itself says what is driven and
                # in which order, pickups interleaved with deliveries.
                plan_stops = drive_plans.setdefault(vehicle_id, [])
                for kind, order_id, facility_id in stop_plan:
                    assignments[order_id] = vehicle_id
                    plan_stops.append(PlannedStop(kind, order_id, facility_id))
                    if kind == "delivery":
                        sequence.append(order_id)
                continue
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
        # Stock is drawn where the order is collected, which for a multi-source
        # plan is the order's own origin — a distribution point holds its own
        # goods. Reserving only from the warehouse would refuse a plan the loader
        # just proved feasible (2026-09-16, PDPTW step 4).
        source = order.origin_facility_id or DISPATCH_ORIGIN
        for lot in inventory:
            if (lot.status != "available" or lot.facility_id != source
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
            replaces_order_id=order.replaces_order_id,
        ) for order_id, order in by_order.items()
    }
    spare_by_vehicle = {vehicle.vehicle_id: vehicle.onboard_spare for vehicle in vehicles}
    vehicle_states = {
        vehicle_id: VehicleProgress(vehicle_id, starts[vehicle_id], tuple(sequence),
                                    onboard_spare=spare_by_vehicle.get(vehicle_id, ()),
                                    end_node_id=end_nodes.get(vehicle_id),
                                    drive_plan=tuple(drive_plans.get(vehicle_id, ())),
                                    start_facility_id=starts[vehicle_id],
                                    schedule_start_min=start_times.get(vehicle_id),
                                    ready_from_min=(None if start_times.get(vehicle_id) is None else
                                        start_times[vehicle_id] - (0 if pickups.get(vehicle_id) else 15)),
                                    schedule_start_facility_id=starts[vehicle_id],
                                    pickup_facility_ids=pickups.get(vehicle_id, ()),
                                    schedule_stops=(tuple(drive_plans[vehicle_id])
                                      if vehicle_id in drive_plans else
                                      tuple(PlannedStop("pickup", "", fid, 15)
                                            for fid in pickups.get(vehicle_id, ()))
                                      + tuple(PlannedStop("delivery", oid) for oid in sequence)))
        for vehicle_id, sequence in sequences.items()
    }
    return DispatchState(1, "accepted", order_states, vehicle_states,
                         available, reservations, (command_id,))


def depart(state: DispatchState, *, command_id: str) -> DispatchState:
    """Send every vehicle that is still waiting at the depot.

    ``in_transit`` is accepted as a starting status too: an emergency spare can
    put one vehicle on the road before the main fleet leaves, and the rest must
    still be able to depart afterwards. Only vehicles still ``reserved`` (and
    orders still ``planned``) are promoted, so anything already delivered or
    under way is left exactly as it is.
    """
    if command_id in state.applied_commands:
        return state
    if state.status not in {"accepted", "in_transit"}:
        raise ValueError("dispatch must be accepted before departure")
    vehicles = {
        key: replace(value, status="in_transit") if value.status == "reserved" else value
        for key, value in state.vehicles.items()
    }
    orders = {
        key: replace(value, status="in_transit") if value.status == "planned" else value
        for key, value in state.orders.items()
    }
    return replace(state, version=state.version + 1, status="in_transit",
                   vehicles=vehicles, orders=orders,
                   applied_commands=(*state.applied_commands, command_id))


def planned_stops(vehicle: "VehicleProgress") -> tuple[PlannedStop, ...]:
    """The whole run this vehicle drives, in order, delivered stops included.

    With a ``drive_plan`` that is the plan itself. Without one it is the legacy
    derivation — the leading pickups, then the deliveries in queue order — which
    is what the grouped model and every B6 rescue produce. Keeping this function
    the single description of "what the truck drives" is what stops the map, the
    clock and the ledger from disagreeing.
    """
    if vehicle.drive_plan:
        return vehicle.drive_plan
    leading = tuple(PlannedStop("pickup", order_id="", facility_id=facility_id)
                    for facility_id in vehicle.pickup_facility_ids)
    return leading + tuple(
        PlannedStop("delivery", order_id=order_id)
        for order_id in (*vehicle.delivered_order_ids, *vehicle.remaining_order_ids)
    )


def next_stop(vehicle: "VehicleProgress") -> tuple[int, PlannedStop] | None:
    """The next stop that still has to happen, as ``(plan index, stop)``.

    Pickups leave no ledger entry, so how many of them the truck has already
    passed is not recorded anywhere — but it does not need to be: deliveries
    happen in plan order, so the next delivery is the one after exactly
    ``len(delivered_order_ids)`` earlier deliveries, and every pickup before it
    must have been reached on the way. ``None`` means nothing is left.

    The index doubles as the arrival test: the stop is due once the schedule has
    driven past ``index`` stops (``track["reached_stops"] > index``), which for a
    grouped route is the pre-PDPTW arithmetic ``reached - pickups > delivered``.
    """
    delivered = len(vehicle.delivered_order_ids)
    seen = 0
    for index, stop in enumerate(planned_stops(vehicle)):
        if stop.kind != "delivery":
            continue
        if seen == delivered:
            return index, stop
        seen += 1
    return None


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
