"""Deterministic nearest-insertion baseline for Solomon VRPTW."""
from __future__ import annotations

from .models import ReplanResult, SolomonInstance, VehicleRoute
from .routing import (
    EndLegFn,
    LegFn,
    build_result,
    euclidean_leg,
    evaluate_route,
)


def _best_feasible_insertion(
    instance: SolomonInstance,
    current_ids: tuple[int, ...],
    unassigned: set[int],
    vehicle_id: int,
    leg_fn: LegFn,
    max_stops_per_vehicle: int | None = None,
    end_leg_fn: EndLegFn | None = None,
    mileage_limit: float | None = None,
) -> VehicleRoute | None:
    """Return the minimum-distance feasible one-customer insertion."""
    current = evaluate_route(
        instance, current_ids, vehicle_id=vehicle_id, leg_fn=leg_fn,
        end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
    )
    by_id = {node.node_id: node for node in instance.nodes}
    best: tuple[tuple[float, float, int, int, int], VehicleRoute] | None = None

    for customer_id in sorted(unassigned):
        customer = by_id[customer_id]
        for position in range(len(current_ids) + 1):
            candidate_ids = (
                current_ids[:position] + (customer_id,) + current_ids[position:]
            )
            if (max_stops_per_vehicle is not None
                    and len(candidate_ids) > max_stops_per_vehicle):
                continue
            candidate = evaluate_route(
                instance, candidate_ids, vehicle_id=vehicle_id, leg_fn=leg_fn,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
            )
            if not candidate.feasible:
                continue
            predecessor_id = 0 if position == 0 else current_ids[position - 1]
            nearest_leg, _ = leg_fn(by_id[predecessor_id], customer)
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


def solve_greedy(
    instance: SolomonInstance, *, leg_fn: LegFn = euclidean_leg,
    max_stops_per_vehicle: int | None = None,
    end_leg_fn: EndLegFn | None = None,
    mileage_limit: float | None = None,
) -> ReplanResult:
    """Construct feasible routes with nearest-distance time-window insertion.

    One vehicle is filled at a time.  Every proposed insertion is scheduled
    from the depot and accepted only if capacity, customer time windows, the
    depot return window and the per-vehicle mileage cap remain feasible.
    Customers that cannot be served within the available fleet are reported
    explicitly as unserved.

    Because the mileage cap is enforced inside the insertion test, a tight cap
    makes the first vehicle stop taking orders and the loop opens the next one —
    "share a truck while it stays under the cap, otherwise send another".
    """
    unassigned = {node.node_id for node in instance.customers}
    routes: list[VehicleRoute] = []
    if max_stops_per_vehicle is not None and max_stops_per_vehicle < 1:
        raise ValueError("max_stops_per_vehicle must be a positive integer")
    if mileage_limit is not None and mileage_limit <= 0:
        raise ValueError("mileage_limit must be positive")

    for vehicle_id in range(1, instance.vehicle_nr + 1):
        ids: tuple[int, ...] = ()
        route: VehicleRoute | None = None
        while unassigned:
            candidate = _best_feasible_insertion(
                instance, ids, unassigned, vehicle_id, leg_fn,
                max_stops_per_vehicle=max_stops_per_vehicle,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
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
