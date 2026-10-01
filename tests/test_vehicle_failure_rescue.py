"""Mechanical-failure rescue: a failed truck never delivers its remaining cargo.

The safe v1 boundary is deliberate: no vehicle-to-vehicle or cold-storage
handoff is invented.  Remaining demand is marked failed, replacement stock is
reserved again, and a compatible unused vehicle carries new, traceable orders.
"""
from fastapi.testclient import TestClient
import pytest

from api import service
from api.main import app
from optimisation.dispatch_planner import DISPATCH_ORIGIN


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def _payload(*, stock: int = 120, spares: int = 3) -> dict:
    vehicles = [
        {"vehicle_id": f"V-CHILL-{index}", "capacity": 100,
         "temperature_zone": "chilled", "start_facility_id": DISPATCH_ORIGIN}
        for index in range(1, spares + 1)
    ]
    return {
        "orders": [
            {"order_id": "DO-NUH", "product_id": "vaccine_2_8",
             "destination_facility_id": "H-NUH", "quantity": 20,
             "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"},
            {"order_id": "DO-CGH", "product_id": "vaccine_2_8",
             "destination_facility_id": "H-CGH", "quantity": 30,
             "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"},
        ],
        "inventory": [
            {"lot_id": "LOT-CHILL", "product_id": "vaccine_2_8",
             "facility_id": DISPATCH_ORIGIN, "available_quantity": stock,
             "temperature_zone": "chilled"},
        ],
        "vehicles": vehicles,
        "algorithm": "greedy",
        "dispatch_id": "PLAN-FAILURE",
        "command_id": "create-failure-plan",
    }


def _departed(*, stock: int = 120, spares: int = 3) -> tuple[dict, str]:
    created = client.post("/api/dispatch/runs", json=_payload(stock=stock, spares=spares))
    assert created.status_code == 200
    body = client.post(
        "/api/dispatch/runs/PLAN-FAILURE/depart",
        json={"command_id": "depart-failure-plan"},
    )
    assert body.status_code == 200
    failed_vehicle_id = next(iter(body.json()["vehicles"]))
    return body.json(), failed_vehicle_id


def test_failure_preview_marks_the_safe_boundary_and_offers_spare_vehicles():
    departed, failed_vehicle_id = _departed()

    response = client.post(
        "/api/dispatch/runs/PLAN-FAILURE/failure-preview",
        json={"failed_vehicle_id": failed_vehicle_id, "current_time_min": 600},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["feasible"] is True
    assert set(body["failed_order_ids"]) == set(departed["orders"])
    assert {item["vehicle_id"] for item in body["candidates"]} == {
        "V-CHILL-2", "V-CHILL-3"
    }
    candidate = body["selected_candidate"]
    assert candidate["kind"] == "replacement_vehicle"
    assert candidate["recovery_mode"] == "replacement_delivery"
    assert candidate["transfer_facility_id"] is None
    assert candidate["on_time"] is True
    assert candidate["route_geojson"]["geometry"]["type"] == "LineString"


def test_accepting_failure_freezes_old_orders_and_delivers_replacements_only():
    departed, failed_vehicle_id = _departed()
    preview = client.post(
        "/api/dispatch/runs/PLAN-FAILURE/failure-preview",
        json={"failed_vehicle_id": failed_vehicle_id, "current_time_min": 600},
    ).json()
    replacement_vehicle_id = preview["selected_candidate"]["vehicle_id"]

    accepted = client.post(
        "/api/dispatch/runs/PLAN-FAILURE/failure-accept",
        json={
            "failed_vehicle_id": failed_vehicle_id,
            "replacement_vehicle_id": replacement_vehicle_id,
            "current_time_min": 600,
            "command_id": "accept-failure-1",
        },
    )

    assert accepted.status_code == 200
    body = accepted.json()
    failed_ids = set(preview["failed_order_ids"])
    replacement_ids = set(preview["replacement_order_ids"])
    assert body["vehicles"][failed_vehicle_id]["status"] == "failed"
    assert body["vehicles"][failed_vehicle_id]["remaining_order_ids"] == []
    assert all(body["orders"][order_id]["status"] == "failed" for order_id in failed_ids)
    assert all(body["orders"][order_id]["status"] == "in_transit" for order_id in replacement_ids)
    assert all(body["orders"][order_id]["replaces_order_id"] in failed_ids
               for order_id in replacement_ids)
    assert body["route_view"]["metrics"]["orders_failed"] == 2
    assert next(route for route in body["route_view"]["routes"]
                if route["vehicle_id"] == failed_vehicle_id)["status"] == "failed"
    assert body["mechanical_failures"][-1]["transfer_facility_id"] is None

    duplicate = client.post(
        "/api/dispatch/runs/PLAN-FAILURE/failure-accept",
        json={
            "failed_vehicle_id": failed_vehicle_id,
            "replacement_vehicle_id": replacement_vehicle_id,
            "current_time_min": 600,
            "command_id": "accept-failure-1",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["version"] == body["version"]

    for number, order_id in enumerate(sorted(replacement_ids), 1):
        delivered = client.post(
            "/api/dispatch/runs/PLAN-FAILURE/deliver-next",
            json={"vehicle_id": replacement_vehicle_id, "command_id": f"deliver-{number}"},
        )
        assert delivered.status_code == 200
    final = client.get("/api/dispatch/runs/PLAN-FAILURE").json()
    assert all(final["orders"][order_id]["status"] == "delivered"
               for order_id in replacement_ids)
    assert all(final["orders"][order_id]["status"] == "failed" for order_id in failed_ids)


def test_failure_preview_refuses_to_invent_replacement_stock():
    _, failed_vehicle_id = _departed(stock=50)

    response = client.post(
        "/api/dispatch/runs/PLAN-FAILURE/failure-preview",
        json={"failed_vehicle_id": failed_vehicle_id, "current_time_min": 600},
    )

    assert response.status_code == 200
    assert response.json() == {
        "failed_vehicle_id": failed_vehicle_id,
        "failed_order_ids": ["DO-NUH", "DO-CGH"],
        "replacement_order_ids": [
            f"FR-{failed_vehicle_id}-DO-NUH", f"FR-{failed_vehicle_id}-DO-CGH",
        ],
        "recovery_mode": "replacement_delivery",
        "transfer_facility_id": None,
        "feasible": False,
        "reason": "insufficient_replacement_inventory",
        "candidates": [],
    }


def test_failure_preview_refuses_when_no_spare_vehicle_exists():
    _, failed_vehicle_id = _departed(spares=1)

    response = client.post(
        "/api/dispatch/runs/PLAN-FAILURE/failure-preview",
        json={"failed_vehicle_id": failed_vehicle_id, "current_time_min": 600},
    )

    assert response.status_code == 200
    assert response.json()["feasible"] is False
    assert response.json()["reason"] == "no_compatible_spare_vehicle"
