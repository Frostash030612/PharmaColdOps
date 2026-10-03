"""Original suggestions and human outcomes have separate, durable authority."""
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api import service, case_audit
from api.main import app
from optimisation.case_repository import registered_records
from optimisation.dispatch_repository import load_run

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(service, "write_case", lambda r: True)
    monkeypatch.setattr(case_audit, "audit_cases", lambda records, states: {"status": "passed", "case_count": 1, "cases": [{"run_id": records[0]["run_id"], "coverage": "complete"}]})


def register(**extra):
    body = {"registration_id": "human-case", "product_id": "vaccine_2_8", "excursion_temp_c": 5,
            "duration_min": 0, "mkt_c": 5, "packaging": "intact", "review_requested": True,
            "review_reason": "Operator requests independent demo review", "destination_facility_id": "H-SGH", **extra}
    if not body["review_requested"]:
        body["review_reason"] = ""
    response = client.post("/api/case_close", json=body)
    assert response.status_code == 200, response.text
    return body, response.json()


def review(record, outcome="scrap", command="review-1", **extra):
    body = {"command_id": command, "expected_version": record["workflow_version"], "disposition": outcome,
            "reviewer": "Demo reviewer A", "reason": "Demonstration check and review rationale", **extra}
    return client.post(f"/api/runs/{record['run_id']}/review", json=body), body


@pytest.mark.parametrize("outcome,reship,pending", [("release", False, False), ("retest", False, True), ("scrap", True, False), ("quarantine", False, True)])
def test_outcomes_separate_from_original_and_review_necessary(outcome, reship, pending):
    _, record = register()
    assert record["disposition"] == "release" and record["effective_disposition"] is None
    assert record["review_status"] == "pending"
    assert client.post("/api/dispatch/reshipments/preview", json={"run_id": record["run_id"]}).status_code == 422
    assert client.post(f"/api/runs/{record['run_id']}/workflow", json={"status": "handled", "expected_version": 0, "remark": "attempted shortcut"}).status_code == 409
    original = copy.deepcopy(registered_records(service.DISPATCH_DATABASE_URL)[0])
    result, _ = review(record, outcome)
    assert result.status_code == 200, result.text
    updated = result.json()
    assert updated["disposition"] == "release" and updated["reshipment_required"] is False
    assert updated["effective_disposition"] == outcome and updated["effective_reshipment_required"] == reship
    assert (updated["review_status"] == "pending") == pending
    assert registered_records(service.DISPATCH_DATABASE_URL)[0] == original
    assert updated["review_history"][0]["demo_self_declared_reviewer"]


def test_review_retry_is_idempotent_conflicting_command_and_stale_version_refused():
    _, record = register()
    first, body = review(record, "quarantine")
    assert first.status_code == 200
    path = f"/api/runs/{record['run_id']}/review"
    assert client.post(path, json=body).json() == first.json()
    assert client.post(path, json={**body, "reason": "different reason"}).status_code == 409
    assert client.post(path, json={**body, "command_id": "new-stale"}).status_code == 409
    second, _ = review(first.json(), "release", "second-review")
    assert second.status_code == 200
    replay = client.post(path, json=body).json()
    assert len(replay["review_history"]) == 2 and replay["effective_disposition"] == "release"


def test_racing_reviewers_only_one_can_write_expected_version():
    _, record = register()
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda c: review(record, "release", c)[0].status_code, ["review-a", "review-b"]))
    assert sorted(statuses) == [200, 409]
    assert len(service.find_run(record["run_id"])["review_history"]) == 1


@pytest.mark.parametrize("extra", [{"reviewer": " "}, {"reason": " a "}, {"disposition": "invented"}, {"expected_version": -1}])
def test_invalid_review_inputs_refused(extra):
    _, record = register()
    assert review(record, **extra)[0].status_code == 422


