"""Load a versioned Singapore road matrix without GIS/network dependencies.

Node coordinates remain placeholders in the shared Solomon model. Always pass
returned leg_fn to a solver. Stored metres/seconds become kilometres/minutes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .models import Node, SolomonInstance
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
        for i, node in enumerate(nodes):
            integer(node['node_id'], f'nodes[{i}].node_id')
            if node['node_id'] != i or node['role'] != ('depot' if i == 0 else 'customer'):
                fail(f'nodes[{i}].node_id/role')
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
    raw = read_network(path)
    nodes = tuple(Node(n['node_id'], 0, 0, n['demand'], n['earliest_min'],
                       n['latest_min'], n['service_min']) for n in raw['nodes'])
    distance = raw['matrix']['distance_m']
    duration = raw['matrix']['duration_s']

    def leg_fn(a: Node, b: Node) -> tuple[float, float]:
        return distance[a.node_id][b.node_id] / 1000, duration[a.node_id][b.node_id] / 60

    return SolomonInstance(raw['instance'], raw['vehicle_nr'], raw['capacity'], nodes), leg_fn
