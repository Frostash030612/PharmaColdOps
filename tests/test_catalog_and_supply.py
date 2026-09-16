"""B1 (2026-09-16): the product catalogue and the supply-point table.

What these tests protect, in one line each:

* the catalogue cannot invent a product the decision layer cannot judge — its ids
  must be exactly the ones in A's ``rules_config.json``;
* moving ``product → temperature_zone`` out of two literals into one file did not
  change any behaviour (the old mapping is pinned here as a golden value);
* the supply table obeys the 2026-09-16 decision: one warehouse with everything,
  every distribution point at most two categories, all of them real network nodes
  with the matching role, and a hospital can never be a source.
"""
from __future__ import annotations

import json

import pytest

from optimisation.catalog import (
    MAX_PRODUCTS_PER_DISTRIBUTION_POINT,
    PRODUCT_CATALOG_PATH,
    TEMPERATURE_ZONES,
    available_quantity,
    product_zones,
    read_catalog,
    read_supply_points,
    supply_points_for_product,
    zone_products,
)
from optimisation.daily_orders import ZONE_PRODUCT
from optimisation.reshipment import PRODUCT_TEMPERATURE_ZONE
from optimisation.singapore_loader import read_network

RULES_CONFIG = (PRODUCT_CATALOG_PATH.parents[2] / "src/rule_engine/rules_config.json")


@pytest.fixture(scope="module")
def catalog():
    return read_catalog()


@pytest.fixture(scope="module")
def points(catalog):
    return read_supply_points(catalog=catalog)


# --- the catalogue ----------------------------------------------------------

def test_the_catalogue_is_exactly_what_the_rule_engine_can_judge(catalog):
    """No product may exist here that A cannot disposition.

    Routing can only carry goods the decision layer knows: a product added to the
    catalogue alone would arrive as an order nobody can rule on.
    """
    engine = {p["product_id"] for p in json.loads(RULES_CONFIG.read_text(encoding="utf-8"))["products"]}
    assert {p.product_id for p in catalog} == engine


def test_the_catalogue_keeps_the_zones_that_used_to_be_hard_coded(catalog):
    """Golden values: the refactor must not move a single product's zone."""
    assert product_zones(catalog) == {
        "vaccine_2_8": "chilled", "frozen_m20": "frozen",
        "insulin_2_8": "chilled", "mrna_ultracold": "ultracold",
    }
    assert PRODUCT_TEMPERATURE_ZONE == product_zones(catalog)


def test_one_representative_product_per_zone_and_the_demo_batch_is_unchanged(catalog):
    representatives = zone_products(catalog)
    assert set(representatives) <= set(TEMPERATURE_ZONES)
    # the demo batch still ships vaccine_2_8 / frozen_m20 / mrna_ultracold
    assert representatives == ZONE_PRODUCT
    assert representatives == {"chilled": "vaccine_2_8", "frozen": "frozen_m20",
                               "ultracold": "mrna_ultracold"}


def test_every_catalogue_row_is_complete(catalog):
    for product in catalog:
        assert product.name_zh and product.name_en and product.unit
        assert product.temperature_zone in TEMPERATURE_ZONES


# --- the supply table -------------------------------------------------------

def test_one_warehouse_and_it_covers_every_product(points, catalog):
    warehouses = [p for p in points if p.kind == "warehouse"]
    assert len(warehouses) == 1
    warehouse = warehouses[0]
    covered = {pid for pid, _ in warehouse.supplies}
    assert covered == {p.product_id for p in catalog}


def test_every_distribution_point_has_at_most_two_categories(points):
    for point in points:
        if point.kind != "distribution":
            continue
        assert len(point.supplies) <= MAX_PRODUCTS_PER_DISTRIBUTION_POINT, point.facility_id
        assert point.supplies, point.facility_id


def test_supply_points_are_real_nodes_with_the_role_their_kind_claims(points):
    roles = {n["facility_id"]: n["role"] for n in read_network()["nodes"]}
    for point in points:
        expected = "depot" if point.kind == "warehouse" else "distribution"
        assert roles[point.facility_id] == expected, point.facility_id


def test_a_hospital_can_never_be_a_source(catalog, points):
    """Absence from the table means "cannot supply" — the point of the table."""
    hospitals = [n["facility_id"] for n in read_network()["nodes"]
                 if n["role"] == "customer"]
    assert not ({p.facility_id for p in points} & set(hospitals))
    for hospital in hospitals:
        assert available_quantity(hospital, "vaccine_2_8", points=points) == 0


def test_the_third_party_warehouse_is_deliberately_not_a_source(points):
    """Kept for comparison only; it must not quietly become an origin."""
    assert "W-KN-PIONEER" not in {p.facility_id for p in points}


def test_the_origin_candidates_for_a_product_put_the_warehouse_first(catalog, points):
    for product in catalog:
        candidates = supply_points_for_product(product.product_id, points=points)
        assert candidates, product.product_id
        assert candidates[0] == "W-WESTGATE"
        assert "D-NORTHPOINT" in candidates or product.product_id not in {"vaccine_2_8"}


