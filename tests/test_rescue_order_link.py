"""B6 (2026-09-16, first half): the excursion input says which order it concerns.

Because the input is ours, that link rides along with the case: ``event.order_id``
points at an order of the running operation, and the rescue then reads the
product, the receiving hospital and the quantity off **that order**. What that
replaces is worth naming, because both are wrong for a scrapped shipment:

* an operator-picked hospital dropdown (the case form's stopgap), and
* a quantity taken from the destination node's demo demand (30 units for every
  hospital, whatever the shipment actually carried).

"Scrapped" means the whole shipment, so the linked order's quantity is exactly the
right replacement amount — no batch-level bookkeeping needed.
"""
from __future__ import annotations

import pytest

from api import service
from optimisation.dispatch_planner import DISPATCH_ORIGIN
from optimisation.reshipment import build_delivery_order

LINKED_ORDER = "DO-DAILY-H-KKH"


@pytest.fixture(autouse=True)
def isolated_dispatch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(tmp_path / "dispatch.sqlite3"))


def _case(*, order_id: str | None = LINKED_ORDER, product: str = "vaccine_2_8",
          destination: str | None = "H-SGH", run_id: str = "R-LINK-1") -> dict:
    event = {"product_id": product, "excursion_temp_c": -30.0, "duration_min": 150,
             "mkt_c": -31.0, "packaging": "intact", "stage": "transit"}
    if order_id is not None:
        event["order_id"] = order_id
    if destination is not None:
        event["destination_facility_id"] = destination
    return {"run_id": run_id, "created_at": "2026-09-16T09:10:00",
            "disposition": "scrap", "reshipment_required": True, "event": event}


class _Progress:
    """Stand-in for the state's OrderProgress (the fields the bridge reads)."""

    def __init__(self, order_id, product_id, destination, quantity):
        self.order_id, self.product_id = order_id, product_id
        self.destination_facility_id, self.quantity = destination, quantity


# --- the bridge -------------------------------------------------------------

def test_a_linked_order_overrides_the_dropdown_and_the_node_demand():
    linked = _Progress(LINKED_ORDER, "vaccine_2_8", "H-KKH", 45)
    order = build_delivery_order(_case(), linked_order=linked)

    assert order.destination_facility_id == "H-KKH"      # not the event's H-SGH
    assert order.quantity == 45                          # not the node's 30
    assert order.product_id == "vaccine_2_8"
    assert order.source_run_id == "R-LINK-1"             # still traceable to the case


def test_a_link_to_an_order_carrying_another_product_is_refused():
    """A case about vaccine X cannot be settled by an order carrying Y."""
    linked = _Progress("DO-FROZEN", "frozen_m20", "H-KKH", 30)
    with pytest.raises(ValueError, match="carries 'frozen_m20'"):
        build_delivery_order(_case(), linked_order=linked)


def test_without_a_link_the_old_fallback_still_works():
    """Existing cases (and every older caller) keep their behaviour."""
    order = build_delivery_order(_case(order_id=None))
    assert order.destination_facility_id == "H-SGH"      # the event's own field
    assert order.quantity == 30                          # the node's demo demand


# --- through the API --------------------------------------------------------

def test_an_excursion_riding_along_with_todays_order():
    from optimisation.daily_orders import daily_delivery_batch

    orders, inventory, vehicles = daily_delivery_batch(hospitals=4, seed=1)
    service.create_dispatch(service.DispatchCreateIn(
        dispatch_id="PLAN-LINK", command_id="create-PLAN-LINK", algorithm="greedy",
        orders=[service._order_dump(o) for o in orders],
        inventory=[service._lot_dump(lot) for lot in inventory],
        vehicles=[service._vehicle_dump(v) for v in vehicles],
    ))
    linked = next(o for o in orders if o.destination_facility_id == "H-KKH")

    preview = service.reshipment_branch_plan(_case(order_id=linked.order_id))

    assert preview["order_source"] == "linked_order"
    assert preview["order"]["destination_facility_id"] == linked.destination_facility_id
    assert preview["order"]["quantity"] == linked.quantity
    # the rescue is planned against the running operation, not a new one
    assert preview["dispatch_id"] == "PLAN-LINK"
    assert preview["candidates"], "an in-transit fleet must offer at least one way"


def test_the_preview_says_when_it_had_to_fall_back_to_the_event():
    from optimisation.daily_orders import daily_delivery_batch

    orders, inventory, vehicles = daily_delivery_batch(hospitals=4, seed=1)
    service.create_dispatch(service.DispatchCreateIn(
        dispatch_id="PLAN-FB", command_id="create-PLAN-FB", algorithm="greedy",
        orders=[service._order_dump(o) for o in orders],
        inventory=[service._lot_dump(lot) for lot in inventory],
        vehicles=[service._vehicle_dump(v) for v in vehicles],
    ))

    preview = service.reshipment_branch_plan(_case(order_id=None))

    assert preview["order_source"] == "event_fallback"
    assert preview["order"]["destination_facility_id"] == "H-SGH"


def test_a_link_to_an_order_outside_the_running_operation_is_refused():
    from optimisation.daily_orders import daily_delivery_batch

    orders, inventory, vehicles = daily_delivery_batch(hospitals=4, seed=1)
    service.create_dispatch(service.DispatchCreateIn(
        dispatch_id="PLAN-STRICT", command_id="create-PLAN-STRICT", algorithm="greedy",
        orders=[service._order_dump(o) for o in orders],
        inventory=[service._lot_dump(lot) for lot in inventory],
        vehicles=[service._vehicle_dump(v) for v in vehicles],
    ))

    with pytest.raises(ValueError, match="not part of the running operation"):
        service.reshipment_branch_plan(_case(order_id="DO-DAILY-H-NOT-REAL"))


def test_a_case_that_needs_no_reshipment_is_refused_before_anything_else(day_plan):
    """Case-level refusal must not be masked by "no plan is open"."""
    record = _case()
    record["reshipment_required"] = False
    with pytest.raises(ValueError, match="does not require reshipment"):
        service.reshipment_branch_plan(record)
