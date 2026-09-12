import pytest

from optimisation.dispatch_models import (
    DeliveryOrder,
    DispatchVehicle,
    InventoryLot,
    validate_dispatch_inputs,
)


def order(**changes):
    values = dict(
        order_id="DO-1", product_id="vaccine_2_8",
        destination_facility_id="H-NUH", quantity=30,
        earliest_min=540, latest_min=1020, temperature_zone="chilled",
    )
    values.update(changes)
    return DeliveryOrder(**values)


def test_dispatch_inputs_require_matching_inventory_and_vehicle():
    validate_dispatch_inputs(
        (order(),),
        (InventoryLot("LOT-1", "vaccine_2_8", "W-KN-PIONEER", 30, "chilled"),),
        (DispatchVehicle("V-1", 100, "chilled", "W-KN-PIONEER"),),
    )


def test_dispatch_inputs_do_not_use_quarantined_inventory():
    with pytest.raises(ValueError, match="insufficient available inventory"):
        validate_dispatch_inputs(
            (order(),),
            (InventoryLot("LOT-1", "vaccine_2_8", "W-KN-PIONEER", 30,
                          "chilled", status="quarantine"),),
            (DispatchVehicle("V-1", 100, "chilled", "W-KN-PIONEER"),),
        )


def test_dispatch_inputs_require_temperature_capable_vehicle():
    with pytest.raises(ValueError, match="no available vehicle"):
        validate_dispatch_inputs(
            (order(),),
            (InventoryLot("LOT-1", "vaccine_2_8", "W-KN-PIONEER", 30, "chilled"),),
            (DispatchVehicle("V-1", 100, "frozen", "W-KN-PIONEER"),),
        )


def test_order_rejects_missing_destination_or_bad_quantity():
    with pytest.raises(ValueError, match="IDs are required"):
        order(destination_facility_id="")
    with pytest.raises(ValueError, match="positive"):
        order(quantity=0)
