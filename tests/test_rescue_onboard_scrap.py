"""B6 (2026-09-16, last piece): the scrapped shipment is still ON the truck.

The case names the order it is about (B6 first half). If that order is still in a
vehicle's remaining queue, the goods are physically in the truck, and the rescue
has one extra obligation the "already at the hospital" case does not: **the
spoiled goods must not be delivered**. They are handed over at the pickup stop —
the cold-chain reality is "return the spoiled batch, collect the replacement" in
one visit — and the order leaves the queue as ``scrapped``, which is neither
pending nor delivered.

Delivery status is what tells the two cases apart, and it comes straight out of
the state: in ``remaining_order_ids`` ⇒ on board; in ``delivered_order_ids`` ⇒
already handed over at the hospital.
"""
from __future__ import annotations

import pytest

from api import service
from optimisation.dispatch_models import DeliveryOrder
from optimisation.dispatch_planner import DISPATCH_ORIGIN
from optimisation.dispatch_state import DispatchState, OrderProgress, VehicleProgress
from optimisation.dynamic_problem import accept_emergency_order, preview_emergency_order
from optimisation.singapore_loader import read_network

NETWORK = read_network()
NODE = {n["facility_id"]: n["node_id"] for n in NETWORK["nodes"]}
RESCUE_DESTINATION = "H-SKH"


def _leg(a, b):
    return (NETWORK["matrix"]["duration_s"][NODE[a]][NODE[b]] / 60.0,
            NETWORK["matrix"]["distance_m"][NODE[a]][NODE[b]])


@pytest.fixture(scope="module")
def network():
    return NETWORK


def _state_with_cargo(*, on_board_order: str | None, onboard_spare: int = 50):
    """One in-transit truck carrying ``DO-1`` (unless it was already delivered)."""
    carried = DeliveryOrder("DO-1", "vaccine_2_8", "H-SGH", 20, 540, 1020, "chilled")
    rescue = DeliveryOrder("RO-1", "vaccine_2_8", RESCUE_DESTINATION, 20, 540, 1020,
                           "chilled")
    if on_board_order == "DO-1":
        remaining, delivered = ("DO-1",), ()
    else:                                   # already handed over at the hospital
        remaining, delivered = (), ("DO-1",)
    state = DispatchState(
        version=1, status="in_transit",
        orders={"DO-1": OrderProgress("DO-1", "vaccine_2_8", "H-SGH", 20, "V-1",
                                      "in_transit")},
        vehicles={"V-1": VehicleProgress("V-1", "H-NUH", remaining,
                                         delivered_order_ids=delivered,
                                         status="in_transit",
                                         onboard_spare=(("vaccine_2_8", "chilled",
                                                         onboard_spare),))},
        available_by_lot={"LOT-1": 200}, reserved_by_order={}, applied_commands=(),
    )
    context = {"input": {
        "orders": [
            {"order_id": "DO-1", "product_id": "vaccine_2_8",
             "destination_facility_id": "H-SGH", "quantity": 20,
             "earliest_min": 540, "latest_min": 1020},
            {"order_id": "RO-1", "product_id": "vaccine_2_8",
             "destination_facility_id": RESCUE_DESTINATION, "quantity": 20,
             "earliest_min": 540, "latest_min": 1020},
        ],
        "inventory": [{"lot_id": "LOT-1", "product_id": "vaccine_2_8",
                       "facility_id": DISPATCH_ORIGIN, "temperature_zone": "chilled",
                       "status": "available"}],
        "vehicles": [{"vehicle_id": "V-1", "capacity": 200,
                      "temperature_zone": "chilled", "status": "in_transit",
                      "start_facility_id": DISPATCH_ORIGIN, "available_from_min": 0}],
    }}
    return state, context, rescue


def test_a_shipment_still_in_the_truck_is_flagged_as_on_board(network):
    state, context, rescue = _state_with_cargo(on_board_order="DO-1")
    preview = preview_emergency_order(state, context, rescue, current_time_min=600,
                                      spoiled_order_id="DO-1")

    assert preview["quarantine_order_id"] == "DO-1"
    assert preview["quarantine_vehicle_id"] == "V-1"


