"""PDPTW step 1 (2026-09-16): signed load and pickup/delivery pairing in the core.

Everything downstream — greedy, OR-Tools, the GA, the feasibility diagnosis —
goes through ``routing.evaluate_route``, so the load model has to live there and
it has to be **additive**: every legacy instance keeps the old "preloaded"
behaviour byte for byte (the 289 pre-existing tests are that proof), and only an
instance that declares ``load_model="pickup_delivery"`` changes meaning.

Two things the old model could not express, and both are silent killers if wrong:

* **the peak, not the final load** — a truck can be over capacity mid-tour and
  unload again before it finishes;
* **a delivery before its own pickup** — not a capacity question but a broken
  plan, which must be reported rather than quietly satisfied by a negative load.
"""
from __future__ import annotations

import pytest

from optimisation.models import Node, SolomonInstance
from optimisation.routing import build_result, evaluate_route

#: A tiny grid: depot at the origin, one source, two hospitals.
COORDS = {0: (0.0, 0.0), 1: (10.0, 0.0), 2: (20.0, 0.0), 3: (30.0, 0.0), 4: (40.0, 0.0)}


def leg(a: Node, b: Node):
    distance = abs(a.x - b.x) + abs(a.y - b.y)
    return distance, distance


def _node(node_id: int, demand: int, *, kind: str = "delivery",
          pair: str | None = None, earliest: int = 0, latest: int = 10_000) -> Node:
    x, y = COORDS[node_id]
    return Node(node_id, int(x), int(y), demand, earliest, latest, 0,
                kind=kind, pair_id=pair)


def _preloaded_instance() -> SolomonInstance:
    """How every instance was built before today."""
    return SolomonInstance("LEGACY", 1, 100, (
        _node(0, 0), _node(1, 10), _node(2, 20),
    ))


def _pickup_delivery_instance() -> SolomonInstance:
    """Order A picks up at node 1 and delivers to node 3."""
    return SolomonInstance("PD", 1, 100, (
        _node(0, 0),
        _node(1, 10, kind="pickup", pair="A"),
        _node(3, 10, kind="delivery", pair="A"),
    ), load_model="pickup_delivery")


# --- legacy behaviour is untouched ------------------------------------------

def test_a_legacy_instance_looks_exactly_as_before():
    instance = _preloaded_instance()
    assert instance.load_model == "preloaded"
    assert instance.pickups == ()
    assert instance.customers == instance.deliveries
    assert instance.n_customers == 2
    assert instance.total_demand == 30


def test_a_legacy_route_still_accumulates_load_at_each_delivery():
    instance = _preloaded_instance()
    route = evaluate_route(instance, (1, 2), leg_fn=leg)

    assert [stop.cumulative_load for stop in route.stops] == [10, 30]
    assert route.capacity_violation_units == 0
    assert route.pairing_violation is False
    assert route.node_sequence == route.customer_ids == (1, 2)


# --- the signed model -------------------------------------------------------

def test_load_rises_at_the_pickup_and_falls_at_its_delivery():
    instance = _pickup_delivery_instance()
    route = evaluate_route(instance, (1, 3), leg_fn=leg)

    assert [stop.kind for stop in route.stops] == ["pickup", "delivery"]
    assert [stop.cumulative_load for stop in route.stops] == [10, 0]
    assert route.pairing_violation is False
    assert route.feasible
    # the driven sequence keeps the pickup; only the delivery counts as served
    assert route.node_sequence == (1, 3)
    assert route.customer_ids == (3,)


def test_a_route_may_interleave_two_orders():
    """Pick both up, then deliver both — the whole point of the model."""
    instance = SolomonInstance("PD2", 1, 100, (
        _node(0, 0),
        _node(1, 10, kind="pickup", pair="A"),
        _node(3, 10, kind="delivery", pair="A"),
        _node(2, 20, kind="pickup", pair="B"),
        _node(4, 20, kind="delivery", pair="B"),
    ), load_model="pickup_delivery")

    route = evaluate_route(instance, (1, 2, 3, 4), leg_fn=leg)

    assert [stop.cumulative_load for stop in route.stops] == [10, 30, 20, 0]
    assert route.pairing_violation is False
    assert route.customer_ids == (3, 4)


def test_capacity_is_judged_on_the_peak_not_the_final_load():
    """Two pickups of 8 with a capacity of 10: peak 16, final 8."""
    instance = SolomonInstance("PD3", 1, 10, (
        _node(0, 0),
        _node(1, 8, kind="pickup", pair="A"),
        _node(3, 8, kind="delivery", pair="A"),
        _node(2, 8, kind="pickup", pair="B"),
        _node(4, 8, kind="delivery", pair="B"),
    ), load_model="pickup_delivery")

    route = evaluate_route(instance, (1, 2, 3, 4), leg_fn=leg)

    assert route.stops[-1].cumulative_load == 0      # what a naive check would see
    assert [stop.cumulative_load for stop in route.stops] == [8, 16, 8, 0]
    assert route.capacity_violation_units == 6       # ...but the peak was 16
    assert not route.feasible


def test_a_delivery_before_its_pickup_is_reported():
    instance = _pickup_delivery_instance()
    route = evaluate_route(instance, (3, 1), leg_fn=leg)

    assert route.pairing_violation is True
    assert not route.feasible
    # ...and it is counted, so a caller cannot miss it in the metrics
    result = build_result(instance, "test", (route,))
    assert result.metrics.pairing_violations == 1
    assert not result.feasible


def test_only_deliveries_count_as_served():
    instance = SolomonInstance("PD4", 1, 100, (
        _node(0, 0),
        _node(1, 10, kind="pickup", pair="A"),
        _node(3, 10, kind="delivery", pair="A"),
        _node(2, 20, kind="pickup", pair="B"),
        _node(4, 20, kind="delivery", pair="B"),
    ), load_model="pickup_delivery")

    # only order A is served: B's pickup happens but its delivery never does
    result = build_result(instance, "test", (evaluate_route(instance, (1, 3), leg_fn=leg),))

    assert result.metrics.served_customers == 1
    assert result.metrics.unserved_customer_ids == (4,)
