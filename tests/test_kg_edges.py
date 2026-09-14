"""Static edge tests: Facility road links + Product→SOP derivation.

Both edge sets must mirror their sources exactly — the Facility layer
recomputes nothing from C's network.json (matrix parity check), and the
Product→SOP edges must equal an independent recomputation from the shared
RULE_TO_* maps (so static and runtime derivations can never disagree).
Skipped when the dev Neo4j (``docker compose up -d``) is unreachable.
"""
from __future__ import annotations

import json
import os

import pytest
from neo4j import GraphDatabase

from knowledge_graph.build_graph import (
    PRODUCT_RULES,
    RULE_TO_REGULATIONS,
    RULE_TO_SOPS,
    NETWORK_PATH,
    REPO_ROOT,
)

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")


def _query(q: str, **params) -> list:
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        return [dict(r) for r in driver.execute_query(q, parameters_=params).records]
    finally:
        driver.close()


@pytest.mark.needs_db
def test_connects_edges_match_network_matrix():
    net = json.loads(NETWORK_PATH.read_text(encoding="utf-8"))
    nodes = net["nodes"]
    dist = net["matrix"]["distance_m"]
    dur = net["matrix"]["duration_s"]
    id_by_node = {n["node_id"]: n["facility_id"] for n in nodes}

    edges = _query(
        """
        MATCH (a:Facility)-[r:CONNECTS]->(b:Facility)
        RETURN a.facility_id AS a, b.facility_id AS b, r
        """
    )
    # 11 facilities → 55 unordered pairs, exactly once each
    assert len(edges) == 55
    pairs = {frozenset((e["a"], e["b"])) for e in edges}
    assert len(pairs) == 55

    for e in edges:
        r = e["r"]
        assert r["distance_m"] > 0 and r["duration_s"] > 0
        assert r["source"].startswith("osmnx-shortest-path")
        # every pair carries real route geometry ([lon, lat] GeoJSON order)
        geom = json.loads(r["geometry"])
        assert len(geom) >= 2
        for pt in geom[:3]:
            assert len(pt) == 2 and abs(pt[0]) < 180 and abs(pt[1]) < 90

    # spot check one pair against the matrix, verbatim
    i = 0  # W-KN-PIONEER
    j = 2  # H-NUH
    row = _query(
        """
        MATCH (a:Facility {facility_id: $a})-[r:CONNECTS]-(b:Facility {facility_id: $b})
        RETURN r.distance_m AS d, r.duration_s AS t
        """,
        a=id_by_node[i],
        b=id_by_node[j],
    )[0]
    assert row["d"] == pytest.approx(dist[i][j], rel=1e-9)
    assert row["t"] == pytest.approx(dur[i][j], rel=1e-9)


@pytest.mark.needs_db
def test_product_sop_edges_match_rule_maps():
    # independent recomputation: product clauses -> rules -> SOPs
    clause_to_rules: dict = {}
    for rule_no, clause_ids in RULE_TO_REGULATIONS.items():
        for cid in clause_ids:
            clause_to_rules.setdefault(cid, set()).add(rule_no)

    raw = json.loads(
        (REPO_ROOT / "src" / "rule_engine" / "rules_config.json").read_text(encoding="utf-8")
    )
    expected = {}
    for p in raw["products"]:
        rule_ids = list(PRODUCT_RULES["common"])
        if p["freeze_sensitive"]:
            rule_ids += PRODUCT_RULES["freeze_sensitive"]
        rules = set().union(*(clause_to_rules.get(cid, set()) for cid in rule_ids))
        expected[p["product_id"]] = sorted(
            {sid for r in rules for sid in RULE_TO_SOPS.get(r, [])}
        )

    rows = _query(
        """
        MATCH (p:Product)-[:FOLLOWS_PROCEDURE]->(s:SOP)
        RETURN p.product_id AS pid, collect(s.sop_id) AS sops
        """
    )
    got = {r["pid"]: sorted(r["sops"]) for r in rows}

    assert set(got) == set(expected)          # every product linked, nothing extra
    for pid in expected:
        assert got[pid] == expected[pid]
        assert expected[pid]                  # derivation is never empty
    # freeze-sensitive products follow the shake-test SOP too; others don't
    freeze = {p["product_id"] for p in raw["products"] if p["freeze_sensitive"]}
    for pid in freeze:
        assert "SOP-GDP-002" in got[pid]
    for pid in set(expected) - freeze:
        assert "SOP-GDP-002" not in got[pid]
