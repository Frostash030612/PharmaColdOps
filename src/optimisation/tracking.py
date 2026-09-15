"""Where each vehicle is at a given simulated minute.

DERIVED, never stored. The audited state machine stays the authority on what
has *happened* (departed / delivered); this module only answers "where would
the truck be right now", so the map can move a marker and — the reason it is a
server-side module rather than a browser animation — so that later features
have one place to ask the same question:

* spoilage while in transit  → needs "how long has this box been on the road"
* vehicle-to-vehicle handover → needs "how far apart are these two right now"
* emergency re-route          → needs "where do we divert *from*"

Travel is free-flow (the network's own duration matrix); no congestion model.
"""
from __future__ import annotations

import datetime

LOADING_MIN = 15          # depot dwell before a vehicle rolls
SERVICE_MIN = 0           # per-stop dwell; kept explicit, see limitations


def make_clock(sim_start_min: float, speed: float,
               started_real: str | None = None) -> dict:
    """A simulated clock: where it started, when that was, how fast it runs."""
    if speed <= 0:
        raise ValueError("clock speed must be positive")
    return {
        "sim_start_min": float(sim_start_min),
        "started_real": started_real or datetime.datetime.now().isoformat(timespec="seconds"),
        "speed": float(speed),
    }


def simulated_now(clock: dict, real_now: datetime.datetime | None = None) -> float:
    """Simulated minute-of-day implied by the wall clock and the speed factor.

    speed=1 tracks real time; speed=60 turns one real second into one minute.
    """
    if not clock:
        return 0.0
    started = datetime.datetime.fromisoformat(clock["started_real"])
    now = real_now or datetime.datetime.now()
    elapsed_real_min = (now - started).total_seconds() / 60.0
    return clock["sim_start_min"] + elapsed_real_min * clock["speed"]


def _leg(network: dict, a: int, b: int) -> tuple[list, float]:
    """Road polyline and free-flow minutes for one depot/facility leg.

    A leg from a node to itself has no geometry (the committed network stores one
    polyline per distinct pair) and no travel time: it happens when a branch
    order is added for a hospital the vehicle is already due to visit, so the
    queue holds that node twice in a row. The truck simply does not move — that
    is a zero-length leg, not a missing-data error.
    """
    if a == b:
        return [], 0.0
    coords = network["leg_geometry"][f"{a}:{b}"]
    minutes = network["matrix"]["duration_s"][a][b] / 60.0
    return coords, minutes


def point_along(coords: list, fraction: float) -> list:
    """Interpolate a point at ``fraction`` of the polyline's length.

    Distance-proportional rather than segment-proportional, so a marker moves
    at a steady speed instead of jumping across long straight sections.
    """
    if not coords:
        return [0.0, 0.0]
    if fraction <= 0:
        return list(coords[0])
    if fraction >= 1:
        return list(coords[-1])
    spans = []
    total = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        spans.append(length)
        total += length
    if total <= 0:
        return list(coords[0])
    target = total * fraction
    walked = 0.0
    for index, length in enumerate(spans):
        if walked + length >= target:
            rest = (target - walked) / length if length else 0.0
            (x1, y1), (x2, y2) = coords[index], coords[index + 1]
            return [x1 + (x2 - x1) * rest, y1 + (y2 - y1) * rest]
        walked += length
    return list(coords[-1])


def vehicle_track(network: dict, node_sequence: list[int], depart_min: float,
                  sim_now: float) -> dict:
    """Position and stop progress for one vehicle's depot→…→depot run.

    ``node_sequence`` is the vehicle's remaining stops in order (network node
    ids). Returns the interpolated position, which leg it is on, and how many
    stops it has reached by ``sim_now`` — the caller turns "reached" into an
    audited delivery command; this function never mutates anything.
    """
    route = [0, *node_sequence, 0]
    arrivals: list[float] = []
    clock = depart_min
    position = point_along(_leg(network, 0, route[1])[0], 0.0) if len(route) > 1 else [0.0, 0.0]
    leg_from, leg_to, fraction = 0, route[1] if len(route) > 1 else 0, 0.0

    for a, b in zip(route, route[1:]):
        coords, minutes = _leg(network, a, b)
        arrive = clock + minutes
        if b != 0:
            arrivals.append(arrive)
        if minutes <= 0:
            # A zero-length leg (the same node twice in a row): the truck does
            # not move, so the marker stays where it is. There is no geometry to
            # interpolate and no time passes beyond the stop's own service.
            if sim_now >= arrive:
                leg_from, leg_to, fraction = a, b, 1.0
            clock = arrive + (SERVICE_MIN if b != 0 else 0)
            continue
        if clock <= sim_now < arrive:
            fraction = (sim_now - clock) / minutes
            leg_from, leg_to = a, b
            position = point_along(coords, fraction)
        elif sim_now >= arrive:
            leg_from, leg_to, fraction = a, b, 1.0
            position = list(coords[-1])
        clock = arrive + (SERVICE_MIN if b != 0 else 0)

    reached = sum(1 for arrive in arrivals if sim_now >= arrive)
    return {
        "position": position,
        "leg_from": leg_from,
        "leg_to": leg_to,
        "leg_fraction": round(fraction, 4),
        "reached_stops": reached,
        "arrivals": [round(a, 2) for a in arrivals],
        "finished": bool(route) and sim_now >= clock,
    }
