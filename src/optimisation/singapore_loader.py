"""Load a versioned Singapore road matrix without GIS/network dependencies.

Node coordinates remain placeholders in the shared Solomon model. Always pass
returned leg_fn to a solver. Stored metres/seconds become kilometres/minutes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .models import Node, ReplanMetrics, ReplanResult, RouteStop, SolomonInstance, VehicleRoute
from .routing import LegFn

SINGAPORE_NETWORK_PATH = Path(__file__).resolve().parents[2] / 'data/optimisation/singapore/network.json'


def validate_network(raw: dict, where: str = 'network') -> None:
    """Reject invalid input before any solver callback can conceal an error."""
    def fail(field):
        raise ValueError(f'{where}: invalid {field}')

    def integer(value, field, minimum=0):
        if type(value) is not int or value < minimum:
            fail(field)

    def number(value, field):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            fail(field)

    try:
        if raw['schema_version'] != 1:
            fail('schema_version')
        if not isinstance(raw['instance'], str) or not raw['instance'].strip():
            fail('instance')
        integer(raw['vehicle_nr'], 'vehicle_nr', 1)
        integer(raw['capacity'], 'capacity', 1)
        nodes = raw['nodes']
        if not isinstance(nodes, list) or len(nodes) < 2:
            fail('nodes (need depot and customer)')
        # Node 0 stays the default warehouse. Since 2026-09-16 the network also
        # carries supply points (``distribution``) and the retained third-party
        # warehouse (``third_party``); neither is a delivery destination, so both
        # must stay demand-free and service-free.
        supply_roles = {'distribution', 'third_party'}
        for i, node in enumerate(nodes):
            integer(node['node_id'], f'nodes[{i}].node_id')
            role = node['role']
            matches_position = role == 'depot' if i == 0 else role in {'customer'} | supply_roles
            if node['node_id'] != i or not matches_position:
                fail(f'nodes[{i}].node_id/role')
            if i and role in supply_roles and (node['demand'] or node['service_min']):
                fail(f'nodes[{i}] supply point demand/service')
            for field in ('demand', 'earliest_min', 'latest_min', 'service_min'):
                integer(node[field], f'nodes[{i}].{field}')
            if node['latest_min'] < node['earliest_min']:
                fail(f'nodes[{i}].time_window')
            for field, lower, upper in (('lat', -90, 90), ('lon', -180, 180)):
                value = node[field]
                if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
                    fail(f'nodes[{i}].{field}')
        if nodes[0]['demand'] or nodes[0]['service_min']:
            fail('depot demand/service')
        n = len(nodes)
        for field in ('distance_m', 'duration_s'):
            matrix = raw['matrix'][field]
            if not isinstance(matrix, list) or len(matrix) != n:
                fail(f'matrix.{field} shape')
            for i, row in enumerate(matrix):
                if not isinstance(row, list) or len(row) != n:
                    fail(f'matrix.{field}[{i}] shape')
                for j, value in enumerate(row):
                    number(value, f'matrix.{field}[{i}][{j}]')
                    if i == j and value != 0:
                        fail(f'matrix.{field} diagonal')
    except (KeyError, TypeError) as exc:
        raise ValueError(f'{where}: missing or malformed field {exc}') from exc


def read_network(path: str | Path = SINGAPORE_NETWORK_PATH) -> dict:
    path = Path(path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    validate_network(raw, str(path))
    return raw


def load_singapore_instance(path: str | Path = SINGAPORE_NETWORK_PATH) -> tuple[SolomonInstance, LegFn]:
    """Depot + receiving sites only — supply points are not delivery stops.

    The network also carries supply points and a retained third-party warehouse.
    They must not enter a delivery instance: the solvers would be free to route
    to them, the comparison table would silently change, and the exported demo
    plan would show a supermarket as a receiving site.
    """
    raw = read_network(path)
    nodes = tuple(Node(n['node_id'], 0, 0, n['demand'], n['earliest_min'],
                       n['latest_min'], n['service_min'])
                  for n in raw['nodes'] if n['role'] in ('depot', 'customer'))
    distance = raw['matrix']['distance_m']
    duration = raw['matrix']['duration_s']

    def leg_fn(a: Node, b: Node) -> tuple[float, float]:
        return distance[a.node_id][b.node_id] / 1000, duration[a.node_id][b.node_id] / 60

    return SolomonInstance(raw['instance'], raw['vehicle_nr'], raw['capacity'], nodes), leg_fn


def load_singapore_subset(
    facility_demands: dict[str, int],
    path: str | Path = SINGAPORE_NETWORK_PATH,
    *,
    vehicle_nr: int | None = None,
    capacity: int | None = None,
    facility_windows: dict[str, tuple[int, int]] | None = None,
) -> tuple[SolomonInstance, LegFn, tuple[int, ...]]:
    """Build a dense solver problem for only the requested facilities.

    The returned tuple maps dense solver IDs back to the committed network IDs.
    This separation is essential: OR-Tools indexes ``instance.nodes`` densely,
    while GeoJSON geometry uses the original network node IDs.
    """
    if not facility_demands:
        raise ValueError("at least one destination facility is required")
    raw = read_network(path)
    by_facility = {node['facility_id']: node for node in raw['nodes']}
    unknown = sorted(set(facility_demands) - set(by_facility))
    if unknown:
        raise ValueError(f"unknown Singapore destination facilities: {unknown}")
    requested = []
    for facility_id, demand in facility_demands.items():
        node = by_facility[facility_id]
        if node['role'] != 'customer':
            raise ValueError(f"destination {facility_id!r} is not a customer")
        if type(demand) is not int or demand <= 0:
            raise ValueError(f"demand for {facility_id!r} must be a positive integer")
        requested.append((node, demand))
    requested.sort(key=lambda item: item[0]['node_id'])

    source_ids = (raw['nodes'][0]['node_id'], *(node['node_id'] for node, _ in requested))
    nodes = [Node(0, 0, 0, 0, raw['nodes'][0]['earliest_min'],
                  raw['nodes'][0]['latest_min'], raw['nodes'][0]['service_min'])]
    facility_windows = facility_windows or {}
    for dense_id, (node, demand) in enumerate(requested, start=1):
        requested_window = facility_windows.get(
            node['facility_id'], (node['earliest_min'], node['latest_min'])
        )
        earliest = max(node['earliest_min'], requested_window[0])
        latest = min(node['latest_min'], requested_window[1])
        if earliest > latest:
            raise ValueError(f"order window for {node['facility_id']!r} does not overlap facility hours")
        nodes.append(Node(dense_id, 0, 0, demand, earliest, latest, node['service_min']))
    distance = raw['matrix']['distance_m']
    duration = raw['matrix']['duration_s']

    def leg_fn(a: Node, b: Node) -> tuple[float, float]:
        source_a, source_b = source_ids[a.node_id], source_ids[b.node_id]
        return distance[source_a][source_b] / 1000, duration[source_a][source_b] / 60

    resolved_vehicle_nr = raw['vehicle_nr'] if vehicle_nr is None else vehicle_nr
    resolved_capacity = raw['capacity'] if capacity is None else capacity
    if type(resolved_vehicle_nr) is not int or resolved_vehicle_nr < 1:
        raise ValueError("vehicle_nr must be a positive integer")
    if type(resolved_capacity) is not int or resolved_capacity < 1:
        raise ValueError("capacity must be a positive integer")
    instance = SolomonInstance(
        f"{raw['instance']}-ORDERS-{len(requested)}",
        resolved_vehicle_nr, resolved_capacity, tuple(nodes),
    )
    return instance, leg_fn, source_ids


def restore_network_node_ids(result: ReplanResult, source_ids: tuple[int, ...]) -> ReplanResult:
    """Translate a subset solution back to network IDs for API and GeoJSON use."""
    def source(dense_id: int) -> int:
        try:
            return source_ids[dense_id]
        except IndexError as exc:
            raise ValueError(f"solver returned unknown dense node {dense_id}") from exc

    routes = tuple(VehicleRoute(
        vehicle_id=route.vehicle_id,
        customer_ids=tuple(source(node_id) for node_id in route.customer_ids),
        stops=tuple(RouteStop(
            node_id=source(stop.node_id), arrival=stop.arrival,
            service_start=stop.service_start, departure=stop.departure,
            demand=stop.demand, cumulative_load=stop.cumulative_load,
            late_by=stop.late_by,
        ) for stop in route.stops),
        total_load=route.total_load, total_distance=route.total_distance,
        duration=route.duration,
        time_window_violations=route.time_window_violations,
        capacity_violation_units=route.capacity_violation_units,
        depot_return_violation=route.depot_return_violation,
        # The parking node is NOT a dense solver node: ``end_leg_fn`` is built by
        # the planner straight from the network matrix, so this id is already a
        # network node id and must not be translated again (2026-09-16).
        end_node_id=route.end_node_id,
        mileage_limit_violation=route.mileage_limit_violation,
    ) for route in result.routes)
    old = result.metrics
    metrics = ReplanMetrics(
        total_distance=old.total_distance, total_duration=old.total_duration,
        vehicles_used=old.vehicles_used, served_customers=old.served_customers,
        on_time_customers=old.on_time_customers, on_time_rate=old.on_time_rate,
        time_window_violations=old.time_window_violations,
        capacity_violations=old.capacity_violations,
        depot_return_violations=old.depot_return_violations,
        vehicle_limit_violations=old.vehicle_limit_violations,
        unserved_customer_ids=tuple(source(node_id) for node_id in old.unserved_customer_ids),
        mileage_violations=old.mileage_violations,
    )
    return ReplanResult(result.instance, result.algorithm, routes, metrics)
