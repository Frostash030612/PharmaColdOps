"""Cypher constraints & indices for the KG (M6, DAILY_PLAN D 9/11 ①).

Mirrors docs/KG_SCHEMA_v1.md §5 — this file implements the schema
document, it does not define new rules. Idempotent: every statement uses
``IF NOT EXISTS``, so re-running (or being called from build_graph on
every rebuild) is safe.

Usage (cold-chain env, compose Neo4j up — ``docker compose up -d`` — from the repo root)::

    python -m src.knowledge_graph.schema

build_graph also calls :func:`ensure_constraints` first, so a rebuild
always runs against a constrained graph.
"""
from __future__ import annotations

from .connect import get_driver

# (constraint name, label, property) — uniqueness, per KG_SCHEMA §5.
# Shipment/RootCause are in the graph but outside the 9-entity schema;
# constrained so runtime writers can MERGE against them safely.
UNIQUE_CONSTRAINTS = [
    ("product_id_unique", "Product", "product_id"),
    ("excursion_event_run_id_unique", "ExcursionEvent", "run_id"),
    ("cause_code_unique", "Cause", "cause_code"),
    ("disposition_unique", "Disposition", "disposition"),
    ("regulation_clause_id_unique", "Regulation", "clause_id"),
    ("facility_id_unique", "Facility", "facility_id"),
    ("sop_id_unique", "SOP", "sop_id"),
    ("reshipment_order_id_unique", "ReshipmentOrder", "order_id"),
    ("shipment_id_unique", "Shipment", "shipment_id"),
    ("root_cause_id_unique", "RootCause", "cause_id"),
]

# (index name, label, property) — per KG_SCHEMA §5: QA aggregation and
# per-product case history on ExcursionEvent.
INDEXES = [
    ("exc_event_product_id", "ExcursionEvent", "product_id"),
    ("exc_event_stage", "ExcursionEvent", "stage"),
    ("exc_event_created_at", "ExcursionEvent", "created_at"),
]


def ensure_constraints(driver) -> None:
    """Create every constraint / index that does not exist yet."""
    for name, label, prop in UNIQUE_CONSTRAINTS:
        driver.execute_query(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
    for name, label, prop in INDEXES:
        driver.execute_query(
            f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
        )


def main() -> None:
    driver = get_driver()
    try:
        ensure_constraints(driver)
        cons = driver.execute_query("SHOW CONSTRAINTS YIELD name").records
        idx = driver.execute_query("SHOW INDEXES YIELD name").records
        print(f"constraints ({len(cons)}):", sorted(r["name"] for r in cons))
        print(f"indexes ({len(idx)}):", sorted(r["name"] for r in idx))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
