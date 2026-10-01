"""Order-driven static dispatch planning over the Singapore road matrix."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .dispatch_models import (
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
    validate_dispatch_inputs,
)
from .feasibility import diagnose_unserved
from .greedy import solve_greedy
from .models import Node, RouteStop, ReplanResult
from .tracking import LOADING_MIN, SERVICE_MIN
from .parking_policy import validate_terminals, validate_end_node
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
    #: Which routing model produced this group (2026-09-16). The mode travels with
    #: the plan instead of being assumed by whoever consumes it.
    routing_model: str = "grouped"
    #: Per dense vehicle id, the ordered stops of its route as
    #: ``(kind, order_id, facility_id)`` — a pickup carries its supply point, a
    #: delivery the hospital (2026-09-16, PDPTW step 4). This is the sequence the
    #: execution state drives, so the map and the clock show the truck collecting
    #: before it delivers. Empty in the grouped model, where every order's origin
    #: is the group's own start and the order queue already is the sequence.
    stop_plan_by_vehicle: dict[int, tuple[tuple[str, str, str], ...]] = field(
        default_factory=dict)


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


def _validate_route_ends(result, network, fallback):
    for route in result.routes:
        end = route.end_node_id if route.end_node_id is not None else route.start_node_id
        validate_end_node(network, fallback if end is None else end)


def _dispatch_starts(instance, leg_fn, source_ids, network, vehicles, orders, *, grouped=False):
    """Price each truck's actual start, including grouped-source deadhead.

    Dispatch uses the declared zero per-stop dwell, shared with the simulator;
    research loaders retain their own service-time assumptions.
    """
    by_facility = {n["facility_id"]: n for n in network["nodes"]}
    by_node = {n["node_id"]: n for n in network["nodes"]}
    source = by_node[source_ids[0]]
    day_start = min(order.earliest_min for order in orders)
    nodes = [replace(n, service=SERVICE_MIN) for n in instance.nodes]
    nodes[0] = replace(nodes[0], earliest=max(source["earliest_min"], day_start) + LOADING_MIN)
    mapping = list(source_ids)
    starts = []
    for vehicle in vehicles:
        if vehicle.start_facility_id not in by_facility:
            raise ValueError(f"unknown vehicle start {vehicle.start_facility_id!r}")
        facility = by_facility[vehicle.start_facility_id]
        start_at = max(day_start, vehicle.available_from_min, facility["earliest_min"])
        reposition = grouped and facility["node_id"] != source["node_id"]
        start_at += 0 if reposition else LOADING_MIN
        if facility["node_id"] == source["node_id"] and start_at == nodes[0].earliest:
            starts.append(0)
            continue
        index = len(nodes)
        nodes.append(Node(index, 0, 0, 0, start_at, network["nodes"][0]["latest_min"],
                          0, kind="start"))
        mapping.append(facility["node_id"])
        starts.append(index)
    mapping = tuple(mapping)

    def actual_leg(a, b):
        if grouped and a.kind == "start" and not b.is_depot:
            i, pickup, j = mapping[a.node_id], source["node_id"], mapping[b.node_id]
            matrix = network["matrix"]
            travel = matrix["duration_s"][i][pickup] / 60
            wait = max(0, source["earliest_min"] - (a.earliest + travel))
            return ((matrix["distance_m"][i][pickup] + matrix["distance_m"][pickup][j]) / 1000,
                    travel + wait + LOADING_MIN + matrix["duration_s"][pickup][j] / 60)
        i, j = mapping[a.node_id], mapping[b.node_id]
        return (network["matrix"]["distance_m"][i][j] / 1000,
                network["matrix"]["duration_s"][i][j] / 60)

    usable = tuple(max(0, v.capacity - sum(q for _, _, q in v.onboard_spare)) for v in vehicles)
    return replace(instance, nodes=tuple(nodes), vehicle_start_node_ids=tuple(starts),
                   vehicle_capacities=usable), actual_leg, mapping



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

    Both solvers handle the pairing themselves: OR-Tools through
    ``AddPickupAndDelivery`` (step 3) and the greedy baseline through whole-pair
    insertion (step 4). Genetic search is not one of them — see the fleet-wide
    algorithm check in :func:`plan_delivery_orders` for why.
    """
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
        if not zone_vehicles:
            raise ValueError(f"fleet limit leaves no available vehicle for zone {zone}")
        usable_capacity = max(v.capacity - sum(qty for _, _, qty in v.onboard_spare) for v in zone_vehicles)
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
        instance, leg_fn, source_ids = _dispatch_starts(
            instance, leg_fn, source_ids, network, zone_vehicles, zone_orders)
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
        if vehicles_remaining is not None:
            vehicles_remaining -= len(result.routes)
        order_ids_by_node = {
            source_ids[node.node_id]: (node.pair_id,)
            for node in instance.deliveries
        }
        # Read the stop sequence off the DENSE routes: several orders may share one
        # hospital, and after the id mapping their stops would be indistinguishable
        # — the order has to be pinned before that collapse, not guessed after it.
        order_by_id = {order.order_id: order for order in zone_orders}
        order_at_dense_node = {
            node.node_id: node.pair_id
            for node in (*instance.pickups, *instance.deliveries)
        }
        stop_plan_by_vehicle: dict[int, tuple[tuple[str, str, str], ...]] = {}
        for route in dense_result.routes:
            if not route.stops:
                continue
            entries = []
            for stop in route.stops:
                order_id = order_at_dense_node[stop.node_id]
                order = order_by_id[order_id]
                facility_id = (
                    order.origin_facility_id or DISPATCH_ORIGIN
                    if stop.kind == "pickup" else order.destination_facility_id
                )
                entries.append((stop.kind, order_id, facility_id))
            stop_plan_by_vehicle[route.vehicle_id] = tuple(entries)
        unserved_reasons = {
            source_ids[dense_id]: reasons
            for dense_id, reasons in diagnose_unserved(
                instance, dense_result.metrics.unserved_customer_ids,
                dense_result.routes, leg_fn=leg_fn, end_leg_fn=end_leg_fn,
                mileage_limit=mileage_limit_km,
                max_stops_per_vehicle=constraints.max_stops_per_vehicle,
            ).items()
        }
        _validate_route_ends(result, network, source_ids[0])
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
            stop_plan_by_vehicle=stop_plan_by_vehicle,
        ))
    label = "greedy-pair-insertion" if algorithm == "greedy" else "ortools"
    return DispatchPlan(f"{label}-pickup-delivery", len(orders), tuple(zone_plans))


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
        terminal = next(node for node in network["nodes"] if node["node_id"] == best)
        return EndLeg(distance=distance_matrix[last][best] / 1000.0,
                      duration=duration_matrix[last][best] / 60.0, node_id=best,
                      earliest_min=terminal["earliest_min"], latest_min=terminal["latest_min"])

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
    vehicles. Each vehicle's own rated capacity minus its remaining onboard
    spare is passed to the solver; starts and capacities may differ.

    ``constraints.mileage_limit_m`` caps each vehicle's total driven distance and
    ``constraints.terminal_facility_ids`` makes routes open (they end at a supply
    point instead of driving home).  Both are optional and, when omitted, the
    planner behaves exactly as before.
    """
    if algorithm not in {"greedy", "ortools"}:
        # Genetic search stays a single-origin research baseline
        # (scripts/benchmark_solvers.py, POST /api/route): it evolves one
        # permutation of a tour that starts at one place with the load already on
        # board. Neither holds once several sources share a run, so rather than
        # quietly answering with a different solver it is refused — and
        # ga_solver.solve_ga refuses the instance directly for its own callers.
        raise ValueError(
            f"unsupported routing algorithm {algorithm!r}: dispatch offers 'greedy' "
            f"and 'ortools'. Genetic search plans one single-origin tour with the "
            f"load taken at the route start and cannot express pickup-delivery pairs"
        )
    constraints = constraints or DispatchConstraints()
    # Both modes: an order's origin must be a declared source for its product. The
    # pickup-delivery path used to skip this simply because the check lived further
    # down the grouped path (found by a test).
    _assert_origins_can_supply(orders)
    validate_terminals(read_network(network_path), (constraints or DispatchConstraints()).terminal_facility_ids)
    if constraints.routing_model == "pickup_delivery":
        # The single-origin check below would reject a truck that starts at the
        # warehouse to collect from a distribution point, so the mode is decided
        # before any of it runs.
        return _plan_pickup_delivery(
            orders, inventory, vehicles, algorithm=algorithm,
            network_path=network_path, constraints=constraints,
        )
    validate_dispatch_inputs(
        orders, inventory, vehicles, origin_facility_id=DISPATCH_ORIGIN, vehicles_anywhere=True
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
                earliest_min=next(n["earliest_min"] for n in network["nodes"] if n["node_id"] == best),
                latest_min=next(n["latest_min"] for n in network["nodes"] if n["node_id"] == best),
            )

        return end_leg

    zone_plans = []
    vehicles_remaining = constraints.max_vehicles
    used_vehicles = set()
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
            and vehicle.vehicle_id not in used_vehicles
        )
        at_origin = tuple(sorted(at_origin, key=lambda v: (v.start_facility_id != origin, v.vehicle_id)))
        if not at_origin:
            raise ValueError(
                f"no available vehicle for temperature zone {zone} at {origin}"
            )
        zone_vehicles = at_origin
        if vehicles_remaining is not None:
            zone_vehicles = at_origin[:vehicles_remaining]
        if not zone_vehicles:
            raise ValueError(
                f"fleet limit leaves no available vehicle for zone {zone} at {origin}"
            )
        # Onboard spare occupies space, so the planner must not fill a vehicle to
        # its rated capacity and then also claim it carries spare stock. The
        # usable capacity is recorded per vehicle, including different leftover
        # spare quantities inherited from the previous operating day.
        usable_capacity = max(v.capacity - sum(qty for _, _, qty in v.onboard_spare) for v in zone_vehicles)
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
        instance, leg_fn, source_ids = _dispatch_starts(
            instance, leg_fn, source_ids, network, zone_vehicles, zone_orders, grouped=True)
        end_leg_fn = make_end_leg_fn(source_ids)
        if end_leg_fn is None and any(v.start_facility_id != origin for v in zone_vehicles):
            origin_node = node_by_facility[origin]
            def end_leg_fn(dense_id):
                last = source_ids[dense_id]
                return EndLeg(distance_matrix[last][origin_node] / 1000,
                              duration_matrix[last][origin_node] / 60, origin_node)
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
        for route in result.routes:
            used_vehicles.add(zone_vehicles[route.vehicle_id - 1].vehicle_id)
        if vehicles_remaining is not None:
            vehicles_remaining -= len(result.routes)
        physical_routes = []
        for route in result.routes:
            if route.start_node_id != node_by_facility[origin]:
                source_node = node_by_facility[origin]
                arrival = route.start_time_min + duration_matrix[route.start_node_id][source_node] / 60
                opening = next(n["earliest_min"] for n in network["nodes"] if n["node_id"] == source_node)
                service = max(arrival, opening)
                prefix = RouteStop(source_node, arrival, service, service + LOADING_MIN, 0, 0, kind="pickup")
                route = replace(route, stops=(prefix, *route.stops))
            physical_routes.append(route)
        result = replace(result, routes=tuple(physical_routes))
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
        _validate_route_ends(result, network, source_ids[0])
        used_indices = {route.vehicle_id for route in result.routes}
        kept_indices = [index for index, v in enumerate(zone_vehicles, 1)
                        if index in used_indices or v.start_facility_id == origin]
        renumber = {index: new for new, index in enumerate(kept_indices, 1)}
        result = replace(result, routes=tuple(replace(route, vehicle_id=renumber[route.vehicle_id])
                                             for route in result.routes))
        zone_vehicles = tuple(zone_vehicles[index - 1] for index in kept_indices)
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
