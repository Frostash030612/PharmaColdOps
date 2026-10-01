"""M2 numerical correctness, missing coverage, source integrity and retries."""
import copy
import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import service
from api.main import app
from temperature_monitoring import Interval, TemperatureSeries, SimulateIn, analyse, mkt, simulate


def series(values, horizon=None, energy=83.144):
    return TemperatureSeries(observation_end_min=horizon or values[-1][1],
                             activation_energy_kj_mol=energy,
                             intervals=[Interval(start_min=a, end_min=b, temp_c=t) for a, b, t in values])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "cases.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(service, "write_case", lambda r: True)


@pytest.mark.parametrize("temp", [-273.149, -80, -20, 5, 30, 200])
def test_constant_temperature_identity_and_numerical_stability(temp):
    data = series([(0, .5, temp), (.5, 120, temp)])
    assert mkt(data.intervals, data.activation_energy_kj_mol) == pytest.approx(temp, abs=1e-9)


def test_time_weighted_arrhenius_not_arithmetic_or_sample_weighted():
    data = series([(0, 10, 5), (10, 100, 25)])
    a = 83144 / 8.31446261815324
    expected = -a / math.log(.1 * math.exp(-a / 278.15) + .9 * math.exp(-a / 298.15)) - 273.15
    result = mkt(data.intervals, 83.144)
    assert result == pytest.approx(expected)
    assert result != pytest.approx(23)  # time-weighted arithmetic
    assert result != pytest.approx(mkt(series([(0, 50, 5), (50, 100, 25)]).intervals, 83.144))
    split = series([(0, 10, 5), (10, 55, 25), (55, 100, 25)])
    assert mkt(split.intervals, 83.144) == pytest.approx(result)


def test_subnormal_duration_does_not_underflow_weight_before_log():
    data = series([(0, 5e-324, 200), (5e-324, 10080, 5)])
    assert mkt(data.intervals, 83.144) == pytest.approx(5)


def test_missing_simulation_always_contains_a_gap_even_at_minimum_resolution():
    spec = service.resolve_spec("vaccine_2_8", None)
    data = simulate(SimulateIn(product_id=spec.product_id, scenario="gap", observation_end_min=30, interval_min=5), spec)
    assert any(i.temp_c is None for i in data.intervals)
    assert not analyse(data, spec)["coverage_complete"]


def test_boundaries_contiguous_windows_and_round_up_only_at_m3_boundary():
    data = series([(0, 2, 2), (2, 3, 8), (3, 3.5, 9), (3.5, 4.25, 13), (4.25, 5, 5),
                   (5, 6, -1), (6, 7, 1), (7, 8, 10), (8, 9, 5)])
    result = analyse(data, service.resolve_spec("vaccine_2_8", None))
    assert result["coverage_complete"] and result["coverage_ratio"] == 1
    assert [w["kind"] for w in result["windows"]] == ["hot", "cold", "hot"]
    first = result["windows"][0]
    assert first["duration_exact_min"] == 1.25 and first["event"]["duration_min"] == 2
    assert first["event"]["excursion_temp_c"] == 13
    assert 9 < first["event"]["mkt_c"] < 13
    assert result["total_hot_min"] == 2.25 and result["total_cold_min"] == 2
    assert result["windows"][1]["event"]["excursion_temp_c"] == -1
    assert all(w["registration_allowed"] for w in result["windows"])


def test_cold_and_freezing_are_not_hidden_by_low_mkt():
    for pid, temp, allowed in [("vaccine_2_8", 1, False), ("vaccine_2_8", 0, True),
                                ("frozen_m20", -30, False), ("mrna_ultracold", -85, False)]:
        result = analyse(series([(0, 10, temp)]), service.resolve_spec(pid, None))
        window = result["windows"][0]
        assert window["kind"] == "cold" and window["registration_allowed"] == allowed


def test_null_and_uncovered_intervals_are_not_interpolated_or_merged():
    data = series([(2, 5, 10), (5, 7, None), (7, 9, 10), (10, 12, 10)], horizon=15)
    result = analyse(data, service.resolve_spec("vaccine_2_8", None))
    assert not result["coverage_complete"]
    assert result["known_duration_min"] == 7 and result["coverage_ratio"] == pytest.approx(7 / 15)
    assert len(result["missing_intervals"]) == 4 and len(result["windows"]) == 3
    assert result["known_only_mkt_c"] == pytest.approx(10)
    assert all(w["blocked_reason"] == "incomplete_coverage" for w in result["windows"])
    unknown = analyse(series([(0, 10, None)]), service.resolve_spec("vaccine_2_8", None))
    assert unknown["known_only_mkt_c"] is None and unknown["windows"] == []


@pytest.mark.parametrize("values,horizon", [([(1, 1, 5)], 10), ([(2, 1, 5)], 10),
    ([(0, 2, 5), (1, 3, 8)], 3), ([(3, 4, 5), (0, 1, 8)], 4),
    ([(0, 11, 5)], 10), ([(0, 1, -273.15)], 1), ([(0, 1, float('nan'))], 1),
    ([(0, 1, float('inf'))], 1), ([(0, 1, 201)], 1)])
def test_invalid_intervals_fail(values, horizon):
    with pytest.raises(ValidationError):
        series(values, horizon=horizon)


@pytest.mark.parametrize("pid", service.valid_product_ids())
@pytest.mark.parametrize("scenario", ["normal", "hot", "cold", "mixed", "gap"])
def test_simulator_reproducible_for_every_product_and_scenario(pid, scenario):
    spec = service.resolve_spec(pid, None)
    req = SimulateIn(product_id=pid, scenario=scenario, observation_end_min=121, interval_min=7)
    first = simulate(req, spec)
    assert first == simulate(req, spec)
    assert first != simulate(req.model_copy(update={"seed": 43}), spec)
    result = analyse(first, spec)
    assert first.intervals[-1].end_min == 121
    assert result["coverage_complete"] == (scenario != "gap")
    if scenario == "normal": assert result["windows"] == []
    elif scenario == "mixed": assert [w["kind"] for w in result["windows"]] == ["hot", "cold"]
    elif scenario != "gap": assert result["windows"][0]["kind"] == scenario


