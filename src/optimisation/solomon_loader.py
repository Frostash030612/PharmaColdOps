"""Load the committed Solomon JSON instances into unified data classes.

Reads ``data/optimisation/solomon/{c101,c201,r101,r201,rc101,rc201}.json``
(the six canonical VRPTW benchmark instances) and maps each onto
:class:`~optimisation.models.SolomonInstance` with one honest name change:
the JSON ``cost`` column is the Solomon **service time** (per-instance
constant: 90 in C-class, 10 in R/RC-class; 0 for the depot) and is exposed as
``Node.service`` — see :mod:`optimisation.models`.

Canonical source: the classic Solomon (1987) instances (as distributed, e.g.
in CVRPLIB). ``c101``'s best-known total distance is 828.94, which the team
docs already cite as the reference for W2 CP-SAT error checks.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Node, SolomonInstance

# <repo>/src/optimisation/solomon_loader.py → <repo>/data/optimisation/solomon
SOLOMON_DIR = Path(__file__).resolve().parents[2] / "data" / "optimisation" / "solomon"

# The six committed benchmark instances (see DAILY_PLAN role C, W0).
SOLOMON_NAMES = ("c101", "c201", "r101", "r201", "rc101", "rc201")

# JSON key → Node field for the customer row (source names differ from ours).
_ROW_KEYS = {
    "node_id": "id",
    "x": "x",
    "y": "y",
    "demand": "demand",
    "earliest": "earliest",
    "latest": "latest",
    "service": "cost",  # Solomon service-time column, misnamed in the JSON
}


def _parse_nodes(raw_nodes: list[dict], where: str) -> list[Node]:
    """Validate and map one JSON customer list; depot is node id 0."""
    if not raw_nodes:
        raise ValueError(f"{where}: empty customer list")
    seen: set[int] = set()
    parsed: list[Node] = []
    for row in raw_nodes:
        try:
            values = {field: int(row[key]) for field, key in _ROW_KEYS.items()}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{where}: malformed node row {row!r}") from exc
        node = Node(**values)
        if node.node_id in seen:
            raise ValueError(f"{where}: duplicate node id {node.node_id}")
        seen.add(node.node_id)
        if node.node_id < 0:
            raise ValueError(f"{where}: negative node id {node.node_id}")
        if node.earliest < 0 or node.latest < node.earliest:
            raise ValueError(
                f"{where}: invalid time window [{node.earliest}, {node.latest}] "
                f"on node {node.node_id}"
            )
        if node.demand < 0:
            raise ValueError(f"{where}: negative demand on node {node.node_id}")
        parsed.append(node)
    if 0 not in seen:
        raise ValueError(f"{where}: no depot node (id 0)")
    return sorted(parsed, key=lambda n: n.node_id)


def load_instance(path: str | Path) -> SolomonInstance:
    """Load one Solomon JSON file into a validated :class:`SolomonInstance`."""
    path = Path(path)
    where = f"{path.name}: {path}"
    raw = json.loads(path.read_text(encoding="utf-8"))

    try:
        instance = str(raw["instance"]).strip().upper()
        vehicle_nr = int(raw["vehicle-nr"])
        capacity = int(raw["capacity"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{where}: missing/invalid header (need instance, vehicle-nr, capacity)") from exc
    if not instance:
        raise ValueError(f"{where}: empty instance label")
    if vehicle_nr < 1:
        raise ValueError(f"{where}: vehicle-nr must be >= 1")
    if capacity < 1:
        raise ValueError(f"{where}: capacity must be >= 1")

    nodes = _parse_nodes(raw["customers"], where)
    depot = nodes[0]
    if depot.demand != 0 or depot.service != 0:
        raise ValueError(f"{where}: depot (node 0) must have demand 0 and service 0")

    return SolomonInstance(
        instance=instance,
        vehicle_nr=vehicle_nr,
        capacity=capacity,
        nodes=tuple(nodes),
    )


def load_dir(directory: str | Path | None = None) -> dict[str, SolomonInstance]:
    """Load every ``*.json`` in a Solomon directory, keyed by instance label.

    Defaults to the six canonical committed files; anything on disk (matching
    the header schema) also loads, so ad-hoc instances land in the same shape.
    """
    directory = Path(directory) if directory else SOLOMON_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"Solomon data directory not found: {directory}")

    instances: dict[str, SolomonInstance] = {}
    for path in sorted(directory.glob("*.json")):
        inst = load_instance(path)
        instances[inst.instance] = inst
    if not instances:
        raise FileNotFoundError(f"No Solomon JSON files under {directory}")
    return instances