# --- availability -----------------------------------------------------------

def test_the_lot_ledger_wins_over_the_demo_number(points):
    lots = [
        {"facility_id": "D-HOUGANG", "product_id": "vaccine_2_8", "available_quantity": 12,
         "status": "available"},
        {"facility_id": "D-HOUGANG", "product_id": "vaccine_2_8", "available_quantity": 5,
         "status": "quarantine"},
    ]
    # 12 available + 5 quarantined ⇒ the ledger knows the pair, so 12 (not 90)
    assert available_quantity("D-HOUGANG", "vaccine_2_8", lots=lots, points=points) == 12


def test_a_real_zero_is_not_papered_over_by_the_demo_number(points):
    lots = [{"facility_id": "D-HOUGANG", "product_id": "vaccine_2_8",
             "available_quantity": 0, "status": "available"}]
    assert available_quantity("D-HOUGANG", "vaccine_2_8", lots=lots, points=points) == 0


def test_without_a_ledger_the_declared_demo_quantity_applies(points):
    assert available_quantity("D-BUGIS", "insulin_2_8", points=points) == 120
    assert available_quantity("W-WESTGATE", "frozen_m20", points=points) == 300


def test_a_product_the_point_does_not_carry_is_zero(points):
    # Bugis+ carries insulin and frozen only
    assert available_quantity("D-BUGIS", "vaccine_2_8", points=points) == 0


# --- the table refuses to be wrong -----------------------------------------

def _write(tmp_path, payload):
    path = tmp_path / "supply_points.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _points(entries):
    return {"schema_version": 1, "assumptions": "test", "points": entries}


def test_a_distribution_point_with_three_products_is_rejected(tmp_path, catalog):
    path = _write(tmp_path, _points([
        {"facility_id": "W-WESTGATE", "kind": "warehouse", "supplies": "all",
         "demo_quantity": {p.product_id: 10 for p in catalog}},
        {"facility_id": "D-BUGIS", "kind": "distribution",
         "supplies": {"vaccine_2_8": 1, "insulin_2_8": 1, "frozen_m20": 1}},
    ]))
    with pytest.raises(ValueError, match="more than the agreed maximum"):
        read_supply_points(path, catalog=catalog)


def test_an_unknown_product_is_rejected_before_it_reaches_a_solver(tmp_path, catalog):
    path = _write(tmp_path, _points([
        {"facility_id": "W-WESTGATE", "kind": "warehouse", "supplies": "all",
         "demo_quantity": {p.product_id: 10 for p in catalog}},
        {"facility_id": "D-BUGIS", "kind": "distribution", "supplies": {"vacine_2_8": 5}},
    ]))
    with pytest.raises(ValueError, match="unknown product"):
        read_supply_points(path, catalog=catalog)


def test_a_hospital_declared_as_a_distribution_point_is_rejected(tmp_path, catalog):
    path = _write(tmp_path, _points([
        {"facility_id": "W-WESTGATE", "kind": "warehouse", "supplies": "all",
         "demo_quantity": {p.product_id: 10 for p in catalog}},
        {"facility_id": "H-SGH", "kind": "distribution", "supplies": {"vaccine_2_8": 5}},
    ]))
    with pytest.raises(ValueError, match="network role"):
        read_supply_points(path, catalog=catalog)


def test_a_warehouse_that_does_not_cover_everything_is_rejected(tmp_path, catalog):
    path = _write(tmp_path, _points([
        {"facility_id": "W-WESTGATE", "kind": "warehouse", "supplies": "all",
         "demo_quantity": {"vaccine_2_8": 10}},
    ]))
    with pytest.raises(ValueError, match="covers every catalogue product"):
        read_supply_points(path, catalog=catalog)


def test_a_third_party_node_cannot_be_promoted_to_a_second_warehouse(tmp_path, catalog):
    """The role check fires first — a 3PL node is not the warehouse.

    This is the guard that keeps ``W-KN-PIONEER`` in its comparison-only slot:
    declaring it as the warehouse is refused before any planning happens.
    """
    path = _write(tmp_path, _points([
        {"facility_id": "W-WESTGATE", "kind": "warehouse", "supplies": "all",
         "demo_quantity": {p.product_id: 10 for p in catalog}},
        {"facility_id": "W-KN-PIONEER", "kind": "warehouse", "supplies": "all",
         "demo_quantity": {p.product_id: 10 for p in catalog}},
    ]))
    with pytest.raises(ValueError, match="network role"):
        read_supply_points(path, catalog=catalog)


def test_a_table_without_a_warehouse_is_rejected(tmp_path, catalog):
    path = _write(tmp_path, _points([
        {"facility_id": "D-BUGIS", "kind": "distribution", "supplies": {"vaccine_2_8": 5}},
    ]))
    with pytest.raises(ValueError, match="exactly one warehouse"):
        read_supply_points(path, catalog=catalog)
