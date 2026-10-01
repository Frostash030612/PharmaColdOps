"""Inspect an in-transit dispatch for predicted delivery-window misses.

This is deliberately a *preview then accept* workflow.  A late ETA can be
reported automatically, but changing the sequence of consignments is an
operator decision: the preview exposes the old and proposed queues, every ETA
and the exact lateness improvement before ``accept_delay_replan`` writes it to
the audited dispatch state.

The live state stores positions at facilities, not arbitrary GPS coordinates.
Consequently the estimate starts at the vehicle's last audited facility at the
inspection minute.  That is conservative while a truck is between nodes, and
the limitation is returned with every preview rather than being hidden.
"""
from __future__ import annotations

from dataclasses import replace
from itertools import permutations

from .dispatch_state import DispatchState
from .singapore_loader import read_network
from .execution import checkpoint, install_schedule
from .dispatch_constraints import price_work


# A daily vehicle normally has at most four stops.  Eight is a deliberate
# safety rail: 8! exact alternatives are still small, while a larger queue uses
# the documented deterministic deadline heuristic rather than causing a slow
# API call during an incident.
MAX_EXACT_STOPS = 8


def _reject_paired_run(state: DispatchState) -> None:
    """Do not mutate a PDPTW order queue behind its explicit stop plan."""
    paired = sorted(vehicle_id for vehicle_id, vehicle in state.vehicles.items()
                    if vehicle.drive_plan)
    if paired:
        raise ValueError(
            "delay re-planning is not available for a pickup-delivery run yet: "
            "that run drives an explicit pickup/delivery stop sequence, while "
            "this v1 remedy re-orders a delivery queue. Re-plan today's batch "
            "with routing_model='grouped' first "
            f"(paired vehicles: {', '.join(paired)})"
        )


def _orders(context: dict) -> dict[str, dict]:
    return {item["order_id"]: item
            for item in context.get("input", {}).get("orders", ())}


def _simulate(order_ids: tuple[str, ...], *, start_facility_id: str,
              start_time_min: float, order_by_id: dict[str, dict], leg) -> tuple[dict, float, float]:
    """Return ETA rows, completion time and road distance for one queue.

    The planner's receiving-window semantics are preserved: a vehicle waits for
    an early window rather than treating an early arrival as a violation.
    """
    at_facility = start_facility_id
    at_time = float(start_time_min)
    distance_m = 0.0
    arrivals: dict[str, float] = {}
    for order_id in order_ids:
        order = order_by_id[order_id]
        distance, travel = leg(at_facility, order["destination_facility_id"])
        distance_m += distance
        at_time = max(at_time + travel, float(order["earliest_min"]))
        arrivals[order_id] = at_time
        at_facility = order["destination_facility_id"]
    return arrivals, at_time, distance_m


def _score(arrivals: dict[str, float], order_ids: tuple[str, ...],
           order_by_id: dict[str, dict], completion: float, distance_m: float) -> tuple:
    lateness = [max(0.0, arrivals[order_id] - order_by_id[order_id]["latest_min"])
                for order_id in order_ids]
    # The order of this tuple is the policy: prevent as many late deliveries as
    # possible, then reduce their aggregate and worst miss, then deadhead.
    return (
        sum(minutes > 1e-9 for minutes in lateness),
        round(sum(lateness), 9),
        round(max(lateness, default=0.0), 9),
        round(completion, 9),
        round(distance_m, 9),
        order_ids,
    )


