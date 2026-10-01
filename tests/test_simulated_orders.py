"""Synthetic business inputs remain reproducible, constrained and honestly labelled."""
import dataclasses
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.catalog import read_supply_points, supplies_product
from optimisation.dispatch_models import validate_dispatch_inputs
from optimisation.dispatch_planner import plan_delivery_orders
from optimisation.simulated_orders import GENERATOR_VERSION, PROFILES, SimulationConfig, generate_simulated_batch
from optimisation.singapore_loader import read_network

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))
    monkeypatch.setattr(service, "RUNS_FILE", tmp_path / "runs.jsonl")


def config(scenario="routine", **overrides):
    return SimulationConfig(scenario=scenario, operating_date="2026-10-01", seed=7, **overrides)


@pytest.mark.parametrize("scenario", PROFILES)
def test_identical_effective_inputs_reproduce_everything(scenario):
    first = generate_simulated_batch(config(scenario))
    assert first == generate_simulated_batch(config(scenario))
    replay = generate_simulated_batch(SimulationConfig(**first.metadata["config"]))
    assert first == replay
    assert first.metadata["simulated"] is True
    assert first.metadata["generator_version"] == GENERATOR_VERSION
    assert len(first.metadata["source_sha256"]["network"]) == 64


def test_different_seed_or_day_changes_ids_and_seed_changes_business_values():
    first = generate_simulated_batch(config())
    other_seed = generate_simulated_batch(dataclasses.replace(config(), seed=8))
    other_day = generate_simulated_batch(dataclasses.replace(config(), operating_date="2026-10-02"))
    assert first.metadata["batch_id"] != other_seed.metadata["batch_id"] != other_day.metadata["batch_id"]
    assert {(o.quantity, o.earliest_min, o.latest_min) for o in first.orders} != {
        (o.quantity, o.earliest_min, o.latest_min) for o in other_seed.orders}
    assert not {o.order_id for o in first.orders} & {o.order_id for o in other_day.orders}


@pytest.mark.parametrize("scenario", PROFILES)
def test_stock_fleet_windows_and_sources_obey_existing_contract(scenario):
    batch = generate_simulated_batch(config(scenario))
    points = {p.facility_id: p for p in read_supply_points()}
    hospitals = {n["facility_id"]: n for n in read_network()["nodes"]}
    demand = Counter()
    assert len({o.order_id for o in batch.orders}) == len(batch.orders)
    assert len({o.destination_facility_id for o in batch.orders}) == len(batch.orders)
    for order in batch.orders:
        node = hospitals[order.destination_facility_id]
        assert node["earliest_min"] <= order.earliest_min <= order.latest_min <= node["latest_min"]
        assert supplies_product(points[order.origin_facility_id], order.product_id)
        demand[(order.origin_facility_id, order.product_id)] += order.quantity
    for lot in batch.inventory:
        assert lot.available_quantity >= demand[(lot.facility_id, lot.product_id)]
    assert len(batch.vehicles) == batch.constraints.max_vehicles
    validate_dispatch_inputs(batch.orders, batch.inventory, batch.vehicles, vehicles_anywhere=True)
    for vehicle in batch.vehicles:
        assert sum(q for _, _, q in vehicle.onboard_spare) < vehicle.capacity
        assert all(zone == vehicle.temperature_zone for _, zone, _ in vehicle.onboard_spare)


def test_routine_varies_quantity_windows_and_products():
    batch = generate_simulated_batch(config())
    assert len({o.quantity for o in batch.orders}) > 1
    assert len({(o.earliest_min, o.latest_min) for o in batch.orders}) > 1
    assert len({o.product_id for o in batch.orders}) == 4


def test_multi_source_spans_sources_and_temperature_groups():
    batch = generate_simulated_batch(config("multi_source"))
    assert len({o.origin_facility_id for o in batch.orders}) >= 3
    assert len({o.temperature_zone for o in batch.orders}) == 3
    plan = plan_delivery_orders(batch.orders, batch.inventory, batch.vehicles, constraints=batch.constraints)
    assert len(plan.zone_plans) >= 4
    assert plan.feasible


