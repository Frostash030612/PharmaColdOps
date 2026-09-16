"""B6 second half (2026-09-16): the pickup point is the nearest source that HAS it.

Before this, every rescue fetched from the main warehouse. Now the candidate is
priced and reserved at the nearest **supply point that carries the product and
actually holds it** — the supply table grants permission, the request's ledger
supplies the fact, and both have to agree.

The leg is real work, so it lives in the state too: the clock must not deliver the
first order the moment the truck reaches the pickup point, and the map has to draw
the stop. Those two are the same bug seen from two sides, which is why they are
tested together.
"""
from __future__ import annotations

import pytest

from optimisation.dispatch_models import DeliveryOrder
from optimisation.dispatch_planner import DISPATCH_ORIGIN
from optimisation.dispatch_state import DispatchState, OrderProgress, VehicleProgress
from optimisation.dynamic_problem import accept_emergency_order, preview_emergency_order
from optimisation.singapore_loader import read_network
from optimisation.tracking import vehicle_track

NETWORK = read_network()
NODE = {n["facility_id"]: n["node_id"] for n in NETWORK["nodes"]}

#: A hospital the north-east depot is much closer to than the west warehouse.
NEAR_THE_DEPOT = "H-SKH"


def _leg(a, b):
    return (NETWORK["matrix"]["duration_s"][NODE[a]][NODE[b]] / 60.0,
            NETWORK["matrix"]["distance_m"][NODE[a]][NODE[b]])


@pytest.fixture(scope="module")
def network():
    return NETWORK


def _setup(*, lots: list[tuple[str, int]], carried=(), spare=0, position="H-NUH"):
    """An in-transit vehicle plus the ledger the rescue may draw from."""
    rescue = DeliveryOrder("RO-1", "vaccine_2_8", NEAR_THE_DEPOT, 20, 540, 1020, "chilled")
    orders = {o.order_id: OrderProgress(o.order_id, o.product_id,
                                        o.destination_facility_id, o.quantity,
                                        "V-1", "in_transit") for o in carried}
    inventory = [{"lot_id": f"LOT-{facility}", "product_id": "vaccine_2_8",
                  "facility_id": facility, "temperature_zone": "chilled",
                  "status": "available"} for facility, _ in lots]
    context = {"input": {
        "orders": [{"order_id": o.order_id, "product_id": o.product_id,
                    "destination_facility_id": o.destination_facility_id,
                    "quantity": o.quantity, "earliest_min": o.earliest_min,
                    "latest_min": o.latest_min} for o in (*carried, rescue)],
        "inventory": inventory,
        "vehicles": [
            {"vehicle_id": "V-1", "capacity": 200,
             "temperature_zone": "chilled", "status": "in_transit",
             "start_facility_id": DISPATCH_ORIGIN, "available_from_min": 0},
            # an idle truck, so the "send another one" option exists to compare
            {"vehicle_id": "V-2", "capacity": 200,
             "temperature_zone": "chilled", "status": "available",
             "start_facility_id": DISPATCH_ORIGIN, "available_from_min": 0},
        ],
    }}
    state = DispatchState(
        version=1, status="in_transit", orders=orders,
        vehicles={"V-1": VehicleProgress(
            "V-1", position, tuple(o.order_id for o in carried), status="in_transit",
            onboard_spare=(("vaccine_2_8", "chilled", spare),) if spare else ())},
        available_by_lot={f"LOT-{facility}": units for facility, units in lots},
        reserved_by_order={}, applied_commands=(),
    )
    return state, context, rescue


def _pickup_of(preview, kind):
    return next(c["pickup_facility_id"] for c in preview["candidates"]
                if c["kind"] == kind)


# --- which point is chosen --------------------------------------------------

def _detour(start: str, pickup: str, destination: str) -> float:
    """Metres driven to fetch at ``pickup`` instead of going straight there."""
    return (NETWORK["matrix"]["distance_m"][NODE[start]][NODE[pickup]]
            + NETWORK["matrix"]["distance_m"][NODE[pickup]][NODE[destination]])


def _expected_pickup(sources, start: str, destination: str) -> str:
    return min(sources, key=lambda facility: _detour(start, facility, destination))


