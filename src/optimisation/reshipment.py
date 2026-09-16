"""Bridge closed disposition cases to the fixed Singapore routing demo."""
from __future__ import annotations

from pathlib import Path

from .dispatch_models import DeliveryOrder
from .dispatch_planner import DISPATCH_ORIGIN
from .greedy import solve_greedy
from .models import ReplanResult, ReshipmentOrder
from .ortools_solver import solve_ortools
from .singapore_loader import (
    SINGAPORE_NETWORK_PATH,
    load_singapore_subset,
    read_network,
    restore_network_node_ids,
)

# Single source of truth: the default origin lives in dispatch_planner. Keeping a
# second literal here is how the new supply structure would silently drift.
DEPOT_FACILITY_ID = DISPATCH_ORIGIN

# A resupply must travel in the temperature zone its product actually needs;
# defaulting everything to "chilled" would let a frozen product be matched to a
# chilled vehicle, which dispatch_models is specifically meant to prevent.
#
# Read from the shared catalogue (2026-09-16): this used to be a second literal
# copy of the same four products, which is precisely how one list grows a product
# the other one has never heard of.
from .catalog import product_zones

PRODUCT_TEMPERATURE_ZONE = product_zones()


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


def build_delivery_order(record: dict) -> DeliveryOrder | None:
    """Derive a dispatch ``DeliveryOrder`` from one ``close_case()`` record.

    This is the bridge that keeps resupply on ONE pathway: the order carries
    ``source_run_id`` so it stays traceable to the disposition that caused it,
    and because it is an ordinary ``DeliveryOrder`` it goes through the same
    inventory / vehicle / temperature-zone checks as any manually entered
    order.  ``build_reshipment_order`` above remains for the stateless
    ``/api/route`` preview, which never reserves anything.

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
    node = next((item for item in customers if item["facility_id"] == destination), None)
    if node is None:
        raise ValueError(
            f"destination facility {destination!r} is not in Singapore demo customers"
        )
    product_id = event["product_id"]
    try:
        zone = PRODUCT_TEMPERATURE_ZONE[product_id]
    except KeyError as exc:
        raise ValueError(f"no temperature zone mapped for product {product_id!r}") from exc
    return DeliveryOrder(
        order_id=f"RO-{record['run_id']}",
        product_id=product_id,
        destination_facility_id=destination,
        quantity=node["demand"],
        earliest_min=node["earliest_min"],
        latest_min=node["latest_min"],
        temperature_zone=zone,
        source_run_id=record["run_id"],
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
