from fastapi.testclient import TestClient
import pytest

from api import service
from api.main import app
from optimisation.dispatch_planner import DISPATCH_ORIGIN
from optimisation.singapore_loader import read_network


def _node_id(facility_id: str) -> int:
    """Resolve a facility to its network node id (order changes with the network)."""
    return next(n["node_id"] for n in read_network()["nodes"] if n["facility_id"] == facility_id)


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
             "facility_id": DISPATCH_ORIGIN, "available_quantity": 50,
             "temperature_zone": "chilled"},
        ],
        "vehicles": [
            {"vehicle_id": "V-CHILL-1", "capacity": 100,
             "temperature_zone": "chilled", "start_facility_id": DISPATCH_ORIGIN},
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
    assert set(zone["routes"][0]["customer_ids"]) == {_node_id("H-NUH"), _node_id("H-CGH")}
    assert len(zone["geojson"]["features"]) == 1


def test_dispatch_endpoint_rejects_invalid_hard_limits():
    request = payload()
    request["constraints"] = {"max_vehicles": 0, "max_stops_per_vehicle": 4}

    response = client.post("/api/dispatch/plan", json=request)

    assert response.status_code == 422


def test_created_operation_cannot_reintroduce_vehicles_above_fleet_limit():
    request = payload()
    request["vehicles"].extend([
        {**request["vehicles"][0], "vehicle_id": "V-CHILL-2"},
        {**request["vehicles"][0], "vehicle_id": "V-CHILL-3"},
    ])
    request.update(
        constraints={"max_vehicles": 1, "max_stops_per_vehicle": 4},
        dispatch_id="DSP-FLEET-LIMIT", command_id="create-fleet-limit",
    )

    response = client.post("/api/dispatch/runs", json=request)

    assert response.status_code == 200
    assert set(response.json()["vehicles"]) == {"V-CHILL-1"}
    assert len(response.json()["input"]["vehicles"]) == 1


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
    # The persisted operation must survive a reload untouched. `route_view` is
    # deliberately excluded: once a run has departed it carries the simulated
    # clock's position, which moves between two calls by design.
    persistent = lambda body: {k: v for k, v in body.items() if k != "route_view"}
    assert persistent(restored.json()) == persistent(delivered.json())


def test_recent_runs_are_listed_newest_first_with_their_status():
    request = payload()
    request.update(dispatch_id="DSP-OLD", command_id="create-old")
    assert client.post("/api/dispatch/runs", json=request).status_code == 200
    request.update(dispatch_id="DSP-NEW", command_id="create-new")
    assert client.post("/api/dispatch/runs", json=request).status_code == 200

    runs = client.get("/api/dispatch/runs?limit=5").json()["runs"]

    assert [run["dispatch_id"] for run in runs][:2] == ["DSP-NEW", "DSP-OLD"]
    assert {run["status"] for run in runs} == {"accepted"}


def test_replaying_a_run_restarts_the_same_batch_as_a_new_operation():
    """A finished demo could not be watched again: nothing was open, so the panel
    silently fell back to the demo plan. Replay re-plans the SAME stored batch."""
    request = payload()
    request.update(dispatch_id="DSP-REPLAY", command_id="create-replay")
    created = client.post("/api/dispatch/runs", json=request).json()

    replayed = client.post("/api/dispatch/runs/DSP-REPLAY/replay",
                           json={"speed": 300.0})

    assert replayed.status_code == 200
    body = replayed.json()
    assert body["replayed_from"] == "DSP-REPLAY"
    assert body["dispatch_id"] != "DSP-REPLAY"          # history is not overwritten
    assert body["status"] == "in_transit"               # …and it is already rolling
    assert body["clock"]["speed"] == 300.0
    assert set(body["orders"]) == set(created["orders"])
    assert client.get("/api/dispatch/runs?limit=5").json()["runs"][0]["dispatch_id"] \
        == body["dispatch_id"]


def test_replaying_an_unknown_run_is_refused():
    assert client.post("/api/dispatch/runs/DSP-NOPE/replay", json={}).status_code == 404


def test_emergency_preview_compares_spare_vehicle_and_return_to_depot():
    request = payload()
    request.update(dispatch_id="DSP-EMERGENCY", command_id="accept-emergency")
    request["inventory"][0]["available_quantity"] = 80
    request["vehicles"].append({
        "vehicle_id": "V-CHILL-2", "capacity": 100,
        "temperature_zone": "chilled", "start_facility_id": DISPATCH_ORIGIN,
    })
    request["vehicles"].append({
        "vehicle_id": "V-CHILL-3", "capacity": 100,
        "temperature_zone": "chilled", "start_facility_id": DISPATCH_ORIGIN,
    })
    assert client.post("/api/dispatch/runs", json=request).status_code == 200
    assert client.post(
        "/api/dispatch/runs/DSP-EMERGENCY/depart", json={"command_id": "depart-emergency"}
    ).status_code == 200
    response = client.post("/api/dispatch/runs/DSP-EMERGENCY/emergency-preview", json={
        "current_time_min": 600,
        "order": {
            "order_id": "DO-URGENT", "product_id": "vaccine_2_8",
            "destination_facility_id": "H-KKH", "quantity": 20,
            "earliest_min": 600, "latest_min": 700, "temperature_zone": "chilled",
        },
    })
    assert response.status_code == 200
    body = response.json()
    assert body["feasible"] is True
    assert body["selected_candidate"]["kind"] == "spare_vehicle"
    assert {item["kind"] for item in body["candidates"]} == {
        "spare_vehicle", "return_to_depot"
    }
    accepted = client.post("/api/dispatch/runs/DSP-EMERGENCY/emergency-accept", json={
        "current_time_min": 600,
        "candidate_kind": body["selected_candidate"]["kind"],
        "vehicle_id": body["selected_candidate"]["vehicle_id"],
        "command_id": "accept-urgent",
        "order": {
            "order_id": "DO-URGENT", "product_id": "vaccine_2_8",
            "destination_facility_id": "H-KKH", "quantity": 20,
            "earliest_min": 600, "latest_min": 700, "temperature_zone": "chilled",
        },
    })
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    assert accepted_body["available_by_lot"] == {"LOT-1": 10}
    assert accepted_body["orders"]["DO-URGENT"]["status"] == "in_transit"
    assert accepted_body["vehicles"][body["selected_candidate"]["vehicle_id"]][
        "remaining_order_ids"
    ] == ["DO-URGENT"]
