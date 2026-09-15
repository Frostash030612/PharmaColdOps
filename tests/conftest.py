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


@pytest.fixture
def day_plan():
    """Create "today's delivery plan" the way the API does, and return its id.

    Branch events (a closed excursion case, an urgent order) attach to the OPEN
    daily plan — there is no longer any fallback that starts a one-order operation
    of its own (``docs/C_配送模块.md`` §4.4-2). Tests that exercise a branch
    therefore have to establish the main line first, which is exactly what an
    operator does: build today's plan, confirm it, then handle what goes wrong.
    """
    from api import service
    from api.schemas import DispatchCreateIn
    from optimisation.daily_orders import daily_delivery_batch

    def _make(dispatch_id: str = "PLAN-TEST-1", *, hospitals: int = 4,
              seed: int = 1, algorithm: str = "greedy") -> str:
        orders, inventory, vehicles = daily_delivery_batch(
            hospitals=hospitals, seed=seed)
        response = service.create_dispatch(DispatchCreateIn(
            dispatch_id=dispatch_id, command_id=f"create-{dispatch_id}",
            algorithm=algorithm,
            orders=[service._order_dump(order) for order in orders],
            inventory=[service._lot_dump(lot) for lot in inventory],
            vehicles=[service._vehicle_dump(vehicle) for vehicle in vehicles],
        ))
        assert response["dispatch_id"] == dispatch_id
        return dispatch_id

    return _make
