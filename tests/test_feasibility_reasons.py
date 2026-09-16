"""B7 (2026-09-16): an infeasible plan must say *why*, with measured numbers.

"Nothing fits" is not an answer an operator can act on. Every reason here is
produced by really attempting the insertion with the same gate the solvers use,
so the reported gap (needed vs allowed) is the gap the solver saw.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.daily_orders import daily_delivery_batch
from optimisation.dispatch_models import (
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
)
from optimisation.dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders
from optimisation.feasibility import diagnose_unserved
from optimisation.models import Node, SolomonInstance
from optimisation.routing import evaluate_route

client = TestClient(app)
TERMINALS = ("D-NORTHPOINT", "D-HOUGANG", "D-BUGIS")


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def _plan(constraints, orders=None, *, hospitals: int = 4):
    if orders is None:
        orders, inventory, vehicles = daily_delivery_batch(hospitals=hospitals)
    else:
        inventory = (InventoryLot("L1", "vaccine_2_8", DISPATCH_ORIGIN, 500, "chilled"),)
        vehicles = (DispatchVehicle("V1", 100, "chilled", DISPATCH_ORIGIN),)
    return plan_delivery_orders(orders, inventory, vehicles,
                                constraints=constraints).zone_plans[0]


def _reasons(zone_plan, node_id):
    return {reason["code"]: reason["detail"]
            for reason in zone_plan.unserved_reasons[node_id]}


def test_a_tight_cap_reports_the_measured_shortfall():
    """The gap is a number, not a shrug: needed distance vs the cap."""
    zone_plan = _plan(DispatchConstraints(
        mileage_limit_m=12_000, terminal_facility_ids=TERMINALS))

    assert zone_plan.result.metrics.served_customers == 0
    assert len(zone_plan.unserved_reasons) == 4
    for node_id, reasons in zone_plan.unserved_reasons.items():
        detail = {r["code"]: r["detail"] for r in reasons}
        assert "mileage_limit_exceeded" in detail, node_id
        assert detail["mileage_limit_exceeded"]["limit_m"] == 12_000
        # measured: the shortest attempt still exceeds the cap
        assert detail["mileage_limit_exceeded"]["needed_distance_m"] > 12_000


def test_an_order_larger_than_any_vehicle_reports_capacity():
    order = DeliveryOrder("O-BIG", "vaccine_2_8", "H-SGH", 150, 540, 1020, "chilled")
    zone_plan = _plan(DispatchConstraints(), orders=(order,))

    detail = _reasons(zone_plan, zone_plan.result.metrics.unserved_customer_ids[0])
    assert detail["capacity_exceeded"] == {"needed_units": 150, "capacity_units": 100}


def test_a_time_window_reason_carries_the_arrival_the_window_and_the_lateness():
    """Crafted so the order fits alone but is late when appended to the route."""
    instance = SolomonInstance("T", 1, 100, (
        Node(0, 0, 0, 0, 480, 1080, 0),
        Node(1, 30, 0, 10, 540, 1020, 10),
        Node(2, 5, 0, 10, 560, 570, 10),
    ))
    leg = lambda a, b: (abs(a.x - b.x) + abs(a.y - b.y), abs(a.x - b.x) + abs(a.y - b.y))
    routes = (evaluate_route(instance, (1,), leg_fn=leg),)

    diagnosis = diagnose_unserved(instance, (2,), routes, leg_fn=leg)

    detail = {r["code"]: r["detail"] for r in diagnosis[2]}
    assert detail["time_window_infeasible"]["latest_min"] == 570
    assert detail["time_window_infeasible"]["earliest_arrival_min"] == 575
    assert detail["time_window_infeasible"]["late_by_min"] == 5


def test_a_feasible_plan_reports_no_unserved_reasons():
    zone_plan = _plan(DispatchConstraints(terminal_facility_ids=TERMINALS))
    assert zone_plan.result.metrics.unserved_customer_ids == ()
    assert zone_plan.unserved_reasons == {}


def test_the_api_explains_which_order_is_stuck_and_why():
    orders, inventory, vehicles = daily_delivery_batch(hospitals=4)
    body = {
        "algorithm": "greedy",
        "constraints": {"mileage_limit_m": 12_000,
                        "terminal_facility_ids": list(TERMINALS)},
        "orders": [service._order_dump(o) for o in orders],
        "inventory": [service._lot_dump(l) for l in inventory],
        "vehicles": [service._vehicle_dump(v) for v in vehicles],
    }
    response = client.post("/api/dispatch/plan", json=body)

    assert response.status_code == 200
    zone = response.json()["zones"][0]
    assert zone["feasible"] is False
    assert len(zone["unserved"]) == 4
    for entry in zone["unserved"]:
        assert entry["facility_id"].startswith("H-")
        assert entry["order_ids"] and entry["order_ids"][0].startswith("DO-DAILY-")
        codes = {reason["code"] for reason in entry["reasons"]}
        assert "mileage_limit_exceeded" in codes
        detail = next(r["detail"] for r in entry["reasons"]
                      if r["code"] == "mileage_limit_exceeded")
        assert set(detail) == {"needed_distance_m", "limit_m"}
