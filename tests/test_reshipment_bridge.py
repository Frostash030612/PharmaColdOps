"""Every resupply is a BRANCH of the day's delivery plan.

Before this bridge a disposition-triggered reshipment was routed by a stateless
preview that reserved nothing, while inventory/vehicle checks only existed for
manually entered orders — two parallel stories about the same delivery. These
tests pin the merged behaviour: a closed case becomes a real DeliveryOrder,
traceable by source_run_id, checked against real stock and real capacity.

2026-09-15 (docs/C_配送模块.md §4.4-2): the bridge no longer *bootstraps* an
operation out of the first case it sees. It attaches the case to the open daily
plan, and refuses the case when there is none — bootstrapping was how a
multi-stop planner got reduced to a one-order vehicle dispatcher (§3.2). The
tests below therefore establish today's plan first, exactly as an operator does.
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


def test_a_case_without_a_days_plan_is_refused_not_promoted():
    """The removed fallback: a case used to CREATE an operation of its own.

    That is what let every vehicle serve exactly one hospital and made greedy /
    OR-Tools / GA agree in a live demo (§3.2). The refusal has to be explicit and
    actionable, and it must not leave a run behind.
    """
    with pytest.raises(service.NoActiveDeliveryPlan, match="no daily delivery plan"):
        service.route_reshipment(case("R1"))

    assert service.latest_dispatch_id(service.DISPATCH_DATABASE_URL) is None


def test_a_case_joins_the_days_plan_and_reserves_its_stock(day_plan):
    plan_id = day_plan()
    result = service.route_reshipment(case("R1"))

    assert result["dispatch_id"] == plan_id          # attached, not bootstrapped
    assert result["inserted"] is True
    assert "RO-R1" in result["orders"]
    # Stock was actually consumed, not merely routed around.
    assert result["reserved_by_order"]["RO-R1"]
    # The plan's own orders are still there: a branch must not replace the main line.
    assert len(result["orders"]) == 5


def test_later_cases_join_the_same_run_rather_than_starting_a_new_one(day_plan):
    plan_id = day_plan()
    service.route_reshipment(case("R1"))
    second = service.route_reshipment(case("R2", destination="H-NUH"))

    assert second["inserted"] is True
    assert second["dispatch_id"] == plan_id
    assert {"RO-R1", "RO-R2"} <= set(second["orders"])
    # Context must carry both orders, or the next preview cannot resolve the
    # delivery window of an order already assigned to a vehicle.
    assert {item["order_id"] for item in second["input"]["orders"]} >= {"RO-R1", "RO-R2"}


def test_replaying_one_case_does_not_double_book_it(day_plan):
    day_plan()
    service.route_reshipment(case("R1"))
    first = service.route_reshipment(case("R2", destination="H-NUH"))
    replay = service.route_reshipment(case("R2", destination="H-NUH"))

    assert replay["inserted"] is False
    assert sorted(replay["orders"]) == sorted(first["orders"])
    assert replay["available_by_lot"] == first["available_by_lot"]


def test_a_zone_with_no_fleet_yet_gets_its_own_vehicles(day_plan):
    day_plan()                       # a chilled plan
    frozen = service.route_reshipment(
        case("R2", destination="H-KKH", product="frozen_m20"))
    carrier = frozen["orders"]["RO-R2"]["vehicle_id"]
    zones = {item["vehicle_id"]: item["temperature_zone"]
             for item in frozen["input"]["vehicles"]}
    assert zones[carrier] == "frozen"


def test_unknown_destination_is_refused_rather_than_silently_redirected(day_plan):
    day_plan()
    with pytest.raises(ValueError, match="not in Singapore demo customers"):
        service.route_reshipment(case("R1", destination="H-NOT-REAL"))


def test_orders_added_before_departure_all_wait_for_it(day_plan):
    """A spare assigned to a run that has not departed must wait with the rest.
    Letting it leave alone flipped the run to "in transit" while other vehicles
    were still loading — and those could then never depart."""
    plan_id = day_plan()
    service.route_reshipment(case("R1"))
    service.route_reshipment(case("R2", destination="H-NUH"))
    state = service.load_run(service.DISPATCH_DATABASE_URL, plan_id)

    assert state.status == "accepted"
    assert {v.status for v in state.vehicles.values()} == {"reserved"}

    departed = depart(state, command_id="depart-1")
    assert all(item.status == "in_transit" for item in departed.vehicles.values())


def test_depart_leaves_work_already_under_way_untouched(day_plan):
    """Once the fleet is out, a new resupply's spare does roll immediately; a
    later departure must neither be refused nor reset what is already moving."""
    plan_id = day_plan()
    service.route_reshipment(case("R1"))
    service.depart_dispatch(plan_id, "depart-1")
    service.route_reshipment(case("R2", destination="H-NUH"))
    state = service.load_run(service.DISPATCH_DATABASE_URL, plan_id)
    early = state.orders["RO-R2"].vehicle_id
    assert state.vehicles[early].status == "in_transit"

    departed = depart(state, command_id="depart-2")

    assert departed.vehicles[early].remaining_order_ids == \
        state.vehicles[early].remaining_order_ids


def test_a_completed_plan_is_history_and_does_not_absorb_the_next_case(day_plan):
    """Found by driving the live API: after the only delivery completed, the next
    excursion could not be routed at all. A finished plan must not be reopened —
    and, since 2026-09-15, must not be silently replaced by a one-order run
    either: the operator is told to start a new plan (§4.4-2)."""
    plan_id = day_plan()
    service.route_reshipment(case("R1"))
    state = service.load_run(service.DISPATCH_DATABASE_URL, plan_id)
    service.depart_dispatch(plan_id, "depart-1")
    # The branch may have gone to a spare vehicle, so every vehicle has to be
    # driven to the end before the operation counts as finished.
    for vehicle, progress in state.vehicles.items():
        for order_id in list(progress.remaining_order_ids):
            service.deliver_dispatch(plan_id, vehicle, f"deliver-{vehicle}-{order_id}")
    assert service.load_run(
        service.DISPATCH_DATABASE_URL, plan_id).status == "completed"

    with pytest.raises(service.NoActiveDeliveryPlan):
        service.route_reshipment(case("R2", destination="H-NUH"))

    # A new plan opens the way again, and the finished one is untouched.
    day_plan("PLAN-TEST-2")
    nxt = service.route_reshipment(case("R2", destination="H-NUH"))
    assert nxt["dispatch_id"] == "PLAN-TEST-2"
    assert "RO-R2" in nxt["orders"]
    assert set(nxt["orders"]) != {"RO-R2"}     # it joined a plan, it did not become one
    assert "RO-R1" in service.load_run(service.DISPATCH_DATABASE_URL, plan_id).orders


def test_case_raised_after_the_receiving_window_is_scheduled_next_day(day_plan):
    """Found by driving the live API at 21:35: a real case timestamp fell past
    the hospital's 09:00-17:00 receiving window, and the bridge reported "no
    vehicle can deliver" — untrue; vehicles existed, the day had ended."""
    day_plan()
    late = case("R1")
    late["created_at"] = "2026-09-12T21:35:00"

    result = service.route_reshipment(late)

    assert result["scheduled_next_day"] is True
    assert "RO-R1" in result["orders"]


def test_case_inside_the_window_is_not_deferred(day_plan):
    day_plan()
    result = service.route_reshipment(case("R1"))   # 09:30
    assert result["scheduled_next_day"] is False
