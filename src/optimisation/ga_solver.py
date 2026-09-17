"""Genetic-algorithm VRPTW solver (C's batch 6 — doc A1).

**Encoding.** One chromosome is a permutation of every customer id ("giant
tour").  A *split* pass cuts that permutation into depot-to-depot routes: the
next customer joins the open route while capacity, its own time window and the
depot-return window all still hold, otherwise a new vehicle is opened; once the
fleet limit is reached the remaining customers are reported as unserved instead
of being hidden.

**Fitness.** A single scalar following the classic lexicographic VRPTW
objective: serve everyone, then use the fewest vehicles, then shorten distance.

**Why no library.** ``deap`` is declared in ``requirements.txt`` but was never
used — and recent deap builds (1.4.4) hard-depend on ``moocore``, so using it
would add a wheel that this project's environments cannot reliably install (pip
and PowerShell both fail on TLS here, see HANDOFF §7).  A standard-library GA
keeps the three-way comparison reproducible on any teammate's machine with no
new install, so ``requirements.txt`` no longer declares deap.

**No local search.** The comparison produced by ``scripts/run_routing_baselines.py``
is between the algorithms *as implemented*, so this stays a pure metaheuristic:
no 2-opt or other polishing is applied to GA offspring.
"""
from __future__ import annotations

import random
import time
from collections.abc import Sequence

from .greedy import solve_greedy
from .models import ReplanResult, SolomonInstance, VehicleRoute
from .routing import LegFn, build_result, euclidean_leg, evaluate_route

#: Fitness weights.  An unserved customer dominates vehicle count, which in turn
#: dominates distance — the standard lexicographic VRPTW objective expressed as
#: one scalar so a plain GA can rank any two solutions.
UNSERVED_PENALTY = 1_000_000.0
VEHICLE_PENALTY = 1_000.0

EPSILON = 1e-9

ALGORITHM_NAME = "ga-order-crossover"


def _schedule_block(
    sequence: Sequence, start: int, end: int, leg_fn: LegFn, depot, depot_ready: float,
    horizon: float,
) -> tuple[float, bool]:
    """Distance and feasibility of ``depot → sequence[start:end] → depot``."""
    current = depot
    departure = depot_ready
    distance = 0.0
    for index in range(start, end):
        node = sequence[index]
        leg, travel = leg_fn(current, node)
        distance += leg
        service_start = max(departure + travel, float(node.earliest))
        if service_start > node.latest + EPSILON:
            return distance, False
        departure = service_start + node.service
        current = node
    leg, travel = leg_fn(current, depot)
    distance += leg
    if departure + travel > horizon + EPSILON:
        return distance, False
    return distance, True


def split_permutation(
    instance: SolomonInstance,
    order: Sequence[int],
    *,
    leg_fn: LegFn = euclidean_leg,
) -> tuple[list[list[int]], list[int], float]:
    """Cut a giant tour into routes with the classic *optimal* split procedure.

    A greedy left-to-right cut is a poor decoder: it fills a vehicle until the
    next customer no longer fits, which routinely splits one full vehicle into
    two half-full ones and can never recover.  Here a dynamic program over
    prefixes keeps the best ``(unserved, vehicles, distance)`` triple for every
    prefix, so for a fixed customer sequence the partition — and therefore the
    vehicle count — is optimal.  That is what makes the fitness landscape a
    function of the *sequence* rather than of the decoder.

    Returns ``(routes, unserved_customer_ids, total_distance)``.  The schedule
    matches :func:`routing.evaluate_route` exactly and
    ``tests/test_ga_solver.py`` cross-checks the two.

    Pruning follows from prepending monotonicity: adding another customer to
    the *front* of a block pushes every later service start later (distances
    obey the triangle inequality), so once a block ending at ``i`` is
    infeasible every longer block ending there is too, and the scan can stop.
    A wrongly pruned branch could only cost optimality, never validity, because
    every accepted block is scheduled and checked first.
    """
    by_id = {node.node_id: node for node in instance.nodes}
    sequence = [by_id[customer_id] for customer_id in order]
    depot = instance.depot
    depot_ready = float(depot.earliest)
    horizon = float(depot.latest)
    capacity = instance.capacity
    fleet_limit = instance.vehicle_nr
    count = len(sequence)

    infinity = float("inf")
    # (unserved, vehicles, distance) for each prefix; skipping is always legal,
    # so every prefix is reachable even when the fleet cannot cover everyone.
    best: list[tuple[int, int, float]] = [(0, 0, 0.0)] + [(0, 0, infinity)] * count
    parent: list[int] = [0] * (count + 1)
    is_block: list[bool] = [False] * (count + 1)

    for end in range(1, count + 1):
        unserved, vehicles, distance = best[end - 1]
        best[end] = (unserved + 1, vehicles, distance)
        parent[end] = end - 1
        is_block[end] = False

        load = 0
        for start in range(end, 0, -1):
            node = sequence[start - 1]
            load += node.demand
            if load > capacity:
                break
            block_distance, feasible = _schedule_block(
                sequence, start - 1, end, leg_fn, depot, depot_ready, horizon
            )
            if not feasible:
                break
            previous_unserved, previous_vehicles, previous_distance = best[start - 1]
            if previous_vehicles + 1 > fleet_limit:
                continue
            candidate = (
                previous_unserved,
                previous_vehicles + 1,
                previous_distance + block_distance,
            )
            if candidate < best[end]:
                best[end] = candidate
                parent[end] = start - 1
                is_block[end] = True

    routes: list[list[int]] = []
    unserved_ids: list[int] = []
    cursor = count
    while cursor > 0:
        start = parent[cursor]
        if is_block[cursor]:
            routes.append([sequence[index].node_id for index in range(start, cursor)])
        else:
            unserved_ids.append(sequence[cursor - 1].node_id)
        cursor = start

    routes.reverse()
    unserved_ids.reverse()
    return routes, unserved_ids, best[count][2]