def test_unknown_case_and_destination_cannot_be_reviewed():
    _, record = register(destination_facility_id=None)
    assert review(record)[0].status_code == 409
    assert review(record, destination_facility_id="D-NORTHPOINT")[0].status_code == 409
    assert review({**record, "run_id": "missing"})[0].status_code == 404
    result, _ = review(record, destination_facility_id="H-SGH")
    assert result.status_code == 200 and result.json()["effective_destination_facility_id"] == "H-SGH"
    assert result.json()["event"].get("destination_facility_id") is None


def test_registration_request_reason_and_identity_frozen():
    body, record = register()
    assert client.post("/api/case_close", json=body).json() == record
    assert client.post("/api/case_close", json={**body, "review_reason": "Changed request"}).status_code == 409
    assert client.post("/api/case_close", json={**body, "registration_id": "blank-reason", "review_reason": " "}).status_code == 422


def test_cold_manual_and_multiple_windows_require_review_without_changing_rules():
    _, cold = register(excursion_temp_c=1, review_requested=False)
    assert "cold_policy_gap" in cold["review_reasons"] and cold["review_status"] == "pending"
    result = client.post("/api/m2/simulate", json={"product_id": "vaccine_2_8", "scenario": "mixed"}).json()
    body = {"registration_id": "multi-window", "product_id": "vaccine_2_8", "packaging": "intact",
            **result["analysis"]["windows"][0]["event"],
            "temperature_context": {"series": result["series"], "window_id": "window-001"}}
    response = client.post("/api/case_close", json=body)
    assert response.status_code == 200 and "multiple_excursion_windows" in response.json()["review_reasons"]


@pytest.mark.parametrize("temperatures", [[None, None], [5, None], [12, None]])
def test_whole_observation_missing_data_has_no_fake_scalar_rule_or_model(temperatures):
    series = {"observation_end_min": 10, "intervals": [{"start_min": 0, "end_min": 5, "temp_c": temperatures[0]}, {"start_min": 5, "end_min": 10, "temp_c": temperatures[1]}]}
    body = {"product_id": "vaccine_2_8", "packaging": "intact", "registration_id": "observation",
            "temperature_context": {"series": series, "window_id": None}}
    response = client.post("/api/case_close", json=body)
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["automatic_assessment_available"] is False and record["rule_no"] == 0
    assert record["event"]["excursion_temp_c"] is None and record["event"]["mkt_c"] is None
    assert record["risk"]["score"] is None and record["review_status"] == "pending"
    assert client.post("/api/case_close", json={**body, "registration_id": "invented", "mkt_c": 0}).status_code == 422
    resolved, _ = review(record, "release")
    assert resolved.status_code == 200 and resolved.json()["automatic_assessment_available"] is False


def linked(day_plan, **extra):
    did = day_plan("PLAN-HUMAN", hospitals=1)
    order = service.get_dispatch(did)["input"]["orders"][0]
    _, record = register(order_id=order["order_id"], dispatch_id=did, product_id=order["product_id"],
                         destination_facility_id=order["destination_facility_id"], **extra)
    return did, order, record


def test_review_scrap_drives_real_reshipment_and_locks_changed_outcomes(day_plan):
    did, order, record = linked(day_plan)
    resolved, _ = review(record)
    assert resolved.status_code == 200
    updated = resolved.json()
    preview = client.post("/api/dispatch/reshipments/preview", json={"run_id": record["run_id"]})
    assert preview.status_code == 200 and preview.json()["order"]["destination_facility_id"] == order["destination_facility_id"]
    adopted = client.post("/api/dispatch/reshipments", json={"run_id": record["run_id"]})
    assert adopted.status_code == 200, adopted.text
    state = load_run(service.DISPATCH_DATABASE_URL, did)
    assert f"RO-{record['run_id']}" in state.orders
    assert service.find_run(record["run_id"])["execution_locked"]
    assert review(updated, "release", "cannot-undo")[0].status_code == 409
    assert registered_records(service.DISPATCH_DATABASE_URL)[0]["disposition"] == "release"
    assert client.post("/api/dispatch/reshipments", json={"run_id": record["run_id"]}).status_code == 200


