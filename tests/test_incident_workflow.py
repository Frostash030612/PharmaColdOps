"""Run-scoped incident associations and the operator/delivery lifecycle."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from api.schemas import DispatchCreateIn
from optimisation.daily_orders import daily_delivery_batch
from optimisation.dispatch_repository import load_context

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))
    monkeypatch.setattr(service, "write_case", lambda record: True)


def plan(dispatch_id="PLAN-INCIDENT", *, quantity=17):
    orders, lots, vehicles = daily_delivery_batch(hospitals=1)
    order = dataclasses.replace(orders[0], quantity=quantity, latest_min=720)
    service.create_dispatch(DispatchCreateIn(
        dispatch_id=dispatch_id, command_id=f"create-{dispatch_id}", algorithm="greedy",
        orders=[service._order_dump(order)], inventory=[service._lot_dump(l) for l in lots],
        vehicles=[service._vehicle_dump(v) for v in vehicles]))
    return order


def incident(order=None, dispatch_id="PLAN-INCIDENT", *, reship=True):
    payload = dict(product_id="vaccine_2_8", excursion_temp_c=20 if reship else 5,
                   duration_min=90 if reship else 0, mkt_c=19 if reship else 5,
                   packaging="intact", stage="transit", facility_id="D-NORTHPOINT")
    if order:
        payload.update(order_id=order.order_id, dispatch_id=dispatch_id,
                       destination_facility_id=order.destination_facility_id)
    response = client.post("/api/case_close", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def status(run_id):
    return next(r for r in client.get("/api/runs").json()["runs"] if r["run_id"] == run_id)


def transition(record, new_status, remark="confirmed handling"):
    return client.post(f"/api/runs/{record['run_id']}/workflow", json={
        "status": new_status, "expected_version": record["workflow_version"], "remark": remark})


def test_archive_retains_order_location_quantity_and_deadline():
    order = plan()
    closed = incident(order)
    archived = status(closed["run_id"])
    assert archived["event"]["order_id"] == order.order_id
    assert archived["event"]["dispatch_id"] == "PLAN-INCIDENT"
    assert archived["event"]["facility_id"] == "D-NORTHPOINT"
    assert archived["linked_order"]["quantity"] == 17
    preview = client.post("/api/dispatch/reshipments/preview", json={"run_id": closed["run_id"]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["order_source"] == "linked_order"
    assert preview.json()["order"]["quantity"] == 17
    assert preview.json()["order"]["latest_min"] == 720


@pytest.mark.parametrize("field,value", [
    ("order_id", "missing"), ("dispatch_id", "missing"), ("product_id", "insulin_2_8"),
    ("destination_facility_id", "H-NUH"), ("facility_id", "missing"),
])
def test_invalid_links_are_rejected_without_archiving(field, value):
    order = plan()
    payload = dict(product_id="vaccine_2_8", excursion_temp_c=20, duration_min=90,
                   mkt_c=19, packaging="intact", stage="transit", facility_id="D-NORTHPOINT",
                   order_id=order.order_id, dispatch_id="PLAN-INCIDENT",
                   destination_facility_id=order.destination_facility_id)
    payload[field] = value
    response = client.post("/api/case_close", json=payload)
    assert response.status_code == 422, response.text
    assert client.get("/api/runs").json()["count"] == 0


def test_repeated_daily_order_ids_cannot_move_incident_to_new_run():
    order = plan("PLAN-FIRST", quantity=17)
    closed = incident(order, "PLAN-FIRST")
    plan("PLAN-SECOND", quantity=25)
    preview = client.post("/api/dispatch/reshipments/preview", json={"run_id": closed["run_id"]}).json()
    assert preview["dispatch_id"] == "PLAN-FIRST"
    assert preview["order"]["quantity"] == 17
    accepted = client.post("/api/dispatch/reshipments", json={"run_id": closed["run_id"]})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["dispatch_id"] == "PLAN-FIRST"
    assert all(o["order_id"] != f"RO-{closed['run_id']}"
               for o in load_context(service.DISPATCH_DATABASE_URL, "PLAN-SECOND")["input"]["orders"])


def test_reshipment_processing_to_handled_requires_real_delivery_then_closure():
    order = plan()
    closed = incident(order)
    assert status(closed["run_id"])["processing_status"] == "pending"
    assert transition(status(closed["run_id"]), "closed").status_code == 409
    assert transition(status(closed["run_id"]), "handled").status_code == 409
    accepted = client.post("/api/dispatch/reshipments", json={"run_id": closed["run_id"]})
    assert accepted.status_code == 200, accepted.text
    assert status(closed["run_id"])["processing_status"] == "processing"
    assert transition(status(closed["run_id"]), "closed").status_code == 409
    service.depart_dispatch("PLAN-INCIDENT", "depart")
    run = service.get_dispatch("PLAN-INCIDENT")
    for vehicle_id, vehicle in run["vehicles"].items():
        for i, _ in enumerate(vehicle["remaining_order_ids"]):
            service.deliver_dispatch("PLAN-INCIDENT", vehicle_id, f"deliver-{vehicle_id}-{i}")
    handled = status(closed["run_id"])
    assert handled["processing_status"] == "handled"
    assert transition(handled, "closed", "").status_code == 409
    result = transition(handled, "closed", "replacement received and quality action recorded")
    assert result.status_code == 200, result.text
    assert status(closed["run_id"])["processing_status"] == "closed"
    assert transition(handled, "closed").status_code == 409  # stale tab/version


def test_non_reshipment_operator_actions_are_persistent_and_audited():
    closed = incident(reship=False)
    assert closed["processing_status"] == "pending"
    processing = transition(closed, "processing")
    assert processing.status_code == 200
    handled = transition(processing.json(), "handled", "quality check completed")
    assert handled.status_code == 200
    result = transition(handled.json(), "closed", "reviewed")
    assert result.status_code == 200
    persisted = status(closed["run_id"])
    assert persisted["workflow_version"] == 3
    assert [h["status"] for h in persisted["workflow_history"]] == ["processing", "handled", "closed"]


def test_dispatch_without_order_is_invalid():
    response = client.post("/api/case_close", json=dict(product_id="vaccine_2_8",
        excursion_temp_c=5, duration_min=0, mkt_c=5, packaging="intact", dispatch_id="PLAN-X"))
    assert response.status_code == 422


def test_old_order_only_client_captures_dispatch_at_archive_time():
    order = plan()
    response = client.post("/api/case_close", json=dict(product_id="vaccine_2_8",
        excursion_temp_c=20, duration_min=90, mkt_c=19, packaging="intact", order_id=order.order_id))
    assert response.status_code == 200
    assert response.json()["event"]["dispatch_id"] == "PLAN-INCIDENT"
    assert response.json()["event"]["destination_facility_id"] == order.destination_facility_id


def test_completed_day_cannot_receive_old_incident_on_new_day():
    order = plan("PLAN-OLD")
    closed = incident(order, "PLAN-OLD")
    departed = service.depart_dispatch("PLAN-OLD", "depart")
    vehicle = next(iter(departed["vehicles"]))
    service.deliver_dispatch("PLAN-OLD", vehicle, "delivered")
    plan("PLAN-NEW")
    response = client.post("/api/dispatch/reshipments/preview", json={"run_id": closed["run_id"]})
    assert response.status_code == 422  # read-only preview uses validation-error contract
    assert "operating day is completed" in response.text
    response = client.post("/api/dispatch/reshipments", json={"run_id": closed["run_id"]})
    assert response.status_code == 422


def test_workflow_unknown_run_is_404():
    response = client.post("/api/runs/missing/workflow", json={"status": "processing", "expected_version": 0})
    assert response.status_code == 404


def test_sqlite_concurrent_boot_reads_can_migrate_old_schema(tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from optimisation.dispatch_repository import recent_runs
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE dispatch_runs (dispatch_id TEXT PRIMARY KEY, version INTEGER, state_json TEXT)")
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: recent_runs(path), range(16))) == [[]] * 16