def _fitness(
    instance: SolomonInstance, order: Sequence[int], *, leg_fn: LegFn
) -> float:
    routes, unserved, distance = split_permutation(instance, order, leg_fn=leg_fn)
    return (
        len(unserved) * UNSERVED_PENALTY
        + len(routes) * VEHICLE_PENALTY
        + distance
    )


def _order_crossover(rng: random.Random, first: Sequence[int], second: Sequence[int]) -> list[int]:
    """Order crossover (OX): keep a slice of ``first``, fill the rest from ``second``."""
    size = len(first)
    if size < 2:
        return list(first)
    left, right = sorted(rng.sample(range(size), 2))
    child: list[int | None] = [None] * size
    child[left:right + 1] = first[left:right + 1]
    taken = set(first[left:right + 1])
    filler = [gene for gene in second if gene not in taken]
    positions = list(range(right + 1, size)) + list(range(0, left))
    for position, gene in zip(positions, filler):
        child[position] = gene
    return [gene for gene in child if gene is not None]


def _mutate(rng: random.Random, order: list[int], rate: float) -> None:
    """Permutation-preserving moves: segment reversal, relocate, random swap.

    Reversal is the 2-opt analogue; relocation (pull one customer out and drop
    it elsewhere) is the move VRPTW sequences respond to most strongly, because
    it can move a customer into a different vehicle without disturbing the rest
    of the order.
    """
    if len(order) < 2:
        return
    if rng.random() < rate:
        left, right = sorted(rng.sample(range(len(order)), 2))
        order[left:right + 1] = reversed(order[left:right + 1])
    if rng.random() < rate:
        source = rng.randrange(len(order))
        gene = order.pop(source)
        order.insert(rng.randrange(len(order) + 1), gene)
    for _ in range(2):
        if rng.random() < rate:
            i, j = rng.randrange(len(order)), rng.randrange(len(order))
            order[i], order[j] = order[j], order[i]


def _perturb(rng: random.Random, order: list[int], moves: int) -> list[int]:
    """A copy of ``order`` with ``moves`` random permutation-preserving moves."""
    child = list(order)
    for _ in range(max(1, moves)):
        _mutate(rng, child, 1.0)
    return child


def _tournament(
    rng: random.Random, population: list[list[int]], fitness: list[float], size: int
) -> list[int]:
    best_index = rng.randrange(len(population))
    for _ in range(size - 1):
        challenger = rng.randrange(len(population))
        if fitness[challenger] < fitness[best_index]:
            best_index = challenger
    return population[best_index]