def test_pending_original_order_cannot_deliver_or_tick_release_can_resume(day_plan):
    did, order, record = linked(day_plan)
    departed = service.depart_dispatch(did, "depart", speed=60)
    vehicle = next(v for v in departed["vehicles"].values() if order["order_id"] in v["remaining_order_ids"])
    vehicle_id = next(k for k, v in departed["vehicles"].items() if v is vehicle)
    with pytest.raises(ValueError, match="held"):
        service.deliver_dispatch(did, vehicle_id, "manual-delivery")
    held = service.tick_dispatch(did)
    assert held["clock"]["speed"] == 0 and held["review_hold"]["case_ids"] == [record["run_id"]]
    assert load_run(service.DISPATCH_DATABASE_URL, did).orders[order["order_id"]].status != "delivered"
    with pytest.raises(ValueError, match="hold"):
        service.set_dispatch_speed(did, 60)
    resolved, _ = review(record, "release")
    assert resolved.status_code == 200
    service.set_dispatch_speed(did, 60)
    service.deliver_dispatch(did, vehicle_id, "released-delivery")
    latest = service.find_run(record["run_id"])
    assert latest["execution_locked"] and review(latest, "scrap", "too-late")[0].status_code == 409


def test_retest_requires_explicit_result_review_before_source_delivery(day_plan):
    did, order, record = linked(day_plan)
    resolved, _ = review(record, "retest")
    updated = resolved.json()
    service.depart_dispatch(did, "depart", speed=0)
    vehicle_id = next(k for k, v in service.get_dispatch(did)["vehicles"].items() if order["order_id"] in v["remaining_order_ids"])
    with pytest.raises(ValueError):
        service.deliver_dispatch(did, vehicle_id, "not-tested")
    handled = client.post(f"/api/runs/{record['run_id']}/workflow", json={"status": "handled", "expected_version": updated["workflow_version"], "remark": "Retest done but result unspecified"})
    assert handled.status_code == 409
    released, _ = review(updated, "release", "retest-result", reason="Demo retest result reviewed; explicit release")
    assert released.status_code == 200
    service.deliver_dispatch(did, vehicle_id, "retest-done")


def test_bound_destination_cannot_change(day_plan):
    _, order, record = linked(day_plan)
    other = "H-NUH" if order["destination_facility_id"] != "H-NUH" else "H-SGH"
    assert review(record, destination_facility_id=other)[0].status_code == 409


def test_export_includes_original_effective_reviews_complete_source_and_no_writes():
    _, record = register(remark='<script>alert("bad")</script>')
    resolved, _ = review(record, "release", reason="Checked demo; <img src=x onerror=alert(1)>")
    before = copy.deepcopy(service.find_run(record["run_id"]))
    path = f"/api/runs/{record['run_id']}/audit"
    exported = client.get(path, params={"format": "json"})
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    report = exported.json()
    assert report["original_registration"]["review_required"] and report["effective_assessment"]["effective_disposition"] == "release"
    assert len(report["review_history"]) == 1 and report["graph"]["status"] == "passed"
    payload = {k: v for k, v in report.items() if k not in {"exported_at", "content_sha256", "hash_scope"}}
    assert hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest() == report["content_sha256"]
    for lang in ["zh", "en"]:
        text = client.get(path, params={"format": "html", "lang": lang}).text
        assert '<script>' not in text and '<img src=x' not in text
        assert '&lt;script&gt;' in text and report["content_sha256"] in text
        assert '@media print' in text
    assert service.find_run(record["run_id"]) == before
    assert client.get(path, params={"format": "pdf"}).status_code == 422
    assert client.get('/api/runs/missing/audit').status_code == 404