def test_urgent_deadline_is_an_explicit_short_window_not_a_hidden_insertion():
    batch = generate_simulated_batch(config("urgent"))
    urgent = [o for o in batch.orders if o.order_id in batch.metadata["urgent_order_ids"]]
    assert len(urgent) == 1
    assert urgent[0].latest_min - urgent[0].earliest_min < min(
        o.latest_min - o.earliest_min for o in batch.orders if o not in urgent)


def test_requested_regular_window_bounds_are_not_silently_clipped():
    batch = generate_simulated_batch(config(window_min=480, window_max=480))
    assert all(o.latest_min - o.earliest_min == 480 for o in batch.orders)
    assert all(o.earliest_min == 540 for o in batch.orders)


def test_capacity_shortage_does_not_expand_the_fleet_to_hide_unserved_orders():
    batch = generate_simulated_batch(config("capacity_shortage"))
    assert len(batch.vehicles) == 1
    plan = plan_delivery_orders(batch.orders, batch.inventory, batch.vehicles, constraints=batch.constraints)
    assert not plan.feasible
    assert sum(len(z.result.metrics.unserved_customer_ids) for z in plan.zone_plans) > 0


def test_custom_products_source_quantities_and_spare_zero_are_respected():
    batch = generate_simulated_batch(config(product_ids=("insulin_2_8",), origin_facility_ids=("D-BUGIS",),
        quantity_min=12, quantity_max=12, window_min=180, window_max=180,
        fleet_size=2, spare_quantity=0, vehicle_capacity=50))
    assert all(o.product_id == "insulin_2_8" and o.origin_facility_id == "D-BUGIS" and o.quantity == 12 for o in batch.orders)
    assert len(batch.vehicles) == 2
    assert all(v.capacity == 50 and not v.onboard_spare for v in batch.vehicles)


@pytest.mark.parametrize("overrides", [
    {"scenario": "unknown"}, {"seed": -1}, {"seed": True}, {"operating_date": "2026-02-30"},
    {"order_count": 15}, {"order_count": 2}, {"quantity_min": 50, "quantity_max": 10},
    {"window_min": 120, "window_max": 60}, {"product_ids": ()}, {"product_ids": ("missing",)},
    {"product_ids": ("insulin_2_8",), "origin_facility_ids": ("D-HOUGANG",)},
    {"origin_facility_ids": ("H-SGH",)}, {"fleet_size": 1}, {"vehicle_capacity": 10},
])
def test_invalid_semantics_are_rejected(overrides):
    values = {"operating_date": "2026-10-01", "seed": 7, **overrides}
    with pytest.raises(ValueError):
        generate_simulated_batch(SimulationConfig(**values))


def test_endpoint_is_read_only_and_exported_config_reproduces_json():
    payload = {"scenario": "multi_source", "operating_date": "2026-10-01", "seed": 7}
    response = client.post("/api/dispatch/simulated-orders", json=payload)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["metadata"]["simulated"] is True and first["note"]
    assert first == client.post("/api/dispatch/simulated-orders", json=first["metadata"]["config"]).json()
    from pathlib import Path
    assert not Path(service.DISPATCH_DATABASE_URL).exists()
    assert not service.RUNS_FILE.exists()
    preview = client.post("/api/dispatch/plan", json=first["plan"])
    assert preview.status_code == 200 and preview.json()["feasible"]