def _best_sequence(original: tuple[str, ...], *, start_facility_id: str,
                   start_time_min: float, order_by_id: dict[str, dict], leg,
                   admissible=None) -> tuple[tuple[str, ...], str]:
    """Find the smallest late-delivery queue, deterministically.

    Small daily queues use every permutation, which makes the chosen queue
    explainable and avoids a heuristic claiming an improvement it missed.  The
    larger fallback puts earlier deadlines first and is only retained as a
    bounded operational fallback.
    """
    if len(original) <= 1:
        return original, "unchanged"
    if len(original) <= MAX_EXACT_STOPS:
        candidates = permutations(original)
        method = "exact_permutation"
    else:
        candidates = (tuple(sorted(
            original,
            key=lambda order_id: (order_by_id[order_id]["latest_min"], order_id),
        )),)
        method = "deadline_heuristic"

    best = original
    original_arrivals, completion, distance = _simulate(
        original, start_facility_id=start_facility_id, start_time_min=start_time_min,
        order_by_id=order_by_id, leg=leg)
    best_score = _score(original_arrivals, original, order_by_id, completion, distance)
    protected = {oid for oid in original
                 if original_arrivals[oid] <= order_by_id[oid]["latest_min"]}
    for candidate in candidates:
        arrivals, completion, distance_m = _simulate(
            candidate, start_facility_id=start_facility_id,
            start_time_min=start_time_min, order_by_id=order_by_id, leg=leg,
        )
        if any(arrivals[oid] > order_by_id[oid]["latest_min"] for oid in protected):
            continue
        if admissible is not None and not admissible(candidate, completion, distance_m):
            continue
        score = _score(arrivals, candidate, order_by_id, completion, distance_m)
        if score < best_score:
            best, best_score = candidate, score
    return tuple(best), method


def _late_summary(arrivals: dict[str, float], order_ids: tuple[str, ...],
                  order_by_id: dict[str, dict]) -> dict:
    lateness = {
        order_id: max(0.0, arrivals[order_id] - order_by_id[order_id]["latest_min"])
        for order_id in order_ids
    }
    late = [order_id for order_id in order_ids if lateness[order_id] > 1e-9]
    return {
        "predicted_late_order_ids": late,
        "predicted_late_order_count": len(late),
        "total_lateness_min": round(sum(lateness.values()), 2),
        "maximum_lateness_min": round(max(lateness.values(), default=0.0), 2),
        "lateness_by_order": lateness,
    }


def _order_effects(original: tuple[str, ...], before: dict[str, float], after: dict[str, float],
                   order_by_id: dict[str, dict]) -> list[dict]:
    """One stable, before/after row per original order for the operator."""
    effects = []
    for order_id in original:
        latest = float(order_by_id[order_id]["latest_min"])
        before_lateness = max(0.0, before[order_id] - latest)
        after_lateness = max(0.0, after[order_id] - latest)
        effects.append({
            "order_id": order_id,
            "baseline_eta_min": round(before[order_id], 2),
            "replanned_eta_min": round(after[order_id], 2),
            "baseline_lateness_min": round(before_lateness, 2),
            "replanned_lateness_min": round(after_lateness, 2),
            "recovered_on_time": before_lateness > 1e-9 and after_lateness <= 1e-9,
            "newly_late": before_lateness <= 1e-9 and after_lateness > 1e-9,
        })
    return effects


def _improves(before: dict, after: dict) -> bool:
    return (
        after["predicted_late_order_count"],
        after["total_lateness_min"],
        after["maximum_lateness_min"],
    ) < (
        before["predicted_late_order_count"],
        before["total_lateness_min"],
        before["maximum_lateness_min"],
    )


