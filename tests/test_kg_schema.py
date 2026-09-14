"""Cypher constraint/index tests (M6, DAILY_PLAN D 9/11 ①).

The uniqueness guarantees behind the writer's idempotency must live at the
DB level, not just in MERGE logic: re-running ensure_constraints is a
no-op, and a duplicate key is rejected by Neo4j itself.
Skipped when the dev Neo4j (``docker compose up -d``) is unreachable.
"""
from __future__ import annotations

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ConstraintError

from knowledge_graph.connect import URI, USER, PASSWORD
from knowledge_graph.schema import UNIQUE_CONSTRAINTS, ensure_constraints


@pytest.mark.needs_db
def test_ensure_constraints_idempotent_and_enforced():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        driver.verify_connectivity()
        ensure_constraints(driver)  # twice: must be a no-op the second time
        ensure_constraints(driver)

        names = {r["name"] for r in driver.execute_query(
            "SHOW CONSTRAINTS YIELD name").records}
        assert {name for name, _, _ in UNIQUE_CONSTRAINTS} <= names

        # uniqueness is enforced by the database, not just by MERGE
        driver.execute_query("CREATE (e:ExcursionEvent {run_id: 'RSCHEMA-TEST'})")
        with pytest.raises(ConstraintError):
            driver.execute_query("CREATE (e:ExcursionEvent {run_id: 'RSCHEMA-TEST'})")

        driver.execute_query(
            "MATCH (e:ExcursionEvent {run_id: 'RSCHEMA-TEST'}) DETACH DELETE e"
        )
    finally:
        driver.close()