def solve_ga(
    instance: SolomonInstance,
    *,
    leg_fn: LegFn = euclidean_leg,
    seed: int = 42,
    time_limit_seconds: float = 10.0,
    population_size: int = 60,
    elite: int = 2,
    tournament_size: int = 3,
    mutation_rate: float = 0.3,
    max_generations: int | None = None,
) -> ReplanResult:
    """Evolve a giant tour, then split it into the routes we report.

    ``time_limit_seconds`` makes this an anytime algorithm, exactly like
    :func:`ortools_solver.solve_ortools` — the number of generations completed
    therefore depends on machine speed, so the comparison table records the
    budget and the seed rather than claiming bit-identical runs.  Pass
    ``max_generations`` to make a run fully deterministic (used by the tests).

    The returned routes are rebuilt through :func:`routing.evaluate_route`, so
    the schedule attached to the result is authoritative even though the search
    itself used the cheaper incremental decoder.
    """
    if instance.load_model == "pickup_delivery":
        # The giant tour is one sequence over ONE origin: the split procedure then
        # cuts it into routes that all start there, and the load is assumed to be
        # on board from the start. A pickup-delivery instance breaks both
        # assumptions — its routes visit several sources and its load rises and
        # falls — so a permutation cannot describe a solution, let alone a good
        # one. Refuse instead of returning a schedule with deliveries before their
        # pickups (2026-09-16, PDPTW step 4).
        raise ValueError(
            "the genetic solver plans a single origin with the load taken at the "
            "route start; it cannot express pickup-delivery pairs (several sources, "
            "load rising and falling). Use algorithm='ortools' or the greedy pair "
            "insertion for pickup-delivery orders"
        )
    if population_size < 2:
        raise ValueError("population_size must be >= 2")
    if elite < 0 or elite * 2 > population_size:
        raise ValueError("elite must be >= 0 and at most half the population")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be > 0")

    # The budget covers the whole call, construction included, so it means the
    # same thing as OR-Tools' ``time_limit``.  Construction is not interruptible
    # (the greedy seed on the capacity-700 instances alone costs ~3.5s), so the
    # real total is ``max(budget, construction)`` plus at most one generation.
    deadline = time.monotonic() + time_limit_seconds

    customers = [node.node_id for node in instance.customers]
    if not customers:
        return build_result(instance, ALGORITHM_NAME, ())

    by_id = {node.node_id: node for node in instance.nodes}
    rng = random.Random(seed)

    def random_order() -> list[int]:
        order = list(customers)
        rng.shuffle(order)
        return order

    def earliest_deadline_order() -> list[int]:
        return sorted(customers, key=lambda cid: (by_id[cid].latest, cid))

    def nearest_neighbour_order() -> list[int]:
        remaining = set(customers)
        order: list[int] = []
        current = instance.depot
        while remaining:
            nxt = min(remaining, key=lambda cid: (leg_fn(current, by_id[cid])[0], cid))
            order.append(nxt)
            remaining.discard(nxt)
            current = by_id[nxt]
        return order

    def greedy_tour() -> list[int]:
        """The committed greedy solution, flattened into a giant tour.

        Seeding a metaheuristic with a constructive heuristic is standard (and
        ``ortools_solver`` likewise starts from a first-solution strategy), but
        it does change what the comparison means: this GA *improves on* greedy
        rather than being independent of it, which the report states explicitly.
        Customers greedy could not serve are appended in deadline order so the
        seed is always a full permutation.
        """
        result = solve_greedy(instance, leg_fn=leg_fn)
        tour = [cid for route in result.routes for cid in route.customer_ids]
        if len(tour) < len(customers):
            served = set(tour)
            tour.extend(cid for cid in earliest_deadline_order() if cid not in served)
        return tour

    # Seed with deterministic constructive orders so the GA starts from
    # something sane, then fill up with *perturbed copies* of the constructive
    # solution rather than random permutations.
    #
    # Random permutations are useless here: on C101 an unconstrained shuffle
    # leaves roughly 70 customers unservable, and the 1e6-per-customer penalty
    # puts them so far from any feasible sequence that selection cannot bridge
    # the gap (measured: 1000 generations of pure-random population never
    # improved on the constructive seed once).  Perturbing a good sequence keeps
    # every individual feasible, which is what lets the GA actually climb.
    population: list[list[int]] = []
    constructive = greedy_tour()
    for seed_order in (constructive, nearest_neighbour_order(), earliest_deadline_order()):
        if len(seed_order) == len(customers) and seed_order not in population:
            population.append(seed_order)
    while len(population) < population_size:
        population.append(_perturb(rng, constructive, rng.randint(1, 6)))
    population = population[:population_size]

    fitness = [_fitness(instance, order, leg_fn=leg_fn) for order in population]
    best_index = min(range(len(population)), key=lambda i: fitness[i])
    best_order = list(population[best_index])
    best_fitness = fitness[best_index]

    generation = 0
    while True:
        if max_generations is not None and generation >= max_generations:
            break
        if time.monotonic() >= deadline:
            break
        generation += 1

        ranked = sorted(range(len(population)), key=lambda i: fitness[i])
        offspring = [population[i] for i in ranked[:elite]]
        while len(offspring) < population_size:
            parent_a = _tournament(rng, population, fitness, tournament_size)
            parent_b = _tournament(rng, population, fitness, tournament_size)
            child = _order_crossover(rng, parent_a, parent_b)
            _mutate(rng, child, mutation_rate)
            offspring.append(child)

        population = offspring
        fitness = [_fitness(instance, order, leg_fn=leg_fn) for order in population]
        best_index = min(range(len(population)), key=lambda i: fitness[i])
        if fitness[best_index] < best_fitness:
            best_fitness = fitness[best_index]
            best_order = list(population[best_index])

    route_ids, _unserved, _distance = split_permutation(instance, best_order, leg_fn=leg_fn)
    routes: list[VehicleRoute] = [
        evaluate_route(instance, ids, vehicle_id=index, leg_fn=leg_fn)
        for index, ids in enumerate(route_ids, start=1)
    ]
    return build_result(instance, ALGORITHM_NAME, routes)