def test_graph_unavailable_export_is_honest(monkeypatch):
    _, record = register()
    monkeypatch.setattr(case_audit, "audit_cases", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    report = client.get(f"/api/runs/{record['run_id']}/audit?format=json").json()
    assert report["graph"]["status"] == "unavailable" and report["effective_assessment"]["review_status"] == "pending"


def test_export_only_includes_case_orders_not_unrelated_ones(day_plan):
    did = day_plan("PLAN-MANY", hospitals=4)
    orders = service.get_dispatch(did)["input"]["orders"]
    order = orders[0]
    _, record = register(order_id=order["order_id"], dispatch_id=did, product_id=order["product_id"], destination_facility_id=order["destination_facility_id"])
    report = client.get(f"/api/runs/{record['run_id']}/audit?format=json").json()
    assert set(report["delivery"]["orders"]) == {order["order_id"]}


def test_handled_case_cannot_change_review_and_workflow_preserves_history():
    _, record = register()
    updated = review(record, "release")[0].json()
    handled = client.post(f"/api/runs/{record['run_id']}/workflow", json={"status": "handled", "expected_version": updated["workflow_version"], "remark": "quality handled"}).json()
    assert len(handled["review_history"]) == 1
    assert handled["execution_locked"]
    assert review(handled, "scrap", "late")[0].status_code == 409


def test_legacy_quarantine_registration_does_not_reopen_closed_cases():
    from api.case_review import projection
    original = {"disposition": "quarantine", "reshipment_required": True, "event": {}, "processing_status": "closed"}
    effective = projection(original, {})
    assert effective["review_status"] == "not_required" and effective["effective_reshipment_required"]
    assert service._case_progress(original, {"status": "closed"}, {})["processing_status"] == "closed"


def test_malformed_known_case_report_is_not_misreported_as_unknown_case(monkeypatch):
    _, record = register()
    monkeypatch.setattr(case_audit, "render", lambda *args: (_ for _ in ()).throw(KeyError("source metadata missing")))
    response = client.get(f"/api/runs/{record['run_id']}/audit?format=html")
    assert response.status_code == 503 and "no report was produced" in response.text
    assert client.get("/api/runs/missing/audit").status_code == 404


def test_automatic_retest_also_requires_explicit_review_result():
    _, record = register(review_requested=False, excursion_temp_c=9.5, duration_min=25, mkt_c=9.6)
    assert record["disposition"] == "retest" and record["review_status"] == "pending"
    assert "retest_result_required" in record["review_reasons"]
    assert client.post(f"/api/runs/{record['run_id']}/workflow", json={"status": "handled", "expected_version": 0, "remark": "ambiguous retest note"}).status_code == 409
    resolved, _ = review(record, "release", reason="Demo retest result explicitly reviewed as passing")
    assert resolved.status_code == 200 and resolved.json()["review_status"] == "resolved"


def test_review_of_goods_delivered_before_registration_can_complete_retest(day_plan):
    did = day_plan("PLAN-LATE-REVIEW", hospitals=1)
    order = service.get_dispatch(did)["input"]["orders"][0]
    service.depart_dispatch(did, "depart", speed=0)
    vehicle_id = next(k for k, v in service.get_dispatch(did)["vehicles"].items() if order["order_id"] in v["remaining_order_ids"])
    service.deliver_dispatch(did, vehicle_id, "already-delivered")
    _, record = register(order_id=order["order_id"], dispatch_id=did, product_id=order["product_id"], destination_facility_id=order["destination_facility_id"])
    assert record["linked_order"]["status_at_registration"] == "delivered"
    retest = review(record, "retest")[0].json()
    assert retest["review_status"] == "pending" and not retest["execution_locked"]
    resolved, _ = review(retest, "release", "late-result", reason="Demo post-delivery retest result recorded; no delivery facts undone")
    assert resolved.status_code == 200
    assert load_run(service.DISPATCH_DATABASE_URL, did).orders[order["order_id"]].status == "delivered"
