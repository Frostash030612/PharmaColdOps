"""Deterministic nearest-insertion baseline for Solomon VRPTW."""
from __future__ import annotations

from .models import ReplanResult, SolomonInstance, VehicleRoute
from .routing import build_result, euclidean, evaluate_route


def _best_feasible_insertion(
    instance: SolomonInstance,
    current_ids: tuple[int, ...],
    unassigned: set[int],
    vehicle_id: int,
) -> VehicleRoute | None:
    """Return the minimum-distance feasible one-customer insertion."""
    current = evaluate_route(instance, current_ids, vehicle_id=vehicle_id)
    by_id = {node.node_id: node for node in instance.nodes}
    best: tuple[tuple[float, float, int, int, int], VehicleRoute] | None = None

    for customer_id in sorted(unassigned):
        customer = by_id[customer_id]
        for position in range(len(current_ids) + 1):
            candidate_ids = (
                current_ids[:position] + (customer_id,) + current_ids[position:]
            )
            candidate = evaluate_route(
                instance, candidate_ids, vehicle_id=vehicle_id
            )
            if not candidate.feasible:
                continue
            predecessor_id = 0 if position == 0 else current_ids[position - 1]
            nearest_leg = euclidean(by_id[predecessor_id], customer)
            added_distance = candidate.total_distance - current.total_distance
            key = (
                round(added_distance, 12),
                round(nearest_leg, 12),
                customer.latest,
                customer_id,
                position,
            )
            if best is None or key < best[0]:
                best = (key, candidate)
    return None if best is None else best[1]


def solve_greedy(instance: SolomonInstance) -> ReplanResult:
    """Construct feasible routes with nearest-distance time-window insertion.

    One vehicle is filled at a time.  Every proposed insertion is scheduled
    from the depot and accepted only if capacity, customer time windows and
    the depot return window remain feasible.  Customers that cannot be served
    within the available fleet are reported explicitly as unserved.
    """
    unassigned = {node.node_id for node in instance.customers}
    routes: list[VehicleRoute] = []

    for vehicle_id in range(1, instance.vehicle_nr + 1):
        ids: tuple[int, ...] = ()
        route: VehicleRoute | None = None
        while unassigned:
            candidate = _best_feasible_insertion(
                instance, ids, unassigned, vehicle_id
            )
            if candidate is None:
                break
            route = candidate
            ids = route.customer_ids
            # The accepted sequence contains exactly one id not present before.
            accepted = set(ids) & unassigned
            if len(accepted) != 1:
                raise RuntimeError("greedy insertion did not add exactly one customer")
            unassigned.remove(accepted.pop())

        if route is None:
            break
        routes.append(route)
        if not unassigned:
            break

    return build_result(instance, "greedy-nearest-insertion", routes)
