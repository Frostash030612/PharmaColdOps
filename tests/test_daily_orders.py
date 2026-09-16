"""Today's delivery plan — the batch input that makes multi-stop planning real.

The regression this file guards is the one that motivated the feature: committing
a reshipment case plans exactly ONE order (``plan_delivery_orders((order,), …)``),
so every vehicle served exactly one hospital, the multi-stop planner was never
exercised by the running system, and greedy / OR-Tools / GA had nothing to
disagree about (``docs/C_配送模块.md`` §3.2).  A *batch* of ordinary hospital
orders is what turns that into a one-truck-many-stops loop.

The second half covers the plumbing fix: a plan created through
``POST /api/dispatch/runs`` must be visible to ``GET /api/dispatch/active``,
otherwise an operator could build a plan and the panel would keep saying
"no active dispatch operation".
"""
from __future__ import annotations

import datetime
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.daily_orders import ZONE_PRODUCT, daily_delivery_batch
from optimisation.dispatch_models import DispatchConstraints, validate_dispatch_inputs
from optimisation.dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders
from optimisation.dispatch_repository import latest_dispatch_id
from optimisation.singapore_loader import read_network


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


# --- the batch itself --------------------------------------------------------

def test_default_batch_is_a_stable_demo_set():
    """No seed means the fixed set, so a rehearsal and the report agree."""
    orders, _inventory, _vehicles = daily_delivery_batch()
    again, _i2, _v2 = daily_delivery_batch()
    assert len(orders) == 4
    assert [order.order_id for order in orders] == [order.order_id for order in again]


def test_seeded_batches_are_reproducible_and_explore():
    same = [order.order_id for order in daily_delivery_batch(seed=7)[0]]
    assert same == [order.order_id for order in daily_delivery_batch(seed=7)[0]]
    draws = {
        tuple(order.destination_facility_id for order in daily_delivery_batch(seed=seed)[0])
        for seed in range(6)
    }
    assert len(draws) > 1, "seeded draws should not all pick the same hospitals"


def test_orders_take_windows_and_demand_from_the_committed_network():
    orders, _inventory, _vehicles = daily_delivery_batch()
    customers = {
        node["facility_id"]: node
        for node in read_network()["nodes"] if node["role"] == "customer"
    }
    for order in orders:
        node = customers[order.destination_facility_id]
        assert order.quantity == node["demand"]
        assert (order.earliest_min, order.latest_min) == (
            node["earliest_min"], node["latest_min"]
        )


def test_fleet_carries_the_whole_batch():
    orders, inventory, vehicles = daily_delivery_batch()
    total = sum(order.quantity for order in orders)
    assert sum(lot.available_quantity for lot in inventory) == total
    assert sum(vehicle.capacity for vehicle in vehicles) >= total
    # ... and the batch must pass the same validation any manual order batch does
    validate_dispatch_inputs(
        orders, inventory, vehicles, origin_facility_id=DISPATCH_ORIGIN
    )


def test_zone_must_be_known_and_hospitals_bounded():
    with pytest.raises(ValueError, match="unknown temperature zone"):
        daily_delivery_batch(temperature_zone="tepid")
    with pytest.raises(ValueError, match="hospitals must be between"):
        daily_delivery_batch(hospitals=0)
    with pytest.raises(ValueError, match="hospitals must be between"):
        daily_delivery_batch(hospitals=99)


def test_zone_product_mapping_matches_the_dispatch_contract():
    assert ZONE_PRODUCT["chilled"] == "vaccine_2_8"
    assert set(ZONE_PRODUCT) == {"chilled", "frozen", "ultracold"}


def test_batch_plans_one_vehicle_over_every_stop():
    """This is the whole point of the batch: one truck, many hospitals."""
    orders, inventory, vehicles = daily_delivery_batch()
    plan = plan_delivery_orders(orders, inventory, vehicles)
    assert plan.feasible
    zone = plan.zone_plans[0]
    assert zone.result.metrics.vehicles_used == 1
    assert zone.result.metrics.served_customers == len(orders)
    assert len(zone.result.routes[0].customer_ids) == len(orders)
    assert zone.result.metrics.violation_count == 0


