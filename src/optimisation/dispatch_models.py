"""Business inputs for order-driven cold-chain dispatch.

These types sit above the Solomon benchmark model.  They keep business IDs,
inventory and vehicle capabilities explicit instead of encoding them as
anonymous customer demand.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TemperatureZone = Literal["chilled", "frozen", "ultracold"]

#: What a vehicle carries beyond its assigned orders, as
#: ``(product_id, temperature_zone, quantity)`` triples.
#:
#: This is a **model assumption about the load**, not a depot lot: the demo puts
#: a small safety margin on every vehicle so an in-transit truck can serve a
#: branch event without driving back to the depot. It deliberately does not
#: appear in ``available_by_lot`` (the loading step is not modelled), which is
#: why an order served from it is recorded against an ``ONBOARD-…`` reserve.
OnboardSpare = tuple[tuple[str, str, int], ...]


@dataclass(frozen=True)
class DispatchConstraints:
    """Hard fleet limits applied by every static dispatch solver.

    ``mileage_limit_m`` is the whole distance one vehicle may drive in a day,
    including empty repositioning and the closing leg (2026-09-16 decision).
    ``terminal_facility_ids`` turns the closed round trip into an **open route**:
    when set, every route must end at one of those nodes and no return-to-depot
    leg is charged.  Left unset, both keep the legacy behaviour exactly.
    """

    max_vehicles: int | None = None
    max_stops_per_vehicle: int | None = None
    mileage_limit_m: int | None = None
    terminal_facility_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.max_vehicles is not None and self.max_vehicles < 1:
            raise ValueError("max_vehicles must be a positive integer")
        if self.max_stops_per_vehicle is not None and self.max_stops_per_vehicle < 1:
            raise ValueError("max_stops_per_vehicle must be a positive integer")
        if self.mileage_limit_m is not None and self.mileage_limit_m < 1:
            raise ValueError("mileage_limit_m must be a positive integer")
        if self.terminal_facility_ids is not None:
            if not self.terminal_facility_ids:
                raise ValueError("terminal_facility_ids must not be empty when given")
            if len(set(self.terminal_facility_ids)) != len(self.terminal_facility_ids):
                raise ValueError("terminal_facility_ids must be unique")


def normalise_onboard_spare(value: object) -> OnboardSpare:
    """Canonicalise onboard spare stock from tuples, lists or dicts.

    The API layer parses JSON objects while the optimiser builds tuples; both
    must land in one shape, or a state written by one and reloaded by the other
    would silently disagree about what is on the truck.
    """
    items: list[tuple[str, str, int]] = []
    for raw in value or ():  # type: ignore[union-attr]
        if isinstance(raw, dict):
            item = (raw["product_id"], raw["temperature_zone"], int(raw["quantity"]))
        else:
            item = (raw[0], raw[1], int(raw[2]))  # type: ignore[index]
        if item[2] < 0:
            raise ValueError("onboard spare quantity cannot be negative")
        items.append(item)
    return tuple(items)


@dataclass(frozen=True)
class DeliveryOrder:
    order_id: str
    product_id: str
    destination_facility_id: str
    quantity: int
    earliest_min: int
    latest_min: int
    temperature_zone: TemperatureZone
    source_run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.order_id or not self.product_id or not self.destination_facility_id:
            raise ValueError("order, product and destination IDs are required")
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        if self.earliest_min < 0 or self.latest_min < self.earliest_min:
            raise ValueError("order time window is invalid")


@dataclass(frozen=True)
class InventoryLot:
    lot_id: str
    product_id: str
    facility_id: str
    available_quantity: int
    temperature_zone: TemperatureZone
    status: Literal["available", "reserved", "quarantine", "scrap"] = "available"

    def __post_init__(self) -> None:
        if not self.lot_id or not self.product_id or not self.facility_id:
            raise ValueError("lot, product and facility IDs are required")
        if self.available_quantity < 0:
            raise ValueError("inventory quantity cannot be negative")


@dataclass(frozen=True)
class DispatchVehicle:
    vehicle_id: str
    capacity: int
    temperature_zone: TemperatureZone
    start_facility_id: str
    available_from_min: int = 0
    status: Literal["available", "in_transit", "failed"] = "available"
    onboard_spare: OnboardSpare = ()

    def __post_init__(self) -> None:
        if not self.vehicle_id or not self.start_facility_id:
            raise ValueError("vehicle and start facility IDs are required")
        if self.capacity <= 0 or self.available_from_min < 0:
            raise ValueError("vehicle capacity/time is invalid")
        # Frozen dataclass: normalise through object.__setattr__ so every caller
        # (API dicts, optimiser tuples, a reloaded state) sees one shape.
        object.__setattr__(
            self, "onboard_spare", normalise_onboard_spare(self.onboard_spare)
        )


def validate_dispatch_inputs(
    orders: tuple[DeliveryOrder, ...],
    inventory: tuple[InventoryLot, ...],
    vehicles: tuple[DispatchVehicle, ...],
    *,
    origin_facility_id: str | None = None,
) -> None:
    """Reject duplicate IDs and resource claims that cannot form a plan."""
    if not orders:
        raise ValueError("at least one delivery order is required")
    for label, values in (
        ("order", [item.order_id for item in orders]),
        ("lot", [item.lot_id for item in inventory]),
        ("vehicle", [item.vehicle_id for item in vehicles]),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {label}_id")

    available: dict[tuple[str, str], int] = {}
    for lot in inventory:
        if lot.status == "available" and (
            origin_facility_id is None or lot.facility_id == origin_facility_id
        ):
            key = (lot.product_id, lot.temperature_zone)
            available[key] = available.get(key, 0) + lot.available_quantity
    required: dict[tuple[str, str], int] = {}
    for order in orders:
        key = (order.product_id, order.temperature_zone)
        required[key] = required.get(key, 0) + order.quantity
    for key, quantity in required.items():
        if available.get(key, 0) < quantity:
            raise ValueError(f"insufficient available inventory for {key[0]} ({key[1]})")
        if not any(v.status == "available" and v.temperature_zone == key[1] for v in vehicles):
            raise ValueError(f"no available vehicle for temperature zone {key[1]}")
    if origin_facility_id is not None and any(
        vehicle.status == "available" and vehicle.start_facility_id != origin_facility_id
        for vehicle in vehicles
    ):
        raise ValueError("available vehicles must start at the dispatch origin")
