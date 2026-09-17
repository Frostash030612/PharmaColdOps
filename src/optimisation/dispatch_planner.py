"""Order-driven static dispatch planning over the Singapore road matrix."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .dispatch_models import (
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
    validate_dispatch_inputs,
)
from .feasibility import diagnose_unserved
from .greedy import solve_greedy
from .models import ReplanResult
from .ortools_solver import solve_ortools
from .routing import EndLeg, EndLegFn
from .singapore_loader import (
    PickupDeliveryOrder,
    load_pickup_delivery_subset,
    SINGAPORE_NETWORK_PATH,
    load_singapore_subset,
    read_network,
    restore_network_node_ids,
)

#: Default main warehouse. Since 2026-09-16 this is the Scarlett Westgate outlet
#: (node 0 in network.json); the former Kuehne+Nagel depot is kept as a
#: third-party warehouse for comparison and is no longer the default origin.
DISPATCH_ORIGIN = "W-WESTGATE"


@dataclass(frozen=True)
class ZonePlan:
    """One (temperature zone, origin) group and the fleet planned for it."""

    temperature_zone: str
    vehicle_ids: tuple[str, ...]
    order_ids_by_node: dict[int, tuple[str, ...]]
    result: ReplanResult
    #: Where this group's orders are loaded — the route starts here (B4).
    #: ``None`` in pickup-delivery mode, where every order brings its own source.
    origin_facility_id: str | None = DISPATCH_ORIGIN
    #: Parking nodes this group's routes were allowed to end at (empty ⇒ closed
    #: routes that return to the depot).
    terminal_facility_ids: tuple[str, ...] = ()
    #: Measured reasons per unserved destination node (network node id), keyed so
    #: the API can explain *why* an order did not fit (B7).
    unserved_reasons: dict[int, tuple[dict, ...]] = field(default_factory=dict)
    #: Which routing model produced this group (2026-09-16). Execution currently
    #: understands "grouped" only, so the mode travels with the plan instead of
    #: being assumed by whoever consumes it.
    routing_model: str = "grouped"


@dataclass(frozen=True)
class DispatchPlan:
    algorithm: str
    order_count: int
    zone_plans: tuple[ZonePlan, ...]

    @property
    def feasible(self) -> bool:
        return all(plan.result.feasible for plan in self.zone_plans)



def _assert_origins_can_supply(orders: tuple[DeliveryOrder, ...]) -> None:
    """An order's origin must be declared able to supply that product (B1b).

    The inventory check already proves the goods are physically there; this is the
    other half — the node is *allowed* to be a source for it. It is what turns
    "put any node in the origin box" into "pick a supply point that carries the
    product", and it is the reason a hospital can never be an origin by accident.
    """
    from .catalog import read_supply_points, supplies_product

    points = read_supply_points()
    by_facility = {point.facility_id: point for point in points}
    wanted: dict[str, set[str]] = {}
    for order in orders:
        origin = order.origin_facility_id or DISPATCH_ORIGIN
        wanted.setdefault(origin, set()).add(order.product_id)
    for origin, products in sorted(wanted.items()):
        point = by_facility.get(origin)
        if point is None:
            raise ValueError(
                f"origin {origin!r} is not a supply point; it cannot supply "
                f"{sorted(products)}"
            )
        for product_id in sorted(products):
            if not supplies_product(point, product_id):
                raise ValueError(
                    f"origin {origin!r} does not supply {product_id!r}"
                )



def _plan_pickup_delivery(
    orders: tuple[DeliveryOrder, ...],
    inventory: tuple[InventoryLot, ...],
    vehicles: tuple[DispatchVehicle, ...],
    *,
    algorithm: str,
    network_path: str | Path,
    constraints: DispatchConstraints,
) -> DispatchPlan:
    """Plan every zone as one pickup-delivery problem (PDPTW, 2026-09-16).

    Unlike the grouped model, a truck is not tied to one source: it may collect
    order A at a distribution point and order B at the warehouse on the same run,
    because each order now contributes a pickup node and a delivery node to one
    instance instead of being filed under its origin.

    Only OR-Tools is wired up so far — the greedy baseline still inserts one node
    at a time, and a pair must be inserted as a pair. Asking for it is refused
    loudly rather than answered with a plan that ignores the pairing.
    """
    if algorithm != "ortools":
        raise ValueError(
            "routing_model='pickup_delivery' currently needs algorithm='ortools': "
            "the greedy baseline has no pair insertion yet"
        )
    # Goods still have to be at each order's own origin; only the *vehicle* check
    # is relaxed, because the truck may start anywhere and drive to the sources.
    validate_dispatch_inputs(
        orders, inventory, vehicles, origin_facility_id=DISPATCH_ORIGIN,
        vehicles_anywhere=True,
    )
    network = read_network(network_path)
    facility_by_node = {n["node_id"]: n["facility_id"] for n in network["nodes"]}

    zone_plans = []
    vehicles_remaining = constraints.max_vehicles
    for zone in sorted({order.temperature_zone for order in orders}):
        zone_orders = tuple(order for order in orders if order.temperature_zone == zone)
        zone_vehicles = tuple(
            vehicle for vehicle in vehicles
            if vehicle.temperature_zone == zone and vehicle.status == "available"
        )
        if not zone_vehicles:
            raise ValueError(f"no available vehicle for temperature zone {zone}")
        if vehicles_remaining is not None:
            zone_vehicles = zone_vehicles[:vehicles_remaining]
            vehicles_remaining -= len(zone_vehicles)
        if not zone_vehicles:
            raise ValueError(f"fleet limit leaves no available vehicle for zone {zone}")
        capacities = {vehicle.capacity for vehicle in zone_vehicles}
        if len(capacities) != 1:
            raise ValueError(f"vehicles in zone {zone} must currently share one capacity")
        spares = {sum(qty for _, _, qty in vehicle.onboard_spare)
                  for vehicle in zone_vehicles}
        if len(spares) != 1:
            raise ValueError(f"vehicles in zone {zone} must currently share one onboard spare")
        usable_capacity = next(iter(capacities)) - next(iter(spares))
        if usable_capacity <= 0:
            raise ValueError(f"onboard spare leaves no usable capacity in zone {zone}")

        instance, leg_fn, source_ids = load_pickup_delivery_subset(
            tuple(PickupDeliveryOrder(
                order_id=order.order_id,
                origin_facility_id=order.origin_facility_id or DISPATCH_ORIGIN,
                destination_facility_id=order.destination_facility_id,
                quantity=order.quantity,
                earliest_min=order.earliest_min,
                latest_min=order.latest_min,
            ) for order in zone_orders),
            network_path,
            vehicle_nr=len(zone_vehicles), capacity=usable_capacity,
        )
        mileage_limit_km = (
            None if constraints.mileage_limit_m is None
            else constraints.mileage_limit_m / 1000.0
        )
        terminal_node_ids = ()
        if constraints.terminal_facility_ids:
            node_by_facility = {n["facility_id"]: n["node_id"] for n in network["nodes"]}
            unknown = sorted(set(constraints.terminal_facility_ids) - set(node_by_facility))
            if unknown:
                raise ValueError(f"unknown terminal facilities: {unknown}")
            terminal_node_ids = tuple(
                node_by_facility[fid] for fid in constraints.terminal_facility_ids)
        end_leg_fn = _end_leg_fn(network, source_ids, terminal_node_ids)
        dense_result = solve_ortools(
            instance, leg_fn=leg_fn,
            max_stops_per_vehicle=constraints.max_stops_per_vehicle,
            end_leg_fn=end_leg_fn, mileage_limit=mileage_limit_km,
        )
        result = restore_network_node_ids(dense_result, source_ids)
        order_ids_by_node = {
            source_ids[node.node_id]: (node.pair_id,)
            for node in instance.deliveries
        }
        unserved_reasons = {
            source_ids[dense_id]: reasons
            for dense_id, reasons in diagnose_unserved(
                instance, dense_result.metrics.unserved_customer_ids,
                dense_result.routes, leg_fn=leg_fn, end_leg_fn=end_leg_fn,
                mileage_limit=mileage_limit_km,
                max_stops_per_vehicle=constraints.max_stops_per_vehicle,
            ).items()
        }
        zone_plans.append(ZonePlan(
            temperature_zone=zone,
            # Each order brings its own source; there is no single origin for the
            # group any more, and saying otherwise would misreport the plan.
            origin_facility_id=None,
            vehicle_ids=tuple(vehicle.vehicle_id for vehicle in zone_vehicles),
            order_ids_by_node=order_ids_by_node,
            result=result,
            terminal_facility_ids=tuple(constraints.terminal_facility_ids or ()),
            unserved_reasons=unserved_reasons,
            routing_model="pickup_delivery",
        ))
    return DispatchPlan("ortools-pickup-delivery", len(orders), tuple(zone_plans))


def _end_leg_fn(network: dict, source_ids: tuple[int, ...],
                terminal_node_ids: tuple[int, ...]):
    """Nearest allowed parking node, priced in the solver's km/minute units."""
    if not terminal_node_ids:
        return None
    distance_matrix = network["matrix"]["distance_m"]
    duration_matrix = network["matrix"]["duration_s"]

    def end_leg(dense_id: int):
        last = source_ids[dense_id]
        best = min(terminal_node_ids,
                   key=lambda terminal: distance_matrix[last][terminal])
        return EndLeg(distance=distance_matrix[last][best] / 1000.0,
                      duration=duration_matrix[last][best] / 60.0, node_id=best)

    return end_leg

