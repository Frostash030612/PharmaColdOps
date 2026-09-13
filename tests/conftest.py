"""Shared helpers for the DB-touching KG tests.

``needs_db`` marks tests that require a running Neo4j (``docker compose up -d``
in the repo root). Collection skips them, with a reason naming whichever of the
two is missing — the driver or the database — so the suite stays runnable
without a graph, and a missing ``neo4j`` package skips instead of aborting
collection for every other module's tests.
"""
import os

import pytest

try:  # only the DB tests need the driver; never break the whole suite for it
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover - the skip branch below covers this
    GraphDatabase = None

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "needs_db: test requires a running Neo4j (skipped when unreachable)",
    )


def _skip_reason() -> str:
    """'' when the graph is usable, otherwise why the needs_db tests skip."""
    if GraphDatabase is None:
        return "neo4j driver not installed (pip install -r requirements.txt)"
    try:
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        driver.verify_connectivity()
        driver.close()
    except Exception:
        return f"Neo4j unreachable at {URI} (docker compose up -d)"
    return ""


def pytest_collection_modifyitems(config, items):
    reason = _skip_reason()
    if not reason:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "needs_db" in item.keywords:
            item.add_marker(skip)
