"""Covers the two logic gaps fixed in dynamic_problem.py:

1. Free capacity (rated capacity minus what the vehicle is already carrying)
   gates whether an in-transit vehicle can take an emergency order — not the
   vehicle's rated capacity alone.
2. A return-to-depot detour must not silently make the vehicle's own
   remaining orders miss their delivery windows; a candidate that would is no
   longer reported as on_time, and the newly-late order is named.
"""
from optimisation.dispatch_models import DeliveryOrder
from optimisation.dispatch_state import DispatchState, OrderProgress, VehicleProgress
from optimisation.dynamic_problem import preview_emergency_order
from optimisation.singapore_loader import read_network

NETWORK = read_network()
NODE_IDS = {n["facility_id"]: n["node_id"] for n in NETWORK["nodes"]}


def leg_minutes(a, b):
    return NETWORK["matrix"]["duration_s"][NODE_IDS[a]][NODE_IDS[b]] / 60.0


def _context(orders):
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
            "vehicles": [
                {"vehicle_id": "V-1", "capacity": 40, "temperature_zone": "chilled",
                 "status": "in_transit", "available_from_min": 0},
            ],
        }
    }


def _state(remaining_order, onboard_quantity):
    return DispatchState(
        version=1, status="in_transit",
        orders={remaining_order.order_id: OrderProgress(
            remaining_order.order_id, remaining_order.product_id,
            remaining_order.destination_facility_id, onboard_quantity, "V-1", "in_transit",
        )},
        vehicles={"V-1": VehicleProgress(
            "V-1", "H-NUH", (remaining_order.order_id,), status="in_transit",
        )},
        available_by_lot={"LOT-1": 100},
        reserved_by_order={remaining_order.order_id: (("LOT-1", onboard_quantity),)},
    )


def test_in_transit_vehicle_without_free_capacity_is_not_a_candidate():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 30, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=30)
    context = _context([onboard])
    # Vehicle's rated capacity (40) alone would fit this order (20), but only
    # 10 units are actually free (40 - 30 already on board).
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-NHCS", 20, 540, 1200, "chilled")

    result = preview_emergency_order(state, context, emergency, current_time_min=600)

    assert result["candidates"] == []
    assert result["feasible"] is False


def test_in_transit_vehicle_with_enough_free_capacity_is_offered():
    onboard = DeliveryOrder("DO-1", "vaccine_2_8", "H-CGH", 10, 540, 1200, "chilled")
    state = _state(onboard, onboard_quantity=10)
    context = _context([onboard])
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-NHCS", 20, 540, 1200, "chilled")

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
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-NHCS", 5, 540, 1200, "chilled")

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
    emergency = DeliveryOrder("URG-1", "vaccine_2_8", "H-NHCS", 5, 540, 1200, "chilled")

    # H-NUH -> H-CGH alone already takes well past minute 601.
    result = preview_emergency_order(state, context, emergency, current_time_min=600)

    candidate = next(c for c in result["candidates"] if c["kind"] == "return_to_depot")
    affected = {a["order_id"]: a for a in candidate["affected_orders"]}
    assert affected["DO-1"]["already_late"] is True
    assert affected["DO-1"]["newly_late"] is False
