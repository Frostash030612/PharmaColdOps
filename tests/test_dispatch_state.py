from optimisation.dispatch_models import DeliveryOrder, DispatchVehicle, InventoryLot
from optimisation.dispatch_planner import plan_delivery_orders
from optimisation.dispatch_planner import DISPATCH_ORIGIN
from optimisation.dispatch_state import accept_plan, deliver_next, depart
from optimisation import dispatch_repository


def fixtures():
    orders = tuple(DeliveryOrder(
        f"DO-{i}", "vaccine_2_8", facility, quantity, 540, 1020, "chilled"
    ) for i, facility, quantity in ((1, "H-NUH", 20), (2, "H-CGH", 30)))
    inventory = (InventoryLot("LOT-1", "vaccine_2_8", DISPATCH_ORIGIN, 60, "chilled"),)
    vehicles = (DispatchVehicle("V-1", 100, "chilled", DISPATCH_ORIGIN),)
    return orders, inventory, vehicles


def test_accept_depart_and_deliver_preserve_quantities_and_progress():
    orders, inventory, vehicles = fixtures()
    plan = plan_delivery_orders(orders, inventory, vehicles)
    state = accept_plan(plan, orders, inventory, command_id="accept-1")
    assert state.available_by_lot == {"LOT-1": 10}
    assert sum(qty for parts in state.reserved_by_order.values() for _, qty in parts) == 50
    state = depart(state, command_id="depart-1")
    first = deliver_next(state, "V-1", command_id="deliver-1")
    assert first.version == 3
    assert len(first.vehicles["V-1"].remaining_order_ids) == 1
    assert sum(item.status == "delivered" for item in first.orders.values()) == 1
    duplicate = deliver_next(first, "V-1", command_id="deliver-1")
    assert duplicate == first
    final = deliver_next(first, "V-1", command_id="deliver-2")
    assert final.status == "completed"
    assert all(item.status == "delivered" for item in final.orders.values())


def test_depart_command_is_idempotent():
    orders, inventory, vehicles = fixtures()
    state = accept_plan(plan_delivery_orders(orders, inventory, vehicles), orders, inventory,
                        command_id="accept-1")
    departed = depart(state, command_id="depart-1")
    assert depart(departed, command_id="depart-1") == departed


def test_repository_recognises_cloud_postgres_urls():
    assert dispatch_repository._is_postgres("postgresql://host/database")
    assert dispatch_repository._is_postgres("postgres://host/database")
    assert not dispatch_repository._is_postgres("/tmp/dispatch.sqlite3")