def test_a_shipment_already_delivered_is_not_on_board(network):
    """Today's demo path: the excursion was found at the hospital."""
    state, context, rescue = _state_with_cargo(on_board_order=None)
    preview = preview_emergency_order(state, context, rescue, current_time_min=600,
                                      spoiled_order_id="DO-1")

    assert preview["quarantine_order_id"] is None
    assert preview["quarantine_vehicle_id"] is None


def test_the_pickup_option_carries_the_batch_it_hands_over(network):
    state, context, rescue = _state_with_cargo(on_board_order="DO-1")
    preview = preview_emergency_order(state, context, rescue, current_time_min=600,
                                      spoiled_order_id="DO-1")

    picking = [c for c in preview["candidates"] if c["pickup_facility_id"]]
    assert picking, "a truck without the replacement on board must fetch it"
    for candidate in picking:
        assert candidate["quarantine_order_ids"] == ["DO-1"]

    # the onboard option makes no stop, so it hands nothing over: declared, not silent
    onboard = next((c for c in preview["candidates"]
                    if c["kind"] == "add_stop_in_transit"), None)
    if onboard is not None:
        assert onboard["quarantine_order_ids"] == []


def test_adopting_the_plan_scraps_it_instead_of_delivering_it(network):
    state, context, rescue = _state_with_cargo(on_board_order="DO-1")
    candidate = next(c for c in preview_emergency_order(
        state, context, rescue, current_time_min=600, spoiled_order_id="DO-1",
    )["candidates"] if c["kind"] == "add_stop_in_transit")

    after = accept_emergency_order(
        state, context, rescue, current_time_min=600,
        candidate_kind=candidate["kind"], vehicle_id=candidate["vehicle_id"],
        command_id="scrap-1", spoiled_order_id="DO-1",
    )

    assert after.orders["DO-1"].status == "scrapped"
    # out of the queue: the clock must not deliver goods that were written off
    assert "DO-1" not in after.vehicles["V-1"].remaining_order_ids
    assert "DO-1" not in after.vehicles["V-1"].delivered_order_ids
    # ...while the replacement is on its way
    assert after.vehicles["V-1"].remaining_order_ids == ("RO-1",)


def test_a_delivered_shipment_is_left_alone(network):
    state, context, rescue = _state_with_cargo(on_board_order=None)
    candidate = next(c for c in preview_emergency_order(
        state, context, rescue, current_time_min=600, spoiled_order_id="DO-1",
    )["candidates"] if c["kind"] == "add_stop_in_transit")

    after = accept_emergency_order(
        state, context, rescue, current_time_min=600,
        candidate_kind=candidate["kind"], vehicle_id=candidate["vehicle_id"],
        command_id="keep-1", spoiled_order_id="DO-1",
    )

    # the hospital already has it: nothing is written off by this decision
    assert after.orders["DO-1"].status == "in_transit"
    assert after.vehicles["V-1"].delivered_order_ids == ("DO-1",)


def test_the_view_still_shows_a_truck_whose_only_order_was_scrapped(network):
    """Otherwise the truck would vanish from the map with a run still to finish."""
    state, context, rescue = _state_with_cargo(on_board_order="DO-1")
    # fetch from the depot: that leg must remain visible after the scrapping
    candidate = next(c for c in preview_emergency_order(
        state, context, rescue, current_time_min=600, spoiled_order_id="DO-1",
    )["candidates"] if c["kind"] == "return_to_depot")

    after = accept_emergency_order(
        state, context, rescue, current_time_min=600,
        candidate_kind=candidate["kind"], vehicle_id=candidate["vehicle_id"],
        command_id="scrap-2", spoiled_order_id="DO-1",
    )
    # pretend the replacement was delivered too: the truck is now empty
    emptied = DispatchState(
        version=after.version, status=after.status, orders=after.orders,
        vehicles={"V-1": VehicleProgress("V-1", "H-SKH", (), delivered_order_ids=("RO-1",),
                                         status="in_transit",
                                         pickup_facility_ids=after.vehicles["V-1"].pickup_facility_ids,
                                         end_node_id=None)},
        available_by_lot=after.available_by_lot,
        reserved_by_order=after.reserved_by_order, applied_commands=after.applied_commands,
    )

    view = service.dispatch_route_view(emptied, context)

    assert view["routes"], "an emptied truck still has to drive to its parking node"
    stops = view["routes"][0]["stops"]
    assert any(stop.get("kind") == "pickup" for stop in stops)
