"""Shared Neo4j connection factory (M6, DAILY_PLAN D 9/11 ①).

One place for URI / user / password resolution so build_graph, writer, qa
and schema can never drift apart. Resolution order: ``NEO4J_URI`` /
``NEO4J_USER`` / ``NEO4J_PASSWORD`` environment variables override a
repo-root ``.env`` (loaded when python-dotenv is installed), which
overrides the defaults below. Those defaults mirror the repo-root
``docker-compose.yml`` (``docker compose up -d`` — container
``pharmacoldops-neo4j-1``, Bolt on ``localhost:7687``), so a local run
needs no environment variables at all.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:  # python-dotenv optional — env vars still work
    pass

from neo4j import GraphDatabase

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")


def get_driver():
    """A verified, connected driver — the caller closes it (or uses ``with``).

    Raises on unreachable graphs so callers can decide how to handle it
    (writer swallows it; build_graph lets it crash).
    """
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    driver.verify_connectivity()
    return driver
