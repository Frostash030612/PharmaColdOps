"""Shared route scheduling and metrics for all VRPTW algorithms."""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable

from .models import (
    Node,
    ReplanMetrics,
    ReplanResult,
    RouteStop,
    SolomonInstance,
    VehicleRoute,
)

EPSILON = 1e-9


def euclidean(a: Node, b: Node) -> float:
    """Solomon travel distance and travel time (unit speed)."""
    return math.hypot(a.x - b.x, a.y - b.y)


LegFn = Callable[[Node, Node], tuple[float, float]]


def euclidean_leg(a: Node, b: Node) -> tuple[float, float]:
    """Default Solomon leg: distance equals travel time."""
    d = euclidean(a, b)
    return d, d


def evaluate_route(
    instance: SolomonInstance,
    customer_ids: Iterable[int],
    *,
    vehicle_id: int = 1,
    leg_fn: LegFn = euclidean_leg,
) -> VehicleRoute:
    """Build the schedule for one depot-to-depot customer sequence.

    Waiting before a time window opens is allowed.  A customer is late when
    service starts after its latest time, matching the standard Solomon
    convention.  Violations are returned as metrics instead of hidden so the
    same function can evaluate heuristic and OR-Tools results.
    """
    ids = tuple(customer_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("a vehicle route cannot visit a customer more than once")
    if 0 in ids:
        raise ValueError("customer_ids must not contain depot node 0")

    by_id = {node.node_id: node for node in instance.nodes}
    unknown = sorted(set(ids) - set(by_id))
    if unknown:
        raise ValueError(f"unknown customer ids: {unknown}")

    depot = instance.depot
    current = depot
    departure = float(depot.earliest)
    distance = 0.0
    load = 0
    stops: list[RouteStop] = []

    for node_id in ids:
        node = by_id[node_id]
        leg, travel_time = leg_fn(current, node)
        distance += leg
        arrival = departure + travel_time
        service_start = max(arrival, float(node.earliest))
        late_by = max(0.0, service_start - node.latest)
        departure = service_start + node.service
        load += node.demand
        stops.append(RouteStop(
            node_id=node_id,
            arrival=arrival,
            service_start=service_start,
            departure=departure,
            demand=node.demand,
            cumulative_load=load,
            late_by=late_by,
        ))
        current = node

    return_leg, return_travel_time = leg_fn(current, depot)
    distance += return_leg
    return_time = departure + return_travel_time
    return VehicleRoute(
        vehicle_id=vehicle_id,
        customer_ids=ids,
        stops=tuple(stops),
        total_load=load,
        total_distance=distance,
        duration=return_time - depot.earliest,
        time_window_violations=sum(stop.late_by > EPSILON for stop in stops),
        capacity_violation_units=max(0, load - instance.capacity),
        depot_return_violation=return_time > depot.latest + EPSILON,
    )


def build_result(
    instance: SolomonInstance,
    algorithm: str,
    routes: Iterable[VehicleRoute],
) -> ReplanResult:
    """Aggregate route-level values into one comparable result."""
    route_tuple = tuple(route for route in routes if route.customer_ids)
    visited = [node_id for route in route_tuple for node_id in route.customer_ids]
    if len(visited) != len(set(visited)):
        raise ValueError("a result cannot serve the same customer twice")

    expected = {node.node_id for node in instance.customers}
    unknown = sorted(set(visited) - expected)
    if unknown:
        raise ValueError(f"result contains unknown customer ids: {unknown}")
    unserved = tuple(sorted(expected - set(visited)))
    time_violations = sum(route.time_window_violations for route in route_tuple)
    capacity_violations = sum(
        route.capacity_violation_units > 0 for route in route_tuple
    )
    depot_violations = sum(route.depot_return_violation for route in route_tuple)
    served = len(visited)

    metrics = ReplanMetrics(
        total_distance=sum(route.total_distance for route in route_tuple),
        total_duration=sum(route.duration for route in route_tuple),
        vehicles_used=len(route_tuple),
        served_customers=served,
        on_time_customers=served - time_violations,
        on_time_rate=(served - time_violations) / served if served else 0.0,
        time_window_violations=time_violations,
        capacity_violations=capacity_violations,
        depot_return_violations=depot_violations,
        vehicle_limit_violations=max(0, len(route_tuple) - instance.vehicle_nr),
        unserved_customer_ids=unserved,
    )
    return ReplanResult(
        instance=instance.instance,
        algorithm=algorithm,
        routes=route_tuple,
        metrics=metrics,
    )
