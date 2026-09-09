"""Compliance QA over the PharmaColdOps knowledge graph (M6).

Answers the demo's "why" questions by traversing the graph and returns the
evidence nodes that back each answer, in the /api/qa contract shape
(see PROGRESS.md): ``{answer: str, evidence: [{node_type, node_id, summary}]}``.

Requires the graph built by :mod:`src.knowledge_graph.build_graph`. Connection
defaults: ``NEO4J_URI`` / ``NEO4J_USER`` / ``NEO4J_PASSWORD`` env vars.
"""
from __future__ import annotations

import os
from typing import Dict, List

from neo4j import GraphDatabase

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")


def _connect():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    driver.verify_connectivity()
    return driver


def _run(driver, query: str, **params) -> List[Dict]:
    return [dict(r) for r in driver.execute_query(query, parameters_=params).records]


def why_disposition(scenario_id: str) -> Dict:
    """Why did scenario X get its disposition? Answer + regulatory basis + SOPs."""
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (dec:Decision {scenario_id: $sid})-[:RESOLVES]->(e:ExcursionEvent)
            OPTIONAL MATCH (dec)-[:CITES]->(r:Regulation)
            OPTIONAL MATCH (dec)-[:FOLLOWS]->(sp:SOP)
            RETURN dec, e, collect(DISTINCT r) AS cited, collect(DISTINCT sp) AS sops
            """,
            sid=scenario_id,
        )
    if not rows:
        return {"answer": f"no decision recorded for scenario {scenario_id}", "evidence": []}
    row = rows[0]
    dec, e = row["dec"], row["e"]
    cited = sorted(row["cited"], key=lambda r: r["clause_id"])
    sops = sorted(row["sops"], key=lambda s: s["sop_id"])
    answer = (
        f"Scenario {scenario_id}: {dec['disposition'].upper()} — {dec['reason']}. "
        f"Excursion: {e['excursion_temp_c']} °C for {e['duration_min']} min "
        f"(MKT {e['mkt_c']} °C, packaging {e['packaging']}, stage {e['stage']})."
    )
    evidence = []
    for r in cited:
        evidence.append(
            {
                "node_type": "Regulation",
                "node_id": r["clause_id"],
                "summary": f"{r['title']} — {r['clause']}: {r['summary']}",
            }
        )
    for s in sops:
        evidence.append(
            {"node_type": "SOP", "node_id": s["sop_id"], "summary": f"{s['title']}: {s['summary']}"}
        )
    return {"answer": answer, "evidence": evidence}


def audit_chain(scenario_id: str) -> Dict:
    """Full traceable chain for one scenario: shipment → product → event →
    decision → regulations/SOPs (+ root cause if recorded)."""
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (dec:Decision {scenario_id: $sid})-[:RESOLVES]->(e:ExcursionEvent)-[:OCCURRED_ON]->(s:Shipment)
            MATCH (s)-[:CARRIES]->(p:Product)
            MATCH (s)-[:DEPARTS_FROM]->(o:Facility)
            MATCH (s)-[:DELIVERS_TO]->(d:Facility)
            OPTIONAL MATCH (dec)-[:CITES]->(r:Regulation)
            OPTIONAL MATCH (dec)-[:FOLLOWS]->(sp:SOP)
            OPTIONAL MATCH (c:RootCause)-[:CAUSED]->(e)
            RETURN dec, e, s, p, o, d, collect(DISTINCT r) AS cited,
                   collect(DISTINCT sp) AS sops, collect(DISTINCT c) AS causes
            """,
            sid=scenario_id,
        )
    if not rows:
        return {"answer": f"no decision recorded for scenario {scenario_id}", "evidence": []}
    row = rows[0]
    dec, e, s, p, o, d = row["dec"], row["e"], row["s"], row["p"], row["o"], row["d"]
    answer = (
        f"{s['shipment_id']}: {o['name']} → {d['name']} carrying {p['product_id']}; "
        f"excursion {e['excursion_temp_c']} °C for {e['duration_min']} min → "
        f"{dec['disposition'].upper()} (rule {dec['rule_no']}: {dec['reason']})."
    )
    evidence = [
        {"node_type": "Shipment", "node_id": s["shipment_id"], "summary": f"{o['name']} → {d['name']}"},
        {"node_type": "Product", "node_id": p["product_id"], "summary": f"{p['storage_min_c']}–{p['storage_max_c']} °C, allowable {p['allowable_duration_min']} min"},
        {"node_type": "ExcursionEvent", "node_id": e["scenario_id"], "summary": f"{e['excursion_temp_c']} °C for {e['duration_min']} min (MKT {e['mkt_c']} °C)"},
        {"node_type": "Decision", "node_id": dec["scenario_id"], "summary": f"{dec['disposition']} · rule {dec['rule_no']}"},
    ]
    for r in sorted(row["cited"], key=lambda r: r["clause_id"]):
        evidence.append(
            {"node_type": "Regulation", "node_id": r["clause_id"], "summary": f"{r['title']} — {r['clause']}"}
        )
    for sp in sorted(row["sops"], key=lambda s: s["sop_id"]):
        evidence.append({"node_type": "SOP", "node_id": sp["sop_id"], "summary": sp["title"]})
    for c in row["causes"]:
        evidence.append(
            {"node_type": "RootCause", "node_id": c["cause_id"], "summary": c["description"]}
        )
    return {"answer": answer, "evidence": evidence}


def product_requirements(product_id: str) -> Dict:
    """Thresholds + governing regulations for one product."""
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (p:Product {product_id: $pid})-[:REGULATED_BY]->(r:Regulation)
            RETURN p, collect(r) AS rules
            """,
            pid=product_id,
        )
    if not rows:
        return {"answer": f"unknown product {product_id}", "evidence": []}
    p = rows[0]["p"]
    rules = sorted(rows[0]["rules"], key=lambda r: r["clause_id"])
    answer = (
        f"{product_id}: storage {p['storage_min_c']}–{p['storage_max_c']} °C, "
        f"allowable excursion {p['allowable_duration_min']} min, MKT ceiling {p['mkt_threshold_c']} °C, "
        f"freeze-sensitive: {p['freeze_sensitive']}, retestable: {p['retestable']}."
    )
    evidence = [
        {"node_type": "Regulation", "node_id": r["clause_id"], "summary": f"{r['title']} — {r['clause']}"}
        for r in rules
    ]
    return {"answer": answer, "evidence": evidence}


def disposition_stats() -> Dict:
    """Distribution of dispositions over the 57 scenarios (gold-label cross-check)."""
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (dec:Decision)-[:RESOLVES]->(e:ExcursionEvent)
            RETURN dec.disposition AS disposition, count(*) AS n,
                   sum(CASE WHEN dec.disposition = e.gold_label THEN 1 ELSE 0 END) AS match_gold
            ORDER BY disposition
            """,
        )
    return {
        "answer": "; ".join(f"{r['disposition']}: {r['n']} (gold match {r['match_gold']})" for r in rows),
        "evidence": [],
    }
