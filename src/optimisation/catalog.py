"""The product catalogue and the supply-point table (B1, 2026-09-16).

Two questions the routing layer could not answer before, and both are now data
instead of hard-coded literals:

* **what products exist** — ``product_catalog.csv`` is the single source for
  ``product_id → temperature_zone`` (the mapping was duplicated in
  ``reshipment.py`` and ``daily_orders.py``, which is exactly how one copy ends
  up missing a product the other one knows);
* **which node holds which goods** — ``supply_points.json`` says which nodes may
  be an order's origin and what each of them supplies. Absence means "cannot
  supply", so a hospital never needs to be listed.

Thresholds are deliberately **not** duplicated here: ``storage_min_c``,
``mkt_threshold_c``, ``retestable`` and friends live in A's
``src/rule_engine/rules_config.json`` with clause-level provenance. This module
only carries what routing needs on top of A's product ids; a test asserts the two
sets stay identical, so the catalogue cannot invent a product the decision layer
cannot judge.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from .singapore_loader import SINGAPORE_NETWORK_PATH, read_network

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_CATALOG_PATH = REPO_ROOT / "data/optimisation/product_catalog.csv"
SUPPLY_POINTS_PATH = REPO_ROOT / "data/optimisation/supply_points.json"

#: The temperature zones the fleet and the models understand.
TEMPERATURE_ZONES = ("chilled", "frozen", "ultracold")

#: 2026-09-16 decision: the warehouse carries everything, a distribution point at
#: most two categories — enough to make "not every node has every product" real
#: without turning the demo into a warehouse exercise.
MAX_PRODUCTS_PER_DISTRIBUTION_POINT = 2

CATALOG_COLUMNS = ("product_id", "name_zh", "name_en", "temperature_zone", "unit")


@dataclass(frozen=True)
class Product:
    product_id: str
    name_zh: str
    name_en: str
    temperature_zone: str
    unit: str


@dataclass(frozen=True)
class SupplyPoint:
    facility_id: str
    kind: str                                   # "warehouse" | "distribution"
    #: ``None`` means every catalog product; otherwise ``(product_id, quantity)``
    #: pairs of **demo** quantities (used only when no lot ledger exists for that
    #: facility/product — see ``available_quantity``).
    supplies: tuple[tuple[str, int], ...] | None


def read_catalog(path: str | Path = PRODUCT_CATALOG_PATH) -> tuple[Product, ...]:
    """Read and validate the one product catalogue."""
    path = Path(path)
    # utf-8-sig: a BOM is what Excel leaves behind when someone edits the CSV.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: catalogue is empty")
    missing = [column for column in CATALOG_COLUMNS if column not in rows[0]]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")

    products: list[Product] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        values = {column: (row.get(column) or "").strip() for column in CATALOG_COLUMNS}
        if not all(values.values()):
            raise ValueError(f"{path}:{index}: every column is required, got {values}")
        if values["temperature_zone"] not in TEMPERATURE_ZONES:
            raise ValueError(
                f"{path}:{index}: unknown temperature_zone {values['temperature_zone']!r}; "
                f"expected one of {list(TEMPERATURE_ZONES)}"
            )
        if values["product_id"] in seen:
            raise ValueError(f"{path}:{index}: duplicate product_id {values['product_id']!r}")
        seen.add(values["product_id"])
        products.append(Product(**values))
    return tuple(products)


def product_zones(catalog: tuple[Product, ...] | None = None) -> dict[str, str]:
    """``product_id → temperature_zone`` — the map that used to be hard-coded."""
    return {p.product_id: p.temperature_zone for p in (catalog or read_catalog())}


def zone_products(catalog: tuple[Product, ...] | None = None) -> dict[str, str]:
    """``temperature_zone → one representative product`` for the demo batch.

    The first catalogue row of each zone wins, so the choice is deterministic and
    documented rather than accidental.
    """
    catalog = catalog or read_catalog()
    chosen: dict[str, str] = {}
    for product in catalog:
        chosen.setdefault(product.temperature_zone, product.product_id)
    return chosen


def read_supply_points(
    path: str | Path = SUPPLY_POINTS_PATH,
    *,
    catalog: tuple[Product, ...] | None = None,
    network_path: str | Path = SINGAPORE_NETWORK_PATH,
) -> tuple[SupplyPoint, ...]:
    """Read the supply-point table and check it against the network and catalogue."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported schema_version")
    points = raw.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError(f"{path}: points must be a non-empty list")

    known_products = {p.product_id for p in (catalog or read_catalog())}
    roles = {n["facility_id"]: n["role"] for n in read_network(network_path)["nodes"]}

    parsed: list[SupplyPoint] = []
    seen: set[str] = set()
    for index, entry in enumerate(points):
        where = f"{path}: points[{index}]"
        facility_id = entry.get("facility_id")
        kind = entry.get("kind")
        if kind not in {"warehouse", "distribution"}:
            raise ValueError(f"{where}: unknown kind {kind!r}")
        if facility_id in seen:
            raise ValueError(f"{where}: duplicate facility_id {facility_id!r}")
        seen.add(facility_id)
        if facility_id not in roles:
            raise ValueError(f"{where}: {facility_id!r} is not in the network")
        expected_role = "depot" if kind == "warehouse" else "distribution"
        if roles[facility_id] != expected_role:
            raise ValueError(
                f"{where}: network role of {facility_id!r} is {roles[facility_id]!r}, "
                f"expected {expected_role!r} for kind {kind!r}"
            )

        supplies = entry.get("supplies")
        if kind == "warehouse":
            if supplies != "all":
                raise ValueError(f"{where}: a warehouse must declare supplies: \"all\"")
            demo = entry.get("demo_quantity") or {}
            pairs = tuple(
                (product_id, _quantity(f"{where}.demo_quantity", product_id, quantity,
                                       known_products))
                for product_id, quantity in demo.items()
            )
            if {p for p, _ in pairs} != known_products:
                raise ValueError(
                    f"{where}: a warehouse covers every catalogue product "
                    f"({sorted(known_products)}), got {sorted(p for p, _ in pairs)}"
                )
            parsed.append(SupplyPoint(facility_id, kind, pairs))
            continue

        if not isinstance(supplies, dict) or not supplies:
            raise ValueError(f"{where}: a distribution point needs a non-empty supplies object")
        if len(supplies) > MAX_PRODUCTS_PER_DISTRIBUTION_POINT:
            raise ValueError(
                f"{where}: {len(supplies)} products is more than the agreed maximum of "
                f"{MAX_PRODUCTS_PER_DISTRIBUTION_POINT} per distribution point"
            )
        pairs = tuple(
            (product_id, _quantity(f"{where}.supplies", product_id, quantity, known_products))
            for product_id, quantity in supplies.items()
        )
        parsed.append(SupplyPoint(facility_id, kind, pairs))

    if sum(point.kind == "warehouse" for point in parsed) != 1:
        raise ValueError(f"{path}: exactly one warehouse is required")
    return tuple(parsed)


