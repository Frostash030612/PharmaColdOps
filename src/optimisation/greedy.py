"""Deterministic nearest-insertion baseline for Solomon VRPTW.

Two models live here. The grouped model inserts one customer at a time: the load
is on board from the route's single start, so any order fits anywhere capacity,
time windows and the mileage cap allow. The pickup-delivery model inserts one
whole **pair** at a time — a truck has to collect goods before it can hand them
over, so the pickup and the delivery are placed together and the capacity test
sees the real load profile in between (2026-09-16, PDPTW step 4).
"""
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
            predecessor_id = ((instance.vehicle_start_node_ids[vehicle_id - 1]
                               if instance.vehicle_start_node_ids else 0)
                              if position == 0 else current_ids[position - 1])
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


def pair_nodes(instance: SolomonInstance) -> dict[str, tuple[int, int]]:
    """``order_id -> (pickup node id, delivery node id)`` for a paired instance."""
    pickups = {node.pair_id: node.node_id for node in instance.pickups}
    deliveries = {node.pair_id: node.node_id for node in instance.deliveries}
    missing = sorted(set(pickups) - set(deliveries)) + sorted(set(deliveries) - set(pickups))
    if missing:
        raise ValueError(f"pickup-delivery pairs are incomplete: {missing}")
    return {pair_id: (pickups[pair_id], deliveries[pair_id]) for pair_id in deliveries}


def _best_feasible_pair_insertion(
    instance: SolomonInstance,
    current_ids: tuple[int, ...],
    unassigned: set[str],
    vehicle_id: int,
    leg_fn: LegFn,
    max_stops_per_vehicle: int | None = None,
    end_leg_fn: EndLegFn | None = None,
    mileage_limit: float | None = None,
) -> VehicleRoute | None:
    """Return the minimum-distance feasible insertion of one whole pair.

    Every ``(i, j)`` with ``i <= j`` is tried: the pickup goes in at ``i`` and the
    delivery at ``j`` of the original sequence, which covers "deliver it next",
    "deliver it last" and everything between. The candidate is scheduled in full,
    so ``evaluate_route`` judges capacity on the peak load rather than on the
    delivery's own quantity — inserting the two nodes independently and hoping
    the pairing survived is exactly the bug this avoids.
    """
    current = evaluate_route(
        instance, current_ids, vehicle_id=vehicle_id, leg_fn=leg_fn,
        end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
    )
    by_id = {node.node_id: node for node in instance.nodes}
    pairs = pair_nodes(instance)
    best: tuple[tuple[float, float, float, str, int, int], VehicleRoute] | None = None

    for pair_id in sorted(unassigned):
        pickup_id, delivery_id = pairs[pair_id]
        pickup = by_id[pickup_id]
        for pickup_at in range(len(current_ids) + 1):
            for delivery_at in range(pickup_at, len(current_ids) + 1):
                candidate_ids = (
                    current_ids[:pickup_at] + (pickup_id,)
                    + current_ids[pickup_at:delivery_at] + (delivery_id,)
                    + current_ids[delivery_at:]
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
                predecessor_id = ((instance.vehicle_start_node_ids[vehicle_id - 1]
                                   if instance.vehicle_start_node_ids else 0)
                                  if pickup_at == 0 else current_ids[pickup_at - 1])
                nearest_leg, _ = leg_fn(by_id[predecessor_id], pickup)
                added_distance = candidate.total_distance - current.total_distance
                key = (
                    round(added_distance, 12),
                    round(nearest_leg, 12),
                    pickup.latest,
                    pair_id,
                    pickup_at,
                    delivery_at,
                )
                if best is None or key < best[0]:
                    best = (key, candidate)
    return None if best is None else best[1]


def _solve_greedy_pairs(
    instance: SolomonInstance, *, leg_fn: LegFn,
    max_stops_per_vehicle: int | None,
    end_leg_fn: EndLegFn | None,
    mileage_limit: float | None,
) -> ReplanResult:
    """Fill one vehicle at a time with whole pickup-delivery pairs."""
    pairs = pair_nodes(instance)
    unassigned = set(pairs)
    routes: list[VehicleRoute] = []
    delivery_of = {pair_id: delivery_id for pair_id, (_, delivery_id) in pairs.items()}
    for vehicle_id in range(1, instance.vehicle_nr + 1):
        # ``ids`` is the whole driven sequence, pickups included: dropping them
        # would leave the next candidate delivering goods nobody collected, and
        # every later insertion would be judged infeasible against a broken route.
        ids: tuple[int, ...] = ()
        served_deliveries: set[int] = set()
        route: VehicleRoute | None = None
        while unassigned:
            candidate = _best_feasible_pair_insertion(
                instance, ids, unassigned, vehicle_id, leg_fn,
                max_stops_per_vehicle=max_stops_per_vehicle,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
            )
            if candidate is None:
                break
            route = candidate
            # In this model ``customer_ids`` lists the deliveries, so the pair the
            # insertion added is the one whose delivery is new.
            added = set(route.customer_ids) - served_deliveries
            if len(added) != 1:
                raise RuntimeError("greedy pair insertion did not add exactly one pair")
            served_deliveries = set(route.customer_ids)
            served = added.pop()
            unassigned.remove(next(pair_id for pair_id, delivery_id in delivery_of.items()
                                   if delivery_id == served))
            ids = route.node_sequence
        if route is None:
            continue
        routes.append(route)
        if not unassigned:
            break
    result = build_result(instance, "greedy-pair-insertion", routes)
    return result


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
    if max_stops_per_vehicle is not None and max_stops_per_vehicle < 1:
        raise ValueError("max_stops_per_vehicle must be a positive integer")
    if mileage_limit is not None and mileage_limit <= 0:
        raise ValueError("mileage_limit must be positive")
    if instance.load_model == "pickup_delivery":
        return _solve_greedy_pairs(
            instance, leg_fn=leg_fn, max_stops_per_vehicle=max_stops_per_vehicle,
            end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
        )

    unassigned = {node.node_id for node in instance.customers}
    routes: list[VehicleRoute] = []

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
            continue
        routes.append(route)
        if not unassigned:
            break

    return build_result(instance, "greedy-nearest-insertion", routes)
