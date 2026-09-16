"""Order-driven static dispatch planning over the Singapore road matrix."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dispatch_models import (
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
    validate_dispatch_inputs,
)
from .greedy import solve_greedy
from .models import ReplanResult
from .ortools_solver import solve_ortools
from .routing import EndLeg, EndLegFn
from .singapore_loader import (
    SINGAPORE_NETWORK_PATH,
    load_singapore_subset,
    read_network,
    restore_network_node_ids,
)

#: Default main warehouse. Since 2026-09-16 this is the Scarlett Westgate outlet
#: (node 0 in network.json); the former Kuehne+Nagel depot is kept as a
#: third-party warehouse for comparison and is no longer the default origin.
DISPATCH_ORIGIN = "W-WESTGATE"


@dataclass(frozen=True)
class ZonePlan:
    temperature_zone: str
    vehicle_ids: tuple[str, ...]
    order_ids_by_node: dict[int, tuple[str, ...]]
    result: ReplanResult
    #: Parking nodes this zone's routes were allowed to end at (empty ⇒ closed
    #: routes that return to the depot).
    terminal_facility_ids: tuple[str, ...] = ()


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
    constraints: DispatchConstraints | None = None,
) -> DispatchPlan:
    """Plan available inventory orders, with one independent fleet per zone.

    This is a preview: it validates resources but does not reserve inventory or
    vehicles. Vehicles within one temperature zone must currently share a
    capacity because the existing solver model has one fleet-wide capacity.

    ``constraints.mileage_limit_m`` caps each vehicle's total driven distance and
    ``constraints.terminal_facility_ids`` makes routes open (they end at a supply
    point instead of driving home).  Both are optional and, when omitted, the
    planner behaves exactly as before.
    """
    validate_dispatch_inputs(
        orders, inventory, vehicles, origin_facility_id=DISPATCH_ORIGIN
    )
    if algorithm not in {"greedy", "ortools"}:
        raise ValueError(f"unsupported routing algorithm {algorithm!r}")

    constraints = constraints or DispatchConstraints()
    network = read_network(network_path)
    node_by_facility = {n["facility_id"]: n["node_id"] for n in network["nodes"]}
    terminal_node_ids: tuple[int, ...] = ()
    if constraints.terminal_facility_ids:
        unknown = sorted(set(constraints.terminal_facility_ids) - set(node_by_facility))
        if unknown:
            raise ValueError(f"unknown terminal facilities: {unknown}")
        terminal_node_ids = tuple(
            node_by_facility[fid] for fid in constraints.terminal_facility_ids
        )
    mileage_limit_km = (
        None if constraints.mileage_limit_m is None
        else constraints.mileage_limit_m / 1000.0
    )
    distance_matrix = network["matrix"]["distance_m"]
    duration_matrix = network["matrix"]["duration_s"]

    def make_end_leg_fn(source_ids: tuple[int, ...]) -> EndLegFn | None:
        """Nearest allowed parking node, priced in the solver's km/min units."""
        if not terminal_node_ids:
            return None

        def end_leg(dense_id: int) -> EndLeg:
            last = source_ids[dense_id]
            best = min(
                terminal_node_ids,
                key=lambda terminal: distance_matrix[last][terminal],
            )
            return EndLeg(
                distance=distance_matrix[last][best] / 1000.0,
                duration=duration_matrix[last][best] / 60.0,
                node_id=best,
            )

        return end_leg

    zone_plans = []
    vehicles_remaining = constraints.max_vehicles
    for zone in sorted({order.temperature_zone for order in orders}):
        zone_orders = tuple(order for order in orders if order.temperature_zone == zone)
        zone_vehicles = tuple(
            vehicle for vehicle in vehicles
            if vehicle.temperature_zone == zone and vehicle.status == "available"
        )
        if vehicles_remaining is not None:
            zone_vehicles = zone_vehicles[:vehicles_remaining]
            vehicles_remaining -= len(zone_vehicles)
        if not zone_vehicles:
            raise ValueError(f"fleet limit leaves no available vehicle for zone {zone}")
        capacities = {vehicle.capacity for vehicle in zone_vehicles}
        if len(capacities) != 1:
            raise ValueError(f"vehicles in zone {zone} must currently share one capacity")
        # Onboard spare occupies space, so the planner must not fill a vehicle to
        # its rated capacity and then also claim it carries spare stock. The
        # solver model has one fleet-wide capacity, so all vehicles in a zone must
        # currently carry the same spare.
        spares = {sum(qty for _, _, qty in vehicle.onboard_spare)
                  for vehicle in zone_vehicles}
        if len(spares) != 1:
            raise ValueError(f"vehicles in zone {zone} must currently share one onboard spare")
        usable_capacity = next(iter(capacities)) - next(iter(spares))
        if usable_capacity <= 0:
            raise ValueError(f"onboard spare leaves no usable capacity in zone {zone}")
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
            vehicle_nr=len(zone_vehicles), capacity=usable_capacity,
            facility_windows=windows,
        )
        end_leg_fn = make_end_leg_fn(source_ids)
        if algorithm == "greedy":
            dense_result = solve_greedy(
                instance, leg_fn=leg_fn,
                max_stops_per_vehicle=constraints.max_stops_per_vehicle,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit_km,
            )
        else:
            dense_result = solve_ortools(
                instance, leg_fn=leg_fn,
                max_stops_per_vehicle=constraints.max_stops_per_vehicle,
                end_leg_fn=end_leg_fn, mileage_limit=mileage_limit_km,
            )
        result = restore_network_node_ids(dense_result, source_ids)
        # Rebuild by source node without relying on request dictionary order.
        order_ids_by_node = {
            node_by_facility[facility_id]: tuple(order_ids)
            for facility_id, order_ids in orders_by_facility.items()
        }
        zone_plans.append(ZonePlan(
            temperature_zone=zone,
            vehicle_ids=tuple(vehicle.vehicle_id for vehicle in zone_vehicles),
            order_ids_by_node=order_ids_by_node,
            result=result,
            terminal_facility_ids=tuple(constraints.terminal_facility_ids or ()),
        ))
    return DispatchPlan(algorithm, len(orders), tuple(zone_plans))