@pytest.mark.parametrize("scenario", ["routine", "urgent", "multi_source"])
def test_postable_plans_execute_with_generator_snapshot_and_selected_date(scenario):
    batch = client.post("/api/dispatch/simulated-orders", json={
        "scenario": scenario, "operating_date": "2026-11-05", "seed": 7}).json()
    created = client.post("/api/dispatch/runs", json={**batch["plan"],
        "dispatch_id": "PLAN-SIM", "command_id": "create-sim"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["operating_date"] == "2026-11-05"
    assert body["simulation"] == batch["metadata"]
    assert len(body["orders"]) == 8
    assert client.get("/api/dispatch/runs/PLAN-SIM").json()["simulation"] == batch["metadata"]
    departed = client.post("/api/dispatch/runs/PLAN-SIM/depart", json={"command_id": "depart-sim", "speed": 0})
    assert departed.status_code == 200, departed.text


def test_infeasible_generated_batch_is_previewable_but_not_committable():
    batch = client.post("/api/dispatch/simulated-orders", json={"scenario": "capacity_shortage", "seed": 7}).json()
    preview = client.post("/api/dispatch/plan", json=batch["plan"])
    assert preview.status_code == 200 and not preview.json()["feasible"]
    response = client.post("/api/dispatch/runs", json={**batch["plan"], "dispatch_id": "PLAN-SHORT", "command_id": "create-short"})
    assert response.status_code == 422


@pytest.mark.parametrize("payload", [{"seed": -1}, {"seed": True}, {"scenario": "missing"}, {"operating_date": "not-a-date"}, {"order_count": 0}, {"unknown_parameter": 1}])
def test_endpoint_rejects_invalid_requests(payload):
    assert client.post("/api/dispatch/simulated-orders", json=payload).status_code == 422


def _completed_generated_run():
    batch = client.post("/api/dispatch/simulated-orders", json={
        "operating_date": "2026-11-05", "seed": 7, "order_count": 2,
        "product_ids": ["vaccine_2_8"], "quantity_min": 12, "quantity_max": 12,
        "fleet_size": 1, "spare_quantity": 0}).json()
    created = client.post("/api/dispatch/runs", json={**batch["plan"], "dispatch_id": "PLAN-DATED", "command_id": "create"})
    assert created.status_code == 200, created.text
    service.depart_dispatch("PLAN-DATED", "depart", speed=0)
    for vehicle_id, vehicle in created.json()["vehicles"].items():
        for index, _ in enumerate(vehicle["remaining_order_ids"]):
            service.deliver_dispatch("PLAN-DATED", vehicle_id, f"deliver-{index}")
    from optimisation.dispatch_repository import load_context, update_context
    context = load_context(service.DISPATCH_DATABASE_URL, "PLAN-DATED")
    context["clock"] = service.make_clock(1080, 0)
    update_context(service.DISPATCH_DATABASE_URL, "PLAN-DATED", context)
    completed = service.tick_dispatch("PLAN-DATED")
    assert completed["status"] == "completed"
    return batch, completed


def test_generated_snapshot_survives_fixed_batch_next_day_without_claiming_regeneration():
    batch, completed = _completed_generated_run()
    replenishments = [{**batch["plan"]["inventory"][0], "lot_id": "LOT-NEXT-DAY", "available_quantity": 24}]
    request = {"replenishments": replenishments}
    preview = client.post("/api/dispatch/runs/PLAN-DATED/overnight-preview", json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["tomorrow"]["operating_date"] == "2026-11-06"
    accepted = client.post("/api/dispatch/runs/PLAN-DATED/overnight-accept", json={
        **request, "command_id": "parking", "expected_version": completed["version"]})
    assert accepted.status_code == 200, accepted.text
    next_day = client.post("/api/dispatch/runs/PLAN-DATED/next-day", json={
        "dispatch_id": "PLAN-TOMORROW", "command_id": "next", "expected_version": accepted.json()["version"], "depart": False})
    assert next_day.status_code == 200, next_day.text
    assert next_day.json()["operating_date"] == "2026-11-06"
    assert next_day.json()["simulation"]["config"]["operating_date"] == "2026-11-05"
    assert next_day.json()["simulation"]["carried_forward_to"] == "2026-11-06"


def test_explicit_tomorrow_batch_cannot_silently_change_its_date():
    batch, _ = _completed_generated_run()
    response = client.post("/api/dispatch/runs/PLAN-DATED/overnight-preview", json={
        "tomorrow": {**batch["plan"], "operating_date": "2026-12-01"}})
    assert response.status_code == 409
    assert "next day" in response.text


def test_old_run_without_operating_date_keeps_the_existing_clock_date_fallback():
    batch, _ = _completed_generated_run()
    from optimisation.dispatch_repository import load_context, update_context
    import datetime
    context = load_context(service.DISPATCH_DATABASE_URL, "PLAN-DATED")
    context.pop("operating_date")
    expected = (datetime.datetime.fromisoformat(context["clock"]["started_real"]).date()
                + datetime.timedelta(days=1)).isoformat()
    update_context(service.DISPATCH_DATABASE_URL, "PLAN-DATED", context)
    preview = client.post("/api/dispatch/runs/PLAN-DATED/overnight-preview", json={
        "replenishments": [{**batch["plan"]["inventory"][0], "lot_id": "LOT-LEGACY-NEXT", "available_quantity": 24}]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["tomorrow"]["operating_date"] == expected