def preview_delay_risks(state: DispatchState, context: dict, *, current_time_min: float,
                        delay_min: float = 0.0, optimise: bool = True) -> dict:
    """Scan every active vehicle and propose a safer remaining stop order.

    ``delay_min`` is an observed extra delay (for example from a driver's/GPS
    exception feed) layered over the inspected simulated minute.  Keeping it an
    explicit request field makes a simulated demo honest: this prototype has no
    live traffic provider that could manufacture a delay on its own.
    """
    if state.status != "in_transit":
        raise ValueError("delay inspection requires an in-transit dispatch")
    if delay_min < 0:
        raise ValueError("delay_min cannot be negative")
    _reject_paired_run(state)

    order_by_id = _orders(context)
    network = read_network()
    node_by_facility = {node["facility_id"]: node["node_id"] for node in network["nodes"]}
    distance_m = network["matrix"]["distance_m"]
    duration_s = network["matrix"]["duration_s"]

    def leg(origin: str, destination: str) -> tuple[float, float]:
        try:
            i, j = node_by_facility[origin], node_by_facility[destination]
        except KeyError as exc:
            raise ValueError(f"unknown facility {exc.args[0]!r} in delay inspection") from exc
        return distance_m[i][j], duration_s[i][j] / 60.0

    inspected_at = float(current_time_min) + float(delay_min)
    candidates = []
    baselines: dict[str, dict] = {}
    inspected_vehicles = 0
    for vehicle_id, vehicle in sorted(state.vehicles.items()):
        if vehicle.status != "in_transit" or not vehicle.remaining_order_ids:
            continue
        if vehicle.pickup_facility_ids:
            # These legacy diversion pickups are a driven prefix.  Re-ordering
            # only its deliveries while a pickup is still ahead would require a
            # second explicit stop-plan model, so keep the same safe boundary as
            # the PDPTW path instead of presenting a misleading ETA.
            raise ValueError(
                "delay re-planning is not available while a vehicle still has "
                "a pending pickup diversion; complete that pickup or re-plan "
                "the grouped dispatch first "
                f"(vehicle: {vehicle_id})"
            )
        original = tuple(vehicle.remaining_order_ids)
        anchor = checkpoint(vehicle, state, context, current_time_min, network=network)
        vehicle = replace(vehicle, current_facility_id=anchor["facility_id"])
        route_start = anchor["time_min"] + delay_min
        missing = [order_id for order_id in original if order_id not in order_by_id]
        if missing:
            raise ValueError(f"dispatch context is missing orders for delay inspection: {missing}")
        if vehicle.current_facility_id not in node_by_facility:
            raise ValueError(
                f"unknown current facility {vehicle.current_facility_id!r} for {vehicle_id!r}"
            )
        inspected_vehicles += 1
        before_arrivals, before_completion, before_distance = _simulate(
            original, start_facility_id=vehicle.current_facility_id,
            start_time_min=route_start, order_by_id=order_by_id, leg=leg,
        )
        before = _late_summary(before_arrivals, original, order_by_id)
        if before["predicted_late_order_count"] == 0:
            continue
        end_node = vehicle.end_node_id if vehicle.end_node_id is not None else 0
        end_facility = next(node["facility_id"] for node in network["nodes"]
                            if node["node_id"] == end_node)
        closing = next(node["latest_min"] for node in network["nodes"]
                       if node["node_id"] == end_node)
        limit = context.get("input", {}).get("constraints", {}).get("mileage_limit_m")
        history = [network["nodes"][0]["facility_id"],
                   *(order_by_id[oid]["destination_facility_id"]
                     for oid in vehicle.delivered_order_ids), vehicle.current_facility_id]
        driven = anchor["distance_m"]

        def admissible(queue, completion, distance):
            last = order_by_id[queue[-1]]["destination_facility_id"]
            final_distance, final_time = leg(last, end_facility)
            return ((limit is None or driven + distance + final_distance <= limit + 1e-9)
                    and completion + final_time <= closing + 1e-9)

        replanned, method = (original, "inspection_only")
        if optimise:
            replanned, method = _best_sequence(
                original, start_facility_id=vehicle.current_facility_id,
                start_time_min=route_start, order_by_id=order_by_id, leg=leg,
                admissible=admissible,
            )
        after_arrivals, after_completion, after_distance = _simulate(
            replanned, start_facility_id=vehicle.current_facility_id,
            start_time_min=route_start, order_by_id=order_by_id, leg=leg,
        )
        after = _late_summary(after_arrivals, replanned, order_by_id)
        # A re-plan is a response to a window-risk.  Do not present a normal
        # mileage optimisation as a delay remedy when there is no risk at all.
        at_risk = before["predicted_late_order_count"] > 0
        if not at_risk:
            continue
        candidate = {
            "kind": "resequence_remaining_stops",
            "vehicle_id": vehicle_id,
            "current_facility_id": vehicle.current_facility_id,
            "inspected_at_min": round(inspected_at, 2),
            "original_order_ids": list(original),
            "remaining_order_ids_after": list(replanned),
            "resequenced": replanned != original,
            "search_method": method,
            "replan_available": _improves(before, after),
            "baseline": {
                **{key: value for key, value in before.items() if key != "lateness_by_order"},
                "completion_eta_min": round(before_completion, 2),
                "distance_m": round(before_distance, 2),
            },
            "replanned": {
                **{key: value for key, value in after.items() if key != "lateness_by_order"},
                "completion_eta_min": round(after_completion, 2),
                "distance_m": round(after_distance, 2),
            },
            "affected_orders": _order_effects(
                original, before_arrivals, after_arrivals, order_by_id),
            "node_sequence": [
                node_by_facility[vehicle.current_facility_id],
                *(node_by_facility[order_by_id[order_id]["destination_facility_id"]]
                  for order_id in replanned),
            ],
        }
        priced = price_work(state, context, vehicle_id=vehicle_id, order_ids=replanned,
                            current_time_min=current_time_min, loading_min=delay_min)
        candidate.update({key: value for key, value in priced.items()
                          if key not in {"affected_orders", "affected_order_ids", "arrivals"}})
        candidate["replan_available"] = candidate["replan_available"] and priced["feasible"]
        candidates.append(candidate)
        baselines[vehicle_id] = {
            "node_sequence": [
                node_by_facility[vehicle.current_facility_id],
                *(node_by_facility[order_by_id[order_id]["destination_facility_id"]]
                  for order_id in original), priced["end_node_id"],
            ],
            "original_order_ids": list(original),
        }

    candidates.sort(key=lambda candidate: (
        not candidate["replan_available"],
        candidate["replanned"]["predicted_late_order_count"],
        candidate["replanned"]["total_lateness_min"],
        candidate["vehicle_id"],
    ))
    return {
        "state_version": state.version,
        "inspected_at_min": round(inspected_at, 2),
        "current_time_min": round(float(current_time_min), 2),
        "delay_min": round(float(delay_min), 2),
        "inspected_vehicle_count": inspected_vehicles,
        "predicted_late_order_count": sum(
            candidate["baseline"]["predicted_late_order_count"] for candidate in candidates),
        "replan_candidate_count": sum(
            candidate["replan_available"] for candidate in candidates),
        "candidates": candidates,
        "baselines": baselines,
        "limitations": [
            "ETA uses static road travel time and no service dwell.",
            "Vehicle position is represented by its last audited facility; an in-leg GPS position is not modeled.",
            "delay_min is an observed extra delay supplied by the caller; no live traffic feed is connected.",
        ],
    }


