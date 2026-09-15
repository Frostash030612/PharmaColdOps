"""Tests for the genetic-algorithm VRPTW solver (M5 / doc A1).

The decoder is the load-bearing part: every fitness value the GA ranks on comes
from :func:`ga_solver.split_permutation`, which must agree with the shared,
audited :func:`routing.evaluate_route` or the search optimises a fiction.  The
first test cross-checks the two on random permutations; the rest pin the
contract (shared output type), determinism, the fleet limit and the guarantee
that the GA never does worse than the constructive seed it starts from.
"""
from __future__ import annotations

import random

import pytest

from optimisation.ga_solver import (
    ALGORITHM_NAME,
    _fitness,
    _order_crossover,
    solve_ga,
    split_permutation,
)
from optimisation.greedy import solve_greedy
from optimisation.models import ReplanResult
from optimisation.routing import euclidean_leg, evaluate_route
from optimisation.solomon_loader import load_dir


@pytest.fixture(scope="module")
def instances():
    return load_dir()


def test_split_permutation_agrees_with_evaluate_route(instances):
    """The incremental decoder must reproduce the shared schedule exactly."""
    instance = instances["C101"]
    customer_ids = [node.node_id for node in instance.customers]
    rng = random.Random(20260914)
    for _ in range(25):
        order = list(customer_ids)
        rng.shuffle(order)
        routes, unserved, distance = split_permutation(instance, order, leg_fn=euclidean_leg)
        evaluated = [
            evaluate_route(instance, ids, vehicle_id=index, leg_fn=euclidean_leg)
            for index, ids in enumerate(routes, start=1)
        ]
        # Feasibility: the decoder may only cut where the shared scheduler agrees.
        assert all(route.feasible for route in evaluated)
        # Distance: the returned total is the sum of the routes it returned.
        assert sum(route.total_distance for route in evaluated) == pytest.approx(distance)
        # Coverage: every customer is either served once or reported unserved.
        served = [cid for ids in routes for cid in ids]
        assert sorted(served + list(unserved)) == sorted(customer_ids)
        assert len(served) == len(set(served))
        # Hard fleet limit.
        assert len(routes) <= instance.vehicle_nr


def test_split_permutation_keeps_a_feasible_partition_of_a_good_order(instances):
    """Given the constructive order, the split must serve everyone."""
    instance = instances["C101"]
    greedy = solve_greedy(instance)
    order = [cid for route in greedy.routes for cid in route.customer_ids]
    routes, unserved, distance = split_permutation(instance, order, leg_fn=euclidean_leg)
    assert unserved == []
    assert distance <= greedy.metrics.total_distance + 1e-9
    assert len(routes) <= greedy.metrics.vehicles_used


def test_ga_returns_the_shared_result_contract(instances):
    instance = instances["C101"]
    result = solve_ga(instance, seed=1, time_limit_seconds=30, max_generations=40)
    assert isinstance(result, ReplanResult)
    assert result.algorithm == ALGORITHM_NAME
    assert result.instance == instance.instance
    assert result.metrics.vehicles_used >= 1
    assert result.metrics.served_customers == instance.n_customers
    assert result.metrics.violation_count == 0


def test_ga_is_deterministic_for_a_fixed_seed(instances):
    """A generation-capped run is reproducible; a different seed may differ."""
    instance = instances["C101"]
    first = solve_ga(instance, seed=7, time_limit_seconds=60, max_generations=60)
    second = solve_ga(instance, seed=7, time_limit_seconds=60, max_generations=60)
    assert first.metrics == second.metrics
    assert [r.customer_ids for r in first.routes] == [r.customer_ids for r in second.routes]


def test_ga_never_does_worse_than_its_constructive_seed(instances):
    """The greedy tour is in the initial population, so elitism must keep it."""
    instance = instances["R101"]
    greedy = solve_greedy(instance)
    result = solve_ga(instance, seed=3, time_limit_seconds=60, max_generations=60)
    assert result.metrics.vehicles_used <= greedy.metrics.vehicles_used
    assert len(result.metrics.unserved_customer_ids) <= len(
        greedy.metrics.unserved_customer_ids
    )
    assert result.metrics.violation_count == 0


def test_ga_reports_unserved_customers_when_the_fleet_is_too_small(instances):
    """A hard fleet limit must surface as explicit unserved customers."""
    import dataclasses

    instance = dataclasses.replace(instances["C101"], vehicle_nr=4)
    result = solve_ga(instance, seed=5, time_limit_seconds=30, max_generations=40)
    assert result.metrics.vehicles_used <= 4
    assert result.metrics.unserved_customer_ids, "a 4-vehicle fleet cannot serve 100 customers"
    assert result.metrics.served_customers + len(result.metrics.unserved_customer_ids) == (
        instance.n_customers
    )
    # Every customer it *did* place must still be served on time and in capacity.
    # (``violation_count`` deliberately also counts unserved customers, so the
    # constraint counters are asserted individually here.)
    assert result.metrics.time_window_violations == 0
    assert result.metrics.capacity_violations == 0
    assert result.metrics.depot_return_violations == 0
    assert result.metrics.vehicle_limit_violations == 0


def test_ga_respects_its_time_budget(instances):
    """The budget covers the whole call (construction included), like OR-Tools'."""
    import time

    instance = instances["C101"]  # its greedy seed is the cheapest of the six
    budget = 1.5
    started = time.monotonic()
    solve_ga(instance, seed=2, time_limit_seconds=budget)
    elapsed = time.monotonic() - started
    # Construction is not interruptible and the deadline is only checked between
    # generations, so allow that much slack rather than pretending to be real-time.
    assert elapsed < budget + 2.5, f"budget {budget}s overshot: {elapsed:.1f}s"


def test_order_crossover_returns_a_valid_permutation():
    rng = random.Random(11)
    parent_a = list(range(20))
    parent_b = list(reversed(parent_a))
    for _ in range(50):
        child = _order_crossover(rng, parent_a, parent_b)
        assert sorted(child) == sorted(parent_a)


def test_ga_rejects_impossible_parameters(instances):
    instance = instances["C101"]
    with pytest.raises(ValueError):
        solve_ga(instance, population_size=1)
    with pytest.raises(ValueError):
        solve_ga(instance, elite=40, population_size=60)
    with pytest.raises(ValueError):
        solve_ga(instance, time_limit_seconds=0)


def test_fitness_penalises_unserved_customers(instances):
    """Serving everyone must dominate any distance saving."""
    instance = instances["C101"]
    served_everyone = [
        cid for route in solve_greedy(instance).routes for cid in route.customer_ids
    ]
    shuffled = [node.node_id for node in instance.customers]
    random.Random(99).shuffle(shuffled)
    assert len(shuffled) == len(served_everyone)
    assert _fitness(instance, served_everyone, leg_fn=euclidean_leg) < _fitness(
        instance, shuffled, leg_fn=euclidean_leg
    )
