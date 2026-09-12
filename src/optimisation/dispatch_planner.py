"""Order-driven static dispatch planning over the Singapore road matrix."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dispatch_models import DeliveryOrder, DispatchVehicle, InventoryLot, validate_dispatch_inputs
from .greedy import solve_greedy
from .models import ReplanResult
from .ortools_solver import solve_ortools
from .singapore_loader import (
    SINGAPORE_NETWORK_PATH,
    load_singapore_subset,
    read_network,
    restore_network_node_ids,
)


@dataclass(frozen=True)
class ZonePlan:
    temperature_zone: str
    vehicle_ids: tuple[str, ...]
    order_ids_by_node: dict[int, tuple[str, ...]]
    result: ReplanResult


@dataclass(frozen=True)
class DispatchPlan:
    algorithm: str
    order_count: int
    zone_plans: tuple[ZonePlan, ...]

    @property
    def feasible(self) -> bool:
        return all(plan.result.feasible for plan in self.zone_plans)


def plan_delivery_orders(
    orders: tuple[DeliveryOrder, ...],
    inventory: tuple[InventoryLot, ...],
    vehicles: tuple[DispatchVehicle, ...],
    *,
    algorithm: str = "greedy",
    network_path: str | Path = SINGAPORE_NETWORK_PATH,
) -> DispatchPlan:
    """Plan available inventory orders, with one independent fleet per zone.

    This is a preview: it validates resources but does not reserve inventory or
    vehicles. Vehicles within one temperature zone must currently share a
    capacity because the existing solver model has one fleet-wide capacity.
    """
    validate_dispatch_inputs(orders, inventory, vehicles)
    if algorithm not in {"greedy", "ortools"}:
        raise ValueError(f"unsupported routing algorithm {algorithm!r}")

    zone_plans = []
    for zone in sorted({order.temperature_zone for order in orders}):
        zone_orders = tuple(order for order in orders if order.temperature_zone == zone)
        zone_vehicles = tuple(
            vehicle for vehicle in vehicles
            if vehicle.temperature_zone == zone and vehicle.status == "available"
        )
        capacities = {vehicle.capacity for vehicle in zone_vehicles}
        if len(capacities) != 1:
            raise ValueError(f"vehicles in zone {zone} must currently share one capacity")
        demands: dict[str, int] = {}
        windows: dict[str, tuple[int, int]] = {}
        orders_by_facility: dict[str, list[str]] = {}
        for order in zone_orders:
            demands[order.destination_facility_id] = (
                demands.get(order.destination_facility_id, 0) + order.quantity
            )
            orders_by_facility.setdefault(order.destination_facility_id, []).append(order.order_id)
            previous = windows.get(order.destination_facility_id)
            if previous is None:
                windows[order.destination_facility_id] = (order.earliest_min, order.latest_min)
            else:
                overlap = (max(previous[0], order.earliest_min), min(previous[1], order.latest_min))
                if overlap[0] > overlap[1]:
                    raise ValueError(
                        f"orders for {order.destination_facility_id!r} have incompatible time windows"
                    )
                windows[order.destination_facility_id] = overlap

        instance, leg_fn, source_ids = load_singapore_subset(
            demands, network_path,
            vehicle_nr=len(zone_vehicles), capacity=next(iter(capacities)),
            facility_windows=windows,
        )
        if algorithm == "greedy":
            dense_result = solve_greedy(instance, leg_fn=leg_fn)
        else:
            dense_result = solve_ortools(instance, leg_fn=leg_fn)
        result = restore_network_node_ids(dense_result, source_ids)
        # Rebuild by source node without relying on request dictionary order.
        node_by_facility = {n["facility_id"]: n["node_id"] for n in read_network(network_path)["nodes"]}
        order_ids_by_node = {
            node_by_facility[facility_id]: tuple(order_ids)
            for facility_id, order_ids in orders_by_facility.items()
        }
        zone_plans.append(ZonePlan(
            temperature_zone=zone,
            vehicle_ids=tuple(vehicle.vehicle_id for vehicle in zone_vehicles),
            order_ids_by_node=order_ids_by_node,
            result=result,
        ))
    return DispatchPlan(algorithm, len(orders), tuple(zone_plans))
