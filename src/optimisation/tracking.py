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
               started_real: str | None = None,
               depart_min: float | None = None) -> dict:
    """A simulated clock: where it started, when that was, how fast it runs.

    ``speed = 0`` is a genuine pause, not a stopped refresh: simulated time is
    derived from the wall clock times the speed, so at 0 nothing advances, and
    resuming re-bases on the frozen minute instead of jumping forward.

    ``depart_min`` is the minute the vehicles ROLLED, and it is deliberately
    separate from ``sim_start_min``: changing the speed re-bases the arithmetic
    (sim_start = "now", or time would jump) but must NOT move the schedule
    origin, because positions are computed as "departure + elapsed time". Tying
    the two together is what teleported every truck back to the depot whenever
    the speed buttons were touched.
    """
    if speed < 0:
        raise ValueError("clock speed cannot be negative")
    return {
        "sim_start_min": float(sim_start_min),
        "started_real": started_real or datetime.datetime.now().isoformat(timespec="seconds"),
        "speed": float(speed),
        "depart_min": float(sim_start_min if depart_min is None else depart_min),
    }


def schedule_origin(clock: dict) -> float:
    """When the fleet rolled — the origin the vehicle schedule is measured from.

    Falls back to ``sim_start_min`` for clocks written before the field existed;
    those can only be speed-changed runs, and the fallback matches the old
    (teleporting) behaviour rather than failing.
    """
    return float(clock.get("depart_min", clock["sim_start_min"]))


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


#: How much real time one tick may account for. Polling is once a second, so
#: this never bites while somebody is watching; it only stops a demo that nobody
#: is watching from racing through the whole day between two polls.
MAX_TICK_SECONDS = 30.0


def watched_now(clock: dict, real_now: datetime.datetime | None = None) -> float:
    """Simulated time as anyone can actually observe it.

    The uncapped value is what the wall clock would say, but no tick will ever
    charge more than :data:`MAX_TICK_SECONDS` of it, so a view that used the
    uncapped number would briefly show a truck near the end of its route and then
    snap back when the first tick landed. Capping here keeps the drawn position
    and the ticked ledger telling the same story.
    """
    if not clock:
        return 0.0
    ceiling = (clock["sim_start_min"]
               + MAX_TICK_SECONDS * clock["speed"] / 60.0)
    return min(simulated_now(clock, real_now), ceiling)


def advance_clock(clock: dict, real_now: datetime.datetime | None = None) -> dict:
    """Move simulated time on by however long was actually watched.

    Simulated time is wall-clock derived, so an operation left alone advances by
    itself — a demo opened in the morning and looked at in the afternoon is over.
    Charging each tick at most :data:`MAX_TICK_SECONDS` makes the clock wait for
    its audience: leaving the page (or the whole app) pauses the day, and coming
    back resumes from where it was instead of jumping to the end. Speed 0 still
    means a full freeze.
    """
    now = real_now or datetime.datetime.now()
    started = datetime.datetime.fromisoformat(clock["started_real"])
    watched = min(max((now - started).total_seconds(), 0.0), MAX_TICK_SECONDS)
    return {
        **clock,
        "sim_start_min": clock["sim_start_min"] + watched * clock["speed"] / 60.0,
        # Microseconds, not seconds: this anchor is re-read immediately by
        # ``simulated_now``, and truncating it would add up to a second of
        # unearned time on every tick (5 simulated minutes at 300x).
        "started_real": now.isoformat(),
    }


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
                  sim_now: float, end_node: int = 0, start_node: int = 0,
                  earliest_mins: list[float] | None = None,
                  service_mins: list[float] | None = None) -> dict:
    """Position and stop progress for one vehicle's start→…→end run.

    ``node_sequence`` is the vehicle's remaining stops in order (network node
    ids). Returns the interpolated position, which leg it is on, and how many
    stops it has reached by ``sim_now`` — the caller turns "reached" into an
    audited delivery command; this function never mutates anything.

    ``end_node`` is where the run finishes: the depot (0) for a closed route, or
    the parking node of an open one (2026-09-16).  It must match what the planner
    charged, otherwise the map would drive the truck home while the plan says it
    parks.
    """
    route = [start_node, *node_sequence, end_node]
    arrivals: list[float] = []
    clock = depart_min
    position = (point_along(_leg(network, start_node, route[1])[0], 0.0)
                if len(route) > 1 else [0.0, 0.0])
    if route[1] == start_node:
        start = next(node for node in network["nodes"] if node["node_id"] == start_node)
        position = [start["lon"], start["lat"]]
    leg_from, leg_to, fraction = start_node, route[1] if len(route) > 1 else start_node, 0.0
    stop_count = len(node_sequence)
    if earliest_mins is not None and len(earliest_mins) != stop_count:
        raise ValueError("one receiving-window start is required per stop")
    if service_mins is not None and len(service_mins) != stop_count:
        raise ValueError("one service time is required per stop")
    driven_distance, total_distance = 0.0, 0.0
    leg_departure, leg_arrival, active_index = depart_min, depart_min, 0

    # A stop is a leg that ends at ``node_sequence[i]``. Judging it by "the leg
    # does not end at the depot" was equivalent until a pickup-delivery run put a
    # collection stop ON the depot node — the warehouse is both the route start
    # and a supply point — and that stop was silently not counted, so the tick
    # delivered the wrong order (2026-09-16, PDPTW step 4).
    for index, (a, b) in enumerate(zip(route, route[1:])):
        is_stop = index < stop_count
        coords, minutes = _leg(network, a, b)
        distance = network["matrix"]["distance_m"][a][b]
        total_distance += distance
        road_arrival = clock + minutes
        arrive = (max(road_arrival, earliest_mins[index])
                  if is_stop and earliest_mins is not None else road_arrival)
        if is_stop:
            arrivals.append(arrive)
        dwell = (service_mins[index] if service_mins is not None else SERVICE_MIN) if is_stop else 0
        if sim_now >= road_arrival:
            driven_distance += distance
        elif clock <= sim_now < road_arrival:
            driven_distance += distance * (sim_now - clock) / minutes
        if minutes <= 0:
            # A zero-length leg (the same node twice in a row): the truck does
            # not move, so the marker stays where it is. There is no geometry to
            # interpolate and no time passes beyond the stop's own service.
            if sim_now >= arrive:
                leg_from, leg_to, fraction = a, b, 1.0
                leg_departure, leg_arrival, active_index = clock, road_arrival, index
            clock = arrive + dwell
            continue
        if clock <= sim_now < road_arrival:
            fraction = (sim_now - clock) / minutes
            leg_from, leg_to = a, b
            position = point_along(coords, fraction)
            leg_departure, leg_arrival, active_index = clock, road_arrival, index
        elif sim_now >= road_arrival:
            leg_from, leg_to, fraction = a, b, 1.0
            position = list(coords[-1])
            leg_departure, leg_arrival, active_index = clock, road_arrival, index
        clock = arrive + dwell

    reached = sum(1 for arrive in arrivals if sim_now >= arrive)
    return {
        "position": position,
        "leg_from": leg_from,
        "leg_to": leg_to,
        "leg_fraction": round(fraction, 4),
        "reached_stops": reached,
        "arrivals": [round(a, 2) for a in arrivals],
        "service_starts": list(arrivals),
        "finished": bool(route) and sim_now >= clock,
        "finished_at_min": clock,
        "leg_depart_min": leg_departure,
        "leg_arrival_min": leg_arrival,
        "leg_index": active_index,
        "distance_driven_m": driven_distance,
        "total_distance_m": total_distance,
    }
