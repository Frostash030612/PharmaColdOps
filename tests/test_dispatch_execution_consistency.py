"""Cross-flow acceptance: physical starts, emergencies and overnight succession."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.dispatch_state import PlannedStop
from optimisation.singapore_loader import read_network
from optimisation.tracking import make_clock

client = TestClient(app)
NETWORK = read_network()
NODE = {n["facility_id"]: n["node_id"] for n in NETWORK["nodes"]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def batch(dispatch_id="PLAN-CONSISTENCY", *, origin="W-WESTGATE", start=None, paired=False,
          algorithm="greedy", spares=1):
    return {"dispatch_id": dispatch_id, "command_id": "create-" + dispatch_id,
        "algorithm": algorithm, "constraints": {
            "routing_model": "pickup_delivery" if paired else "grouped",
            "mileage_limit_m": 150000, "max_vehicles": spares, "max_stops_per_vehicle": 6,
            "terminal_facility_ids": ["D-HOUGANG", "D-NORTHPOINT"]},
        "orders": [{"order_id": "O-CGH", "product_id": "vaccine_2_8",
            "origin_facility_id": origin, "destination_facility_id": "H-CGH", "quantity": 20,
            "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"},
            {"order_id": "O-NUH", "product_id": "vaccine_2_8",
            "origin_facility_id": origin, "destination_facility_id": "H-NUH", "quantity": 20,
            "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}],
        "inventory": [{"lot_id": "LOT-DAILY", "product_id": "vaccine_2_8", "facility_id": origin,
                       "available_quantity": 120, "temperature_zone": "chilled"}],
        "vehicles": [{"vehicle_id": f"V-{i}", "capacity": 100, "temperature_zone": "chilled",
            "start_facility_id": start or origin,
            "onboard_spare": [{"product_id": "vaccine_2_8", "temperature_zone": "chilled", "quantity": 20}]}
            for i in range(1, spares + 1)]}


def create(payload):
    result = client.post("/api/dispatch/runs", json=payload)
    assert result.status_code == 200, result.text
    return result.json()


def position_time(dispatch_id, minute):
    context = service.load_context(service.DISPATCH_DATABASE_URL, dispatch_id)
    context["clock"] = make_clock(minute, 0, depart_min=540)
    service.update_context(service.DISPATCH_DATABASE_URL, dispatch_id, context)


def depart(dispatch_id):
    result = client.post(f"/api/dispatch/runs/{dispatch_id}/depart", json={"command_id": "go", "speed": 0})
    assert result.status_code == 200
    return result.json()


@pytest.mark.parametrize("paired", [False, True])
@pytest.mark.parametrize("algorithm", ["greedy", "ortools"])
def test_actual_start_distance_geometry_and_arrivals_match_the_plan(paired, algorithm):
    body = create(batch(origin="W-WESTGATE" if paired else "D-HOUGANG",
                        start="D-HOUGANG", paired=paired, algorithm=algorithm))
    planned = body["plan"]["zones"][0]["routes"][0]
    live = body["route_view"]["routes"][0]
    assert body["vehicles"]["V-1"]["current_facility_id"] == "D-HOUGANG"
    assert planned["start_node_id"] == live["start_node_id"] == NODE["D-HOUGANG"]
    assert live["total_distance"] == pytest.approx(planned["total_distance"], abs=.01)
    assert body["plan"]["zones"][0]["geojson"]["features"][0]["properties"]["node_order"][0] == NODE["D-HOUGANG"]
    departed = depart(body["dispatch_id"])
    track = departed["route_view"]["routes"][0]["track"]
    for stop, eta in zip(planned["stops"], track["arrivals"]):
        assert stop["service_start"] == pytest.approx(eta, abs=.01)


def test_repositioning_to_a_source_is_priced_and_driven_before_deliveries():
    body = create(batch(origin="W-WESTGATE", start="D-NORTHPOINT"))
    preview = body["plan"]["zones"][0]["routes"][0]
    live = body["route_view"]["routes"][0]
    assert preview["stops"][0]["kind"] == live["stops"][0]["kind"] == "pickup"
    assert live["legs"][0]["from"] == NODE["D-NORTHPOINT"]
    assert live["legs"][0]["to"] == NODE["W-WESTGATE"]
    assert live["total_distance"] == pytest.approx(preview["total_distance"], abs=.01)


def test_failure_uses_the_preview_queue_and_a_new_departure_timeline():
    dispatch_id = "PLAN-FAILURE-CHECK"
    create(batch(dispatch_id, spares=2))
    depart(dispatch_id)
    position_time(dispatch_id, 600)
    old = service.load_run(service.DISPATCH_DATABASE_URL, dispatch_id)
    failed_id = next(iter(old.vehicles))
    failed = replace(old.vehicles[failed_id], remaining_order_ids=("O-CGH", "O-NUH"),
        schedule_start_min=600, schedule_stops=(PlannedStop("delivery", "O-CGH"), PlannedStop("delivery", "O-NUH")))
    changed = replace(old, version=old.version + 1, vehicles={failed_id: failed})
    service.update_run(service.DISPATCH_DATABASE_URL, dispatch_id, changed, expected_version=old.version)
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/failure-preview", json={
        "failed_vehicle_id": failed_id, "current_time_min": 600}).json()
    candidate = preview["selected_candidate"]
    accepted = client.post(f"/api/dispatch/runs/{dispatch_id}/failure-accept", json={
        "failed_vehicle_id": failed_id, "replacement_vehicle_id": candidate["vehicle_id"],
        "current_time_min": 600, "command_id": "accept-failure"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["vehicles"][candidate["vehicle_id"]]["remaining_order_ids"] == candidate["replacement_order_ids"]
    ticked = service.tick_dispatch(dispatch_id)
    assert all(ticked["orders"][oid]["status"] == "in_transit" for oid in candidate["replacement_order_ids"])
    failed_view = next(route for route in ticked["route_view"]["routes"] if route["vehicle_id"] == failed_id)
    frozen_position = failed_view["track"]["position"]
    assert failed_view["stops"] == []
    position_time(dispatch_id, 900)
    final = service.tick_dispatch(dispatch_id)
    assert next(route for route in final["route_view"]["routes"] if route["vehicle_id"] == failed_id)["track"]["position"] == frozen_position
    assert final["vehicles"][candidate["vehicle_id"]]["delivered_order_ids"] == candidate["replacement_order_ids"]
    assert all(final["orders"][oid]["status"] == "failed" for oid in preview["failed_order_ids"])


def test_emergency_honours_mileage_terminal_and_stop_limits():
    dispatch_id = "PLAN-CONSTRAINT-CHECK"
    create(batch(dispatch_id))
    depart(dispatch_id)
    context = service.load_context(service.DISPATCH_DATABASE_URL, dispatch_id)
    context["input"]["constraints"]["mileage_limit_m"] = 1000
    context["input"]["constraints"]["max_stops_per_vehicle"] = 1
    service.update_context(service.DISPATCH_DATABASE_URL, dispatch_id, context)
    order = {"order_id": "URG-1", "product_id": "vaccine_2_8", "destination_facility_id": "H-SKH",
             "quantity": 10, "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-preview",
                          json={"order": order, "current_time_min": 545}).json()
    assert preview["feasible"] is False
    assert preview["candidates"]
    for candidate in preview["candidates"]:
        assert candidate["node_sequence"][-1] in {NODE["D-HOUGANG"], NODE["D-NORTHPOINT"]}
        assert "mileage_limit_exceeded" in {r["code"] for r in candidate["blocked_by"]}
    chosen = preview["candidates"][0]
    accepted = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-accept", json={
        "order": order, "current_time_min": 545, "candidate_kind": chosen["kind"],
        "vehicle_id": chosen["vehicle_id"], "command_id": "bad-emergency"})
    assert accepted.status_code == 409


@pytest.mark.parametrize("paired", [False, True])
def test_overnight_confirmation_parking_and_next_day_form_one_idempotent_chain(paired):
    dispatch_id = "PLAN-OVERNIGHT-CHECK"
    create(batch(dispatch_id, paired=paired))
    depart(dispatch_id)
    # No parking confirmation while the deliveries or closing drive are ahead.
    assert client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-preview", json={}).status_code == 409
    position_time(dispatch_id, 1000)
    completed = service.tick_dispatch(dispatch_id)
    assert completed["status"] == "completed"
    assert completed["route_view"]["metrics"]["still_returning"] == 0
    request = {"parking_overrides": {"V-1": "D-NORTHPOINT"}}
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-preview", json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["feasible"], preview.json()
    request.update({"expected_version": preview.json()["state_version"], "command_id": "park-day"})
    accepted = client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-accept", json=request)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["overnight"]["status"] == "repositioning"
    duplicate = client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-accept", json=request)
    assert duplicate.json()["version"] == accepted.json()["version"]
    next_request = {"dispatch_id": "PLAN-NEXT-DAY", "command_id": "next-day",
                    "expected_version": accepted.json()["version"], "speed": 0}
    assert client.post(f"/api/dispatch/runs/{dispatch_id}/next-day", json=next_request).status_code == 409
    position_time(dispatch_id, 1070)
    parked = service.tick_dispatch(dispatch_id)
    assert parked["overnight"]["status"] == "parked"
    assert parked["vehicles"]["V-1"]["current_facility_id"] == "D-NORTHPOINT"
    assert parked["route_view"]["routes"][0]["distance_driven_m"] > completed["route_view"]["routes"][0]["distance_driven_m"]
    next_request["expected_version"] = parked["version"]
    tomorrow = client.post(f"/api/dispatch/runs/{dispatch_id}/next-day", json=next_request)
    assert tomorrow.status_code == 200, tomorrow.text
    body = tomorrow.json()
    assert body["previous_dispatch_id"] == dispatch_id
    assert body["operating_date"] == preview.json()["next_operating_date"]
    assert body["vehicles"]["V-1"]["start_facility_id"] == "D-NORTHPOINT"
    assert body["vehicles"]["V-1"]["distance_before_schedule_m"] == 0
    assert body["vehicles"]["V-1"]["onboard_spare"] == parked["vehicles"]["V-1"]["onboard_spare"]
    assert body["input"]["inventory"][0]["available_quantity"] == completed["available_by_lot"]["LOT-DAILY"]
    assert body["route_view"]["routes"][0]["legs"][0]["from"] == NODE["D-NORTHPOINT"]
    assert client.post(f"/api/dispatch/runs/{dispatch_id}/next-day", json=next_request).json()["dispatch_id"] == body["dispatch_id"]
    assert service.get_dispatch(dispatch_id)["available_by_lot"] == completed["available_by_lot"]


def test_stale_parking_preview_and_unknown_override_do_not_write_state():
    dispatch_id = "PLAN-PARKING-REFUSALS"
    create(batch(dispatch_id))
    depart(dispatch_id)
    position_time(dispatch_id, 1000)
    completed = service.tick_dispatch(dispatch_id)
    assert client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-preview", json={
        "parking_overrides": {"V-1": "D-NOT-A-NODE"}}).status_code == 409
    refused = client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-accept", json={
        "expected_version": completed["version"] - 1, "command_id": "stale-park"})
    assert refused.status_code == 409
    assert "overnight" not in service.get_dispatch(dispatch_id)


def test_mid_leg_emergency_preserves_the_marker_and_accumulated_mileage():
    dispatch_id = "PLAN-MID-LEG"
    create(batch(dispatch_id))
    depart(dispatch_id)
    position_time(dispatch_id, 560)
    before = service.get_dispatch(dispatch_id)["route_view"]["routes"][0]
    assert 0 < before["track"]["leg_fraction"] < 1
    order = {"order_id": "URG-MID", "product_id": "vaccine_2_8", "destination_facility_id": "H-SKH",
             "quantity": 10, "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-preview",
                          json={"order": order, "current_time_min": 560}).json()
    candidate = next(c for c in preview["candidates"] if c["kind"] == "add_stop_in_transit")
    accepted = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-accept", json={
        "order": order, "current_time_min": 560, "candidate_kind": candidate["kind"],
        "vehicle_id": candidate["vehicle_id"], "command_id": "mid-leg"})
    assert accepted.status_code == 200, accepted.text
    after = accepted.json()["route_view"]["routes"][0]
    assert after["track"]["position"] == pytest.approx(before["track"]["position"], abs=1e-8)
    assert after["distance_driven_m"] == pytest.approx(before["distance_driven_m"], abs=3)
    assert after["total_distance"] * 1000 == pytest.approx(candidate["projected_daily_distance_m"], abs=10)
    assert service.tick_dispatch(dispatch_id)["route_view"]["metrics"]["orders_delivered"] == 0


def test_onboard_stock_does_not_require_an_available_warehouse_lot():
    dispatch_id = "PLAN-ONBOARD-ONLY"
    payload = batch(dispatch_id)
    payload["inventory"][0]["available_quantity"] = 40
    create(payload)
    depart(dispatch_id)
    order = {"order_id": "URG-ONBOARD", "product_id": "vaccine_2_8", "destination_facility_id": "H-SKH",
             "quantity": 10, "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-preview",
                          json={"order": order, "current_time_min": 545}).json()
    assert preview["feasible"] is True
    assert {c["kind"] for c in preview["candidates"]} == {"add_stop_in_transit"}


def test_next_day_needs_real_remaining_stock_or_an_explicit_replenishment():
    dispatch_id = "PLAN-RESTOCK"
    payload = batch(dispatch_id)
    payload["inventory"][0]["available_quantity"] = 40
    create(payload)
    depart(dispatch_id)
    position_time(dispatch_id, 1000)
    completed = service.tick_dispatch(dispatch_id)
    assert completed["available_by_lot"]["LOT-DAILY"] == 0
    assert client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-preview", json={}).status_code == 409
    restock = {"lot_id": "NEXT-SUPPLY", "product_id": "vaccine_2_8", "facility_id": "W-WESTGATE",
               "available_quantity": 40, "temperature_zone": "chilled"}
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/overnight-preview", json={"replenishments": [restock]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["replenishments"] == [{**restock, "status": "available"}]
    assert preview.json()["tomorrow"]["inventory"][0]["available_quantity"] == 0
    assert service.get_dispatch(dispatch_id)["available_by_lot"]["LOT-DAILY"] == 0


def test_reshipment_uses_the_operation_clock_not_the_archive_wall_clock():
    dispatch_id = "PLAN-TIMED-CASE"
    create(batch(dispatch_id))
    depart(dispatch_id)
    position_time(dispatch_id, 600)
    record = {"run_id": "CASE-WALL-CLOCK", "created_at": "2026-10-01T23:59:00",
              "reshipment_required": True, "event": {"product_id": "vaccine_2_8",
              "destination_facility_id": "H-SKH"}}
    preview = service.reshipment_branch_plan(record)
    assert preview["scheduled_next_day"] is False
    assert preview["current_time_min"] == 600
    assert preview["candidates"]
    assert all(c["schedule_start_min"] >= 600 for c in preview["candidates"])


def test_an_older_emergency_timestamp_cannot_restart_the_vehicle_in_the_past():
    dispatch_id = "PLAN-TIMESTAMP-FLOOR"
    create(batch(dispatch_id))
    depart(dispatch_id)
    position_time(dispatch_id, 560)
    order = {"order_id": "URG-OLDER", "product_id": "vaccine_2_8", "destination_facility_id": "H-SKH",
             "quantity": 10, "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-preview",
                          json={"order": order, "current_time_min": 545}).json()
    assert preview["current_time_min"] >= 560
    assert all(c["schedule_start_min"] >= 560 for c in preview["candidates"])


@pytest.mark.parametrize("algorithm", ["greedy", "ortools"])
def test_a_parked_truck_can_help_when_the_local_truck_cannot_carry_the_fixed_batch(algorithm):
    payload = batch("PLAN-MIXED-STARTS", algorithm=algorithm, spares=2)
    for order in payload["orders"]:
        order["quantity"] = 50
    payload["vehicles"][1]["start_facility_id"] = "D-HOUGANG"
    created = create(payload)
    assert set(created["vehicles"]) == {"V-1", "V-2"}
    assert created["vehicles"]["V-2"]["start_facility_id"] == "D-HOUGANG"
    routes = created["route_view"]["routes"]
    assert next(r for r in routes if r["vehicle_id"] == "V-2")["stops"][0]["kind"] == "pickup"


def test_emergency_keeps_the_source_pickup_of_the_next_day_fixed_orders():
    dispatch_id = "PLAN-KEEP-PICKUP"
    create(batch(dispatch_id, start="D-NORTHPOINT"))
    depart(dispatch_id)
    position_time(dispatch_id, 545)
    order = {"order_id": "URG-PRE-PICKUP", "product_id": "vaccine_2_8", "destination_facility_id": "H-SKH",
             "quantity": 10, "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}
    preview = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-preview",
                          json={"order": order, "current_time_min": 545}).json()
    candidate = next(c for c in preview["candidates"] if c["kind"] == "add_stop_in_transit")
    assert candidate["schedule_stops"][0]["kind"] == "pickup"
    assert candidate["schedule_stops"][0]["facility_id"] == "W-WESTGATE"
    assert candidate["schedule_stops"][0]["service_min"] == 15
    accepted = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-accept", json={
        "order": order, "current_time_min": 545, "candidate_kind": "add_stop_in_transit",
        "vehicle_id": "V-1", "command_id": "before-pickup"})
    assert accepted.status_code == 200, accepted.text
    route = accepted.json()["route_view"]["routes"][0]
    assert route["stops"][0]["kind"] == "pickup"
    position_time(dispatch_id, route["track"]["service_starts"][0] + 5)
    assert service.tick_dispatch(dispatch_id)["route_view"]["metrics"]["orders_delivered"] == 0


def test_an_early_urgent_plan_starts_the_clock_before_its_new_departure():
    dispatch_id = "PLAN-EARLY-URGENT"
    create(batch(dispatch_id))
    order = {"order_id": "URG-EARLY", "product_id": "vaccine_2_8", "destination_facility_id": "H-SKH",
             "quantity": 10, "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}
    accepted = client.post(f"/api/dispatch/runs/{dispatch_id}/emergency-accept", json={
        "order": order, "current_time_min": 520, "candidate_kind": "load_before_departure",
        "vehicle_id": "V-1", "command_id": "early-plan"})
    assert accepted.status_code == 200, accepted.text
    started = depart(dispatch_id)
    assert started["clock"]["sim_start_min"] == 520
    assert started["route_view"]["routes"][0]["track"]["leg_fraction"] == 0
    assert service.tick_dispatch(dispatch_id)["route_view"]["metrics"]["orders_delivered"] == 0