def plan_delivery_orders(
    orders: tuple[DeliveryOrder, ...],
    inventory: tuple[InventoryLot, ...],
    vehicles: tuple[DispatchVehicle, ...],
    *,
    algorithm: str = "greedy",
    network_path: str | Path = SINGAPORE_NETWORK_PATH,
    constraints: DispatchConstraints | None = None,
) -> DispatchPlan:
    """Plan available inventory orders, with one independent fleet per zone.

    This is a preview: it validates resources but does not reserve inventory or
    vehicles. Vehicles within one temperature zone must currently share a
    capacity because the existing solver model has one fleet-wide capacity.

    ``constraints.mileage_limit_m`` caps each vehicle's total driven distance and
    ``constraints.terminal_facility_ids`` makes routes open (they end at a supply
    point instead of driving home).  Both are optional and, when omitted, the
    planner behaves exactly as before.
    """
    if algorithm not in {"greedy", "ortools"}:
        raise ValueError(f"unsupported routing algorithm {algorithm!r}")
    constraints = constraints or DispatchConstraints()
    # Both modes: an order's origin must be a declared source for its product. The
    # pickup-delivery path used to skip this simply because the check lived further
    # down the grouped path (found by a test).
    _assert_origins_can_supply(orders)
    if constraints.routing_model == "pickup_delivery":
        # The single-origin check below would reject a truck that starts at the
        # warehouse to collect from a distribution point, so the mode is decided
        # before any of it runs.
        return _plan_pickup_delivery(
            orders, inventory, vehicles, algorithm=algorithm,
            network_path=network_path, constraints=constraints,
        )
    validate_dispatch_inputs(
        orders, inventory, vehicles, origin_facility_id=DISPATCH_ORIGIN
    )

    constraints = constraints or DispatchConstraints()
    network = read_network(network_path)
    node_by_facility = {n["facility_id"]: n["node_id"] for n in network["nodes"]}
    terminal_node_ids: tuple[int, ...] = ()
    if constraints.terminal_facility_ids:
        unknown = sorted(set(constraints.terminal_facility_ids) - set(node_by_facility))
        if unknown:
            raise ValueError(f"unknown terminal facilities: {unknown}")
        terminal_node_ids = tuple(
            node_by_facility[fid] for fid in constraints.terminal_facility_ids
        )
    mileage_limit_km = (
        None if constraints.mileage_limit_m is None
        else constraints.mileage_limit_m / 1000.0
    )
    distance_matrix = network["matrix"]["distance_m"]
    duration_matrix = network["matrix"]["duration_s"]

    def make_end_leg_fn(source_ids: tuple[int, ...]) -> EndLegFn | None:
        """Nearest allowed parking node, priced in the solver's km/min units."""
        if not terminal_node_ids:
            return None

        def end_leg(dense_id: int) -> EndLeg:
            last = source_ids[dense_id]
            best = min(
                terminal_node_ids,
                key=lambda terminal: distance_matrix[last][terminal],
            )
            return EndLeg(
                distance=distance_matrix[last][best] / 1000.0,
                duration=duration_matrix[last][best] / 60.0,
                node_id=best,
            )

        return end_leg

    zone_plans = []
    vehicles_remaining = constraints.max_vehicles
    # One independent fleet per (temperature zone, origin). Grouping by origin is
    # what makes "every order carries an origin" real (B4, 2026-09-16): a route
    # starts at the supply point its orders load from, so the mileage, capacity,
    # time-window and parking rules all apply to the leg that actually happens.
    # A single truck serving orders from *different* origins needs the full
    # pickup-delivery model and is not in this version.
    groups = sorted({(order.temperature_zone,
                      order.origin_facility_id or DISPATCH_ORIGIN)
                     for order in orders})
    for zone, origin in groups:
        zone_orders = tuple(
            order for order in orders
            if order.temperature_zone == zone
            and (order.origin_facility_id or DISPATCH_ORIGIN) == origin
        )
        at_origin = tuple(
            vehicle for vehicle in vehicles
            if vehicle.temperature_zone == zone and vehicle.status == "available"
            and vehicle.start_facility_id == origin
        )
        if not at_origin:
            raise ValueError(
                f"no available vehicle for temperature zone {zone} at {origin}"
            )
        zone_vehicles = at_origin
        if vehicles_remaining is not None:
            zone_vehicles = at_origin[:vehicles_remaining]
            vehicles_remaining -= len(zone_vehicles)
        if not zone_vehicles:
            raise ValueError(
                f"fleet limit leaves no available vehicle for zone {zone} at {origin}"
            )
        capacities = {vehicle.capacity for vehicle in zone_vehicles}
        if len(capacities) != 1:
            raise ValueError(f"vehicles in zone {zone} must currently share one capacity")
        # Onboard spare occupies space, so the planner must not fill a vehicle to
        # its rated capacity and then also claim it carries spare stock. The
        # solver model has one fleet-wide capacity, so all vehicles in a zone must
        # currently carry the same spare.
        spares = {sum(qty for _, _, qty in vehicle.onboard_spare)
                  for vehicle in zone_vehicles}
        if len(spares) != 1:
            raise ValueError(f"vehicles in zone {zone} must currently share one onboard spare")
        usable_capacity = next(iter(capacities)) - next(iter(spares))
        if usable_capacity <= 0:
            raise ValueError(f"onboard spare leaves no usable capacity in zone {zone}")
        demands: dict[str, int] = {}
        windows: dict[str, tuple[int, int]] = {}
        orders_by_facility: dict[str, list[str]] = {}
        for order in zone_orders:
            demands[order.destination_facility_id] = (
                demands.get(order.destination_facility_id, 0) + order.quantity
            )
            orders_by_facility.setdefault(order.destination_facility_id, []).append(order.order_id)
            previous = windows.get(order.destination_facility_id)
            if previous is None:
                windows[order.destination_facility_id] = (order.earliest_min, order.latest_min)
            else:
                overlap = (max(previous[0], order.earliest_min), min(previous[1], order.latest_min))
                if overlap[0] > overlap[1]:
                    raise ValueError(
                        f"orders for {order.destination_facility_id!r} have incompatible time windows"
                    )
                windows[order.destination_facility_id] = overlap

        instance, leg_fn, source_ids = load_singapore_subset(
            demands, network_path,
            vehicle_nr=len(zone_vehicles), capacity=usable_capacity,
            facility_windows=windows, origin_facility_id=origin,
        )
        end_leg_fn = make_end_leg_fn(source_ids)
        if algorithm == "greedy":
            dense_result = solve_greedy(
                instance, leg_fn=leg_fn,
                max_stops_per_vehicle=constraints.max_stops_per_vehicle,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit_km,
            )
        else:
            dense_result = solve_ortools(
                instance, leg_fn=leg_fn,
                max_stops_per_vehicle=constraints.max_stops_per_vehicle,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit_km,
            )
        result = restore_network_node_ids(dense_result, source_ids)
        # Measure why anything was left out, in the solver's own units, so the
        # client can explain it instead of printing "did not fit" (B7).
        dense_reasons = diagnose_unserved(
            instance,
            dense_result.metrics.unserved_customer_ids,
            dense_result.routes,
            leg_fn=leg_fn,
            end_leg_fn=end_leg_fn,
            mileage_limit=mileage_limit_km,
            max_stops_per_vehicle=constraints.max_stops_per_vehicle,
            fleet_has_room=len(zone_vehicles) > len(dense_result.routes),
        )
        unserved_reasons = {
            source_ids[dense_id]: reasons
            for dense_id, reasons in dense_reasons.items()
        }
        # Rebuild by source node without relying on request dictionary order.
        order_ids_by_node = {
            node_by_facility[facility_id]: tuple(order_ids)
            for facility_id, order_ids in orders_by_facility.items()
        }
        zone_plans.append(ZonePlan(
            temperature_zone=zone,
            origin_facility_id=origin,
            vehicle_ids=tuple(vehicle.vehicle_id for vehicle in zone_vehicles),
            order_ids_by_node=order_ids_by_node,
            result=result,
            terminal_facility_ids=tuple(constraints.terminal_facility_ids or ()),
            unserved_reasons=unserved_reasons,
        ))
    return DispatchPlan(algorithm, len(orders), tuple(zone_plans))