def test_the_pickup_minimises_the_whole_detour_not_one_leg(network):
    """Warehouse and a north-east depot both hold it; the answer depends on where
    the truck is, and on both legs — not on which source is nearer to either end.
    """
    sources = [DISPATCH_ORIGIN, "D-HOUGANG"]
    state, context, rescue = _setup(
        lots=[(DISPATCH_ORIGIN, 100), ("D-HOUGANG", 100)], spare=5)
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)

    # the in-transit truck sits at H-NUH: fetching in the north-east is far shorter
    assert _pickup_of(preview, "return_to_depot") == _expected_pickup(
        sources, "H-NUH", NEAR_THE_DEPOT)
    assert _pickup_of(preview, "return_to_depot") == "D-HOUGANG"
    # a spare starts at the warehouse, where going out of the way is not worth it
    assert _pickup_of(preview, "spare_vehicle") == _expected_pickup(
        sources, DISPATCH_ORIGIN, NEAR_THE_DEPOT)
    assert _detour(DISPATCH_ORIGIN, _pickup_of(preview, "spare_vehicle"),
                   NEAR_THE_DEPOT) <= _detour(DISPATCH_ORIGIN, "D-HOUGANG",
                                              NEAR_THE_DEPOT)


def test_a_supply_point_without_stock_is_not_a_pickup(network):
    """The table says the depot *may* supply; the ledger says where it is."""
    state, context, rescue = _setup(lots=[(DISPATCH_ORIGIN, 100)])
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)

    assert _pickup_of(preview, "return_to_depot") == DISPATCH_ORIGIN


def test_a_product_the_point_does_not_carry_is_never_a_pickup(network):
    """Bugis+ holds no vaccine in the supply table, so it cannot be a source.

    The lot below is deliberately planted there to prove the *table* is checked,
    not just the ledger.
    """
    state, context, rescue = _setup(lots=[("D-BUGIS", 500)])
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)

    assert preview["feasible"] is False
    assert preview["reason"] == "insufficient_available_inventory"
    assert preview["candidates"] == []


def test_the_stock_option_needs_no_pickup(network):
    """Goods already on the truck mean no extra stop, and the payload says so."""
    state, context, rescue = _setup(lots=[(DISPATCH_ORIGIN, 100)], spare=50)
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)

    transit = next(c for c in preview["candidates"]
                   if c["kind"] == "add_stop_in_transit")
    assert transit["pickup_facility_id"] is None


# --- the leg reaches the ledger, the clock and the map ----------------------

def test_accepting_reserves_at_the_chosen_pickup(network):
    state, context, rescue = _setup(lots=[(DISPATCH_ORIGIN, 100), ("D-HOUGANG", 100)])
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)
    candidate = next(c for c in preview["candidates"] if c["kind"] == "return_to_depot")
    assert candidate["pickup_facility_id"] == "D-HOUGANG"

    after = accept_emergency_order(
        state, context, rescue, current_time_min=600,
        candidate_kind=candidate["kind"], vehicle_id=candidate["vehicle_id"],
        command_id="accept-pickup",
    )

    # the ledger follows the choice: the depot's stock must be untouched
    assert after.reserved_by_order[rescue.order_id] == (("LOT-D-HOUGANG", 20),)
    assert after.available_by_lot["LOT-D-HOUGANG"] == 80
    assert after.available_by_lot["LOT-" + DISPATCH_ORIGIN] == 100
    # ...and the truck must go there first
    assert after.vehicles["V-1"].pickup_facility_ids == ("D-HOUGANG",)


def test_the_map_shows_the_pickup_stop_first():
    from api import service

    state, context, rescue = _setup(lots=[(DISPATCH_ORIGIN, 100), ("D-HOUGANG", 100)])
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)
    candidate = next(c for c in preview["candidates"] if c["kind"] == "return_to_depot")
    after = accept_emergency_order(
        state, context, rescue, current_time_min=600,
        candidate_kind=candidate["kind"], vehicle_id=candidate["vehicle_id"],
        command_id="accept-map",
    )
    view = service.dispatch_route_view(after, context)

    stops = view["routes"][0]["stops"]
    assert stops[0]["kind"] == "pickup"
    assert stops[0]["node_id"] == NODE["D-HOUGANG"]
    assert stops[0]["order_id"] is None
    # the pickup is not an order: the truck still has exactly one to deliver
    assert [s["order_id"] for s in stops[1:]] == [rescue.order_id]


def test_the_clock_does_not_deliver_before_the_pickup_is_reached():
    """The arithmetic the tick uses, checked where it is easy to get wrong."""
    pickups = [NODE["D-HOUGANG"]]
    deliveries = [NODE[NEAR_THE_DEPOT]]
    sequence = [*pickups, *deliveries]

    # just after the pickup (minutes 0-1 of the run): nothing may be due
    early = vehicle_track(NETWORK, sequence, 480.0, 481.0)
    assert early["reached_stops"] - len(pickups) <= 0

    # well after the delivery: exactly one delivery may be due
    late = vehicle_track(NETWORK, sequence, 480.0, 600.0)
    assert late["reached_stops"] - len(pickups) >= 1
