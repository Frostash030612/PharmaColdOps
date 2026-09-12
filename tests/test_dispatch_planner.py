from fastapi.testclient import TestClient
import pytest

from api import service
from api.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def payload():
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
            {"lot_id": "LOT-1", "product_id": "vaccine_2_8",
             "facility_id": "W-KN-PIONEER", "available_quantity": 50,
             "temperature_zone": "chilled"},
        ],
        "vehicles": [
            {"vehicle_id": "V-CHILL-1", "capacity": 100,
             "temperature_zone": "chilled", "start_facility_id": "W-KN-PIONEER"},
        ],
        "algorithm": "greedy",
    }


def test_dispatch_endpoint_routes_only_order_destinations():
    response = client.post("/api/dispatch/plan", json=payload())
    assert response.status_code == 200
    body = response.json()
    assert body["preview"] is True
    assert body["order_count"] == 2
    zone = body["zones"][0]
    assert zone["target_facilities"] == 2
    assert zone["served_facilities"] == 2
    assert set(zone["routes"][0]["order_ids"]) == {"DO-NUH", "DO-CGH"}
    assert set(zone["routes"][0]["customer_ids"]) == {2, 5}
    assert len(zone["geojson"]["features"]) == 1


def test_dispatch_endpoint_rejects_quarantined_or_insufficient_stock():
    request = payload()
    request["inventory"][0]["status"] = "quarantine"
    response = client.post("/api/dispatch/plan", json=request)
    assert response.status_code == 422
    assert "insufficient available inventory" in response.json()["detail"]


def test_dispatch_endpoint_rejects_unknown_destination():
    request = payload()
    request["orders"][0]["destination_facility_id"] = "H-NOT-REAL"
    response = client.post("/api/dispatch/plan", json=request)
    assert response.status_code == 422
    assert "unknown Singapore destination" in response.json()["detail"]


def test_dispatch_endpoint_rejects_order_outside_facility_hours():
    request = payload()
    request["orders"][0].update(earliest_min=0, latest_min=10)
    response = client.post("/api/dispatch/plan", json=request)
    assert response.status_code == 422
    assert "does not overlap facility hours" in response.json()["detail"]


def test_dispatch_endpoint_does_not_use_inventory_at_another_facility():
    request = payload()
    request["inventory"][0]["facility_id"] = "H-NUH"
    response = client.post("/api/dispatch/plan", json=request)
    assert response.status_code == 422
    assert "insufficient available inventory" in response.json()["detail"]


def test_dispatch_run_persists_and_advances_idempotently():
    request = {**payload(), "dispatch_id": "DSP-1", "command_id": "accept-1"}
    created = client.post("/api/dispatch/runs", json=request)
    assert created.status_code == 200
    assert created.json()["status"] == "accepted"
    assert created.json()["available_by_lot"] == {"LOT-1": 0}
    assert created.json()["plan"]["zones"][0]["target_facilities"] == 2
    assert created.json()["plan"]["zones"][0]["geojson"]["features"]

    departed = client.post("/api/dispatch/runs/DSP-1/depart", json={"command_id": "depart-1"})
    assert departed.status_code == 200
    assert departed.json()["status"] == "in_transit"
    duplicate = client.post("/api/dispatch/runs/DSP-1/depart", json={"command_id": "depart-1"})
    assert duplicate.json()["version"] == departed.json()["version"]

    delivered = client.post("/api/dispatch/runs/DSP-1/deliver-next", json={
        "command_id": "deliver-1", "vehicle_id": "V-CHILL-1",
    })
    assert delivered.status_code == 200
    assert sum(o["status"] == "delivered" for o in delivered.json()["orders"].values()) == 1
    restored = client.get("/api/dispatch/runs/DSP-1")
    assert restored.json() == delivered.json()
