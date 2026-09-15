"""Unified in-memory data classes for the Solomon VRPTW instances.

One shape for every algorithm downstream (greedy → OR-Tools Routing Solver → GA),
regardless of
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


@dataclass(frozen=True)
class RouteStop:
    """Scheduled visit to one customer on a vehicle route."""

    node_id: int
    arrival: float
    service_start: float
    departure: float
    demand: int
    cumulative_load: int
    late_by: float = 0.0


@dataclass(frozen=True)
class VehicleRoute:
    """One depot-to-depot route with its auditable schedule."""

    vehicle_id: int
    customer_ids: tuple[int, ...]
    stops: tuple[RouteStop, ...]
    total_load: int
    total_distance: float
    duration: float
    time_window_violations: int
    capacity_violation_units: int
    depot_return_violation: bool

    @property
    def feasible(self) -> bool:
        return (
            self.time_window_violations == 0
            and self.capacity_violation_units == 0
            and not self.depot_return_violation
        )


@dataclass(frozen=True)
class ReplanMetrics:
    """Comparable metrics shared by greedy and later exact solvers."""

    total_distance: float
    total_duration: float
    vehicles_used: int
    served_customers: int
    on_time_customers: int
    on_time_rate: float
    time_window_violations: int
    capacity_violations: int
    depot_return_violations: int
    vehicle_limit_violations: int
    unserved_customer_ids: tuple[int, ...]

    @property
    def violation_count(self) -> int:
        return (
            self.time_window_violations
            + self.capacity_violations
            + self.depot_return_violations
            + self.vehicle_limit_violations
            + len(self.unserved_customer_ids)
        )


@dataclass(frozen=True)
class ReplanResult:
    """C-owned draft output contract for one routing run.

    This deliberately contains routing outputs only.  The A-owned
    ``ReshipmentOrder`` input fields remain pending until the cross-member
    contract is finalised.
    """

    instance: str
    algorithm: str
    routes: tuple[VehicleRoute, ...]
    metrics: ReplanMetrics

    @property
    def feasible(self) -> bool:
        return self.metrics.violation_count == 0


@dataclass(frozen=True)
class ReshipmentOrder:
    """A resupply request derived from one closed disposition case.

    The ``RO-{run_id}`` id mirrors the Neo4j ``:ReshipmentOrder`` written by
    ``knowledge_graph.writer`` so routing and graph records remain joinable.
    """

    order_id: str
    run_id: str
    product_id: str
    origin_facility_id: str
    destination_facility_id: str
    demand_units: int
    priority: str
    requested_at: str
