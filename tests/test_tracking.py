"""The simulated clock moves vehicles and records arrivals.

Position is derived, never stored: the state machine still owns what happened.
These tests pin that split — a clock tick may only produce ordinary, idempotent
delivery commands, and changing speed must not teleport a vehicle.
"""
import datetime
import tempfile

import pytest

from api import service
from optimisation.singapore_loader import read_network
from optimisation.tracking import (
    LOADING_MIN, make_clock, point_along, simulated_now, vehicle_track,
)

NETWORK = read_network()


@pytest.fixture(autouse=True)
def isolated_dispatch_db(monkeypatch):
    monkeypatch.setattr(
        service, "DISPATCH_DATABASE_URL", tempfile.mktemp(suffix=".sqlite3"))


def _age_clock(dispatch_id, *, minutes_ago):
    """Backdate the clock's start so simulated time has already elapsed."""
    context = service.load_context(service.DISPATCH_DATABASE_URL, dispatch_id)
    started = datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)
    context["clock"] = make_clock(context["clock"]["sim_start_min"],
                                  context["clock"]["speed"], started.isoformat())
    service.update_context(service.DISPATCH_DATABASE_URL, dispatch_id, context)


def test_speed_turns_real_seconds_into_simulated_minutes():
    started = datetime.datetime(2026, 9, 12, 9, 0, 0)
    clock = make_clock(540, 60, started.isoformat())
    # 30 real seconds at 60x = 30 simulated minutes
    assert simulated_now(clock, started + datetime.timedelta(seconds=30)) == 570


def test_real_time_speed_tracks_the_wall_clock():
    started = datetime.datetime(2026, 9, 12, 9, 0, 0)
    clock = make_clock(540, 1, started.isoformat())
    assert simulated_now(clock, started + datetime.timedelta(minutes=7)) == 547


def test_point_along_walks_the_polyline_by_distance():
    line = [[0.0, 0.0], [10.0, 0.0]]
    assert point_along(line, 0.0) == [0.0, 0.0]
    assert point_along(line, 0.5) == [5.0, 0.0]
    assert point_along(line, 1.0) == [10.0, 0.0]


def test_vehicle_waits_at_the_depot_then_moves_then_arrives():
    depart = 0
    at_depot = vehicle_track(NETWORK, [1], depart, sim_now=0)
    arrival = at_depot["arrivals"][0]
    moving = vehicle_track(NETWORK, [1], depart, sim_now=arrival / 2)
    arrived = vehicle_track(NETWORK, [1], depart, sim_now=arrival + 0.1)

    assert at_depot["reached_stops"] == 0
    assert moving["position"] != at_depot["position"]     # actually moved
    assert 0 < moving["leg_fraction"] < 1
    assert arrived["reached_stops"] == 1


def test_a_repeated_stop_is_a_zero_length_leg_not_a_crash():
    """Found by driving the live API: a branch order for a hospital the vehicle
    was already due to visit put that node twice in a row in its queue, and the
    track builder looked up a leg ("2:2") that the network does not store —
    every response containing that route failed with a 500."""
    sequence = [1, 1, 2]
    track = vehicle_track(NETWORK, sequence, 0, sim_now=1_000_000)

    assert track["reached_stops"] == len(sequence)
    assert track["finished"] is True
    # Stops are still counted once each: passing the same node twice is two
    # deliveries, even though no distance is covered between them.
    assert len(track["arrivals"]) == len(sequence)
    assert track["arrivals"][1] == track["arrivals"][0]


def test_clock_starts_on_departure_and_ticks_record_the_arrival(day_plan):
    # A one-order day plan is the smallest real operation: the clock tests need
    # a run that can actually finish, and since 2026-09-15 a branch event can no
    # longer create an operation of its own (docs/C_配送模块.md §4.4-2).
    dispatch_id = day_plan(hospitals=1)
    departed = service.depart_dispatch(dispatch_id, "go", speed=300.0)
    assert departed["clock"]["speed"] == 300.0

    # Start the clock in the past so simulated time has already run past the
    # arrival: moving sim_start_min instead would shift the whole schedule with
    # it and the truck would still be loading.
    _age_clock(dispatch_id, minutes_ago=5)

    ticked = service.tick_dispatch(dispatch_id)

    assert ticked["route_view"]["metrics"]["orders_delivered"] == 1
    assert ticked["status"] == "completed"


def test_ticking_twice_records_one_delivery(day_plan):
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go", speed=300.0)
    _age_clock(dispatch_id, minutes_ago=5)

    first = service.tick_dispatch(dispatch_id)
    second = service.tick_dispatch(dispatch_id)

    assert second["version"] == first["version"]
    assert second["route_view"]["metrics"]["orders_delivered"] == 1


def test_changing_speed_does_not_teleport_the_vehicles(day_plan):
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go", speed=300.0)
    before = service.get_dispatch(dispatch_id)["route_view"]["sim_now_min"]

    after = service.set_dispatch_speed(dispatch_id, 1.0)["route_view"]["sim_now_min"]

    assert after == pytest.approx(before, abs=1.0)   # continues, not restarts


def test_speed_must_be_one_of_the_offered_rates(day_plan):
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go")
    with pytest.raises(ValueError, match="speed must be one of"):
        service.set_dispatch_speed(dispatch_id, 7.5)
