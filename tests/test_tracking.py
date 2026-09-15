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
    """The clock is re-based on "now", but the SCHEDULE origin must not move.

    Positions are derived as "departure + elapsed time". Re-basing the origin
    together with the clock arithmetic snapped every truck back to the depot the
    moment a speed button was pressed — and the old version of this test only
    compared the clock, so it passed while the trucks teleported.
    """
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go", speed=300.0)
    _age_clock(dispatch_id, minutes_ago=3)          # the truck is well under way
    before = service.get_dispatch(dispatch_id)
    position = before["route_view"]["routes"][0]["track"]["position"]
    assert before["route_view"]["routes"][0]["track"]["reached_stops"] >= 0

    after = service.set_dispatch_speed(dispatch_id, 1.0)["route_view"]

    assert after["sim_now_min"] == pytest.approx(before["route_view"]["sim_now_min"], abs=1.0)
    # …and the truck is still where it was, not back at the depot.
    assert after["routes"][0]["track"]["position"] == pytest.approx(position, abs=1e-6)
    assert after["routes"][0]["track"]["leg_from"] == \
        before["route_view"]["routes"][0]["track"]["leg_from"]


def test_deliveries_follow_the_schedule_after_a_speed_change(day_plan):
    """The tick and the map must agree about where the truck is.

    Both derive arrival times from the schedule origin. When the tick used the
    re-based ``sim_start_min`` instead, the map drew the truck past three stops
    while the ledger still said 0 delivered — the state machine stopped
    recording arrivals at all after any speed change.
    """
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go", speed=60.0)
    service.set_dispatch_speed(dispatch_id, 300.0)    # re-bases the clock arithmetic
    _age_clock(dispatch_id, minutes_ago=5)            # …and then five real minutes pass

    ticked = service.tick_dispatch(dispatch_id)

    assert ticked["route_view"]["metrics"]["orders_delivered"] == 1
    # The single-order plan is finished by that delivery, so there is no track
    # left to draw — what matters is that the LEDGER agrees with the schedule.
    assert ticked["status"] == "completed"
    assert ticked["route_view"]["routes"][0]["stops"][0]["delivered"] is True


def test_an_operation_is_still_open_while_its_trucks_drive_home(day_plan):
    """Delivering everything is not the same as being finished.

    A completed operation whose fleet is still returning used to answer 404 from
    /api/dispatch/active, so a refresh dropped the operation and the map lost the
    vehicle at the exact moment the last order was delivered — while a green line
    still ran home.
    """
    dispatch_id = day_plan(hospitals=1)
    # 90x with the 30-second tick cap advances 45 simulated minutes per tick:
    # enough for the one delivery, not enough to be home again.
    service.depart_dispatch(dispatch_id, "go", speed=90.0)
    _age_clock(dispatch_id, minutes_ago=3)
    delivered = service.tick_dispatch(dispatch_id)          # the one order lands

    assert delivered["status"] == "completed"
    assert delivered["route_view"]["metrics"]["still_returning"] == 1
    assert service.get_active_dispatch()["dispatch_id"] == dispatch_id   # not 404

    service.set_dispatch_speed(dispatch_id, 300.0)          # +150 sim-min per tick
    _age_clock(dispatch_id, minutes_ago=30)                 # …and now it is home
    home = service.tick_dispatch(dispatch_id)

    assert home["route_view"]["metrics"]["still_returning"] == 0
    assert home["route_view"]["routes"][0]["track"]["finished"] is True
    with pytest.raises(KeyError):
        service.get_active_dispatch()


def test_the_drive_home_counts_as_driven(day_plan):
    """The last leg serves no order, so it used to look "still ahead" for ever.

    Judging progress by "is this stop's order delivered" left the return leg
    green even after the run finished: the truck vanished at its last stop while
    a green line still ran home. Progress now comes from the schedule.
    """
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go", speed=300.0)

    fresh = service.get_dispatch(dispatch_id)["route_view"]["routes"][0]
    assert [leg["driven"] for leg in fresh["legs"]] == [False, False]
    assert fresh["legs"][-1]["order_id"] is None          # the way home

    _age_clock(dispatch_id, minutes_ago=3)
    service.tick_dispatch(dispatch_id)                    # delivers the one order
    driven = service.get_dispatch(dispatch_id)["route_view"]["routes"][0]

    assert driven["stops"][0]["delivered"] is True
    # Outbound is behind it; the way home is the leg it is on, so still ahead…
    assert driven["legs"][0]["driven"] is True
    # …and once the schedule is finished, everything is grey and the truck is home.
    _age_clock(dispatch_id, minutes_ago=30)
    finished = service.tick_dispatch(dispatch_id)["route_view"]["routes"][0]

    assert all(leg["driven"] for leg in finished["legs"])
    assert finished["track"]["finished"] is True
def test_an_unwatched_operation_does_not_race_through_the_day(day_plan):
    """Simulated time is charged for what was WATCHED, not for however long the
    application sat idle.

    Without the cap, two hours away at 300x threw the operation 36,000 simulated
    minutes forward: a demo opened in the morning and looked at after lunch was
    simply over, which is what happened to the user.
    """
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go", speed=300.0)
    _age_clock(dispatch_id, minutes_ago=120)          # two hours of real idleness

    ticked = service.tick_dispatch(dispatch_id)

    # At most MAX_TICK_SECONDS (30 s) is charged: 30 s × 300 / 60 = 150 sim-min.
    assert 540 < ticked["route_view"]["sim_now_min"] <= 540 + 151


def test_speed_zero_freezes_simulated_time_rather_than_the_refresh(day_plan):
    """The transport view's pause has to stop TIME, not just polling.

    Speed 0 makes ``simulated_now`` constant, so five real minutes later the
    operation is still at the same minute — and resuming re-bases on that frozen
    minute instead of jumping forward to where real time has got to.
    """
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go", speed=300.0)

    paused = service.set_dispatch_speed(dispatch_id, 0.0)["route_view"]["sim_now_min"]
    _age_clock(dispatch_id, minutes_ago=5)

    assert service.get_dispatch(dispatch_id)["route_view"]["sim_now_min"] == paused

    resumed = service.set_dispatch_speed(dispatch_id, 300.0)["route_view"]
    assert resumed["clock"]["speed"] == 300.0
    assert resumed["sim_now_min"] >= paused          # picked up where it stopped


def test_speed_must_be_one_of_the_offered_rates(day_plan):
    dispatch_id = day_plan(hospitals=1)
    service.depart_dispatch(dispatch_id, "go")
    with pytest.raises(ValueError, match="speed must be one of"):
        service.set_dispatch_speed(dispatch_id, 7.5)
