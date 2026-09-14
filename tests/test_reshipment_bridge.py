"""Every resupply goes through ONE dispatch operation.

Before this bridge a disposition-triggered reshipment was routed by a stateless
preview that reserved nothing, while inventory/vehicle checks only existed for
manually entered orders — two parallel stories about the same delivery. These
tests pin the merged behaviour: a closed case becomes a real DeliveryOrder,
traceable by source_run_id, checked against real stock and real capacity.
"""
import tempfile

import pytest

from api import service
from optimisation.dispatch_state import depart
from optimisation.reshipment import build_delivery_order


@pytest.fixture(autouse=True)
def isolated_dispatch_db(monkeypatch):
    monkeypatch.setattr(
        service, "DISPATCH_DATABASE_URL", tempfile.mktemp(suffix=".sqlite3")
    )


def case(run_id, *, destination=None, product="vaccine_2_8", reshipment=True):
    event = {
        "product_id": product, "excursion_temp_c": 20.0, "duration_min": 90,
        "mkt_c": 19.0, "packaging": "intact", "stage": "transit",
    }
    if destination:
        event["destination_facility_id"] = destination
    return {
        "run_id": run_id, "created_at": "2026-09-12T09:30:00",
        "disposition": "scrap" if reshipment else "release",
        "reshipment_required": reshipment, "event": event,
    }


def test_delivery_order_keeps_the_link_back_to_its_case():
    order = build_delivery_order(case("R1"))
    assert order.order_id == "RO-R1"
    assert order.source_run_id == "R1"


def test_temperature_zone_follows_the_product_not_a_default():
    assert build_delivery_order(case("R1")).temperature_zone == "chilled"
    assert build_delivery_order(
        case("R2", product="frozen_m20")).temperature_zone == "frozen"
    assert build_delivery_order(
        case("R3", product="mrna_ultracold")).temperature_zone == "ultracold"


def test_case_without_reshipment_produces_no_order():
    assert build_delivery_order(case("R1", reshipment=False)) is None
    with pytest.raises(ValueError, match="does not require reshipment"):
        service.route_reshipment(case("R1", reshipment=False))


def test_first_case_bootstraps_the_run_and_reserves_its_stock():
    result = service.route_reshipment(case("R1"))
    assert result["bootstrapped"] is True
    assert list(result["orders"]) == ["RO-R1"]
    # Stock was actually consumed, not merely routed around.
    assert sum(result["available_by_lot"].values()) == 0
    assert result["reserved_by_order"]["RO-R1"]


def test_later_cases_join_the_same_run_rather_than_starting_a_new_one():
    service.route_reshipment(case("R1"))
    second = service.route_reshipment(case("R2", destination="H-NUH"))
    assert second["bootstrapped"] is False
    assert second["dispatch_id"].startswith(service.RESHIPMENT_DISPATCH_PREFIX)
    assert sorted(second["orders"]) == ["RO-R1", "RO-R2"]
    # Context must carry both orders, or the next preview cannot resolve the
    # delivery window of an order already assigned to a vehicle.
    assert {item["order_id"] for item in second["input"]["orders"]} == {"RO-R1", "RO-R2"}


def test_replaying_one_case_does_not_double_book_it():
    service.route_reshipment(case("R1"))
    first = service.route_reshipment(case("R2", destination="H-NUH"))
    replay = service.route_reshipment(case("R2", destination="H-NUH"))
    assert sorted(replay["orders"]) == sorted(first["orders"])
    assert replay["available_by_lot"] == first["available_by_lot"]


def test_a_zone_with_no_fleet_yet_gets_its_own_vehicles():
    service.route_reshipment(case("R1"))  # chilled
    frozen = service.route_reshipment(
        case("R2", destination="H-KKH", product="frozen_m20"))
    carrier = frozen["orders"]["RO-R2"]["vehicle_id"]
    zones = {item["vehicle_id"]: item["temperature_zone"]
             for item in frozen["input"]["vehicles"]}
    assert zones[carrier] == "frozen"


def test_unknown_destination_is_refused_rather_than_silently_redirected():
    with pytest.raises(ValueError, match="not in Singapore demo customers"):
        service.route_reshipment(case("R1", destination="H-NOT-REAL"))


def test_orders_added_before_departure_all_wait_for_it():
    """A spare assigned to a run that has not departed must wait with the rest.
    Letting it leave alone flipped the run to "in transit" while other vehicles
    were still loading — and those could then never depart."""
    service.route_reshipment(case("R1"))
    service.route_reshipment(case("R2", destination="H-NUH"))
    _, state = service.active_reshipment_run()

    assert state.status == "accepted"
    assert {v.status for v in state.vehicles.values()} == {"reserved"}

    departed = depart(state, command_id="depart-1")
    assert all(item.status == "in_transit" for item in departed.vehicles.values())


def test_depart_leaves_work_already_under_way_untouched():
    """Once the fleet is out, a new resupply's spare does roll immediately; a
    later departure must neither be refused nor reset what is already moving."""
    service.route_reshipment(case("R1"))
    dispatch_id, _ = service.active_reshipment_run()
    service.depart_dispatch(dispatch_id, "depart-1")
    service.route_reshipment(case("R2", destination="H-NUH"))
    _, state = service.active_reshipment_run()
    early = state.orders["RO-R2"].vehicle_id
    assert state.vehicles[early].status == "in_transit"

    departed = depart(state, command_id="depart-2")

    assert departed.vehicles[early].remaining_order_ids == \
        state.vehicles[early].remaining_order_ids


def test_completed_operation_is_history_and_the_next_case_opens_a_new_one():
    """Found by driving the live API: after the only delivery completed, the
    next excursion could not be routed at all. A finished operation must not be
    reopened, and must not block the next one either."""
    first = service.route_reshipment(case("R1"))
    dispatch_id = first["dispatch_id"]
    state = service.load_run(service.DISPATCH_DATABASE_URL, dispatch_id)
    vehicle = next(iter(state.vehicles))
    service.depart_dispatch(dispatch_id, "depart-1")
    service.deliver_dispatch(dispatch_id, vehicle, "deliver-1")
    assert service.load_run(
        service.DISPATCH_DATABASE_URL, dispatch_id).status == "completed"

    nxt = service.route_reshipment(case("R2", destination="H-NUH"))

    assert nxt["bootstrapped"] is True
    assert nxt["dispatch_id"] != dispatch_id
    assert list(nxt["orders"]) == ["RO-R2"]      # the finished run is untouched


def test_case_raised_after_the_receiving_window_is_scheduled_next_day():
    """Found by driving the live API at 21:35: a real case timestamp fell past
    the hospital's 09:00-17:00 receiving window, and the bridge reported "no
    vehicle can deliver" — untrue; vehicles existed, the day had ended."""
    late = case("R1")
    late["created_at"] = "2026-09-12T21:35:00"

    result = service.route_reshipment(late)

    assert result["scheduled_next_day"] is True
    assert list(result["orders"]) == ["RO-R1"]


def test_case_inside_the_window_is_not_deferred():
    result = service.route_reshipment(case("R1"))   # 09:30
    assert result["scheduled_next_day"] is False
