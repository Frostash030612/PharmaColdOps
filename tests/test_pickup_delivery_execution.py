"""PDPTW step 4 (2026-09-16): an accepted pickup-delivery plan can actually run.

Steps 1-3 taught the planner to *solve* a pickup-delivery problem: one truck, two
sources, one run. That plan could not be dispatched — the execution state modelled
a truck's work as an order queue with at most a leading pickup, so an accepted
operation would have drawn a route the truck does not drive, and the state machine
refused it out loud.

Here the state carries the driven sequence instead. The rule the whole file turns
on: **a delivery is due only once the schedule has driven past its own pickup**,
which for a grouped route collapses to exactly the pre-PDPTW arithmetic
(``reached - pickups > delivered``). That equality is the reason this could be
added behind a switch without disturbing what already ran, and it is pinned below.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.dispatch_models import (
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
)
from optimisation.dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders
from optimisation.dispatch_state import (
    DispatchState, OrderProgress, PlannedStop, VehicleProgress,
    accept_plan, deliver_next, depart, next_stop, planned_stops,
)
from optimisation.singapore_loader import read_network
from optimisation.tracking import make_clock, vehicle_track

client = TestClient(app)
NETWORK = read_network()
NODE = {n["facility_id"]: n["node_id"] for n in NETWORK["nodes"]}

#: One warehouse order, one distribution-point order and a second warehouse order
#: — the case the grouped model must split over two trucks.
ORDERS = (
    DeliveryOrder("O-W1", "vaccine_2_8", "H-SGH", 30, 540, 1020, "chilled",
                  origin_facility_id=DISPATCH_ORIGIN),
    DeliveryOrder("O-D1", "vaccine_2_8", "H-SKH", 20, 540, 1020, "chilled",
                  origin_facility_id="D-HOUGANG"),
    DeliveryOrder("O-W2", "vaccine_2_8", "H-NUH", 25, 540, 1020, "chilled",
                  origin_facility_id=DISPATCH_ORIGIN),
)
INVENTORY = (
    InventoryLot("L-W", "vaccine_2_8", DISPATCH_ORIGIN, 300, "chilled"),
    InventoryLot("L-D", "vaccine_2_8", "D-HOUGANG", 300, "chilled"),
)
ONE_TRUCK = (DispatchVehicle("V-1", 100, "chilled", DISPATCH_ORIGIN),)


def _plan():
    return plan_delivery_orders(
        ORDERS, INVENTORY, ONE_TRUCK, algorithm="ortools",
        constraints=DispatchConstraints(routing_model="pickup_delivery"),
    )


# --- an interleaved run, built by hand so the arithmetic is checked directly ---

#: Collect O-D1 in the north-east, collect O-W2 at the warehouse, deliver O-W2,
#: then deliver O-D1 on the way back past the hospital. The second pickup happens
#: *after* nothing has been delivered and the last delivery comes after a pickup
#: that is not its own — the shape an order queue cannot express.
INTERLEAVED = (
    PlannedStop("pickup", "O-D1", "D-HOUGANG"),
    PlannedStop("pickup", "O-W2", DISPATCH_ORIGIN),
    PlannedStop("delivery", "O-W2", "H-NUH"),
    PlannedStop("pickup", "O-W1", DISPATCH_ORIGIN),
    PlannedStop("delivery", "O-W1", "H-SGH"),
    PlannedStop("delivery", "O-D1", "H-SKH"),
)


def _state(*, delivered: tuple[str, ...] = (), plan=INTERLEAVED, vehicle_id="V-1"):
    """An in-transit truck driving ``plan``, with ``delivered`` already logged."""
    orders = {
        order.order_id: OrderProgress(
            order.order_id, order.product_id, order.destination_facility_id,
            order.quantity, vehicle_id,
            "delivered" if order.order_id in delivered else "in_transit",
        )
        for order in ORDERS
    }
    remaining = tuple(stop.order_id for stop in plan
                      if stop.kind == "delivery" and stop.order_id not in delivered)
    vehicle = VehicleProgress(vehicle_id, DISPATCH_ORIGIN, remaining,
                              status="in_transit", delivered_order_ids=delivered,
                              drive_plan=plan)
    return DispatchState(2, "in_transit", orders, {vehicle_id: vehicle},
                         {"L-W": 300 - 55, "L-D": 300 - 20}, {}, ())


def _context():
    return {"input": {
        "orders": [{
            "order_id": order.order_id, "product_id": order.product_id,
            "destination_facility_id": order.destination_facility_id,
            "quantity": order.quantity, "earliest_min": order.earliest_min,
            "latest_min": order.latest_min,
        } for order in ORDERS],
        "inventory": [], "vehicles": [],
    }}


# --- the accepted plan is the driven plan ------------------------------------

def test_accepting_a_pickup_delivery_plan_records_the_driven_sequence():
    """Step 4's headline: the plan that was priced is the sequence that runs."""
    plan = _plan()
    group = plan.zone_plans[0]
    route = group.result.routes[0]
    expected = group.stop_plan_by_vehicle[route.vehicle_id]

    state = accept_plan(plan, ORDERS, INVENTORY, command_id="accept-pd",
                        vehicles=ONE_TRUCK)
    vehicle = state.vehicles["V-1"]

    assert [(stop.kind, stop.order_id) for stop in vehicle.drive_plan] == [
        (kind, order_id) for kind, order_id, _ in expected]
    # a pickup carries its supply point, so the map can draw the leg
    assert [stop.facility_id for stop in vehicle.drive_plan if stop.is_pickup] == [
        facility_id for kind, _, facility_id in expected if kind == "pickup"]


