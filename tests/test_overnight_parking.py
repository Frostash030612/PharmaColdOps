"""B5 (2026-09-16): where each truck should spend the night.

The rule: the day's fixed orders are known, so the fleet should not just drive
home — park where tomorrow starts cheaply. The decision must also be honest
about its two costs, so the tests check the *comparison* (deadhead saved tomorrow
vs distance driven tonight) and the mileage-cap refusal, not just the chosen node.
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
from optimisation.dispatch_planner import DISPATCH_ORIGIN
from optimisation.overnight import plan_overnight_parking
from optimisation.singapore_loader import read_network

client = TestClient(app)
TERMINALS = ("D-NORTHPOINT", "D-HOUGANG", "D-BUGIS")


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


@pytest.fixture(scope="module")
def matrix():
    net = read_network()
    node = {n["facility_id"]: n["node_id"] for n in net["nodes"]}
    return net["matrix"]["distance_m"], node


def _order(facility_id: str, *, quantity: int = 30):
    return DeliveryOrder(f"DO-{facility_id}", "vaccine_2_8", facility_id,
                         quantity, 540, 1020, "chilled")


def _inputs(destination: str, *, vehicle_at: str, capacity: int = 100):
    orders = (_order(destination),)
    inventory = (InventoryLot("L1", "vaccine_2_8", DISPATCH_ORIGIN, 500, "chilled"),)
    vehicles = (DispatchVehicle("V1", capacity, "chilled", vehicle_at),)
    return orders, inventory, vehicles


def test_the_truck_parks_at_the_allowed_node_closest_to_tomorrows_pickup(matrix):
    """Parking is judged against where tomorrow STARTS, not where it ends.

    With a supply-point origin the truck must reach its pickup point before any
    delivery (B4), so the overnight decision targets that node. A truck that ended
    the day in the far east and must load at the west warehouse should park on the
    way, not at the hospital it will not visit first.
    """
    distance, node = matrix
    orders, inventory, vehicles = _inputs("H-SKH", vehicle_at="H-CGH")
    constraints = DispatchConstraints(terminal_facility_ids=TERMINALS)

    plan = plan_overnight_parking(orders, inventory, vehicles, constraints=constraints)

    choice = plan.choices[0]
    assert choice.tomorrow_origin_facility_id == "W-WESTGATE"
    expected = min(TERMINALS, key=lambda fid: distance[node[fid]][node["W-WESTGATE"]])
    assert choice.park_facility_id == expected
    # distances are reported in whole metres; the matrix keeps decimals
    assert choice.deadhead_m == pytest.approx(distance[node[expected]][node["W-WESTGATE"]], abs=1)
    assert choice.stay_deadhead_m == pytest.approx(distance[node["H-CGH"]][node["W-WESTGATE"]], abs=1)
    assert choice.saved_m == choice.stay_deadhead_m - choice.deadhead_m
    assert choice.reposition_m == pytest.approx(distance[node["H-CGH"]][node[expected]], abs=1)
    # By the triangle inequality the reposition is at least what it saves, so the
    # honest two-day balance is reported as such — the win is tomorrow's shorter
    # first leg (and an earlier start), not a cheaper total distance.
    assert choice.net_m == choice.saved_m - choice.reposition_m
    assert plan.total_net_m == sum(c.net_m for c in plan.choices)
    assert choice.saved_m > 0


def test_the_reposition_is_charged_against_todays_mileage_cap(matrix):
    """No budget left ⇒ stay where you are, and say which limit refused."""
    orders, inventory, vehicles = _inputs("H-SKH", vehicle_at="H-CGH")
    # a realistic cap: 45 km per day, 500 m of it left tonight
    constraints = DispatchConstraints(terminal_facility_ids=TERMINALS,
                                      mileage_limit_m=45_000)

    plan = plan_overnight_parking(orders, inventory, vehicles, constraints=constraints,
                                  today_distance_m={"V1": 44_500})

    choice = plan.choices[0]
    assert choice.park_facility_id in TERMINALS
    assert choice.reposition_m > 0
    assert choice.feasible is False  # impossible parking is not disguised as staying at a hospital
    assert choice.note == "mileage_budget_exhausted"


def test_staying_put_on_an_allowed_node_still_says_the_better_node_was_blocked(matrix):
    """Silence would read as "this was the best choice" — it was not.

    The truck already stands at an allowed node, so staying is affordable, while
    the node that would shorten tomorrow's first leg is out of today's budget.
    The decision is the same either way; the *reason* is what must not be lost.
    """
    orders, inventory, vehicles = _inputs("H-SKH", vehicle_at="D-NORTHPOINT")
    # 45 km cap, 44.5 km already driven: the 10.9 km hop to the better node is out
    constraints = DispatchConstraints(terminal_facility_ids=TERMINALS,
                                      mileage_limit_m=45_000)
    plan = plan_overnight_parking(orders, inventory, vehicles, constraints=constraints,
                                  today_distance_m={"V1": 44_500})

    choice = plan.choices[0]
    assert choice.note == "mileage_budget_exhausted"
    assert choice.park_facility_id == "D-NORTHPOINT"
    assert choice.feasible


def test_without_terminals_the_truck_simply_stays_put():
    orders, inventory, vehicles = _inputs("H-SKH", vehicle_at="H-CGH")
    plan = plan_overnight_parking(orders, inventory, vehicles,
                                  constraints=DispatchConstraints())
    choice = plan.choices[0]
    assert choice.park_facility_id == DISPATCH_ORIGIN
    assert choice.reposition_m > 0
    assert choice.note == "warehouse_required"


def test_a_truck_with_nothing_tomorrow_stays_where_it_is():
    """An idle truck must not burn mileage driving to a nicer spot.

    The first UI run moved one 17.7 km with no order to serve the next day; the
    decision is "park for tomorrow", and with no tomorrow there is nothing to
    park for.
    """
    orders, inventory, vehicles = daily_delivery_batch(hospitals=2)
    extra = (DispatchVehicle("V-IDLE", 100, "chilled", "H-CGH"),)
    constraints = DispatchConstraints(
        terminal_facility_ids=TERMINALS, max_vehicles=1, max_stops_per_vehicle=4)

    plan = plan_overnight_parking(orders, inventory, vehicles + extra,
                                  constraints=constraints)

    idle_choice = next(c for c in plan.choices if c.vehicle_id == "V-IDLE")
    assert idle_choice.tomorrow_origin_facility_id is None
    assert idle_choice.note == "warehouse_required"
    assert idle_choice.park_facility_id in TERMINALS
    assert idle_choice.reposition_m > 0
    assert idle_choice.net_m == -idle_choice.reposition_m


def test_unknown_parking_node_is_refused():
    orders, inventory, vehicles = _inputs("H-SKH", vehicle_at="H-CGH")
    with pytest.raises(ValueError, match="unknown terminal facilities"):
        plan_overnight_parking(orders, inventory, vehicles,
                               constraints=DispatchConstraints(
                                   terminal_facility_ids=("D-NOWHERE",)))


def test_the_endpoint_returns_the_decision_and_the_comparison():
    orders, inventory, vehicles = _inputs("H-SKH", vehicle_at="H-CGH")
    body = {
        "algorithm": "greedy",
        "constraints": {"terminal_facility_ids": list(TERMINALS)},
        "orders": [service._order_dump(o) for o in orders],
        "inventory": [service._lot_dump(l) for l in inventory],
        "vehicles": [service._vehicle_dump(v) for v in vehicles],
        "today_distance_m": {"V1": 5_000},
    }
    response = client.post("/api/dispatch/overnight-plan", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["totals"]) == {"reposition_m", "deadhead_m", "stay_deadhead_m",
                                      "saved_m", "net_two_day_m"}
    choice = payload["choices"][0]
    assert choice["vehicle_id"] == "V1"
    assert choice["from_facility_id"] == "H-CGH"
    assert choice["park_facility_id"] in TERMINALS
    assert payload["totals"]["saved_m"] == sum(c["saved_m"] for c in payload["choices"])
    assert payload["assumptions"], "the simulated-data disclosure must travel with it"


def test_the_endpoint_rejects_an_unknown_parking_node():
    orders, inventory, vehicles = _inputs("H-SKH", vehicle_at="H-CGH")
    body = {
        "algorithm": "greedy",
        "constraints": {"terminal_facility_ids": ["D-NOWHERE"]},
        "orders": [service._order_dump(o) for o in orders],
        "inventory": [service._lot_dump(l) for l in inventory],
        "vehicles": [service._vehicle_dump(v) for v in vehicles],
    }
    assert client.post("/api/dispatch/overnight-plan", json=body).status_code == 422
