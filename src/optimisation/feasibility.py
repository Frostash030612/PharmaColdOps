"""Why an order could not be placed (B7, 2026-09-16).

The delivery rule is "share a truck while it stays inside the limits, otherwise
send another one, and if that still does not work say so". Saying so is only
useful if it is **specific**: which limit blocked it, and by how much.

Every code below is *measured*: the customer is really inserted into each route
(and into an empty vehicle when the fleet still has room) and evaluated with the
same gate the solvers use — ``routing.evaluate_route`` with the same leg function,
parking policy and mileage cap. Nothing here is inferred from the solver's
outcome, so the reported numbers cannot drift away from what the solver saw.

Codes are stable identifiers; the client localises them (the same discipline as
the decision codes in ``api.service``).
"""
from __future__ import annotations

from .models import SolomonInstance, VehicleRoute
from .routing import EndLegFn, LegFn, evaluate_route

#: Reasons an order can come back unserved. One order may carry several.
BLOCKING_CODES = (
    "mileage_limit_exceeded",     # cannot be driven within the per-vehicle cap
    "time_window_infeasible",     # would arrive after the receiving window closes
    "capacity_exceeded",          # no vehicle can carry it together with its load
    "closing_window_exceeded",    # the truck would reach its parking node/warehouse late
    "stop_limit_exceeded",        # every vehicle is already at max stops
    "no_vehicle_available",       # the fleet limit leaves nothing to add
    "placeable_in_isolation",     # it WOULD fit somewhere: the solver exhausted its budget
)


def _keep_best(reasons: dict, code: str, detail: dict, *, smallest: str | None = None) -> None:
    """Record a reason; for measured quantities keep the most favourable value.

    "Favourable" means the attempt that came closest to working: the smallest
    extra distance, the least lateness. Reporting the worst attempt would make a
    nearly-fits order look hopeless.
    """
    current = reasons.get(code)
    if current is None:
        reasons[code] = {"code": code, "detail": dict(detail)}
        return
    if smallest is None:
        return
    if smallest in detail and (smallest not in current["detail"]
                               or detail[smallest] < current["detail"][smallest]):
        current["detail"][smallest] = detail[smallest]



def _diagnose_pickup_delivery(
    instance, unserved, bases, by_id, *, reasons_factory,
    leg_fn, end_leg_fn, mileage_limit, limit_m, max_stops_per_vehicle,
) -> dict[int, tuple[dict, ...]]:
    """Why an ORDER could not be placed, when it is a pickup/delivery pair.

    A single-node insertion is meaningless here: dropping a delivery into a route
    without its pickup is not a plan, and evaluating it would report a pairing
    failure as if it were a mileage or window problem. So the pair is inserted as
    a pair — every ``(i, j)`` with the pickup first — and the reasons come from the
    attempts that were actually made (2026-09-16).
    """
    pickup_by_pair = {node.pair_id: node.node_id for node in instance.pickups}
    diagnosis: dict[int, tuple[dict, ...]] = {}
    for delivery_id in sorted(unserved):
        delivery = by_id[delivery_id]
        pickup_id = pickup_by_pair.get(delivery.pair_id)
        reasons: dict[str, dict] = {}
        if pickup_id is None:                       # a malformed instance, not a limit
            reasons["no_vehicle_available"] = {
                "code": "no_vehicle_available", "detail": {}}
            diagnosis[delivery_id] = tuple(reasons.values())
            continue
        for base in bases:
            if (max_stops_per_vehicle is not None
                    and len(base) + 2 > max_stops_per_vehicle):
                _keep_best(reasons, "stop_limit_exceeded",
                           {"max_stops_per_vehicle": max_stops_per_vehicle})
                continue
            for i in range(len(base) + 1):
                for j in range(i, len(base) + 1):
                    attempt = (base[:i] + (pickup_id,) + base[i:j]
                               + (delivery_id,) + base[j:])
                    route = evaluate_route(
                        instance, attempt, leg_fn=leg_fn, end_leg_fn=end_leg_fn,
                        mileage_limit=mileage_limit,
                    )
                    if route.feasible:
                        _keep_best(reasons, "placeable_in_isolation",
                                   {"fits_after_distance_m":
                                    round(route.total_distance * 1000)})
                        continue
                    if route.mileage_limit_violation and limit_m is not None:
                        _keep_best(reasons, "mileage_limit_exceeded",
                                   {"needed_distance_m":
                                    round(route.total_distance * 1000),
                                    "limit_m": limit_m},
                                   smallest="needed_distance_m")
                    if route.capacity_violation_units:
                        _keep_best(reasons, "capacity_exceeded",
                                   {"needed_units": route.total_load,
                                    "capacity_units": instance.capacity},
                                   smallest="needed_units")
                    if route.time_window_violations:
                        worst = max(route.stops, key=lambda stop: stop.late_by)
                        _keep_best(reasons, "time_window_infeasible",
                                   {"earliest_arrival_min": round(worst.arrival),
                                    "latest_min": by_id[worst.node_id].latest,
                                    "late_by_min": round(worst.late_by)},
                                   smallest="late_by_min")
                    if route.depot_return_violation:
                        _keep_best(reasons, "closing_window_exceeded",
                                   {"closing_min": instance.depot.latest},
                                   smallest="closing_min")
        if not reasons:
            reasons["no_vehicle_available"] = {"code": "no_vehicle_available",
                                               "detail": {}}
        diagnosis[delivery_id] = tuple(reasons.values())
    return diagnosis