def test_the_queue_is_the_deliveries_in_driven_order():
    """The queue still answers "what is left to deliver"; the plan says when."""
    plan = _plan()
    state = accept_plan(plan, ORDERS, INVENTORY, command_id="accept-queue",
                        vehicles=ONE_TRUCK)
    vehicle = state.vehicles["V-1"]

    assert vehicle.remaining_order_ids == tuple(
        stop.order_id for stop in vehicle.drive_plan if stop.kind == "delivery")
    # ...and the ledger drew each order's goods where that order is collected
    assert state.reserved_by_order["O-D1"] == (("L-D", 20),)
    assert state.reserved_by_order["O-W1"] == (("L-W", 30),)


def test_each_pickup_is_followed_by_its_own_delivery():
    """The pairing is a property of the plan, not of whoever reads it."""
    state = accept_plan(_plan(), ORDERS, INVENTORY, command_id="accept-pair",
                        vehicles=ONE_TRUCK)
    plan_stops = state.vehicles["V-1"].drive_plan
    collected: list[str] = []
    for stop in plan_stops:
        if stop.is_pickup:
            collected.append(stop.order_id)
        else:
            assert stop.order_id in collected, "delivered before it was collected"
            collected.remove(stop.order_id)
    assert collected == []


# --- the arithmetic: a delivery waits for its own pickup ---------------------

def test_the_next_delivery_counts_the_pickups_in_front_of_it():
    """Two pickups precede the first delivery, so it is three stops in."""
    state = _state()

    index, stop = next_stop(state.vehicles["V-1"])

    assert (index, stop.order_id) == (2, "O-W2")
    assert index == len(INTERLEAVED[:2])


def test_a_pickup_after_a_delivery_does_not_delay_the_next_one():
    """Once O-W2 is delivered, its own pickup is behind the truck for good."""
    state = _state(delivered=("O-W2",))

    index, stop = next_stop(state.vehicles["V-1"])

    assert (index, stop.order_id) == (4, "O-W1")


def _first_minute(network, sequence, *, index, reached):
    """The first minute of the run at which ``reached`` stops are behind us."""
    for minute in range(1, 601):
        track = vehicle_track(network, sequence, 540.0, 540.0 + minute)
        if track["reached_stops"] >= reached:
            return minute, track
    return None, None


def test_the_truck_is_not_early_for_a_delivery_whose_pickup_is_ahead():
    """The clock reads the same index, so it cannot deliver on the way to collect."""
    state = _state()
    sequence = [NODE[stop.facility_id] for stop in INTERLEAVED]
    index, stop = next_stop(state.vehicles["V-1"])
    assert (index, stop.order_id) == (2, "O-W2")

    # Stop 1 is the last pickup before this delivery. Reaching the pickups — and
    # driving past both of them — must leave the delivery undelivered: the soonest
    # it can be due is when the schedule reaches stop 2 itself.
    pickup_minute, _ = _first_minute(NETWORK, sequence, index=index, reached=2)
    due_minute, due_track = _first_minute(NETWORK, sequence, index=index, reached=3)

    assert pickup_minute is not None and due_minute is not None
    assert due_minute > pickup_minute, "delivered while still collecting"
    assert due_track["reached_stops"] > index
    # ...and nothing is due before that minute
    earlier = vehicle_track(NETWORK, sequence, 540.0, 540.0 + pickup_minute)
    assert earlier["reached_stops"] <= index


