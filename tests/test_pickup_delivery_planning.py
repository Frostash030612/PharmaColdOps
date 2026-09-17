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
    with pytest.raises(ValueError, match="pair insertion"):
        _plan(DispatchConstraints(routing_model="pickup_delivery"), algorithm="greedy")


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


def test_a_pickup_delivery_plan_cannot_be_dispatched_yet():
    """Previewing is wired; executing is not, and that must not be silent.

    The state models a truck's work as an ORDER QUEUE with at most a leading
    pickup (B6). A pickup-delivery plan interleaves them, so accepting one would
    produce a live map the truck does not drive. Refusing is the honest answer
    until the stop-sequence state lands (step 4).
    """
    from optimisation.dispatch_state import accept_plan

    plan = _plan(DispatchConstraints(routing_model="pickup_delivery"))
    with pytest.raises(ValueError, match="cannot be dispatched yet"):
        accept_plan(plan, ORDERS, INVENTORY, command_id="c", vehicles=ONE_TRUCK)
