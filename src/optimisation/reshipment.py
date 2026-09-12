"""Bridge closed disposition cases to the fixed Singapore routing demo."""
from __future__ import annotations

from pathlib import Path

from .greedy import solve_greedy
from .models import ReplanResult, ReshipmentOrder
from .ortools_solver import solve_ortools
from .singapore_loader import (
    SINGAPORE_NETWORK_PATH,
    load_singapore_subset,
    read_network,
    restore_network_node_ids,
)

DEPOT_FACILITY_ID = "W-KN-PIONEER"


def build_reshipment_order(record: dict) -> ReshipmentOrder | None:
    """Derive one order from a ``close_case()`` record.

    The MVP has one fixed depot. An explicit destination is retained for later
    validation; when absent, the first customer in the committed Singapore
    network is used. Demand reuses that customer's configured demo demand.
    Returns ``None`` when the case does not require reshipment.
    """
    if not record["reshipment_required"]:
        return None
    event = record["event"]
    network = read_network()
    customers = [node for node in network["nodes"] if node["role"] == "customer"]
    if not customers:  # validate_network normally prevents this in practice.
        raise ValueError("Singapore network has no customer nodes")
    destination = event.get("destination_facility_id") or customers[0]["facility_id"]
    demand_by_id = {node["facility_id"]: node["demand"] for node in customers}
    demand = demand_by_id.get(destination, customers[0]["demand"])
    return ReshipmentOrder(
        order_id=f"RO-{record['run_id']}",
        run_id=record["run_id"],
        product_id=event["product_id"],
        origin_facility_id=DEPOT_FACILITY_ID,
        destination_facility_id=destination,
        demand_units=demand,
        priority=record["disposition"],
        requested_at=record["created_at"],
    )


def resolve_destination(order: ReshipmentOrder, network: dict) -> str:
    """Validate an explicit destination, or select the first customer for MVP."""
    customers = [node for node in network["nodes"] if node["role"] == "customer"]
    if not customers:
        raise ValueError("Singapore network has no customer nodes")
    destination = order.destination_facility_id or customers[0]["facility_id"]
    valid = {node["facility_id"] for node in customers}
    if destination not in valid:
        raise ValueError(f"destination facility {destination!r} is not in Singapore demo customers")
    return destination


def plan_reshipment_route(
    order: ReshipmentOrder,
    *,
    algorithm: str = "greedy",
    network_path: str | Path = SINGAPORE_NETWORK_PATH,
) -> ReplanResult:
    """Solve only the destination and demand carried by this reshipment order."""
    network = read_network(network_path)
    destination = resolve_destination(order, network)
    instance, leg_fn, source_ids = load_singapore_subset(
        {destination: order.demand_units}, network_path
    )
    if algorithm == "greedy":
        result = solve_greedy(instance, leg_fn=leg_fn)
    elif algorithm == "ortools":
        result = solve_ortools(instance, leg_fn=leg_fn)
    else:
        raise ValueError(f"unsupported routing algorithm {algorithm!r}")
    result = restore_network_node_ids(result, source_ids)
    destination_node = next(
        node["node_id"] for node in network["nodes"]
        if node["facility_id"] == destination
    )
    if destination_node not in {
        node_id for route in result.routes for node_id in route.customer_ids
    }:
        raise ValueError(f"routing result does not serve destination {destination!r}")
    return result
