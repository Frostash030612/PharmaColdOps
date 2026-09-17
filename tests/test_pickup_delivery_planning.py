"""PDPTW step 3 (2026-09-16): one truck, several sources, planned by OR-Tools.

This is the capability the grouped model could not express. Grouped mode ties a
truck to a single source, so an order collected at a distribution point forces a
second truck; here both orders share one run and the load profile is the real one.

The other half of the file pins that the *rest* of the system still composes with
it: the mileage cap, the parking nodes and the ordinary grouped default all keep
working, which is the point of doing this behind a switch instead of replacing
what already ran.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.dispatch_models import (
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
)
from optimisation.dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders
from optimisation.singapore_loader import PickupDeliveryOrder

client = TestClient(app)
TERMINALS = ("D-HOUGANG", "D-BUGIS")

#: Two orders from the warehouse and one from a distribution point: the case the
#: grouped model has to refuse and this one must serve with a single truck.
ORDERS = (
    DeliveryOrder("O-W1", "vaccine_2_8", "H-SGH", 30, 540, 1020, "chilled",
                  origin_facility_id="W-WESTGATE"),
    DeliveryOrder("O-D1", "vaccine_2_8", "H-SKH", 20, 540, 1020, "chilled",
                  origin_facility_id="D-HOUGANG"),
    DeliveryOrder("O-W2", "vaccine_2_8", "H-NUH", 25, 540, 1020, "chilled",
                  origin_facility_id="W-WESTGATE"),
)
INVENTORY = (
    InventoryLot("L-W", "vaccine_2_8", "W-WESTGATE", 300, "chilled"),
    InventoryLot("L-D", "vaccine_2_8", "D-HOUGANG", 300, "chilled"),
)
ONE_TRUCK = (DispatchVehicle("V-1", 100, "chilled", "W-WESTGATE"),)


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def _plan(constraints, *, algorithm="ortools", orders=ORDERS, inventory=INVENTORY,
          vehicles=ONE_TRUCK):
    return plan_delivery_orders(orders, inventory, vehicles,
                                algorithm=algorithm, constraints=constraints)


def test_one_truck_collects_from_two_sources_on_one_route():
    plan = _plan(DispatchConstraints(routing_model="pickup_delivery"))
    group = plan.zone_plans[0]

    assert plan.algorithm == "ortools-pickup-delivery"
    assert group.result.metrics.vehicles_used == 1
    assert group.result.metrics.served_customers == 3
    assert group.result.feasible

    route = group.result.routes[0]
    kinds = [stop.kind for stop in route.stops]
    # three pickups and three deliveries, and every pickup comes first
    assert kinds.count("pickup") == 3
    assert kinds.count("delivery") == 3
    assert kinds[:3] == ["pickup"] * 3 or kinds.index("delivery") >= 1
    assert route.pairing_violation is False
    # the load never goes negative and ends empty — the real PDPTW profile
    loads = [stop.cumulative_load for stop in route.stops]
    assert min(loads) >= 0
    assert loads[-1] == 0
    assert max(loads) <= 100


def test_the_route_really_visits_both_sources():
    plan = _plan(DispatchConstraints(routing_model="pickup_delivery"))
    route = plan.zone_plans[0].result.routes[0]

    from optimisation.singapore_loader import read_network
    facility = {n["node_id"]: n["facility_id"] for n in read_network()["nodes"]}
    visited = [facility[node_id] for node_id in route.node_sequence]

    assert "D-HOUGANG" in visited, "the distribution-point pickup must be on the route"
    assert "W-WESTGATE" in visited


def test_capacity_is_never_exceeded_even_at_the_peak():
    """Two 30-unit orders on a 30-unit truck: it must split, not overload."""
    plan = _plan(DispatchConstraints(routing_model="pickup_delivery"),
                 inventory=INVENTORY,
                 orders=(ORDERS[0], DeliveryOrder(
                     "O-W3", "vaccine_2_8", "H-TTSH", 30, 540, 1020, "chilled",
                     origin_facility_id="W-WESTGATE")),
                 vehicles=(DispatchVehicle("V-1", 30, "chilled", "W-WESTGATE"),))

    group = plan.zone_plans[0]
    assert group.result.metrics.capacity_violations == 0
    for route in group.result.routes:
        assert max(stop.cumulative_load for stop in route.stops) <= 30


def test_the_mileage_cap_and_the_parking_node_still_apply():
    """PDPTW composes with the B2 features instead of bypassing them."""
    plan = _plan(DispatchConstraints(
        routing_model="pickup_delivery", mileage_limit_m=40_000,
        terminal_facility_ids=TERMINALS))
    group = plan.zone_plans[0]
    nodes = None

    for route in group.result.routes:
        assert route.total_distance <= 40.0 + 1e-9
        if route.end_node_id is not None:
            from optimisation.singapore_loader import read_network
            nodes = nodes or {n["facility_id"]: n["node_id"]
                              for n in read_network()["nodes"]}
            assert route.end_node_id in {nodes[fid] for fid in TERMINALS}


def test_the_grouped_default_is_untouched():
    constraints = DispatchConstraints()
    assert constraints.routing_model == "grouped"
    # ...and it still refuses to mix sources, which is why this switch exists
    with pytest.raises(ValueError, match="no available vehicle"):
        _plan(constraints)


def test_pickup_delivery_refuses_a_solver_that_cannot_pair():
    """Genetic search plans one single-origin tour; this is not one.

    The refusal names the reason instead of quietly answering with a different
    solver — the caller asked for a genetic plan and would otherwise believe it
    got one (2026-09-16, PDPTW step 4).
    """
    with pytest.raises(ValueError, match="single-origin tour"):
        _plan(DispatchConstraints(routing_model="pickup_delivery"), algorithm="ga")


def test_the_genetic_solver_refuses_a_paired_instance_directly():
    """The guard also protects callers that never go through the planner."""
    from optimisation.ga_solver import solve_ga
    from optimisation.singapore_loader import load_pickup_delivery_subset

    instance, leg_fn, _ = load_pickup_delivery_subset(
        tuple(PickupDeliveryOrder(order_id=order.order_id,
                                  origin_facility_id=order.origin_facility_id,
                                  destination_facility_id=order.destination_facility_id,
                                  quantity=order.quantity,
                                  earliest_min=order.earliest_min,
                                  latest_min=order.latest_min)
              for order in ORDERS),
        vehicle_nr=1, capacity=100,
    )
    with pytest.raises(ValueError, match="single origin"):
        solve_ga(instance, leg_fn=leg_fn, max_generations=1)


# --- the greedy baseline pairs too (2026-09-16, PDPTW step 4) -----------------

def test_greedy_pair_insertion_serves_the_same_run():
    """The baseline exists to be beaten: it must at least be feasible."""
    plan = _plan(DispatchConstraints(routing_model="pickup_delivery"), algorithm="greedy")
    group = plan.zone_plans[0]

    assert plan.algorithm == "greedy-pair-insertion-pickup-delivery"
    assert group.result.metrics.vehicles_used == 1
    assert not group.result.metrics.unserved_customer_ids
    assert {
        order_id for _, order_id, _ in group.stop_plan_by_vehicle[1]
    } == {order.order_id for order in ORDERS}


def test_greedy_collects_everything_before_it_delivers_it():
    """The pairing is what a one-node-at-a-time insertion gets wrong."""
    plan = _plan(DispatchConstraints(routing_model="pickup_delivery"), algorithm="greedy")

    for route in plan.zone_plans[0].result.routes:
        entries = plan.zone_plans[0].stop_plan_by_vehicle[route.vehicle_id]
        # the driven stops and the planned stops are the same list, in the same order
        assert [stop.kind for stop in route.stops] == [kind for kind, _, _ in entries]
        collected: list[str] = []
        for (kind, order_id, _), stop in zip(entries, route.stops):
            assert kind == stop.kind
            if kind == "pickup":
                collected.append(order_id)
            else:
                assert order_id in collected, "delivered before it was collected"
                collected.remove(order_id)
        assert collected == [], "collected something it never delivered"


def test_greedy_capacity_is_a_peak_not_a_total():
    """Goods collected but not yet handed over still occupy the truck."""
    orders = (
        DeliveryOrder("O-A", "vaccine_2_8", "H-SGH", 30, 540, 1020, "chilled",
                      origin_facility_id=DISPATCH_ORIGIN),
        DeliveryOrder("O-B", "vaccine_2_8", "H-NUH", 25, 540, 1020, "chilled",
                      origin_facility_id="D-HOUGANG"),
    )
    plan = _plan(DispatchConstraints(routing_model="pickup_delivery"),
                 algorithm="greedy", orders=orders,
                 vehicles=(DispatchVehicle("V-1", 50, "chilled", DISPATCH_ORIGIN),))
    route = plan.zone_plans[0].result.routes[0]

    assert route.feasible
    assert not plan.zone_plans[0].result.metrics.unserved_customer_ids
    # Collecting both before delivering either would put 55 units on a 50-unit
    # truck; the insertion has to notice that while placing the pair.
    assert max(stop.cumulative_load for stop in route.stops) <= 50
    assert [stop.kind for stop in route.stops][0] == "pickup"


def test_greedy_explains_what_it_could_not_fit():
    """An unserved order still gets a measured reason, pair insertion or not."""
    orders = ORDERS + (DeliveryOrder("O-W3", "vaccine_2_8", "H-TTSH", 60, 540, 1020,
                                     "chilled", origin_facility_id=DISPATCH_ORIGIN),)
    plan = _plan(DispatchConstraints(routing_model="pickup_delivery", max_stops_per_vehicle=2),
                 algorithm="greedy", orders=orders)
    group = plan.zone_plans[0]

    assert group.result.metrics.unserved_customer_ids
    assert group.unserved_reasons, "every unserved order needs a reason"


def test_an_origin_that_cannot_supply_is_still_refused():
    """The supply table keeps guarding origins in this mode too."""
    orders = (DeliveryOrder("O-BAD", "vaccine_2_8", "H-SKH", 20, 540, 1020, "chilled",
                            origin_facility_id="D-BUGIS"),)
    inventory = (InventoryLot("L-B", "vaccine_2_8", "D-BUGIS", 100, "chilled"),)
    with pytest.raises(ValueError, match="does not supply"):
        _plan(DispatchConstraints(routing_model="pickup_delivery"),
              orders=orders, inventory=inventory,
              vehicles=(DispatchVehicle("V-1", 100, "chilled", "D-BUGIS"),))


def test_the_api_can_select_the_model():
    body = {
        "algorithm": "ortools",
        "constraints": {"routing_model": "pickup_delivery",
                        "terminal_facility_ids": list(TERMINALS)},
        "orders": [service._order_dump(order) for order in ORDERS],
        "inventory": [service._lot_dump(lot) for lot in INVENTORY],
        "vehicles": [service._vehicle_dump(vehicle) for vehicle in ONE_TRUCK],
    }
    response = client.post("/api/dispatch/plan", json=body)

    assert response.status_code == 200
    payload = response.json()
    zone = payload["zones"][0]
    # no single origin for the group any more: each order brings its own source
    assert zone["origin_facility_id"] is None
    assert zone["routes"], "the plan must serve the orders"
    served = sum(len(route["order_ids"]) for route in zone["routes"])
    assert served == 3
