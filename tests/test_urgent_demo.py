"""Independent route-demo urgent requests, without business quantity inputs."""
import copy

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.dispatch_repository import load_context, load_run, update_context
from optimisation.parking_policy import warehouse_ids
from optimisation.singapore_loader import read_network

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")


def create(*, stop_limit=4, terminal="D-NORTHPOINT", paired=False):
    payload = {"dispatch_id": "PLAN-URGENT", "command_id": "create", "algorithm": "greedy",
        "constraints": {"max_vehicles": 2, "max_stops_per_vehicle": stop_limit,
                        "terminal_facility_ids": [terminal], "routing_model": "pickup_delivery" if paired else "grouped"},
        "orders": [{"order_id": "BASE", "product_id": "vaccine_2_8", "origin_facility_id": "W-WESTGATE",
                    "destination_facility_id": "H-SGH", "quantity": 30, "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}],
        "inventory": [{"lot_id": "L-BASE", "product_id": "vaccine_2_8", "facility_id": "W-WESTGATE", "available_quantity": 30, "temperature_zone": "chilled"}],
        "vehicles": [{"vehicle_id": f"V-{index}", "capacity": 30, "temperature_zone": "chilled", "start_facility_id": "W-WESTGATE"} for index in (1, 2)]}
    result = client.post("/api/dispatch/runs", json=payload)
    assert result.status_code == 200, result.text
    return result.json()


def payload(**overrides):
    return {"request_id": "urgent-1", "product_id": "vaccine_2_8", "origin_facility_id": "W-WESTGATE",
            "destination_facility_id": "H-NUH", "latest_min": 1020, **overrides}


def preview(body=None):
    return client.post("/api/dispatch/runs/PLAN-URGENT/urgent-preview", json=body or payload())


def accept(body, response, candidate=None):
    candidate = candidate or next(c for c in response["candidates"] if c["feasible"])
    return {**body, "expected_version": response["state_version"], "command_id": "accept-urgent-1",
            "candidate_kind": candidate["kind"], "vehicle_id": candidate["vehicle_id"]}


def test_options_expose_five_parking_warehouses_and_no_stock_balances():
    options = client.get("/api/dispatch/urgent-options").json()
    assert len(options["warehouses"]) == 5
    assert len(options["destinations"]) == 14
    assert all("quantity" not in w and "available_quantity" not in w for w in options["warehouses"])
    assert next(w for w in options["warehouses"] if w["facility_id"] == "W-KN-PIONEER")["product_ids"] == []


def test_preview_with_full_vehicle_and_zero_warehouse_balance_is_read_only_and_nominal():
    created = create()
    assert created["available_by_lot"]["L-BASE"] == 0
    before_context = copy.deepcopy(load_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT"))
    before_state = load_run(service.DISPATCH_DATABASE_URL, "PLAN-URGENT")
    response = preview()
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["resource_mode"] == "demo_nominal"
    assert any(c["kind"] == "load_before_departure" and c["feasible"] for c in result["candidates"])
    assert all(c["end_node_id"] == 16 for c in result["candidates"])  # selected Northpoint only
    assert load_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT") == before_context
    assert load_run(service.DISPATCH_DATABASE_URL, "PLAN-URGENT") == before_state


def test_accept_is_atomic_idempotent_and_not_a_temperature_case():
    create()
    body = payload()
    response = preview(body).json()
    candidate = next(c for c in response["candidates"] if c["kind"] == "load_before_departure")
    command = accept(body, response, candidate)
    first = client.post("/api/dispatch/runs/PLAN-URGENT/urgent-accept", json=command)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["orders"]["URG-urgent-1"]["quantity"] == 1
    assert result["available_by_lot"]["L-BASE"] == 0
    assert len(result["orders"]) == 2
    assert result["input"]["orders"][-1]["origin_facility_id"] == "W-WESTGATE"
    repeated = client.post("/api/dispatch/runs/PLAN-URGENT/urgent-accept", json=command)
    assert repeated.status_code == 200 and repeated.json()["urgent_result"]["already_committed"]
    assert len(repeated.json()["orders"]) == 2
    assert not service.RUNS_FILE.exists()
    changed = {**command, "destination_facility_id": "H-CGH"}
    assert client.post("/api/dispatch/runs/PLAN-URGENT/urgent-accept", json=changed).status_code == 409
    assert preview(body).json()["already_committed"] is True


def test_selected_pickup_is_respected_not_replaced_by_a_nearer_warehouse():
    create()
    response = preview(payload(origin_facility_id="D-NORTHPOINT"))
    assert response.status_code == 200, response.text
    candidates = response.json()["candidates"]
    assert candidates
    assert all(c["pickup_facility_id"] == "D-NORTHPOINT" for c in candidates)


def test_urgent_delivers_on_the_same_execution_clock_and_is_not_copied_to_tomorrow():
    create()
    proposed = preview().json()
    assigned = next(c for c in proposed["candidates"] if c["kind"] == "load_before_departure")
    command = accept(payload(), proposed, assigned)
    result = client.post("/api/dispatch/runs/PLAN-URGENT/urgent-accept", json=command)
    assert result.status_code == 200, result.text
    service.depart_dispatch("PLAN-URGENT", "depart", speed=0)
    service.deliver_dispatch("PLAN-URGENT", command["vehicle_id"], "deliver-urgent")
    delivered = service.deliver_dispatch("PLAN-URGENT", command["vehicle_id"], "deliver-base")
    assert delivered["orders"]["URG-urgent-1"]["status"] == "delivered"
    assert delivered["orders"]["BASE"]["status"] == "delivered"
    context = load_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT")
    context.pop("fixed_daily_input")  # compatibility with older stored runs
    context["clock"] = service.make_clock(960, 0)
    update_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT", context)
    service.tick_dispatch("PLAN-URGENT")
    response = client.post("/api/dispatch/runs/PLAN-URGENT/overnight-preview", json={"demo_replenish": True})
    assert response.status_code == 200, response.text[:200]
    assert [o["order_id"] for o in response.json()["tomorrow"]["orders"]] == ["BASE"]


def test_nominal_urgent_quantity_remains_nominal_in_case_links_and_replacements():
    create()
    proposed = preview().json()
    assigned = next(c for c in proposed["candidates"] if c["kind"] == "load_before_departure")
    command = accept(payload(), proposed, assigned)
    assert client.post("/api/dispatch/runs/PLAN-URGENT/urgent-accept", json=command).status_code == 200
    from api.schemas import EventIn
    event, snapshot = service._bind_case_order(EventIn(product_id="vaccine_2_8", excursion_temp_c=20,
        duration_min=90, mkt_c=19, packaging="intact", order_id="URG-urgent-1", dispatch_id="PLAN-URGENT"))
    assert snapshot["quantity_is_nominal"] is True
    record = {"run_id": "NOMINAL-CASE", "event": service._event_dump(event),
              "reshipment_required": True, "created_at": "2026-10-01T09:00:00", "disposition": "scrap"}
    replacement = service.reshipment_branch_plan(record)
    assert any(c["feasible"] and c["kind"] == "load_before_departure" for c in replacement["candidates"])


def test_legacy_hospital_terminal_configuration_is_refused_before_insertion():
    create()
    context = load_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT")
    context["input"]["constraints"]["terminal_facility_ids"] = ["H-SGH"]
    update_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT", context)
    response = preview()
    assert response.status_code == 422 and "warehouses" in response.text


@pytest.mark.parametrize("overrides", [
    {"product_id": "missing"}, {"origin_facility_id": "H-SGH"},
    {"origin_facility_id": "W-KN-PIONEER"}, {"destination_facility_id": "D-BUGIS"},
    {"latest_min": 500}, {"latest_min": 1100}, {"quantity": 99},
])
def test_invalid_requests_do_not_mutate_state(overrides):
    create()
    state = load_run(service.DISPATCH_DATABASE_URL, "PLAN-URGENT")
    response = preview(payload(**overrides))
    assert response.status_code == 422
    assert load_run(service.DISPATCH_DATABASE_URL, "PLAN-URGENT") == state


def test_stale_version_rejected_and_paired_boundary_preserved():
    create()
    request = accept(payload(), preview().json())
    service.depart_dispatch("PLAN-URGENT", "depart", speed=0)
    assert client.post("/api/dispatch/runs/PLAN-URGENT/urgent-accept", json=request).status_code == 409


def test_no_compatible_temperature_does_not_expand_the_fleet():
    create()
    response = preview(payload(product_id="frozen_m20"))
    assert response.status_code == 200
    assert not response.json()["candidates"]


def test_stop_limit_is_still_hard_even_when_quantities_are_abstracted():
    create(stop_limit=1)
    response = preview()
    assert response.status_code == 200
    assigned = [c for c in response.json()["candidates"] if c["kind"] == "load_before_departure"]
    assert assigned and not assigned[0]["feasible"]
    assert any(r["code"] == "stop_limit_exceeded" for r in assigned[0]["blocked_by"])


def test_paired_runs_refuse_insertion_explicitly():
    create(paired=True)
    response = preview()
    assert response.status_code == 422 and "pickup" in response.text.lower()


@pytest.mark.parametrize("model", ["grouped", "pickup_delivery"])
def test_hospitals_cannot_be_declared_as_static_terminals(model):
    create()
    batch = load_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT")["fixed_daily_input"]
    batch["constraints"]["terminal_facility_ids"] = ["H-SGH"]
    batch["constraints"]["routing_model"] = model
    response = client.post("/api/dispatch/plan", json=batch)
    assert response.status_code == 422 and "warehouses" in response.text


def test_demo_next_day_does_not_require_operator_replenishment_quantities():
    created = create()
    service.depart_dispatch("PLAN-URGENT", "depart", speed=0)
    service.deliver_dispatch("PLAN-URGENT", "V-1", "deliver")
    context = load_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT")
    context["clock"] = service.make_clock(960, 0)  # time for idle trucks to reach the selected warehouse before closing
    update_context(service.DISPATCH_DATABASE_URL, "PLAN-URGENT", context)
    completed = service.tick_dispatch("PLAN-URGENT")
    request = {"demo_replenish": True}
    response = client.post("/api/dispatch/runs/PLAN-URGENT/overnight-preview", json=request)
    assert response.status_code == 200 and response.json()["feasible"], response.text
    assert response.json()["tomorrow"]["inventory"][0]["available_quantity"] == 0
    assert response.json()["replenishments"] and "Demo" in response.json()["inventory_note"]
    bad = client.post("/api/dispatch/runs/PLAN-URGENT/overnight-preview", json={
        **request, "parking_overrides": {"V-1": "H-SGH"}})
    assert bad.status_code == 409 and "warehouses" in bad.text
