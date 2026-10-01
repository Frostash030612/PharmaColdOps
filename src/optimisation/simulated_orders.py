"""Versioned, reproducible synthetic business inputs; never calls a solver.

Facility identities and road geometry are sourced data. Receiving hours, demand,
fleet, stock and SLA windows remain demo assumptions, not hospital business data.
The old daily_orders fixed benchmark is deliberately left untouched.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from .catalog import PRODUCT_CATALOG_PATH, SUPPLY_POINTS_PATH, read_catalog, read_supply_points, supplies_product
from .dispatch_models import DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot
from .singapore_loader import SINGAPORE_NETWORK_PATH, read_network
from .tracking import LOADING_MIN

GENERATOR_VERSION = "simulated-orders-v1"
PROFILES = {
    "routine": {"quantity_min": 5, "quantity_max": 25, "window_min": 180, "window_max": 300, "fleet_size": 6},
    "urgent": {"quantity_min": 5, "quantity_max": 20, "window_min": 180, "window_max": 300, "fleet_size": 3},
    "multi_source": {"quantity_min": 5, "quantity_max": 25, "window_min": 180, "window_max": 300, "fleet_size": 6},
    "capacity_shortage": {"quantity_min": 55, "quantity_max": 75, "window_min": 240, "window_max": 360, "fleet_size": 1},
}
ASSUMPTIONS = (
    "全部订单、截止时间、需求量、库存和车队为模拟业务数据，非医院真实订单。"
    "设施名称与道路来自已入库资料；收货／营业窗口同样为演示假设。"
    "数量与载重使用目录中的箱单位，不代表真实重量、体积或药品装载认证。"
    "随车备用量为初始载货假设，占载重但不另扣仓库批次；库存按需求加模拟余量生成。"
    "紧急场景是批次内紧截止订单，不是独立在途插单。场景参数可调整，实际可行性由规划器判断，"
    "生成器不会重抽订单以保证成功，也不使用实时拥堵或 GPS。"
)


@dataclass(frozen=True)
class SimulationConfig:
    scenario: str = "routine"
    operating_date: str | None = None
    seed: int | None = None
    order_count: int = 8
    product_ids: tuple[str, ...] | None = None
    origin_facility_ids: tuple[str, ...] | None = None
    quantity_min: int | None = None
    quantity_max: int | None = None
    window_min: int | None = None
    window_max: int | None = None
    fleet_size: int | None = None
    vehicle_capacity: int = 100
    spare_quantity: int = 10
    urgent_slack_min: int = 20


@dataclass(frozen=True)
class SimulatedBatch:
    orders: tuple[DeliveryOrder, ...]
    inventory: tuple[InventoryLot, ...]
    vehicles: tuple[DispatchVehicle, ...]
    constraints: DispatchConstraints
    metadata: dict


def _bounded_integer(name, value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer between {lower} and {upper}")


def generate_simulated_batch(config: SimulationConfig, *, network_path: str | Path = SINGAPORE_NETWORK_PATH) -> SimulatedBatch:
    if config.scenario not in PROFILES:
        raise ValueError(f"unknown scenario {config.scenario!r}")
    day = (dt.date.fromisoformat(config.operating_date) if config.operating_date
           else dt.datetime.now(ZoneInfo("Asia/Singapore")).date())
    seed = config.seed if config.seed is not None else int(day.strftime("%Y%m%d"))
    _bounded_integer("seed", seed, 0, 2**32 - 1)
    _bounded_integer("order_count", config.order_count, 2, 14)
    _bounded_integer("vehicle_capacity", config.vehicle_capacity, 1, 10000)
    _bounded_integer("spare_quantity", config.spare_quantity, 0, 1000)
    _bounded_integer("urgent_slack_min", config.urgent_slack_min, 0, 120)
    settings = {key: getattr(config, key) if getattr(config, key) is not None else value
                for key, value in PROFILES[config.scenario].items()}
    for key in ("quantity_min", "quantity_max"):
        _bounded_integer(key, settings[key], 1, 1000)
    for key in ("window_min", "window_max"):
        _bounded_integer(key, settings[key], 30, 480)
    _bounded_integer("fleet_size", settings["fleet_size"], 1, 20)
    if settings["quantity_min"] > settings["quantity_max"] or settings["window_min"] > settings["window_max"]:
        raise ValueError("minimum quantity/window must not exceed maximum")

    network = read_network(network_path)
    customers = [n for n in network["nodes"] if n["role"] == "customer"]
    if config.order_count > len(customers):
        raise ValueError("order_count exceeds the receiving facilities in this network")
    by_facility = {n["facility_id"]: n for n in network["nodes"]}
    catalog = read_catalog()
    points = read_supply_points(catalog=catalog, network_path=network_path)
    by_product = {p.product_id: p for p in catalog}
    default_products = ([p.product_id for p in catalog if p.temperature_zone == "chilled"]
                        if config.scenario == "urgent" else
                        [catalog[0].product_id] if config.scenario == "capacity_shortage" else list(by_product))
    products = list(config.product_ids) if config.product_ids is not None else default_products
    if not products or len(products) != len(set(products)) or set(products) - by_product.keys():
        raise ValueError("product_ids must be non-empty, unique catalogue products")
    if len(products) > config.order_count:
        raise ValueError("order_count must cover each selected product")
    origins = list(config.origin_facility_ids) if config.origin_facility_ids is not None else [
        p.facility_id for p in points if config.scenario == "multi_source" or p.kind == "warehouse"]
    if not origins or len(origins) != len(set(origins)) or set(origins) - {p.facility_id for p in points}:
        raise ValueError("origin_facility_ids must be non-empty, unique supply points")
    zones = {by_product[pid].temperature_zone for pid in products}
    if settings["fleet_size"] < len(zones):
        raise ValueError("fleet_size must provide at least one vehicle per selected temperature zone")
    if {by_product[pid].unit for pid in products} != {"箱"}:
        raise ValueError("this generator requires the catalogue's common box unit")

    rng = random.Random(seed)
    chosen = rng.sample(customers, config.order_count)
    source_by_product = {}
    for pid in products:
        eligible = [p for p in points if p.facility_id in origins and supplies_product(p, pid)]
        if not eligible:
            raise ValueError(f"selected origins cannot supply {pid!r}")
        if config.scenario == "multi_source":
            regional = [p for p in eligible if p.kind == "distribution"]
            eligible = regional or eligible
        source_by_product[pid] = rng.choice(eligible).facility_id

    effective = {"scenario": config.scenario, "operating_date": day.isoformat(), "seed": seed,
                 "order_count": config.order_count, "product_ids": products, "origin_facility_ids": origins,
                 **settings, "vehicle_capacity": config.vehicle_capacity,
                 "spare_quantity": config.spare_quantity, "urgent_slack_min": config.urgent_slack_min}
    hashes = {"network": hashlib.sha256(Path(network_path).read_bytes()).hexdigest(),
              "catalog": hashlib.sha256(PRODUCT_CATALOG_PATH.read_bytes()).hexdigest(),
              "supply_points": hashlib.sha256(SUPPLY_POINTS_PATH.read_bytes()).hexdigest(),
              "generator": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    token = hashlib.sha256(json.dumps({"config": effective, "sources": hashes, "version": GENERATOR_VERSION},
                                      sort_keys=True).encode()).hexdigest()[:10]
    batch_id = f"SIM-{day.strftime('%Y%m%d')}-{token}"
    orders = []
    urgent_ids = []
    for i, destination in enumerate(chosen):
        pid = products[i % len(products)]
        origin = source_by_product[pid]
        available_window = destination["latest_min"] - destination["earliest_min"]
        if settings["window_min"] > available_window:
            raise ValueError("minimum window exceeds the receiving facility's opening span")
        width = rng.randint(settings["window_min"], min(settings["window_max"], available_window))
        offsets = [offset for offset in (0, 30, 60, 90) if offset + width <= available_window]
        earliest = destination["earliest_min"] + rng.choice(offsets)
        latest = earliest + width
        if config.scenario == "urgent" and i == 0:
            earliest = destination["earliest_min"]
            travel = network["matrix"]["duration_s"][by_facility[origin]["node_id"]][destination["node_id"]] / 60
            latest = min(destination["latest_min"], math.ceil(earliest + LOADING_MIN + travel + config.urgent_slack_min))
            urgent_ids.append(f"{batch_id}-O{i + 1:03}")
        if earliest > latest:
            raise ValueError("network receiving window is too short for this profile")
        orders.append(DeliveryOrder(f"{batch_id}-O{i + 1:03}", pid, destination["facility_id"],
                      rng.randint(settings["quantity_min"], settings["quantity_max"]), earliest, latest,
                      by_product[pid].temperature_zone, origin_facility_id=origin))

    demand = defaultdict(int)
    groups = defaultdict(set)
    for order in orders:
        demand[(order.origin_facility_id, order.product_id, order.temperature_zone)] += order.quantity
        groups[(order.temperature_zone, order.origin_facility_id)].add(order.product_id)
    lots = tuple(InventoryLot(f"{batch_id}-L{i + 1:03}", pid, origin, math.ceil(quantity * 1.2), zone)
                 for i, ((origin, pid, zone), quantity) in enumerate(sorted(demand.items())))
    group_keys = sorted(groups)
    # Cover every temperature first; then fill source groups and spare slots.
    slots, represented = [], set()
    for group in group_keys:
        if group[0] not in represented:
            slots.append(group)
            represented.add(group[0])
    for group in group_keys:
        if group not in slots and len(slots) < settings["fleet_size"]:
            slots.append(group)
    while len(slots) < settings["fleet_size"]:
        slots.append(group_keys[(len(slots) - len(group_keys)) % len(group_keys)])
    fleet = []
    for i, (zone, origin) in enumerate(slots):
        spare = tuple((pid, zone, config.spare_quantity) for pid in sorted(groups[(zone, origin)])
                      if config.spare_quantity)
        if sum(q for _, _, q in spare) >= config.vehicle_capacity:
            raise ValueError("vehicle_capacity must exceed its total onboard spare quantity")
        fleet.append(DispatchVehicle(f"{batch_id}-V{i + 1:02}", config.vehicle_capacity, zone,
                                     origin, by_facility[origin]["earliest_min"], onboard_spare=spare))
    metadata = {"simulated": True, "generator_version": GENERATOR_VERSION, "batch_id": batch_id,
                "config": effective, "source_sha256": hashes, "urgent_order_ids": urgent_ids,
                "summary": {"order_count": len(orders), "quantity": sum(o.quantity for o in orders),
                    "products": sorted({o.product_id for o in orders}), "temperature_zones": sorted(zones),
                    "origins": sorted({o.origin_facility_id for o in orders}), "fleet_size": len(fleet)},
                "assumptions": ASSUMPTIONS}
    return SimulatedBatch(tuple(orders), lots, tuple(fleet),
                          DispatchConstraints(max_vehicles=len(fleet), max_stops_per_vehicle=4), metadata)