def accept_delay_replan(state: DispatchState, context: dict, *, vehicle_id: str,
                        current_time_min: float, delay_min: float, command_id: str) -> tuple[DispatchState, dict]:
    """Revalidate and persist the inspected queue for one vehicle exactly once."""
    if command_id in state.applied_commands:
        return state, {"idempotent": True}
    preview = preview_delay_risks(
        state, context, current_time_min=current_time_min, delay_min=delay_min)
    candidate = next((item for item in preview["candidates"]
                      if item["vehicle_id"] == vehicle_id), None)
    if candidate is None:
        raise ValueError(f"vehicle {vehicle_id!r} has no predicted delivery-window miss")
    if not candidate["replan_available"]:
        raise ValueError(
            f"no better remaining-stop order is available for vehicle {vehicle_id!r}"
        )
    vehicle = state.vehicles[vehicle_id]
    changed = install_schedule(replace(vehicle,
        remaining_order_ids=tuple(candidate["remaining_order_ids_after"]),
        replan_started_min=candidate["schedule_start_min"],
        replan_start_facility_id=candidate["schedule_start_facility_id"],
        replan_order_ids=tuple(candidate["remaining_order_ids_after"]),
        end_node_id=candidate["end_node_id"]), candidate)
    new = replace(
        state,
        version=state.version + 1,
        vehicles={
            **state.vehicles,
            vehicle_id: changed,
        },
        applied_commands=(*state.applied_commands, command_id),
    )
    return new, {"idempotent": False, "candidate": candidate}