def test_delivering_advances_to_the_next_stop_in_the_plan():
    """Not to the next *queued* order: the plan decides, and both agree."""
    state = _state()
    after = deliver_next(state, "V-1", command_id="c1")

    assert after.orders["O-W2"].status == "delivered"
    assert after.vehicles["V-1"].remaining_order_ids == ("O-W1", "O-D1")
    assert next_stop(after.vehicles["V-1"])[1].order_id == "O-W1"
    assert after.vehicles["V-1"].drive_plan == INTERLEAVED, "the run is not pruned"


# --- the map shows what is driven -------------------------------------------

def test_the_map_draws_every_stop_in_the_order_it_is_driven():
    state = _state()
    view = service.dispatch_route_view(state, _context())
    stops = view["routes"][0]["stops"]

    assert [(stop["kind"], stop["order_id"]) for stop in stops] == [
        (stop.kind, stop.order_id) for stop in INTERLEAVED]
    assert [stop["facility_id"] for stop in stops if stop["kind"] == "pickup"] == [
        "D-HOUGANG", DISPATCH_ORIGIN, DISPATCH_ORIGIN]
    assert view["routes"][0]["customer_ids"] == [NODE[stop.facility_id]
                                                 for stop in INTERLEAVED]
    # a pickup serves no order and carries no quantity: it is a detour, not a drop
    assert [stop["quantity"] for stop in stops if stop["kind"] == "pickup"] == [0, 0, 0]
    assert view["metrics"]["orders_delivered"] == 0


def test_the_map_keeps_a_pickup_that_comes_after_a_delivery():
    """Order matters on the map, not just the set of stops."""
    state = _state(delivered=("O-W2",))
    view = service.dispatch_route_view(state, _context())
    stops = view["routes"][0]["stops"]

    kinds = [stop["kind"] for stop in stops]
    assert kinds == ["pickup", "pickup", "delivery", "pickup", "delivery", "delivery"]
    assert [stop["delivered"] for stop in stops] == [False, False, True,
                                                     False, False, False]


# --- the legacy derivation is untouched --------------------------------------

def test_a_grouped_route_still_drives_the_legacy_sequence():
    """No plan ⇒ the old description: leading pickups, then the queue."""
    vehicle = VehicleProgress("V-9", DISPATCH_ORIGIN, ("A", "B"),
                              status="in_transit", delivered_order_ids=("C",),
                              pickup_facility_ids=("D-HOUGANG",))

    assert [(stop.kind, stop.order_id) for stop in planned_stops(vehicle)] == [
        ("pickup", ""), ("delivery", "C"), ("delivery", "A"), ("delivery", "B")]
    # the pre-PDPTW arrival test, unchanged: reached - pickups > delivered
    index, stop = next_stop(vehicle)
    assert (index, stop.order_id) == (1 + 1, "A")


def test_a_finished_truck_has_no_next_stop():
    vehicle = VehicleProgress("V-9", DISPATCH_ORIGIN, (), status="completed",
                              delivered_order_ids=("A",))
    assert next_stop(vehicle) is None


def test_rescue_refuses_a_pickup_delivery_run_instead_of_losing_the_order():
    """A rescue splices the order queue; a paired run drives a stop sequence.

    Splicing only the queue would leave the new order assigned to a truck that
    never drives to it — the ledger and the map would disagree for the rest of the
    day. Refusing names the way out (plan the batch as ``grouped``).
    """
    from optimisation.dynamic_problem import preview_emergency_order

    state = accept_plan(_plan(), ORDERS, INVENTORY, command_id="accept-rescue",
                        vehicles=ONE_TRUCK)
    rescue = DeliveryOrder("RO-1", "vaccine_2_8", "H-TTSH", 20, 540, 1020, "chilled",
                           origin_facility_id=DISPATCH_ORIGIN)

    with pytest.raises(ValueError, match="not available for a pickup-delivery run"):
        preview_emergency_order(state, _context(), rescue, current_time_min=600)


