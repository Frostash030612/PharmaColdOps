"""Covers the logic gaps fixed in dynamic_problem.py:

1. Free capacity (rated capacity minus what the vehicle is already carrying —
   including its onboard spare) gates whether an in-transit vehicle can take an
   emergency order, not the vehicle's rated capacity alone.
2. A return-to-depot detour must not silently make the vehicle's own remaining
   orders miss their delivery windows; a candidate that would is no longer
   reported as on_time, and the newly-late order is named.
3. An in-transit vehicle may serve a branch order out of the spare it already
   carries (`add_stop_in_transit`) instead of driving back to the depot — the
   "change this truck's route" option that used to be missing (B4).
4. Candidates are ranked under a switchable policy: protect the orders already
   on board, or protect the fleet by reusing a vehicle already running (D1).
"""
import pytest

from optimisation.dispatch_models import DeliveryOrder
from optimisation.dispatch_state import DispatchState, OrderProgress, VehicleProgress
from optimisation.dynamic_problem import accept_emergency_order, preview_emergency_order
from optimisation.singapore_loader import read_network

NETWORK = read_network()
NODE_IDS = {n["facility_id"]: n["node_id"] for n in NETWORK["nodes"]}


def leg_minutes(a, b):
    return NETWORK["matrix"]["duration_s"][NODE_IDS[a]][NODE_IDS[b]] / 60.0


def _context(orders, *, capacity=40, spare_vehicle=False, vehicle_status="in_transit"):
    vehicles = [
        {"vehicle_id": "V-1", "capacity": capacity, "temperature_zone": "chilled",
         "status": vehicle_status, "available_from_min": 0},
    ]
    if spare_vehicle:
        # A vehicle that is part of the operation's fleet but is not carrying
        # anything yet: the "send another one" option.
        vehicles.append({
            "vehicle_id": "V-2", "capacity": capacity, "temperature_zone": "chilled",
            "status": "available", "available_from_min": 0,
        })
    return {
        "input": {
            "orders": [
                {"order_id": o.order_id, "destination_facility_id": o.destination_facility_id,
                 "latest_min": o.latest_min, "earliest_min": o.earliest_min}
                for o in orders
            ],
            "inventory": [
                {"lot_id": "LOT-1", "product_id": "vaccine_2_8", "facility_id": "W-KN-PIONEER",
                 "temperature_zone": "chilled", "status": "available"},
            ],
            "vehicles": vehicles,
        }
    }


def _state(remaining_order, onboard_quantity, *, spare=(), status="in_transit"):
    return DispatchState(
        version=1, status="in_transit",
        orders={remaining_order.order_id: OrderProgress(
            remaining_order.order_id, remaining_order.product_id,
            remaining_order.destination_facility_id, onboard_quantity, "V-1", "in_transit",
        )},
        vehicles={"V-1": VehicleProgress(
            "V-1", "H-NUH", (remaining_order.order_id,), status=status,
            onboard_spare=spare,
        )},
        available_by_lot={"LOT-1": 100},
        reserved_by_order={remaining_order.order_id: (("LOT-1", onboard_quantity),)},
    )


def _spare(quantity, product="vaccine_2_8", zone="chilled"):
    return ((product, zone, quantity),)


def test_in_transit_vehicle_without_free_capacity_is_not_a_candidate():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 30, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=30)
    context = _context([onboard])
    # Vehicle's rated capacity (40) alone would fit this order (20), but only
    # 10 units are actually free (40 - 30 already on board).
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    result = preview_emergency_order(state, context, emergency, current_time_min=600)

    assert result["candidates"] == []
    assert result["feasible"] is False


def test_in_transit_vehicle_with_enough_free_capacity_is_offered():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10)
    context = _context([onboard])
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    result = preview_emergency_order(state, context, emergency, current_time_min=600)

    kinds = {c["kind"] for c in result["candidates"]}
    assert "return_to_depot" in kinds


def test_detour_that_makes_a_remaining_order_late_is_not_on_time():
    baseline_direct = leg_minutes("H-NUH", "H-CGH")
    # Tight enough that the direct trip is on time but the return-to-depot
    # detour (H-NUH -> depot -> emergency stop -> H-CGH) cannot be.
    latest_min = 600 + round(baseline_direct) + 5
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 5, 540, latest_min, "chilled")
    state = _state(onboard, onboard_quantity=5)
    context = _context([onboard])
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 5, 540, 1200, "chilled")

    result = preview_emergency_order(state, context, emergency, current_time_min=600)

    candidate = next(c for c in result["candidates"] if c["kind"] == "return_to_depot")
    affected = {a["order_id"]: a for a in candidate["affected_orders"]}
    assert affected["DO-1"]["newly_late"] is True
    assert affected["DO-1"]["already_late"] is False
    assert candidate["on_time"] is False