def diagnose_unserved(
    instance: SolomonInstance,
    unserved: tuple[int, ...] | list[int],
    routes: tuple[VehicleRoute, ...] | list[VehicleRoute],
    *,
    leg_fn: LegFn,
    end_leg_fn: EndLegFn | None = None,
    mileage_limit: float | None = None,
    max_stops_per_vehicle: int | None = None,
    fleet_has_room: bool = False,
) -> dict[int, tuple[dict, ...]]:
    """Return ``{customer_id: (reason, ...)}`` for every unserved customer."""
    by_id = {node.node_id: node for node in instance.nodes}
    bases: list[tuple[int, ...]] = [route.customer_ids for route in routes]
    if fleet_has_room:
        bases.append(())                      # a brand-new vehicle may still take it
    if not bases:
        return {
            customer_id: ({"code": "no_vehicle_available", "detail": {}},)
            for customer_id in unserved
        }

    diagnosis: dict[int, tuple[dict, ...]] = {}
    limit_m = None if mileage_limit is None else round(mileage_limit * 1000)
    if instance.load_model == "pickup_delivery":
        return _diagnose_pickup_delivery(
            instance, unserved, bases, by_id, reasons_factory=dict,
            leg_fn=leg_fn, end_leg_fn=end_leg_fn, mileage_limit=mileage_limit,
            limit_m=limit_m, max_stops_per_vehicle=max_stops_per_vehicle,
        )
    for customer_id in sorted(unserved):
        reasons: dict[str, dict] = {}
        for base in bases:
            if (max_stops_per_vehicle is not None
                    and len(base) + 1 > max_stops_per_vehicle):
                _keep_best(reasons, "stop_limit_exceeded",
                           {"max_stops_per_vehicle": max_stops_per_vehicle})
                continue
            for position in range(len(base) + 1):
                attempt = base[:position] + (customer_id,) + base[position:]
                route = evaluate_route(
                    instance, attempt, leg_fn=leg_fn, end_leg_fn=end_leg_fn,
                    mileage_limit=mileage_limit,
                )
                if route.feasible:
                    # It fits somewhere, so no hard limit blocks this order: the
                    # search simply ran out of budget (OR-Tools) or of vehicles.
                    _keep_best(reasons, "placeable_in_isolation",
                               {"fits_after_distance_m": round(route.total_distance * 1000)})
                    continue
                if route.mileage_limit_violation and limit_m is not None:
                    _keep_best(reasons, "mileage_limit_exceeded",
                               {"needed_distance_m": round(route.total_distance * 1000),
                                "limit_m": limit_m},
                               smallest="needed_distance_m")
                if route.capacity_violation_units:
                    _keep_best(reasons, "capacity_exceeded",
                               {"needed_units": route.total_load,
                                "capacity_units": instance.capacity},
                               smallest="needed_units")
                if route.time_window_violations:
                    worst = max(route.stops, key=lambda stop: stop.late_by)
                    _keep_best(reasons, "time_window_infeasible",
                               {"earliest_arrival_min": round(worst.arrival),
                                "latest_min": by_id[worst.node_id].latest,
                                "late_by_min": round(worst.late_by)},
                               smallest="late_by_min")
                if route.depot_return_violation:
                    _keep_best(reasons, "closing_window_exceeded",
                               {"closing_min": instance.depot.latest},
                               smallest="closing_min")
        if not reasons:
            # Not even an attempted insertion: every vehicle is full/absent.
            reasons["no_vehicle_available"] = {"code": "no_vehicle_available", "detail": {}}
        diagnosis[customer_id] = tuple(reasons.values())
    return diagnosis