def test_rescue_is_not_refused_on_a_grouped_run():
    """The guard keys off the plan, not off the day.

    What the grouped rescue *does* is covered where it belongs
    (``tests/test_rescue_*.py``, 40-odd tests on real fixtures); this only pins
    that a queue-based state still gets through the new gate.
    """
    from optimisation.dynamic_problem import preview_emergency_order

    state = DispatchState(
        2, "in_transit",
        {"O-W1": OrderProgress("O-W1", "vaccine_2_8", "H-SGH", 30, "V-1", "in_transit")},
        {"V-1": VehicleProgress("V-1", DISPATCH_ORIGIN, ("O-W1",), status="in_transit")},
        {"L-W": 300}, {},
    )
    rescue = DeliveryOrder("RO-1", "vaccine_2_8", "H-SGH", 20, 540, 1020, "chilled",
                           origin_facility_id=DISPATCH_ORIGIN)

    preview = preview_emergency_order(state, _context(), rescue, current_time_min=600)

    assert preview["order_id"] == "RO-1", "no pickup-delivery refusal on a grouped run"


# --- and it still goes through the API ---------------------------------------

@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def _age_clock(dispatch_id, *, minutes_ago):
    """Backdate the clock's start so simulated time has already elapsed."""
    context = service.load_context(service.DISPATCH_DATABASE_URL, dispatch_id)
    started = datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)
    context["clock"] = make_clock(context["clock"]["sim_start_min"],
                                  context["clock"]["speed"], started.isoformat())
    service.update_context(service.DISPATCH_DATABASE_URL, dispatch_id, context)


def _create_run(dispatch_id):
    body = {
        "algorithm": "ortools",
        "dispatch_id": dispatch_id,
        "command_id": f"{dispatch_id}-create",
        "constraints": {"routing_model": "pickup_delivery"},
        "orders": [service._order_dump(order) for order in ORDERS],
        "inventory": [service._lot_dump(lot) for lot in INVENTORY],
        "vehicles": [service._vehicle_dump(vehicle) for vehicle in ONE_TRUCK],
    }
    response = client.post("/api/dispatch/runs", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_api_dispatches_a_pickup_delivery_plan():
    """Preview → create → depart over HTTP, so a demo can actually drive it."""
    preview = client.post("/api/dispatch/plan", json={
        "algorithm": "ortools",
        "constraints": {"routing_model": "pickup_delivery"},
        "orders": [service._order_dump(order) for order in ORDERS],
        "inventory": [service._lot_dump(lot) for lot in INVENTORY],
        "vehicles": [service._vehicle_dump(vehicle) for vehicle in ONE_TRUCK],
    })
    assert preview.status_code == 200

    created = _create_run("pd-api")
    assert created["status"] == "accepted"
    # the accepted run carries the driven sequence, pickups interleaved
    stops = created["route_view"]["routes"][0]["stops"]
    assert [stop["kind"] for stop in stops].count("pickup") == 3

    departed = client.post("/api/dispatch/runs/pd-api/depart",
                           json={"command_id": "pd-api-go", "speed": 300.0})
    assert departed.status_code == 200, departed.text
    assert departed.json()["status"] == "in_transit"


def test_the_clock_collects_before_it_delivers_over_http():
    """The end-to-end version of the arithmetic above: the ledger matches the map.

    Nothing may be delivered while the truck is still on its way to collect, and
    once it is delivered the order is the one the sequence says is next.
    """
    _create_run("pd-clock")
    service.depart_dispatch("pd-clock", "pd-clock-go", speed=300.0)
    _age_clock("pd-clock", minutes_ago=25)          # halfway into the run
    half = service.tick_dispatch("pd-clock")
    vehicle = half["vehicles"]["V-1"]
    delivered_half = list(vehicle["delivered_order_ids"])
    stops = half["route_view"]["routes"][0]["stops"]
    sequence = [stop["order_id"] for stop in stops if stop["kind"] == "delivery"]
    # The ledger's order IS the plan's order — not the queue's, not the dict's.
    assert delivered_half == sequence[:len(delivered_half)]
    assert {order_id for order_id, item in half["orders"].items()
            if item["status"] == "delivered"} == set(delivered_half)
    for stop in stops:
        if stop["kind"] == "delivery":
            assert stop["delivered"] is (stop["order_id"] in delivered_half)
    # ...and nothing was delivered before its own pickup was reached: the first
    # pickup comes before the first delivery in the driven sequence.
    kinds = [stop["kind"] for stop in stops]
    assert kinds[:kinds.index("delivery")].count("pickup") == kinds.index("delivery")

    _age_clock("pd-clock", minutes_ago=200)          # well past the last stop
    end = service.tick_dispatch("pd-clock")
    assert end["route_view"]["metrics"]["orders_delivered"] == 3
    assert end["status"] == "completed"
