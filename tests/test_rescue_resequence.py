"""B6 second half (2026-09-16): the diverted vehicle's remaining queue is re-ordered.

Inserting a rescue order used to leave the rest of the queue exactly as it was, so
where the new stop landed decided how much the truck zig-zagged. The new pass is a
bounded 2-opt over the remaining stops, and its hard rule is that it may only
accept a swap that keeps every **currently on-time** order on time.

The two failure modes worth pinning:

* re-sequencing that silently drops or duplicates a remaining order — the accepted
  plan must be exactly the queue that was previewed, nothing more or less;
* "improving" the tour by making a punctual delivery late.
"""
from __future__ import annotations

import pytest

from optimisation.dynamic_problem import (
    _resequence_tail, accept_emergency_order, preview_emergency_order,
)
from optimisation.dispatch_models import DeliveryOrder

# A deliberately crossed layout: A and B sit on one side, C on the other, and the
# queue visits them in the order that zig-zags.
COORDS = {"START": (0.0, 0.0), "A": (10.0, 0.0), "B": (12.0, 0.0), "C": (1.0, 0.0)}


def leg(a, b):
    (x1, y1), (x2, y2) = COORDS[a], COORDS[b]
    return abs(x1 - x2) + abs(y1 - y2), abs(x1 - x2) + abs(y1 - y2)


def lookup(sequence):
    return {order_id: {"destination_facility_id": dest, "latest_min": 10_000}
            for order_id, dest in sequence}


def test_a_crossed_queue_is_reordered():
    """START → A → C → B (26) becomes START → C → A → B (15)."""
    order_lookup = lookup([("o-a", "A"), ("o-b", "B"), ("o-c", "C")])
    sequence, changed = _resequence_tail(
        ["o-a", "o-c", "o-b"], "START", 0.0, order_lookup, leg)

    assert changed is True
    assert sequence == ["o-c", "o-a", "o-b"]
    # ...and it really is shorter, not just different
    def tour(seq):
        at, total = "START", 0.0
        for order_id in seq:
            d, _ = leg(at, order_lookup[order_id]["destination_facility_id"])
            total += d
            at = order_lookup[order_id]["destination_facility_id"]
        return total

    assert tour(sequence) < tour(["o-a", "o-c", "o-b"])


def test_a_swap_that_would_make_a_punctual_order_late_is_refused():
    """The long way round is kept when the short way breaks a window."""
    order_lookup = lookup([("o-a", "A"), ("o-b", "B"), ("o-c", "C")])
    # o-c must be served by minute 2; only the original first position reaches it
    order_lookup["o-c"]["latest_min"] = 2

    sequence, changed = _resequence_tail(
        ["o-c", "o-a", "o-b"], "START", 0.0, order_lookup, leg)

    assert changed is False
    assert sequence == ["o-c", "o-a", "o-b"]


def test_an_already_late_order_does_not_block_the_improvement():
    """Being late is the situation the operator is already in — not a veto."""
    order_lookup = lookup([("o-a", "A"), ("o-b", "B"), ("o-c", "C")])
    order_lookup["o-a"]["latest_min"] = 1        # already impossible from START

    sequence, changed = _resequence_tail(
        ["o-a", "o-c", "o-b"], "START", 0.0, order_lookup, leg)

    assert changed is True
    assert sequence == ["o-c", "o-a", "o-b"]


def test_a_queue_of_one_is_left_alone():
    order_lookup = lookup([("o-a", "A")])
    assert _resequence_tail(["o-a"], "START", 0.0, order_lookup, leg) == (["o-a"], False)


# --- through the preview and the accept path --------------------------------

@pytest.fixture(scope="module")
def network():
    from optimisation.singapore_loader import read_network
    return read_network()


def _preview_with_two_remaining(network):
    """An in-transit vehicle carrying two orders, then a rescue order arrives."""
    from optimisation.dispatch_state import DispatchState, OrderProgress, VehicleProgress
    from optimisation.dispatch_planner import DISPATCH_ORIGIN

    carried = [
        DeliveryOrder("DO-1", "vaccine_2_8", "H-SGH", 10, 540, 1020, "chilled"),
        DeliveryOrder("DO-2", "vaccine_2_8", "H-CGH", 10, 540, 1020, "chilled"),
    ]
    rescue = DeliveryOrder("RO-1", "vaccine_2_8", "H-KKH", 10, 540, 1020, "chilled")
    state = DispatchState(
        version=1, status="in_transit",
        orders={o.order_id: OrderProgress(o.order_id, o.product_id,
                                          o.destination_facility_id, o.quantity,
                                          "V-1", "in_transit") for o in carried},
        vehicles={"V-1": VehicleProgress("V-1", "H-NUH", ("DO-1", "DO-2"),
                                         status="in_transit",
                                         onboard_spare=(("vaccine_2_8", "chilled", 50),))},
        available_by_lot={"LOT-1": 100},
        reserved_by_order={}, applied_commands=(),
    )
    context = {"input": {
        "orders": [{"order_id": o.order_id, "product_id": o.product_id,
                    "destination_facility_id": o.destination_facility_id,
                    "quantity": o.quantity, "earliest_min": o.earliest_min,
                    "latest_min": o.latest_min} for o in (*carried, rescue)],
        "inventory": [{"lot_id": "LOT-1", "product_id": "vaccine_2_8",
                       "facility_id": DISPATCH_ORIGIN, "temperature_zone": "chilled",
                       "status": "available"}],
        "vehicles": [{"vehicle_id": "V-1", "capacity": 100,
                      "temperature_zone": "chilled", "status": "in_transit",
                      "available_from_min": 0}],
    }}
    return state, context, rescue


def test_every_diverting_candidate_carries_the_queue_it_previewed(network):
    state, context, rescue = _preview_with_two_remaining(network)
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)

    diverting = [c for c in preview["candidates"]
                 if c["kind"] in {"add_stop_in_transit", "return_to_depot"}]
    assert diverting, "an in-transit vehicle with spare must offer both options"
    for candidate in diverting:
        queue = candidate["remaining_order_ids_after"]
        assert isinstance(candidate["resequenced"], bool)
        # the queue may be re-ordered, but never lose or duplicate an order
        assert sorted(queue) == ["DO-1", "DO-2"]


def test_accepting_stores_exactly_the_previewed_queue(network):
    """Otherwise the plan that runs is not the plan that was compared."""
    state, context, rescue = _preview_with_two_remaining(network)
    preview = preview_emergency_order(state, context, rescue, current_time_min=600)
    candidate = next(c for c in preview["candidates"]
                     if c["kind"] == "add_stop_in_transit")

    after = accept_emergency_order(
        state, context, rescue, current_time_min=600,
        candidate_kind=candidate["kind"], vehicle_id=candidate["vehicle_id"],
        command_id="accept-1",
    )

    assert after.vehicles["V-1"].remaining_order_ids == (
        rescue.order_id, *candidate["remaining_order_ids_after"])
    assert sorted(after.vehicles["V-1"].remaining_order_ids) == ["DO-1", "DO-2", "RO-1"]
