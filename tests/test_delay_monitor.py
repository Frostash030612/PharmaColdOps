"""Independent delay inspection and auditable remaining-stop re-planning."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.dispatch_planner import DISPATCH_ORIGIN
from optimisation.dispatch_state import PlannedStop
from optimisation.tracking import make_clock
from optimisation.delay_monitor import _best_sequence


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def _payload() -> dict:
    # The first order in the deliberately bad queue is farther away.  At minute
    # 600 it meets its own deadline but pushes the nearer, earlier-deadline order
    # late; reversing them satisfies both windows.
    return {
        "dispatch_id": "PLAN-DELAY",
        "command_id": "create-delay-plan",
        "algorithm": "greedy",
        "orders": [
            {"order_id": "DO-CGH", "product_id": "vaccine_2_8",
             "destination_facility_id": "H-CGH", "quantity": 20,
             "earliest_min": 540, "latest_min": 630, "temperature_zone": "chilled"},
            {"order_id": "DO-NUH", "product_id": "vaccine_2_8",
             "destination_facility_id": "H-NUH", "quantity": 20,
             "earliest_min": 540, "latest_min": 625, "temperature_zone": "chilled"},
        ],
        "inventory": [
            {"lot_id": "LOT-DELAY", "product_id": "vaccine_2_8",
             "facility_id": DISPATCH_ORIGIN, "available_quantity": 50,
             "temperature_zone": "chilled"},
        ],
        "vehicles": [
            {"vehicle_id": "V-DELAY", "capacity": 100,
             "temperature_zone": "chilled", "start_facility_id": DISPATCH_ORIGIN},
        ],
    }


def _departed_with_crossed_queue() -> None:
    assert client.post("/api/dispatch/runs", json=_payload()).status_code == 200
    assert client.post(
        "/api/dispatch/runs/PLAN-DELAY/depart",
        json={"command_id": "depart-delay", "speed": 0},
    ).status_code == 200

    # The independent inspection is at simulated minute 600.  Freeze the
    # operation there so the post-accept tick proves it starts the new tail at
    # that checkpoint instead of immediately replaying the old 09:00 schedule.
    context = service.load_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    context["clock"] = make_clock(600, 0, depart_min=540)
    service.update_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", context)

    # The solver is allowed to select the shorter order itself.  Make the
    # crossed queue explicit so this is a deterministic recovery test, not a
    # test of the initial planning heuristic.
    old = service.load_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    vehicle = old.vehicles["V-DELAY"]
    changed = replace(
        old,
        version=old.version + 1,
        vehicles={**old.vehicles, "V-DELAY": replace(
            vehicle, current_facility_id=DISPATCH_ORIGIN,
            remaining_order_ids=("DO-CGH", "DO-NUH"), status="in_transit",
            schedule_start_min=600, schedule_start_facility_id=DISPATCH_ORIGIN,
            schedule_stops=(PlannedStop("delivery", "DO-CGH"), PlannedStop("delivery", "DO-NUH")),
        )},
    )
    service.update_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", changed,
                       expected_version=old.version)


def test_delay_preview_finds_a_window_miss_and_the_exact_better_queue():
    _departed_with_crossed_queue()

    response = client.post(
        "/api/dispatch/runs/PLAN-DELAY/delay-preview",
        json={"current_time_min": 600, "delay_min": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["inspected_vehicle_count"] == 1
    assert body["predicted_late_order_count"] == 1
    candidate = body["candidates"][0]
    assert candidate["kind"] == "resequence_remaining_stops"
    assert candidate["original_order_ids"] == ["DO-CGH", "DO-NUH"]
    assert candidate["remaining_order_ids_after"] == ["DO-NUH", "DO-CGH"]
    assert candidate["search_method"] == "exact_permutation"
    assert candidate["replan_available"] is True
    assert candidate["baseline"]["predicted_late_order_ids"] == ["DO-NUH"]
    assert candidate["replanned"]["predicted_late_order_ids"] == []
    assert candidate["route_geojson"]["geometry"]["type"] == "LineString"
    assert body["baselines"]["V-DELAY"]["route_geojson"]["geometry"]["type"] == "LineString"


def test_delay_accept_revalidates_persists_and_is_idempotent():
    _departed_with_crossed_queue()
    preview = client.post("/api/dispatch/runs/PLAN-DELAY/delay-preview",
                          json={"current_time_min": 600}).json()
    request = {
        "vehicle_id": "V-DELAY",
        "current_time_min": 600,
        "delay_min": 0,
        "command_id": "accept-delay-replan-1",
        "expected_version": preview["state_version"],
        "remaining_order_ids_after": preview["candidates"][0]["remaining_order_ids_after"],
    }

    accepted = client.post("/api/dispatch/runs/PLAN-DELAY/delay-accept", json=request)

    assert accepted.status_code == 200
    body = accepted.json()
    assert body["vehicles"]["V-DELAY"]["remaining_order_ids"] == ["DO-NUH", "DO-CGH"]
    audit = body["delay_replans"][-1]
    assert audit["original_order_ids"] == ["DO-CGH", "DO-NUH"]
    assert audit["remaining_order_ids_after"] == ["DO-NUH", "DO-CGH"]
    assert audit["baseline"]["predicted_late_order_count"] == 1
    assert audit["replanned"]["predicted_late_order_count"] == 0

    # At minute 600 the re-sequenced tail has only just left the audited
    # checkpoint.  The old global schedule would make both orders immediately
    # due here; the replacement tail must not replay that old timeline.
    ticked = service.tick_dispatch("PLAN-DELAY")
    assert ticked["route_view"]["metrics"]["orders_delivered"] == 0

    duplicate = client.post("/api/dispatch/runs/PLAN-DELAY/delay-accept", json=request)
    assert duplicate.status_code == 200
    assert duplicate.json()["version"] == body["version"]
    assert duplicate.json()["delay_replan"] == {"idempotent": True}

    context = service.load_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    context["clock"] = make_clock(609, 0, depart_min=540)
    service.update_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", context)
    first = service.tick_dispatch("PLAN-DELAY")
    assert first["vehicles"]["V-DELAY"]["delivered_order_ids"] == ["DO-NUH"]
    assert first["vehicles"]["V-DELAY"]["remaining_order_ids"] == ["DO-CGH"]
    assert service.tick_dispatch("PLAN-DELAY")["version"] == first["version"]
    context["clock"] = make_clock(630, 0, depart_min=540)
    service.update_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", context)
    final = service.tick_dispatch("PLAN-DELAY")
    assert final["status"] == "completed"
    assert final["vehicles"]["V-DELAY"]["delivered_order_ids"] == ["DO-NUH", "DO-CGH"]
    assert final["available_by_lot"] == body["available_by_lot"]


def test_delay_preview_reports_a_clean_scan_without_offering_a_mileage_optimisation():
    _departed_with_crossed_queue()
    # Inspect an earlier, genuinely on-time departure rather than the delayed
    # 10:00 schedule established by the shared recovery fixture.
    old = service.load_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    early = replace(old, version=old.version + 1, vehicles={"V-DELAY": replace(
        old.vehicles["V-DELAY"], schedule_start_min=540)})
    service.update_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", early, expected_version=old.version)

    response = client.post(
        "/api/dispatch/runs/PLAN-DELAY/delay-preview",
        json={"current_time_min": 540, "delay_min": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["predicted_late_order_count"] == 0
    assert body["candidates"] == []
    assert body["replan_candidate_count"] == 0


def test_delay_replanning_refuses_to_mutate_a_pickup_delivery_stop_plan():
    _departed_with_crossed_queue()
    old = service.load_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    vehicle = old.vehicles["V-DELAY"]
    paired = replace(
        old,
        version=old.version + 1,
        vehicles={**old.vehicles, "V-DELAY": replace(
            vehicle,
            drive_plan=(
                PlannedStop("pickup", "DO-CGH", DISPATCH_ORIGIN),
                PlannedStop("delivery", "DO-CGH"),
                PlannedStop("pickup", "DO-NUH", DISPATCH_ORIGIN),
                PlannedStop("delivery", "DO-NUH"),
            ),
        )},
    )
    service.update_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", paired,
                       expected_version=old.version)

    response = client.post(
        "/api/dispatch/runs/PLAN-DELAY/delay-preview",
        json={"current_time_min": 600},
    )

    assert response.status_code == 422
    assert "pickup-delivery" in response.json()["detail"]


def test_tick_proactively_reports_risk_without_mutating_the_queue():
    _departed_with_crossed_queue()
    old = service.load_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    vehicle = old.vehicles["V-DELAY"]
    delayed = replace(old, version=old.version + 1, vehicles={"V-DELAY": replace(
        vehicle, replan_started_min=600, replan_start_facility_id=DISPATCH_ORIGIN,
        replan_order_ids=vehicle.remaining_order_ids)})
    service.update_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", delayed,
                       expected_version=old.version)
    ticked = service.tick_dispatch("PLAN-DELAY")
    assert ticked["delay_inspection"]["predicted_late_order_count"] == 1
    assert ticked["vehicles"]["V-DELAY"]["remaining_order_ids"] == ["DO-CGH", "DO-NUH"]
    assert ticked["version"] == delayed.version


def test_stale_or_changed_candidate_is_refused_before_persisting():
    _departed_with_crossed_queue()
    preview = client.post("/api/dispatch/runs/PLAN-DELAY/delay-preview", json={}).json()
    request = {"vehicle_id": "V-DELAY", "command_id": "stale-delay",
               "expected_version": preview["state_version"],
               "remaining_order_ids_after": ["DO-CGH", "DO-NUH"]}
    changed = client.post("/api/dispatch/runs/PLAN-DELAY/delay-accept", json=request)
    assert changed.status_code == 409
    assert client.get("/api/dispatch/runs/PLAN-DELAY").json()["version"] == preview["state_version"]
    request["expected_version"] -= 1
    stale = client.post("/api/dispatch/runs/PLAN-DELAY/delay-accept", json=request)
    assert stale.status_code == 409
    assert "inspect again" in stale.json()["detail"]


def test_a_stale_tick_cannot_overwrite_the_accepted_replan_audit():
    _departed_with_crossed_queue()
    stale_state = service.load_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    stale_context = service.load_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    preview = client.post("/api/dispatch/runs/PLAN-DELAY/delay-preview", json={}).json()
    accepted = client.post("/api/dispatch/runs/PLAN-DELAY/delay-accept", json={
        "vehicle_id": "V-DELAY", "command_id": "atomic-replan",
        "expected_version": preview["state_version"],
        "remaining_order_ids_after": preview["candidates"][0]["remaining_order_ids_after"],
    })
    assert accepted.status_code == 200
    with pytest.raises(ValueError, match="state changed"):
        service.update_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", stale_state,
                           expected_version=stale_state.version, context=stale_context)
    restored = client.get("/api/dispatch/runs/PLAN-DELAY").json()
    assert restored["delay_replans"] == accepted.json()["delay_replans"]
    assert restored["vehicles"]["V-DELAY"]["remaining_order_ids"] == ["DO-NUH", "DO-CGH"]


def test_remedy_never_sacrifices_a_punctual_order_to_reduce_total_lateness():
    orders = {"A": {"destination_facility_id": "A", "earliest_min": 0, "latest_min": 5},
              "B": {"destination_facility_id": "B", "earliest_min": 0, "latest_min": 3}}
    minutes = {("S", "A"): 4, ("A", "B"): 20,
               ("S", "B"): 2, ("B", "A"): 4}
    best, _ = _best_sequence(("A", "B"), start_facility_id="S", start_time_min=0,
                             order_by_id=orders, leg=lambda a, b: (1, minutes[a, b]))
    # B→A would reduce the miss to just 1 min, but it makes punctual A late.
    assert best == ("A", "B")


def test_mileage_limit_blocks_an_otherwise_helpful_resequence():
    _departed_with_crossed_queue()
    context = service.load_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    context["input"]["constraints"]["mileage_limit_m"] = 1
    service.update_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", context)
    preview = client.post("/api/dispatch/runs/PLAN-DELAY/delay-preview", json={}).json()
    assert preview["predicted_late_order_count"] == 1
    assert preview["candidates"][0]["replan_available"] is False


def test_tracker_and_tick_wait_for_a_replanned_receiving_window():
    _departed_with_crossed_queue()
    preview = client.post("/api/dispatch/runs/PLAN-DELAY/delay-preview", json={}).json()
    accepted = client.post("/api/dispatch/runs/PLAN-DELAY/delay-accept", json={
        "vehicle_id": "V-DELAY", "command_id": "wait-delay",
        "expected_version": preview["state_version"],
        "remaining_order_ids_after": preview["candidates"][0]["remaining_order_ids_after"],
    })
    assert accepted.status_code == 200
    context = service.load_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    next(item for item in context["input"]["orders"] if item["order_id"] == "DO-NUH")["earliest_min"] = 615
    context["clock"] = make_clock(609, 0, depart_min=540)
    service.update_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", context)
    ticked = service.tick_dispatch("PLAN-DELAY")
    assert ticked["route_view"]["metrics"]["orders_delivered"] == 0
    track = ticked["route_view"]["routes"][0]["track"]
    assert track["arrivals"][0] == 615
    assert track["reached_stops"] == 0


def test_a_later_resupply_updates_the_replanned_drive_schedule():
    _departed_with_crossed_queue()
    preview = client.post("/api/dispatch/runs/PLAN-DELAY/delay-preview", json={}).json()
    assert client.post("/api/dispatch/runs/PLAN-DELAY/delay-accept", json={
        "vehicle_id": "V-DELAY", "command_id": "before-resupply",
        "expected_version": preview["state_version"],
        "remaining_order_ids_after": preview["candidates"][0]["remaining_order_ids_after"],
    }).status_code == 200
    old = service.load_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    equipped = replace(old, version=old.version + 1, vehicles={"V-DELAY": replace(
        old.vehicles["V-DELAY"], onboard_spare=(("vaccine_2_8", "chilled", 5),))})
    service.update_run(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", equipped,
                       expected_version=old.version)
    order = {"order_id": "RO-LATER", "product_id": "vaccine_2_8",
             "destination_facility_id": "H-NUH", "quantity": 5,
             "earliest_min": 600, "latest_min": 625, "temperature_zone": "chilled"}
    accepted = client.post("/api/dispatch/runs/PLAN-DELAY/emergency-accept", json={
        "order": order, "current_time_min": 600, "candidate_kind": "add_stop_in_transit",
        "vehicle_id": "V-DELAY", "command_id": "later-resupply"})
    assert accepted.status_code == 200
    assert accepted.json()["vehicles"]["V-DELAY"]["replan_order_ids"] == [
        "RO-LATER", "DO-NUH", "DO-CGH"]
    context = service.load_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY")
    context["clock"] = make_clock(609, 0, depart_min=540)
    service.update_context(service.DISPATCH_DATABASE_URL, "PLAN-DELAY", context)
    ticked = service.tick_dispatch("PLAN-DELAY")
    assert ticked["vehicles"]["V-DELAY"]["delivered_order_ids"] == ["RO-LATER", "DO-NUH"]
    # Consecutive orders at one hospital share a zero-length leg.  The following
    # physical leg must still point to CGH's order rather than the repeated NUH.
    legs = ticked["route_view"]["routes"][0]["legs"]
    assert legs[1]["order_id"] == "DO-CGH"