def _quantity(where: str, product_id: str, quantity: object, known_products: set[str]) -> int:
    if product_id not in known_products:
        raise ValueError(
            f"{where}: unknown product {product_id!r}; add it to the catalogue first"
        )
    if type(quantity) is not int or quantity < 0:
        raise ValueError(f"{where}: quantity for {product_id!r} must be a non-negative integer")
    return quantity


def supplies_product(point: SupplyPoint, product_id: str,
                     catalog: tuple[Product, ...] | None = None) -> bool:
    if point.supplies is None:
        return False
    if any(product_id == pid for pid, _ in point.supplies):
        return True
    # A warehouse with supplies="all" is stored as the full catalogue, so a
    # product added to the catalogue later is already covered.
    return point.kind == "warehouse" and product_id in product_zones(catalog)


def demo_quantity(point: SupplyPoint, product_id: str) -> int:
    for pid, quantity in point.supplies or ():
        if pid == product_id:
            return quantity
    return 0


def available_quantity(
    facility_id: str,
    product_id: str,
    *,
    lots: object = None,
    points: tuple[SupplyPoint, ...] | None = None,
) -> int:
    """How much of ``product_id`` this facility can supply right now.

    The lot ledger wins when it knows the pair at all — a real zero means "out of
    stock" and must not be papered over with a demo number. Only when no lot is
    recorded for that facility/product do the demo quantities apply, which is the
    offline-demo case and is declared as such by the caller.
    """
    points = points if points is not None else read_supply_points()
    point = next((p for p in points if p.facility_id == facility_id), None)
    if point is None or not supplies_product(point, product_id):
        return 0

    ledger_total = 0
    ledger_knows_pair = False
    for lot in lots or ():
        get = lot.get if isinstance(lot, dict) else lambda key, _lot=lot: getattr(_lot, key, None)
        if get("facility_id") != facility_id or get("product_id") != product_id:
            continue
        ledger_knows_pair = True
        if (get("status") or "available") == "available":
            ledger_total += int(get("available_quantity") or 0)
    if ledger_knows_pair:
        return ledger_total
    return demo_quantity(point, product_id)


def supply_points_for_product(
    product_id: str, *, points: tuple[SupplyPoint, ...] | None = None,
) -> tuple[str, ...]:
    """Every facility that could be an origin for this product (warehouse first)."""
    points = points if points is not None else read_supply_points()
    ordered = sorted(points, key=lambda p: (p.kind != "warehouse", p.facility_id))
    return tuple(p.facility_id for p in ordered if supplies_product(p, product_id))
