"""W1-C tests for route scheduling, greedy baseline and OR-Tools v1."""
from __future__ import annotations

import pytest

from optimisation.greedy import solve_greedy
from optimisation.models import Node, SolomonInstance
from optimisation.ortools_solver import solve_ortools
from optimisation.reshipment import build_reshipment_order, plan_reshipment_route
from optimisation.routing import build_result, evaluate_route
from optimisation.solomon_loader import SOLOMON_DIR, SOLOMON_NAMES, load_instance


def _small_instance(*, vehicles=2, capacity=10) -> SolomonInstance:
    return SolomonInstance(
        instance="TEST",
        vehicle_nr=vehicles,
        capacity=capacity,
        nodes=(
            Node(0, 0, 0, 0, 0, 100, 0),
            Node(1, 3, 0, 4, 5, 20, 2),
            Node(2, 6, 0, 4, 10, 30, 2),
            Node(3, 0, 4, 4, 0, 30, 2),
        ),
    )


def test_route_schedule_waits_and_accumulates_load():
    route = evaluate_route(_small_instance(), [1, 2])
    assert route.feasible
    assert route.total_load == 8
    assert route.stops[0].arrival == pytest.approx(3.0)
    assert route.stops[0].service_start == pytest.approx(5.0)
    assert route.stops[1].cumulative_load == 8
    assert route.total_distance == pytest.approx(12.0)


def test_route_evaluation_reports_capacity_and_time_violations():
    instance = _small_instance(capacity=5)
    late = Node(2, 60, 0, 4, 0, 10, 2)
    instance = SolomonInstance(
        instance=instance.instance,
        vehicle_nr=instance.vehicle_nr,
        capacity=instance.capacity,
        nodes=(instance.nodes[0], instance.nodes[1], late, instance.nodes[3]),
    )
    route = evaluate_route(instance, [1, 2])
    assert not route.feasible
    assert route.capacity_violation_units == 3
    assert route.time_window_violations == 1


@pytest.mark.parametrize("stem", SOLOMON_NAMES)
def test_greedy_serves_all_six_instances_feasibly(stem: str):
    result = solve_greedy(load_instance(SOLOMON_DIR / f"{stem}.json"))
    assert result.feasible
    assert result.metrics.served_customers == 100
    assert result.metrics.vehicles_used <= 25
    assert result.metrics.on_time_rate == 1.0


def test_greedy_is_deterministic():
    instance = load_instance(SOLOMON_DIR / "c101.json")
    first = solve_greedy(instance)
    second = solve_greedy(instance)
    assert first == second


def test_unserved_customers_are_explicit_when_fleet_is_too_small():
    result = solve_greedy(_small_instance(vehicles=1, capacity=5))
    assert not result.feasible
    assert result.metrics.served_customers == 1
    assert len(result.metrics.unserved_customer_ids) == 2
    assert result.metrics.violation_count == 2


def test_result_rejects_duplicate_service_across_vehicles():
    instance = _small_instance()
    route1 = evaluate_route(instance, [1], vehicle_id=1)
    route2 = evaluate_route(instance, [1], vehicle_id=2)
    with pytest.raises(ValueError, match="same customer twice"):
        build_result(instance, "bad", [route1, route2])


def test_ortools_solves_small_instance_with_hard_constraints():
    result = solve_ortools(_small_instance(), time_limit_seconds=1)
    assert result.feasible
    assert result.metrics.served_customers == 3
    assert result.metrics.on_time_rate == 1.0


def _closed_record(*, reshipment=True, destination=None):
    event = {"product_id": "vaccine_2_8"}
    if destination is not None:
        event["destination_facility_id"] = destination
    return {
        "run_id": "R20260912-001",
        "created_at": "2026-09-12T09:00:00",
        "disposition": "scrap" if reshipment else "release",
        "reshipment_required": reshipment,
        "event": event,
    }


def test_build_reshipment_order_matches_kg_order_id():
    order = build_reshipment_order(_closed_record())
    assert order is not None
    assert order.order_id == "RO-R20260912-001"
    assert order.origin_facility_id == "W-KN-PIONEER"
    assert order.demand_units == 30


def test_build_reshipment_order_skips_non_reshipment_case():
    assert build_reshipment_order(_closed_record(reshipment=False)) is None


def test_plan_reshipment_route_uses_verified_singapore_instance():
    order = build_reshipment_order(_closed_record())
    result = plan_reshipment_route(order)
    assert result.routes
    assert result.metrics.vehicles_used >= 1


def test_plan_reshipment_route_rejects_unknown_destination():
    order = build_reshipment_order(_closed_record(destination="H-NOT-REAL"))
    with pytest.raises(ValueError, match="H-NOT-REAL"):
        plan_reshipment_route(order)
