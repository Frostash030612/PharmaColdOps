"""OR-Tools Routing solver for the capacity-constrained Solomon VRPTW."""
from __future__ import annotations

import math

from .models import ReplanResult, SolomonInstance
from .routing import (
    EndLeg,
    EndLegFn,
    LegFn,
    build_result,
    euclidean_leg,
    evaluate_route,
)


def solve_ortools(
    instance: SolomonInstance,
    *,
    time_limit_seconds: int = 10,
    leg_fn: LegFn = euclidean_leg,
    distance_scale: int = 1000,
    time_scale: int = 1000,
    first_solution: str = "PATH_CHEAPEST_ARC",
    drop_penalty: int = 0,
    minimize_vehicles: bool = False,
    max_stops_per_vehicle: int | None = None,
    end_leg_fn: EndLegFn | None = None,
    mileage_limit: float | None = None,
) -> ReplanResult:
    """Solve with hard capacity/windows and a distance objective.

    Scales are independent: for km/min inputs defaults resolve 1m/0.06s.
    Travel time rounds upward; returned schedules use original precision.
    Guided local search is time-bounded, not an optimality certificate.

    ``first_solution`` and ``drop_penalty`` exist because the default
    configuration cannot solve every instance: on ``r101``/``rc101`` the
    cheapest-arc construction finds **no** feasible first solution, so guided
    local search has nothing to improve and the call returns an empty result
    after burning its whole budget (measured at 10s, 30s and 60s — this is not
    a too-short time limit, it is a construction failure).  Setting
    ``drop_penalty > 0`` adds a per-customer disjunction measured in distance
    units: the model then always has a solution, customers the constraints
    cannot cover come back as ``unserved_customer_ids`` (the same currency
    greedy and the GA report), and the penalty is large enough that dropping one
    is only worth it when no feasible placement exists.

    ``minimize_vehicles`` adds a fixed cost per used vehicle, which turns the
    distance-only objective into Solomon's official hierarchical objective
    (1: fewest vehicles, 2: shortest distance) so the three algorithms are
    compared on the same quantity.

    Reproducibility limit: OR-Tools 9.15's ``RoutingSearchParameters`` has no
    random-seed field (checked against the full field list; the only seed lives
    in the CP-SAT sub-parameters, which this model does not use), so an OR-Tools
    result can only be pinned down to "same configuration and same time budget".
    The GA additionally records its seed. Both are anytime algorithms, so
    iteration counts still vary with machine speed.

    ``end_leg_fn`` + ``mileage_limit`` (2026-09-16) turn the closed VRPTW into an
    **open route with a per-vehicle mileage cap**:

    * a **dummy end node** is appended and made the end of every vehicle, so a
      route no longer has to come back to the depot.  The arc into that dummy is
      priced with ``end_leg_fn`` — the leg from the last real stop to the parking
      node — which is exactly the quantity the schedule reconstruction charges
      too, so model and reported numbers cannot drift apart;
    * the mileage dimension is capacity-limited per vehicle, i.e. a hard
      "≤ N km per vehicle per day" that also covers the final leg to the parking
      node and any empty repositioning before a stop.
    """
    pickup_delivery = instance.load_model == "pickup_delivery"
    if pickup_delivery and first_solution == "PATH_CHEAPEST_ARC":
        # The default construction strategy repeatedly fails to build a feasible
        # start on pickup-delivery instances (measured on this repo's own
        # instances; the same class of failure as the r101/rc101 case recorded in
        # docs/C_配送模块.md §5 A2). Parallel cheapest insertion does construct one.
        first_solution = "PARALLEL_CHEAPEST_INSERTION"
    if time_limit_seconds < 1:
        raise ValueError("time_limit_seconds must be >= 1")
    if max_stops_per_vehicle is not None and max_stops_per_vehicle < 1:
        raise ValueError("max_stops_per_vehicle must be a positive integer")
    if mileage_limit is not None and mileage_limit <= 0:
        raise ValueError("mileage_limit must be positive")
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("OR-Tools is required: pip install ortools") from exc

    if any(type(s) is not int or s < 1 for s in (distance_scale, time_scale)):
        raise ValueError("distance_scale and time_scale must be positive")
    if drop_penalty > 0 and minimize_vehicles:
        # Measured: a dominant per-vehicle fixed cost plus a disjunction penalty
        # makes the solver return no solution at all on every committed
        # instance (the two large cost terms overflow an internal accumulator).
        # Refusing loudly beats silently reporting an empty result as "no
        # feasible plan".
        raise ValueError(
            "drop_penalty and minimize_vehicles cannot be combined: the two cost "
            "terms together make OR-Tools return no solution on every committed "
            "instance. Use minimise_vehicles alone with a first-solution strategy "
            "that can construct a feasible start (e.g. PARALLEL_CHEAPEST_INSERTION)."
        )

    nodes = instance.nodes
    # The dummy end node exists only for open routes; without it the model is the
    # original closed depot-to-depot VRPTW (unchanged for every legacy caller).
    dummy: int | None = len(nodes) if end_leg_fn is not None else None
    starts = list(instance.vehicle_start_node_ids or (0,) * instance.vehicle_nr)
    if dummy is None:
        manager = pywrapcp.RoutingIndexManager(
            len(nodes), instance.vehicle_nr, starts, starts
        )
    else:
        manager = pywrapcp.RoutingIndexManager(
            len(nodes) + 1, instance.vehicle_nr,
            starts, [dummy] * instance.vehicle_nr,
        )
    routing = pywrapcp.RoutingModel(manager)
    for node in nodes:
        if node.is_depot and node.node_id not in starts:
            routing.AddDisjunction([manager.NodeToIndex(node.node_id)], 0)
            routing.ActiveVar(manager.NodeToIndex(node.node_id)).SetValue(0)

    def end_leg(node_index: int) -> EndLeg:
        assert end_leg_fn is not None
        return end_leg_fn(nodes[node_index].node_id)

    def distance(from_index: int, to_index: int) -> int:
        a_index = manager.IndexToNode(from_index)
        b_index = manager.IndexToNode(to_index)
        if dummy is not None and b_index == dummy:
            return round(end_leg(a_index).distance * distance_scale)
        if dummy is not None and a_index == dummy:
            return 0
        a = nodes[a_index]
        b = nodes[b_index]
        d, _ = leg_fn(a, b)
        return round(d * distance_scale)

    distance_index = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(distance_index)

    if minimize_vehicles:
        # Any single route costs at most (n+1) arcs, so a fixed cost this large
        # is never worth paying just to shorten one: the solver removes a
        # vehicle whenever the constraints allow it.
        widest = max(
            leg_fn(a, b)[0] for a in nodes for b in nodes
        )
        routing.SetFixedCostOfAllVehicles(
            int(4 * (instance.n_customers + 1) * widest * distance_scale) + 1
        )

    def demand(from_index: int) -> int:
        node_index = manager.IndexToNode(from_index)
        if dummy is not None and node_index == dummy:
            return 0
        node = nodes[node_index]
        if pickup_delivery and node_index != 0 and not node.is_pickup:
            # Load falls at a delivery: the sign lives here, in one place, while
            # ``Node.demand`` keeps meaning "how much" for every role.
            return -node.demand
        return node.demand

    demand_index = routing.RegisterUnaryTransitCallback(demand)
    routing.AddDimensionWithVehicleCapacity(
        demand_index,
        0,
        list(instance.vehicle_capacities or (instance.capacity,) * instance.vehicle_nr),
        True,
        "Capacity",
    )

    if mileage_limit is not None:
        # Hard cap on the whole driven distance per vehicle: the dimension starts
        # at zero and accumulates the same arc costs as the objective, including
        # the final leg into the dummy end node.
        limit_units = round(mileage_limit * distance_scale)
        routing.AddDimensionWithVehicleCapacity(
            distance_index,
            0,
            [limit_units] * instance.vehicle_nr,
            True,
            "Mileage",
        )

    if max_stops_per_vehicle is not None:
        def stop_count(from_index: int) -> int:
            node_index = manager.IndexToNode(from_index)
            if dummy is not None and node_index == dummy:
                return 0
            return int(not nodes[node_index].is_depot)

        stop_count_index = routing.RegisterUnaryTransitCallback(stop_count)
        routing.AddDimensionWithVehicleCapacity(
            stop_count_index,
            0,
            [max_stops_per_vehicle] * instance.vehicle_nr,
            True,
            "Stops",
        )

    def elapsed(from_index: int, to_index: int) -> int:
        a_index = manager.IndexToNode(from_index)
        if dummy is not None and a_index == dummy:
            return 0
        node = nodes[a_index]
        service = node.service * time_scale
        if dummy is not None and manager.IndexToNode(to_index) == dummy:
            return math.ceil(end_leg(a_index).duration * time_scale) + service
        target = nodes[manager.IndexToNode(to_index)]
        _, minutes = leg_fn(node, target)
        # Round travel upward: integer feasibility must not hide lateness.
        return math.ceil(minutes * time_scale) + service

    elapsed_index = routing.RegisterTransitCallback(elapsed)
    horizon = instance.horizon_end * time_scale
    routing.AddDimension(
        elapsed_index,
        horizon,
        horizon,
        False,
        "Time",
    )
    time_dimension = routing.GetDimensionOrDie("Time")
    for node_index, node in enumerate(nodes):
        if node.is_depot:
            continue
        index = manager.NodeToIndex(node_index)
        time_dimension.CumulVar(index).SetRange(
            node.earliest * time_scale, node.latest * time_scale
        )
    depot = instance.depot
    for vehicle_id in range(instance.vehicle_nr):
        depot = nodes[starts[vehicle_id]]
        time_dimension.CumulVar(routing.Start(vehicle_id)).SetRange(
            depot.earliest * time_scale, depot.latest * time_scale
        )
        time_dimension.CumulVar(routing.End(vehicle_id)).SetRange(
            depot.earliest * time_scale, depot.latest * time_scale
        )
        routing.AddVariableMinimizedByFinalizer(
            time_dimension.CumulVar(routing.Start(vehicle_id))
        )
        routing.AddVariableMinimizedByFinalizer(
            time_dimension.CumulVar(routing.End(vehicle_id))
        )

    if pickup_delivery:
        delivery_by_pair = {node.pair_id: node.node_id
                            for node in nodes if not node.is_pickup}
        for pickup in instance.pickups:
            delivery_id = delivery_by_pair.get(pickup.pair_id)
            if delivery_id is None:
                raise ValueError(f"pickup {pickup.node_id} has no delivery")
            pickup_index = manager.NodeToIndex(pickup.node_id)
            delivery_index = manager.NodeToIndex(delivery_id)
            # Same vehicle, pickup first. The explicit time and vehicle
            # constraints make that intent readable and are cheap to check.
            routing.AddPickupAndDelivery(pickup_index, delivery_index)
            routing.solver().Add(
                routing.VehicleVar(pickup_index) == routing.VehicleVar(delivery_index))
            routing.solver().Add(
                time_dimension.CumulVar(pickup_index)
                <= time_dimension.CumulVar(delivery_index))
        # Nothing may be delivered that was never loaded: without this a negative
        # load could satisfy the capacity dimension instead of exposing a bad route.
        capacity_dimension = routing.GetDimensionOrDie("Capacity")
        for index in range(routing.Size()):
            capacity_dimension.CumulVar(index).SetMin(0)

    if drop_penalty > 0:
        # Without this the model is unsatisfiable for the solver's construction
        # heuristic on some instances; with it, a customer the constraints
        # cannot place is dropped and reported as unserved instead of taking the
        # whole solution down.
        penalty = drop_penalty * distance_scale
        if pickup_delivery:
            # Dropping half a pair is meaningless: a delivery with no pickup (or
            # the reverse) is not a plan. One disjunction per pair drops both.
            for pickup in instance.pickups:
                delivery_by_pair = {node.pair_id: node.node_id
                                    for node in nodes if not node.is_pickup}
                routing.AddDisjunction([
                    manager.NodeToIndex(pickup.node_id),
                    manager.NodeToIndex(delivery_by_pair[pickup.pair_id]),
                ], penalty)
        else:
            for node_index in range(1, len(nodes)):
                routing.AddDisjunction([manager.NodeToIndex(node_index)], penalty)

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = getattr(
        routing_enums_pb2.FirstSolutionStrategy, first_solution
    )
    search.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search.time_limit.FromSeconds(time_limit_seconds)
    solution = routing.SolveWithParameters(search)
    if solution is None:
        return build_result(instance, "ortools-routing", ())

    routes = []
    for vehicle_id in range(instance.vehicle_nr):
        index = routing.Start(vehicle_id)
        customer_ids: list[int] = []
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            if not nodes[node_index].is_depot:
                customer_ids.append(nodes[node_index].node_id)
            index = solution.Value(routing.NextVar(index))
        if customer_ids:
            routes.append(evaluate_route(
                instance, customer_ids, vehicle_id=vehicle_id + 1, leg_fn=leg_fn,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
            ))
    return build_result(instance, "ortools-routing", routes)
