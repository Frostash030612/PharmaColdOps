"""OR-Tools Routing solver for the capacity-constrained Solomon VRPTW."""
from __future__ import annotations

import math

from .models import ReplanResult, SolomonInstance
from .routing import LegFn, build_result, euclidean_leg, evaluate_route


def solve_ortools(
    instance: SolomonInstance,
    *,
    time_limit_seconds: int = 10,
    leg_fn: LegFn = euclidean_leg,
    distance_scale: int = 1000,
    time_scale: int = 1000,
) -> ReplanResult:
    """Solve with hard capacity/windows and a distance objective.

    Scales are independent: for km/min inputs defaults resolve 1m/0.06s.
    Travel time rounds upward; returned schedules use original precision.
    Guided local search is time-bounded, not an optimality certificate.
    """
    if time_limit_seconds < 1:
        raise ValueError("time_limit_seconds must be >= 1")
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("OR-Tools is required: pip install ortools") from exc

    if any(type(s) is not int or s < 1 for s in (distance_scale, time_scale)):
        raise ValueError("distance_scale and time_scale must be positive")

    nodes = instance.nodes
    manager = pywrapcp.RoutingIndexManager(
        len(nodes), instance.vehicle_nr, 0
    )
    routing = pywrapcp.RoutingModel(manager)

    def distance(from_index: int, to_index: int) -> int:
        a = nodes[manager.IndexToNode(from_index)]
        b = nodes[manager.IndexToNode(to_index)]
        d, _ = leg_fn(a, b)
        return round(d * distance_scale)

    distance_index = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(distance_index)

    def demand(from_index: int) -> int:
        return nodes[manager.IndexToNode(from_index)].demand

    demand_index = routing.RegisterUnaryTransitCallback(demand)
    routing.AddDimensionWithVehicleCapacity(
        demand_index,
        0,
        [instance.capacity] * instance.vehicle_nr,
        True,
        "Capacity",
    )

    def elapsed(from_index: int, to_index: int) -> int:
        node = nodes[manager.IndexToNode(from_index)]
        target = nodes[manager.IndexToNode(to_index)]
        _, minutes = leg_fn(node, target)
        # Round travel upward: integer feasibility must not hide lateness.
        return math.ceil(minutes * time_scale) + node.service * time_scale

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
        if node_index == 0:
            continue
        index = manager.NodeToIndex(node_index)
        time_dimension.CumulVar(index).SetRange(
            node.earliest * time_scale, node.latest * time_scale
        )
    depot = instance.depot
    for vehicle_id in range(instance.vehicle_nr):
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

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
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
            if node_index != 0:
                customer_ids.append(nodes[node_index].node_id)
            index = solution.Value(routing.NextVar(index))
        if customer_ids:
            routes.append(evaluate_route(
                instance, customer_ids, vehicle_id=vehicle_id + 1, leg_fn=leg_fn
            ))
    return build_result(instance, "ortools-routing", routes)
