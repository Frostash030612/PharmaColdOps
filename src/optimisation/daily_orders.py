"""A simulated "today's delivery plan" for the Singapore demo (doc §4.1, §4.5).

**Why this exists.** The running app only ever reached the dispatcher through one
closed excursion case, and :func:`api.service.route_reshipment` plans exactly ONE
order at a time (``plan_delivery_orders((order,), …)``).  Every vehicle therefore
served exactly one hospital, the multi-stop planner was never exercised by the
running system, and greedy / OR-Tools / GA produced identical results in a live
demo — the structural problem recorded in ``docs/C_配送模块.md`` §3.2.  This
module supplies the missing input: a *batch* of ordinary hospital orders that the
planner turns into a one-vehicle-many-stops loop.

**Everything here is SIMULATED and must be labelled as such.** The hospital
identities, receiving windows and service times come from the committed
Singapore network (real facilities with sources), but the daily demand, the
product mix and the fleet are demo assumptions — no hospital gave us an order.
Same honesty rule as the rest of the demo data: say what is simulated.

**Fleet sizing is the planner's job, not the caller's.** We hand over enough
vehicles for the batch's total demand; whether one truck can serve every stop in
time is decided by :func:`dispatch_planner.plan_delivery_orders`, which opens a
second vehicle on its own when a window or the capacity forces it.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from .dispatch_models import DeliveryOrder, DispatchVehicle, InventoryLot
from .singapore_loader import SINGAPORE_NETWORK_PATH, read_network

#: A temperature zone needs a product so the planner can match zone and batch.
#: Mirrors ``reshipment.PRODUCT_TEMPERATURE_ZONE`` in the other direction.
ZONE_PRODUCT = {
    "chilled": "vaccine_2_8",
    "frozen": "frozen_m20",
    "ultracold": "mrna_ultracold",
}

#: What the batch means, in the words the UI and report should reuse.
ASSUMPTIONS = (
    "模拟数据：医院名称、收货窗口与服务时长取自已入库的新加坡路网（真实设施），"
    "但每日需求量、产品组合与车队规模是本项目的演示假设，不是医院真实订单。"
)

DEFAULT_HOSPITALS = 4


def daily_delivery_batch(
    *,
    hospitals: int = DEFAULT_HOSPITALS,
    seed: int | None = None,
    temperature_zone: str = "chilled",
    network_path: str | Path = SINGAPORE_NETWORK_PATH,
) -> tuple[tuple[DeliveryOrder, ...], tuple[InventoryLot, ...], tuple[DispatchVehicle, ...]]:
    """Build one batch of ordinary hospital orders for today's plan.

    Without ``seed`` the batch is a **fixed demo set**: the first ``hospitals``
    customers in the committed network order, so a rehearsal and the report can
    quote stable numbers.  With ``seed`` the same number of hospitals is drawn
    reproducibly from the network — the "🎲 随机今日订单" behaviour, which is
    what makes the demo show something different each time without giving up
    reproducibility.

    Returns ``(orders, inventory, vehicles)`` in the shapes the dispatch layer
    already consumes, ready to post to ``/api/dispatch/plan`` or
    ``/api/dispatch/runs``.
    """
    if temperature_zone not in ZONE_PRODUCT:
        raise ValueError(
            f"unknown temperature zone {temperature_zone!r}; "
            f"expected one of {sorted(ZONE_PRODUCT)}"
        )
    network = read_network(network_path)
    customers = [node for node in network["nodes"] if node["role"] == "customer"]
    if not customers:
        raise ValueError("Singapore network has no customer nodes")
    if not 1 <= hospitals <= len(customers):
        raise ValueError(
            f"hospitals must be between 1 and {len(customers)}, got {hospitals}"
        )

    depot = next(node for node in network["nodes"] if node["role"] == "depot")
    product_id = ZONE_PRODUCT[temperature_zone]
    if seed is None:
        chosen = customers[:hospitals]
    else:
        chosen = sorted(
            random.Random(seed).sample(customers, hospitals),
            key=lambda node: node["node_id"],
        )

    orders = tuple(
        DeliveryOrder(
            order_id=f"DO-DAILY-{node['facility_id']}",
            product_id=product_id,
            destination_facility_id=node["facility_id"],
            quantity=node["demand"],
            earliest_min=node["earliest_min"],
            latest_min=node["latest_min"],
            temperature_zone=temperature_zone,
        )
        for node in chosen
    )

    total_demand = sum(order.quantity for order in orders)
    capacity = network["capacity"]
    inventory = (
        InventoryLot(
            lot_id=f"LOT-DAILY-{temperature_zone}",
            product_id=product_id,
            facility_id=depot["facility_id"],
            available_quantity=total_demand,
            temperature_zone=temperature_zone,
        ),
    )
    vehicles = tuple(
        DispatchVehicle(
            vehicle_id=f"V-{temperature_zone.upper()}-{index}",
            capacity=capacity,
            temperature_zone=temperature_zone,
            start_facility_id=depot["facility_id"],
        )
        for index in range(1, math.ceil(total_demand / capacity) + 1)
    )
    return orders, inventory, vehicles