def request(data=None, **extras):
    data = data or series([(0, 20, 5), (20, 30.5, 12), (30.5, 60, 5)])
    analysis = analyse(data, service.resolve_spec("vaccine_2_8", None))
    return {"product_id": "vaccine_2_8", "packaging": "intact", **analysis["windows"][0]["event"],
            "temperature_context": {"series": data.model_dump(), "window_id": "window-001"}, **extras}


def test_api_simulation_analysis_are_read_only_unknown_product_and_invalid_input():
    with TestClient(app) as client:
        simulated = client.post("/api/m2/simulate", json={"product_id": "vaccine_2_8"})
        assert simulated.status_code == 200
        result = simulated.json()
        again = client.post("/api/m2/analyse", json={"product_id": "vaccine_2_8", "series": result["series"]})
        assert again.status_code == 200 and again.json() == result["analysis"]
        assert client.get("/api/runs").json()["count"] == 0
        for path in ["/api/m2/simulate", "/api/m2/analyse"]:
            body = {"product_id": "invalid", "series": result["series"]} if path.endswith("analyse") else {"product_id": "invalid"}
            assert client.post(path, json=body).status_code == 422
        assert client.post("/api/m2/simulate", json={"product_id": "vaccine_2_8", "interval_min": 60, "observation_end_min": 30}).status_code == 422


def test_preview_matches_legacy_rule_only_and_archives_full_source():
    with TestClient(app) as client:
        body = request(registration_id="temperature-case")
        preview = client.post("/api/decide", json=body)
        assert preview.status_code == 200, preview.text
        old = client.post("/api/decide", json={k: v for k, v in body.items() if k != "temperature_context"}).json()
        result = preview.json()
        assert {k: v for k, v in result.items() if k not in {"temperature_context", "temperature_assessment"}} == old
        assert result["event"]["duration_min"] == 11
        saved = client.post("/api/case_close", json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["temperature_context"] == result["temperature_context"]
        assert saved.json()["temperature_assessment"] == result["temperature_assessment"]
        assert client.get("/api/runs").json()["runs"][0]["temperature_assessment"] == result["temperature_assessment"]


def test_retry_does_not_recompute_but_changed_source_conflicts(monkeypatch):
    with TestClient(app) as client:
        body = request(registration_id="immutable-m2")
        saved = client.post("/api/case_close", json=body).json()
        monkeypatch.setattr(service, "_temperature_event", lambda *args: (_ for _ in ()).throw(AssertionError("must not recompute")))
        repeated = client.post("/api/case_close", json=body)
        assert repeated.status_code == 200
        assert repeated.json()["run_id"] == saved["run_id"]
        assert repeated.json()["temperature_assessment"] == saved["temperature_assessment"]
        changed = copy.deepcopy(body)
        changed["temperature_context"]["series"]["intervals"][0]["temp_c"] = 6
        assert client.post("/api/case_close", json=changed).status_code == 409
        assert client.get("/api/runs").json()["count"] == 1


@pytest.mark.parametrize("field", ["excursion_temp_c", "duration_min", "mkt_c"])
def test_client_cannot_tamper_with_derived_event(field):
    body = request(registration_id="tampered")
    body[field] += 1
    with TestClient(app) as client:
        for path in ["/api/decide", "/api/case_close"]:
            result = client.post(path, json=body)
            assert result.status_code == 422 and "mismatch" in result.text
        assert client.get("/api/runs").json()["count"] == 0


def test_missing_coverage_unsupported_cold_and_nonexistent_window_cannot_register():
    with TestClient(app) as client:
        bodies = [request(series([(0, 5, 12), (5, 10, None)])), request(series([(0, 10, 1)])), request()]
        bodies[-1]["temperature_context"]["window_id"] = "window-999"
        for body in bodies:
            for path in ["/api/decide", "/api/case_close"]:
                assert client.post(path, json=body).status_code == 422
        assert client.get("/api/runs").json()["count"] == 0


def test_freezing_window_enters_existing_m3_scrap_rule():
    with TestClient(app) as client:
        result = client.post("/api/decide", json=request(series([(0, 10, -1)])))
        assert result.status_code == 200 and result.json()["disposition"] == "scrap"


def test_temperature_source_stays_linked_to_original_order_and_rescue(day_plan):
    plan_id = day_plan("PLAN-M2")
    order = next(o for o in service.get_dispatch(plan_id)["input"]["orders"] if o["product_id"] == "vaccine_2_8")
    body = request(registration_id="linked-m2", order_id=order["order_id"], dispatch_id=plan_id,
                   facility_id="D-NORTHPOINT", destination_facility_id=order["destination_facility_id"])
    with TestClient(app) as client:
        saved = client.post("/api/case_close", json=body)
        assert saved.status_code == 200, saved.text
        record = saved.json()
        assert record["event"]["order_id"] == order["order_id"] and record["event"]["facility_id"] == "D-NORTHPOINT"
        assert record["temperature_assessment"]["coverage_complete"]
        assert record["linked_order"]["latest_min"] == order["latest_min"]
        preview = client.post("/api/dispatch/reshipments/preview", json={"run_id": record["run_id"]})
        assert preview.status_code == 200, preview.text
        assert preview.json()["order_source"] == "linked_order" and preview.json()["dispatch_id"] == plan_id