def test_a_bigger_batch_than_one_truck_is_split_by_the_planner():
    """The caller hands over vehicles; whether one suffices is the planner's call."""
    orders, inventory, vehicles = daily_delivery_batch(hospitals=8)
    plan = plan_delivery_orders(orders, inventory, vehicles)
    assert plan.feasible
    assert plan.zone_plans[0].result.metrics.served_customers == 8


@pytest.mark.parametrize("algorithm", ["greedy", "ortools"])
def test_hard_fleet_and_stop_limits_are_enforced_by_the_solver(algorithm):
    orders, inventory, vehicles = daily_delivery_batch(hospitals=8)
    constraints = DispatchConstraints(max_vehicles=2, max_stops_per_vehicle=3)

    plan = plan_delivery_orders(
        orders, inventory, vehicles, algorithm=algorithm, constraints=constraints,
    )
    zone = plan.zone_plans[0]

    assert len(zone.vehicle_ids) == 2
    assert zone.result.metrics.vehicles_used <= 2
    assert all(len(route.customer_ids) <= 3 for route in zone.result.routes)
    assert zone.result.metrics.served_customers <= 6
    assert zone.result.metrics.unserved_customer_ids


# --- API plumbing ------------------------------------------------------------

def test_daily_orders_endpoint_returns_a_postable_plan():
    response = client.get("/api/dispatch/daily-orders")
    assert response.status_code == 200
    body = response.json()
    assert body["hospitals"] == 4
    assert len(body["plan"]["orders"]) == 4
    assert body["plan"]["algorithm"] in {"greedy", "ortools"}
    assert body["plan"]["constraints"] == {
        "max_vehicles": 3, "max_stops_per_vehicle": 4,
    }
    # the simulated-data disclosure travels with the payload
    assert body["note"].strip()
    preview = client.post("/api/dispatch/plan", json=body["plan"])
    assert preview.status_code == 200
    assert preview.json()["feasible"] is True
    assert preview.json()["constraints"] == body["plan"]["constraints"]


def test_daily_orders_endpoint_rejects_a_bad_seed_or_zone():
    assert client.get("/api/dispatch/daily-orders?hospitals=0").status_code == 422
    assert client.get("/api/dispatch/daily-orders?temperature_zone=tepid").status_code == 422


def test_a_daily_plan_is_visible_to_the_active_endpoint():
    """Regression: the panel only ever saw RESHIPMENTS-* operations."""
    body = client.get("/api/dispatch/daily-orders").json()
    created = client.post(
        "/api/dispatch/runs",
        json={**body["plan"], "dispatch_id": "PLAN-1", "command_id": "create-PLAN-1"},
    )
    assert created.status_code == 200
    active = client.get("/api/dispatch/active")
    assert active.status_code == 200
    assert active.json()["dispatch_id"] == "PLAN-1"
    # and it carries what the map needs
    assert active.json()["route_view"]["routes"]


def test_seed_today_resolves_to_the_date_and_stays_stable():
    """``today`` is the offline stand-in for a daily delivery feed."""
    first = client.get("/api/dispatch/daily-orders?seed=today")
    assert first.status_code == 200
    body = first.json()
    assert body["seed"] == int(datetime.date.today().strftime("%Y%m%d"))
    again = client.get("/api/dispatch/daily-orders?seed=today").json()
    assert [order["order_id"] for order in again["plan"]["orders"]] == [
        order["order_id"] for order in body["plan"]["orders"]
    ]


def test_unknown_seed_text_is_rejected():
    assert client.get("/api/dispatch/daily-orders?seed=soon").status_code == 422


def test_active_is_404_before_anything_exists():
    assert client.get("/api/dispatch/active").status_code == 404


# --- repository recency ------------------------------------------------------

def test_latest_dispatch_id_reads_a_pre_migration_sqlite_file(tmp_path):
    """A local DB created before updated_at existed must still be readable.

    ``_sqlite_connect`` adds the column on connect (same pattern as
    context_json); rows written before that keep NULL and sort after new ones.
    """
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE dispatch_runs (dispatch_id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
        "state_json TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}')"
    )
    connection.execute(
        "INSERT INTO dispatch_runs (dispatch_id, version, state_json, context_json) "
        "VALUES ('RESHIPMENTS-1', 1, '{}', '{}')"
    )
    connection.commit()
    connection.close()

    assert latest_dispatch_id(path) == "RESHIPMENTS-1"
    assert latest_dispatch_id(tmp_path / "never-created.sqlite3") is None
