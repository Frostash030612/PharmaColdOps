"""B1b + B4 (2026-09-16): orders carry an origin, and routes start there.

The model this version implements: orders are planned **per (temperature zone,
origin)**, and each group's route starts at that supply point. So "where do we
pick this up" is a real part of the route, and the mileage / capacity / time
window / parking rules are applied to the leg that actually happens.

What it does not do (declared, not hidden): one truck serving orders from
*different* origins in a single route needs the full pickup-delivery model.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.daily_orders import daily_delivery_batch
from optimisation.dispatch_models import (
    DeliveryOrder, DispatchVehicle, InventoryLot,
)
from optimisation.dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def _order(order_id: str, destination: str, *, origin: str | None = None,
           product: str = "vaccine_2_8", quantity: int = 30) -> DeliveryOrder:
    return DeliveryOrder(order_id, product, destination, quantity, 540, 1020,
                         "chilled", origin_facility_id=origin)


def _lot(facility: str, *, product: str = "vaccine_2_8", quantity: int = 200):
    return InventoryLot(f"L-{facility}-{product}", product, facility, quantity, "chilled")


def _vehicle(vehicle_id: str, facility: str, *, zone: str = "chilled", capacity: int = 100):
    return DispatchVehicle(vehicle_id, capacity, zone, facility)


# --- routing from the order's own origin ------------------------------------

def test_an_order_routes_from_its_own_origin():
    orders = (_order("O-1", "H-KKH", origin="D-HOUGANG"),)
    plan = plan_delivery_orders(orders, (_lot("D-HOUGANG"),), (_vehicle("V-1", "D-HOUGANG"),))

    group = plan.zone_plans[0]
    assert group.origin_facility_id == "D-HOUGANG"
    assert group.vehicle_ids == ("V-1",)
    assert group.result.routes[0].customer_ids, "the route must serve the order"
    assert group.result.feasible


def test_loading_closer_to_the_destination_is_actually_shorter():
    """The origin has to change the distance, or nothing was modelled."""
    from_depot = plan_delivery_orders(
        (_order("O-1", "H-KKH"),), (_lot(DISPATCH_ORIGIN),), (_vehicle("V-1", DISPATCH_ORIGIN),),
    ).zone_plans[0].result.metrics.total_distance
    from_depot_origin = plan_delivery_orders(
        (_order("O-2", "H-KKH", origin="D-HOUGANG"),),
        (_lot("D-HOUGANG"),), (_vehicle("V-2", "D-HOUGANG"),),
    ).zone_plans[0].result.metrics.total_distance

    assert from_depot_origin < from_depot


def test_two_origins_are_two_groups_each_with_its_own_truck():
    orders = (_order("O-W", "H-SGH"), _order("O-D", "H-KKH", origin="D-HOUGANG"))
    inventory = (_lot(DISPATCH_ORIGIN), _lot("D-HOUGANG"))
    vehicles = (_vehicle("V-W", DISPATCH_ORIGIN), _vehicle("V-D", "D-HOUGANG"))

    plan = plan_delivery_orders(orders, inventory, vehicles)

    origins = {group.origin_facility_id for group in plan.zone_plans}
    assert origins == {DISPATCH_ORIGIN, "D-HOUGANG"}
    for group in plan.zone_plans:
        assert len(group.vehicle_ids) == 1
        # each group is planned and reported independently
        assert group.result.metrics.served_customers == 1


def test_orders_sharing_an_origin_still_share_one_truck():
    """Grouping must not fragment a run that used to be one route."""
    orders = (_order("O-1", "H-KKH", origin="D-HOUGANG"),
              _order("O-2", "H-SKH", origin="D-HOUGANG"))
    plan = plan_delivery_orders(orders, (_lot("D-HOUGANG"),), (_vehicle("V-1", "D-HOUGANG"),))

    assert len(plan.zone_plans) == 1
    result = plan.zone_plans[0].result
    assert result.metrics.vehicles_used == 1
    assert result.metrics.served_customers == 2


def test_the_fleet_limit_is_shared_across_origins():
    orders = (_order("O-W", "H-SGH"), _order("O-D", "H-KKH", origin="D-HOUGANG"))
    inventory = (_lot(DISPATCH_ORIGIN), _lot("D-HOUGANG"))
    vehicles = (_vehicle("V-W", DISPATCH_ORIGIN), _vehicle("V-D", "D-HOUGANG"))

    from optimisation.dispatch_models import DispatchConstraints
    with pytest.raises(ValueError, match="fleet limit"):
        plan_delivery_orders(orders, inventory, vehicles,
                             constraints=DispatchConstraints(max_vehicles=1))


# --- the supply table guards the origin ------------------------------------

def test_an_origin_must_be_a_supply_point():
    """A hospital is not a source, however it got into the payload."""
    orders = (_order("O-1", "H-KKH", origin="H-SGH"),)
    with pytest.raises(ValueError, match="is not a supply point"):
        plan_delivery_orders(orders, (_lot("H-SGH"),), (_vehicle("V-1", "H-SGH"),))


def test_an_origin_must_actually_supply_that_product():
    """Bugis+ carries insulin and frozen — not vaccine."""
    orders = (_order("O-1", "H-KKH", origin="D-BUGIS"),)
    with pytest.raises(ValueError, match="does not supply"):
        plan_delivery_orders(orders, (_lot("D-BUGIS"),), (_vehicle("V-1", "D-BUGIS"),))


def test_the_goods_must_be_at_the_orders_own_origin():
    orders = (_order("O-1", "H-KKH", origin="D-NORTHPOINT"),)
    with pytest.raises(ValueError, match="insufficient available inventory for vaccine_2_8 .*D-NORTHPOINT"):
        plan_delivery_orders(orders, (_lot(DISPATCH_ORIGIN),), (_vehicle("V-1", "D-NORTHPOINT"),))


def test_a_vehicle_must_be_available_at_the_origin():
    orders = (_order("O-1", "H-KKH", origin="D-NORTHPOINT"),)
    with pytest.raises(ValueError, match="no available vehicle .*at D-NORTHPOINT"):
        plan_delivery_orders(orders, (_lot("D-NORTHPOINT"),), (_vehicle("V-1", DISPATCH_ORIGIN),))


def test_an_order_cannot_be_picked_up_where_it_is_delivered():
    with pytest.raises(ValueError, match="cannot be picked up where it is delivered"):
        _order("O-1", "H-SGH", origin="H-SGH")


# --- backward compatibility -------------------------------------------------

def test_omitting_the_origin_plans_exactly_as_before():
    """Every existing caller omits it; the default must be the old behaviour."""
    orders, inventory, vehicles = daily_delivery_batch(hospitals=4)
    plan = plan_delivery_orders(orders, inventory, vehicles)

    assert all(order.origin_facility_id is None for order in orders)
    assert [group.origin_facility_id for group in plan.zone_plans] == [DISPATCH_ORIGIN]
    assert plan.zone_plans[0].result.feasible


# --- the API ----------------------------------------------------------------

def _payload(orders, inventory, vehicles, constraints=None):
    return {
        "algorithm": "greedy",
        "constraints": constraints or {},
        "orders": [service._order_dump(order) for order in orders],
        "inventory": [service._lot_dump(lot) for lot in inventory],
        "vehicles": [service._vehicle_dump(vehicle) for vehicle in vehicles],
    }


def test_the_api_accepts_an_origin_and_reports_it_per_group():
    body = _payload((_order("O-1", "H-KKH", origin="D-HOUGANG"),),
                    (_lot("D-HOUGANG"),), (_vehicle("V-1", "D-HOUGANG"),))
    response = client.post("/api/dispatch/plan", json=body)

    assert response.status_code == 200
    zones = response.json()["zones"]
    assert len(zones) == 1
    assert zones[0]["origin_facility_id"] == "D-HOUGANG"
    assert zones[0]["routes"], "the group must produce a route"


def test_the_api_explains_an_origin_that_cannot_supply():
    body = _payload((_order("O-1", "H-KKH", origin="D-BUGIS"),),
                    (_lot("D-BUGIS"),), (_vehicle("V-1", "D-BUGIS"),))
    response = client.post("/api/dispatch/plan", json=body)

    assert response.status_code == 422
    assert "does not supply" in response.json()["detail"]
