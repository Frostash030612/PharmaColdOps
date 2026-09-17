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
    #: ``"delivery"`` (the default, and every pre-2026-09-16 node) or
    #: ``"pickup"``. Only pickup-delivery instances mix the two.
    kind: str = "delivery"
    #: Identifies the pickup/delivery pair of one order (2026-09-16, PDPTW).
    pair_id: str | None = None

    @property
    def is_depot(self) -> bool:
        return self.node_id == 0

    @property
    def is_pickup(self) -> bool:
        return self.kind == "pickup"


@dataclass(frozen=True)
class SolomonInstance:
    """A single validated Solomon problem instance.

    ``nodes`` is sorted by ``node_id``; node ``0`` (the depot) is always first.
    """

    instance: str  # canonical label, e.g. "C101"
    vehicle_nr: int
    capacity: int
    nodes: tuple[Node, ...]
    #: How load moves through a route. ``"preloaded"`` (default, all legacy
    #: instances): everything is loaded at the origin and the cumulative load
    #: grows at each delivery. ``"pickup_delivery"``: load rises at a pickup node
    #: and falls at its delivery, so the route may interleave the two.
    load_model: str = "preloaded"

    @property
    def depot(self) -> Node:
        return self.nodes[0]

    @property
    def pickups(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.is_pickup)

    @property
    def deliveries(self) -> tuple[Node, ...]:
        """The nodes a route has to serve — one per order.

        For every legacy instance this is exactly "all nodes except the depot", so
        ``customers`` keeps its old meaning everywhere downstream.
        """
        return tuple(n for n in self.nodes if not n.is_depot and not n.is_pickup)

    @property
    def customers(self) -> tuple[Node, ...]:
        """All nodes except the depot."""
        return self.deliveries

    @property
    def n_customers(self) -> int:
        return len(self.deliveries)

    @property
    def total_demand(self) -> int:
        return sum(n.demand for n in self.deliveries)

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
    #: ``"delivery"`` (default) or ``"pickup"`` — so a stop list can be drawn and
    #: read without consulting the instance again.
    kind: str = "delivery"


@dataclass(frozen=True)
class VehicleRoute:
    """One depot-to-end route with its auditable schedule.

    ``end_node_id`` is ``None`` for the legacy closed route (the vehicle returns
    to the depot) and otherwise the node the vehicle parks at, so an open route
    can be told apart from a return trip (2026-09-16, supply-point work).
    """

    vehicle_id: int
    customer_ids: tuple[int, ...]
    stops: tuple[RouteStop, ...]
    total_load: int
    total_distance: float
    duration: float
    time_window_violations: int
    capacity_violation_units: int
    depot_return_violation: bool
    end_node_id: int | None = None
    mileage_limit_violation: bool = False
    #: A delivery was served before its own pickup (or with nothing on board).
    #: Always false for "preloaded" instances.
    pairing_violation: bool = False

    @property
    def feasible(self) -> bool:
        return (
            self.time_window_violations == 0
            and self.capacity_violation_units == 0
            and not self.depot_return_violation
            and not self.mileage_limit_violation
            and not self.pairing_violation
        )

    @property
    def node_sequence(self) -> tuple[int, ...]:
        """Every node the vehicle visits, in order (pickups included).

        Equal to ``customer_ids`` unless the instance mixes pickups and
        deliveries; the map and the road geometry need the full driven sequence.
        """
        return tuple(stop.node_id for stop in self.stops)


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
    mileage_violations: int = 0
    pairing_violations: int = 0

    @property
    def violation_count(self) -> int:
        return (
            self.time_window_violations
            + self.capacity_violations
            + self.depot_return_violations
            + self.vehicle_limit_violations
            + self.mileage_violations
            + self.pairing_violations
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
