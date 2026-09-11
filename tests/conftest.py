"""Shared helpers for the DB-touching KG tests.

``needs_db`` marks tests that require the dev Neo4j container (``pharmaneo``);
collection skips them when the graph is unreachable so the suite stays
runnable without a database.
"""
import os

import pytest
from neo4j import GraphDatabase

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "needs_db: test requires a running Neo4j (skipped when unreachable)",
    )


def pytest_collection_modifyitems(config, items):
    try:
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        driver.verify_connectivity()
        driver.close()
    except Exception:
        skip = pytest.mark.skip(reason="Neo4j (pharmaneo) unreachable")
        for item in items:
            if "needs_db" in item.keywords:
                item.add_marker(skip)
