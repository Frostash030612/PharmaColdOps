"""OR-Tools Routing solver for the capacity-constrained Solomon VRPTW."""
from __future__ import annotations

from .models import ReplanResult, SolomonInstance
from .routing import build_result, euclidean, evaluate_route

SCALE = 100


def solve_ortools(
    instance: SolomonInstance,
    *,
    time_limit_seconds: int = 10,
) -> ReplanResult:
    """Solve one instance with hard capacity and time-window constraints."""
    if time_limit_seconds < 1:
        raise ValueError("time_limit_seconds must be >= 1")
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("OR-Tools is required: pip install ortools") from exc

    nodes = instance.nodes
    manager = pywrapcp.RoutingIndexManager(
        len(nodes), instance.vehicle_nr, 0
    )
    routing = pywrapcp.RoutingModel(manager)

    def distance(from_index: int, to_index: int) -> int:
        a = nodes[manager.IndexToNode(from_index)]
        b = nodes[manager.IndexToNode(to_index)]
        return round(euclidean(a, b) * SCALE)

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
        return distance(from_index, to_index) + node.service * SCALE

    elapsed_index = routing.RegisterTransitCallback(elapsed)
    horizon = instance.horizon_end * SCALE
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
            node.earliest * SCALE, node.latest * SCALE
        )
    depot = instance.depot
    for vehicle_id in range(instance.vehicle_nr):
        time_dimension.CumulVar(routing.Start(vehicle_id)).SetRange(
            depot.earliest * SCALE, depot.latest * SCALE
        )
        time_dimension.CumulVar(routing.End(vehicle_id)).SetRange(
            depot.earliest * SCALE, depot.latest * SCALE
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
                instance, customer_ids, vehicle_id=vehicle_id + 1
            ))
    return build_result(instance, "ortools-routing", routes)
