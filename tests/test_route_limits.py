"""B2 (2026-09-16): per-vehicle mileage cap and open routes that park at a depot.

Two user-facing rules are pinned here:

* "if one truck can serve several orders while staying under its daily mileage
  cap, do that; otherwise send another truck" — so a tight cap must **open a
  second vehicle** rather than quietly return an over-limit route, and a cap that
  cannot even cover one order must come back as an explicit "cannot be served";
* "a truck may finish at a node that is allowed to be a terminal" — the route
  becomes **open**: no return-to-depot leg is charged, and the truck's final leg
  goes to that parking node (the map must not drive it home while the plan says it
  parks).

Both solvers must agree, and omitting the new constraints must reproduce the old
closed-route behaviour exactly (every existing caller depends on that).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.daily_orders import daily_delivery_batch
from optimisation.dispatch_models import DispatchConstraints
from optimisation.dispatch_planner import plan_delivery_orders
from optimisation.dispatch_state import accept_plan
from optimisation.singapore_loader import read_network
from optimisation.tracking import vehicle_track

client = TestClient(app)

TERMINALS = ("D-NORTHPOINT", "D-HOUGANG", "D-BUGIS")


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


@pytest.fixture(scope="module")
def network():
    return read_network()


@pytest.fixture(scope="module")
def node_by_facility(network):
    return {n["facility_id"]: n["node_id"] for n in network["nodes"]}


def _batch(hospitals: int = 4):
    return daily_delivery_batch(hospitals=hospitals)


def _plan(constraints=None, *, algorithm: str = "greedy", hospitals: int = 4):
    orders, inventory, vehicles = _batch(hospitals)
    plan = plan_delivery_orders(
        orders, inventory, vehicles, algorithm=algorithm, constraints=constraints
    )
    return plan.zone_plans[0].result


# --- mileage cap -------------------------------------------------------------

def test_a_tight_cap_sends_a_second_vehicle_instead_of_breaking_the_limit():
    """The cap is a hard constraint, and the fleet grows to respect it."""
    open_ended = DispatchConstraints(terminal_facility_ids=TERMINALS)
    uncapped = _plan(open_ended)
    assert uncapped.metrics.vehicles_used == 1, "precondition: one truck covers the batch"

    capped = DispatchConstraints(
        terminal_facility_ids=TERMINALS, mileage_limit_m=25_000
    )
    result = _plan(capped)

    assert result.metrics.vehicles_used > uncapped.metrics.vehicles_used
    assert result.metrics.unserved_customer_ids == ()
    assert result.metrics.mileage_violations == 0
    assert result.feasible
    # every single route stays under the cap
    for route in result.routes:
        assert route.total_distance <= 25.0 + 1e-9


def test_a_cap_that_cannot_cover_any_order_is_explicitly_infeasible():
    """Nothing is silently dropped: every order comes back as unserved.

    A cap that cannot even pay for one delivery must be reported as "cannot be
    served", not as a plan that quietly violates the limit.
    """
    capped = DispatchConstraints(
        terminal_facility_ids=TERMINALS, mileage_limit_m=1_000
    )
    result = _plan(capped)

    assert result.routes == ()
    assert result.metrics.served_customers == 0
    assert len(result.metrics.unserved_customer_ids) == 4
    assert not result.feasible


@pytest.mark.parametrize("algorithm", ["greedy", "ortools"])
def test_both_algorithms_respect_the_cap_and_end_at_a_parking_node(
    algorithm, node_by_facility
):
    terminal_nodes = {node_by_facility[fid] for fid in TERMINALS}
    capped = DispatchConstraints(
        terminal_facility_ids=TERMINALS, mileage_limit_m=30_000
    )
    result = _plan(capped, algorithm=algorithm)

    assert result.routes, "a 30 km cap must still allow some route"
    assert result.metrics.unserved_customer_ids == ()
    for route in result.routes:
        assert route.total_distance <= 30.0 + 1e-9
        assert route.end_node_id in terminal_nodes


# --- open routes -------------------------------------------------------------

def test_terminals_make_the_route_open_and_cheaper_than_driving_home(node_by_facility):
    closed = _plan()
    open_ended = _plan(DispatchConstraints(terminal_facility_ids=TERMINALS))

    assert closed.routes[0].end_node_id is None, "no terminals ⇒ legacy depot return"
    assert open_ended.routes[0].end_node_id in {
        node_by_facility[fid] for fid in TERMINALS
    }
    # Dropping the return leg is the whole point: it must show up as fewer km.
    assert open_ended.metrics.total_distance < closed.metrics.total_distance


def test_the_parking_node_must_exist_in_the_network():
    with pytest.raises(ValueError, match="unknown terminal facilities"):
        _plan(DispatchConstraints(terminal_facility_ids=("D-NOT-A-PLACE",)))


def test_constraint_validation_rejects_nonsense():
    with pytest.raises(ValueError, match="mileage_limit_m"):
        DispatchConstraints(mileage_limit_m=0)
    with pytest.raises(ValueError, match="terminal_facility_ids"):
        DispatchConstraints(terminal_facility_ids=())
    with pytest.raises(ValueError, match="unique"):
        DispatchConstraints(terminal_facility_ids=("D-BUGIS", "D-BUGIS"))


# --- the plan survives into execution ---------------------------------------

def test_the_state_machine_carries_the_parking_node_and_the_map_follows_it():
    """A plan whose trucks park must not have them drive home on the map."""
    orders, inventory, vehicles = _batch(4)
    plan = plan_delivery_orders(
        orders, inventory, vehicles,
        constraints=DispatchConstraints(terminal_facility_ids=TERMINALS),
    )
    state = accept_plan(plan, orders, inventory, command_id="c", vehicles=vehicles)
    progress = next(iter(state.vehicles.values()))

    assert progress.end_node_id is not None

    # No stops left: the only leg the map should draw is depot → parking node.
    track = vehicle_track(
        read_network(), [], depart_min=480.0, sim_now=600.0,
        end_node=progress.end_node_id,
    )
    assert track["leg_to"] == progress.end_node_id
    assert track["finished"] is True


# --- API contract ------------------------------------------------------------

def test_plan_endpoint_echoes_the_new_constraints_and_the_parking_node():
    orders, inventory, vehicles = _batch(4)
    body = {
        "algorithm": "greedy",
        "constraints": {
            "max_vehicles": 3, "max_stops_per_vehicle": 4,
            "mileage_limit_m": 40_000, "terminal_facility_ids": list(TERMINALS),
        },
        "orders": [service._order_dump(o) for o in orders],
        "inventory": [service._lot_dump(l) for l in inventory],
        "vehicles": [service._vehicle_dump(v) for v in vehicles],
    }
    response = client.post("/api/dispatch/plan", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["constraints"]["mileage_limit_m"] == 40_000
    zone = payload["zones"][0]
    assert zone["terminal_facility_ids"] == list(TERMINALS)
    assert zone["mileage_violations"] == 0
    for route in zone["routes"]:
        assert route["end_facility_id"] in TERMINALS
        assert route["end_node_id"] is not None
        assert route["total_distance"] <= 40.0 + 1e-9


def test_a_zero_mileage_cap_is_rejected_by_the_api():
    orders, inventory, vehicles = _batch(2)
    body = {
        "algorithm": "greedy",
        "constraints": {"mileage_limit_m": 0},
        "orders": [service._order_dump(o) for o in orders],
        "inventory": [service._lot_dump(l) for l in inventory],
        "vehicles": [service._vehicle_dump(v) for v in vehicles],
    }
    assert client.post("/api/dispatch/plan", json=body).status_code == 422
