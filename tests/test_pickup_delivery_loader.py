"""PDPTW step 2 (2026-09-16): one dense node pair per order.

``load_singapore_subset`` aggregates demand **per destination**, which quietly
assumes everything is loaded once at a single origin. That cannot express "order A
is picked up in the north-east, order B at the warehouse, and one truck serves
both". This loader gives every order a pickup node and a delivery node, so the
solvers see the real problem.

Conventions pinned here, because getting one wrong is silent:

* **``Node.demand`` stays a positive quantity** on both nodes; the sign comes from
  ``kind``. That keeps the field meaning "how much" exactly as it does everywhere
  else in the model instead of meaning something different per role;
* **dense ids are assigned in ``order_id`` order**, so the same request always
  produces the same instance (a solver result has to be reproducible);
* the **delivery window is intersected** with the site's receiving hours, while the
  **pickup window is the source's own opening hours** — the order's window is about
  the delivery.
"""
from __future__ import annotations

import pytest

from optimisation.models import Node
from optimisation.routing import build_result, evaluate_route
from optimisation.singapore_loader import (
    PickupDeliveryOrder,
    load_pickup_delivery_subset,
    read_network,
)

NETWORK = read_network()
NODE = {n["facility_id"]: n["node_id"] for n in NETWORK["nodes"]}


def _order(order_id: str, origin: str, destination: str, quantity: int = 30,
           earliest: int = 540, latest: int = 1020) -> PickupDeliveryOrder:
    return PickupDeliveryOrder(order_id, origin, destination, quantity, earliest, latest)


def _leg(a, b):
    return (NETWORK["matrix"]["distance_m"][NODE[a]][NODE[b]] / 1000,
            NETWORK["matrix"]["duration_s"][NODE[a]][NODE[b]] / 60)


@pytest.fixture(scope="module")
def two_origins():
    return load_pickup_delivery_subset(
        (_order("O-1", "W-WESTGATE", "H-SGH", 30),
         _order("O-2", "D-HOUGANG", "H-SKH", 20)),
        vehicle_nr=2, capacity=100,
    )


def test_each_order_contributes_a_pickup_and_a_delivery(two_origins):
    instance, leg_fn, source_ids = two_origins

    assert instance.load_model == "pickup_delivery"
    assert len(instance.nodes) == 1 + 2 * 2          # depot + two pairs
    assert len(instance.pickups) == 2
    assert len(instance.deliveries) == 2
    assert {node.pair_id for node in instance.pickups} == {"O-1", "O-2"}
    # the depot is still node 0 and the driving sequence maps back to the network
    assert instance.depot.node_id == 0
    assert source_ids[0] == NODE["W-WESTGATE"]
    assert source_ids[1] == NODE["W-WESTGATE"]       # O-1 picked up at the warehouse
    assert source_ids[3] == NODE["D-HOUGANG"]        # O-2 picked up at the depot


def test_demand_stays_positive_and_the_quantity_is_the_orders(two_origins):
    instance, _, _ = two_origins
    assert instance.total_demand == 50
    for node in instance.nodes:
        assert node.demand >= 0
    quantities = {node.pair_id: node.demand for node in instance.pickups}
    assert quantities == {"O-1": 30, "O-2": 20}


def test_the_pickup_window_is_the_sources_and_the_delivery_window_the_orders(two_origins):
    instance, _, _ = two_origins
    hougang = NETWORK["nodes"][NODE["D-HOUGANG"]]
    pickup = next(n for n in instance.pickups if n.pair_id == "O-2")
    delivery = next(n for n in instance.deliveries if n.pair_id == "O-2")
    sgh = NETWORK["nodes"][NODE["H-SKH"]]

    assert (pickup.earliest, pickup.latest) == (hougang["earliest_min"], hougang["latest_min"])
    assert (delivery.earliest, delivery.latest) == (max(sgh["earliest_min"], 540),
                                                    min(sgh["latest_min"], 1020))


def test_dense_ids_do_not_depend_on_the_request_order():
    first, _, _ = load_pickup_delivery_subset(
        (_order("O-1", "W-WESTGATE", "H-SGH"), _order("O-2", "D-HOUGANG", "H-SKH")))
    second, _, _ = load_pickup_delivery_subset(
        (_order("O-2", "D-HOUGANG", "H-SKH"), _order("O-1", "W-WESTGATE", "H-SGH")))

    assert [(n.node_id, n.pair_id, n.kind) for n in first.nodes] == \
           [(n.node_id, n.pair_id, n.kind) for n in second.nodes]


def test_the_instance_schedules_both_pickups_and_deliveries(two_origins):
    instance, leg_fn, _ = two_origins

    route = evaluate_route(instance, (1, 2, 3, 4), leg_fn=leg_fn)
    result = build_result(instance, "test", (route,))

    assert [stop.kind for stop in route.stops] == ["pickup", "delivery", "pickup", "delivery"]
    assert [stop.cumulative_load for stop in route.stops] == [30, 0, 20, 0]
    assert route.pairing_violation is False
    assert result.metrics.served_customers == 2
    assert result.metrics.unserved_customer_ids == ()


# --- the loader refuses nonsense -------------------------------------------

def test_a_window_that_misses_the_receiving_hours_is_refused():
    with pytest.raises(ValueError, match="does not overlap"):
        load_pickup_delivery_subset((_order("O-1", "W-WESTGATE", "H-SGH",
                                            earliest=0, latest=100),))


def test_an_unknown_facility_is_refused():
    with pytest.raises(ValueError, match="unknown origin facility"):
        load_pickup_delivery_subset((_order("O-1", "D-NOWHERE", "H-SGH"),))
    with pytest.raises(ValueError, match="unknown destination facility"):
        load_pickup_delivery_subset((_order("O-1", "W-WESTGATE", "H-NOWHERE"),))


def test_a_hospital_cannot_be_a_source_and_a_source_cannot_be_a_destination():
    with pytest.raises(ValueError, match="not a source"):
        load_pickup_delivery_subset((_order("O-1", "H-SGH", "H-NUH"),))
    with pytest.raises(ValueError, match="not a receiving site"):
        load_pickup_delivery_subset((_order("O-1", "W-WESTGATE", "D-BUGIS"),))


def test_nonsense_quantities_and_empty_requests_are_refused():
    with pytest.raises(ValueError, match="at least one"):
        load_pickup_delivery_subset(())
    with pytest.raises(ValueError, match="positive integer quantity"):
        load_pickup_delivery_subset((_order("O-1", "W-WESTGATE", "H-SGH", quantity=0),))
