"""Unified in-memory data classes for the Solomon VRPTW instances.

One shape for every algorithm downstream (greedy → CP-SAT → GA), regardless of
the on-disk JSON key names. Field semantics follow the classic Solomon format:
node ``0`` is the depot (demand 0, no service), customers carry a demand, a
service time and a hard [earliest, latest] time window.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Node:
    """One location (depot or customer).

    ``service`` is the on-site service time. The committed JSON files spell it
    ``cost`` (see ``solomon_loader``); the Solomon column is the service time,
    per-instance constant (90 in C-class, 10 in R/RC-class), so it is mapped to
    an honest name here rather than carried through as a misnomer.
    """

    node_id: int
    x: int
    y: int
    demand: int
    earliest: int
    latest: int
    service: int

    @property
    def is_depot(self) -> bool:
        return self.node_id == 0


@dataclass(frozen=True)
class SolomonInstance:
    """A single validated Solomon problem instance.

    ``nodes`` is sorted by ``node_id``; node ``0`` (the depot) is always first.
    """

    instance: str  # canonical label, e.g. "C101"
    vehicle_nr: int
    capacity: int
    nodes: tuple[Node, ...]

    @property
    def depot(self) -> Node:
        return self.nodes[0]

    @property
    def customers(self) -> tuple[Node, ...]:
        """All nodes except the depot."""
        return tuple(n for n in self.nodes if not n.is_depot)

    @property
    def n_customers(self) -> int:
        return len(self.nodes) - 1

    @property
    def total_demand(self) -> int:
        return sum(n.demand for n in self.customers)

    @property
    def horizon_end(self) -> int:
        """Latest end of the whole planning horizon (depot latest)."""
        return self.depot.latest