def test_already_late_remaining_order_is_not_blamed_on_the_detour():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 5, 540, 601, "chilled")
    state = _state(onboard, onboard_quantity=5)
    context = _context([onboard])
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 5, 540, 1200, "chilled")

    # H-NUH -> H-CGH alone already takes well past minute 601.
    result = preview_emergency_order(state, context, emergency, current_time_min=600)

    candidate = next(c for c in result["candidates"] if c["kind"] == "return_to_depot")
    affected = {a["order_id"]: a for a in candidate["affected_orders"]}
    assert affected["DO-1"]["already_late"] is True
    assert affected["DO-1"]["newly_late"] is False


# --- onboard spare: "change this truck's route" without a depot return (B4) ---

def test_in_transit_vehicle_can_serve_the_order_from_its_own_spare():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10, spare=_spare(30))
    context = _context([onboard], capacity=60)
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    result = preview_emergency_order(state, context, emergency, current_time_min=600)
    kinds = {c["kind"]: c for c in result["candidates"]}

    assert "add_stop_in_transit" in kinds
    # Serving from the spare never drives to the depot, so it is strictly
    # cheaper than fetching more stock — that is the whole point of the option.
    assert kinds["add_stop_in_transit"]["distance_m"] < kinds["return_to_depot"]["distance_m"]
    assert kinds["add_stop_in_transit"]["eta_min"] < kinds["return_to_depot"]["eta_min"]
    assert kinds["add_stop_in_transit"]["onboard_spare_used"] == 20


def test_onboard_option_is_absent_when_the_spare_is_too_small():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10, spare=_spare(5))
    context = _context([onboard], capacity=60)
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    kinds = {c["kind"] for c in preview_emergency_order(
        state, context, emergency, current_time_min=600)["candidates"]}

    assert "add_stop_in_transit" not in kinds
    assert "return_to_depot" in kinds


def test_spare_for_another_product_does_not_count():
    """Cold-chain discipline: a chilled order cannot be served from frozen spare."""
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10, spare=(("frozen_m20", "frozen", 30),))
    context = _context([onboard], capacity=60)
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    kinds = {c["kind"] for c in preview_emergency_order(
        state, context, emergency, current_time_min=600)["candidates"]}

    assert "add_stop_in_transit" not in kinds


def test_accepting_the_spare_option_consumes_it_and_leaves_depot_stock_alone():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10, spare=_spare(30))
    context = _context([onboard], capacity=60)
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    new = accept_emergency_order(
        state, context, emergency, current_time_min=600,
        candidate_kind="add_stop_in_transit", vehicle_id="V-1", command_id="cmd-1",
    )

    assert new.vehicles["V-1"].onboard_spare == _spare(10)      # 30 - 20 consumed
    assert new.vehicles["V-1"].remaining_order_ids[0] == "URG-1"  # served next
    # The goods came off the truck, so the depot ledger must not move.
    assert new.available_by_lot == state.available_by_lot
    assert new.reserved_by_order["URG-1"] == (("ONBOARD-V-1", 20),)
    # Its own remaining order is still on board and still scheduled.
    assert "DO-1" in new.vehicles["V-1"].remaining_order_ids


# --- switchable ranking policy (D1) ----------------------------------------

def test_policy_switches_between_protecting_orders_and_protecting_the_fleet():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10)
    context = _context([onboard], capacity=60, spare_vehicle=True)
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    disruption = preview_emergency_order(
        state, context, emergency, current_time_min=600, policy="minimize_disruption")
    fleet = preview_emergency_order(
        state, context, emergency, current_time_min=600, policy="minimize_vehicles")

    # Default: nobody already on board gets delayed, so a spare is sent.
    assert disruption["selected_candidate"]["kind"] == "spare_vehicle"
    # Fleet-first: reuse the truck that is already rolling and take the delay.
    assert fleet["selected_candidate"]["starts_new_vehicle"] is False
    assert fleet["selected_candidate"]["vehicle_id"] == "V-1"
    assert fleet["policy"] == "minimize_vehicles"
    assert disruption["selected_candidate"] is not fleet["selected_candidate"]


def test_an_unknown_policy_is_refused_rather_than_guessed():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10)
    context = _context([onboard])
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-SGH", 20, 540, 1200, "chilled")

    with pytest.raises(ValueError, match="unknown policy"):
        preview_emergency_order(
            state, context, emergency, current_time_min=600, policy="cheapest")
