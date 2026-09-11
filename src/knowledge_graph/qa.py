"""Compliance QA over the PharmaColdOps knowledge graph (M6).

Answers the demo's "why" questions by traversing the graph and returns the
evidence nodes that back each answer, in the /api/qa contract shape
(see PROGRESS.md): ``{answer: str, evidence: [{node_type, node_id, summary}]}``.

Queries follow docs/KG_SCHEMA_v1.md: cases are keyed by ``run_id``
(ExcursionEvent PK), disposition facts live on the
``EVENT_LEADS_TO_DISPOSITION`` edge, and per-case chains are written by
:mod:`src.knowledge_graph.writer` when a case is closed over the API.
Connections come from ``knowledge_graph.connect`` (``NEO4J_*`` env vars /
``.env`` / ``pharmaneo`` defaults).
"""
from __future__ import annotations

from typing import Dict, List

from .connect import get_driver


def _connect():
    return get_driver()


def _run(driver, query: str, **params) -> List[Dict]:
    return [dict(r) for r in driver.execute_query(query, parameters_=params).records]


def _reg_evidence(cited: list) -> list:
    cited = sorted(cited, key=lambda r: r.get("clause_id") or "")
    return [
        {"node_type": "Regulation", "node_id": r["clause_id"],
         "summary": f"{r.get('title', '')} — {r.get('clause', '')}"}
        for r in cited
    ]


def _sop_evidence(sops: list) -> list:
    sops = sorted(sops, key=lambda s: s.get("sop_id") or "")
    return [
        {"node_type": "SOP", "node_id": s["sop_id"],
         "summary": f"{s.get('title', '')}: {s.get('summary', '')}"}
        for s in sops
    ]


def why_disposition(run_id: str) -> Dict:
    """Why did case ``run_id`` get its disposition? Answer + regulatory basis + SOPs."""
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (e:ExcursionEvent {run_id: $rid})-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
            OPTIONAL MATCH (dis)<-[:CITES]-(r:Regulation)
            OPTIONAL MATCH (e)-[:FOLLOWS]->(sp:SOP)
            RETURN e, d, dis, collect(DISTINCT r) AS cited, collect(DISTINCT sp) AS sops
            """,
            rid=run_id,
        )
    if not rows:
        return {"answer": f"no decision recorded for run {run_id}", "evidence": []}
    row = rows[0]
    e, d, dis = row["e"], row["d"], row["dis"]
    answer = (
        f"Case {run_id}: {dis['disposition'].upper()} — {d['reason']}. "
        f"Excursion: {e['excursion_temp_c']} °C for {e['duration_min']} min "
        f"(MKT {e['mkt_c']} °C, packaging {e['packaging']}, stage {e['stage']})."
    )
    evidence = _reg_evidence(row["cited"]) + _sop_evidence(row["sops"])
    return {"answer": answer, "evidence": evidence}


def audit_chain(run_id: str) -> Dict:
    """Full traceable chain for one case: event → disposition → regulations/SOPs
    (+ cause, occurrence facility, and shipment context when the case
    carries them)."""
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (e:ExcursionEvent {run_id: $rid})-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
            OPTIONAL MATCH (e)-[:EVENT_CAUSED_BY]->(c:Cause)
            OPTIONAL MATCH (e)-[:EVENT_OCCURRED_AT]->(loc:Facility)
            OPTIONAL MATCH (e)-[:OCCURRED_ON]->(s:Shipment)
            OPTIONAL MATCH (s)-[:DEPARTS_FROM]->(o:Facility)
            OPTIONAL MATCH (s)-[:DELIVERS_TO]->(f:Facility)
            OPTIONAL MATCH (dis)<-[:CITES]-(r:Regulation)
            OPTIONAL MATCH (e)-[:FOLLOWS]->(sp:SOP)
            RETURN e, d, dis, c, loc, s, o, f, collect(DISTINCT r) AS cited,
                   collect(DISTINCT sp) AS sops
            """,
            rid=run_id,
        )
    if not rows:
        return {"answer": f"no decision recorded for run {run_id}", "evidence": []}
    row = rows[0]
    e, d, dis = row["e"], row["d"], row["dis"]
    parts = []
    if row["s"] is not None:
        origin = row["o"]["name"] if row["o"] is not None else "unknown origin"
        dest = row["f"]["name"] if row["f"] is not None else "unknown destination"
        parts.append(f"{row['s']['shipment_id']}: {origin} → {dest}")
    parts.append(
        f"excursion {e['excursion_temp_c']} °C for {e['duration_min']} min "
        f"(MKT {e['mkt_c']} °C, packaging {e['packaging']}, stage {e['stage']})"
    )
    if row["loc"] is not None:
        parts.append(f"at {row['loc']['name']}")
    parts.append(
        f"{dis['disposition'].upper()} (rule {d['rule_no']}: {d['reason']})"
    )
    evidence = [
        {"node_type": "ExcursionEvent", "node_id": e["run_id"],
         "summary": f"{e['excursion_temp_c']} °C for {e['duration_min']} min (MKT {e['mkt_c']} °C)"},
        {"node_type": "Disposition", "node_id": dis["disposition"],
         "summary": f"rule {d['rule_no']} · reshipment {d['reshipment_required']}"},
    ]
    if row["c"] is not None:
        evidence.append({"node_type": "Cause", "node_id": row["c"]["cause_code"],
                         "summary": f"deterministic API risk code (score {d.get('risk_score')})"})
    if row["loc"] is not None:
        evidence.append({"node_type": "Facility", "node_id": row["loc"]["facility_id"],
                         "summary": f"event location ({row['loc']['name']})"})
    evidence += _reg_evidence(row["cited"]) + _sop_evidence(row["sops"])
    return {"answer": f"Case {run_id}: " + "; ".join(parts) + ".", "evidence": evidence}


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
    answer = (
        f"{product_id}: storage {p['storage_min_c']}–{p['storage_max_c']} °C, "
        f"allowable excursion {p['allowable_duration_min']} min, MKT ceiling {p['mkt_threshold_c']} °C, "
        f"freeze-sensitive: {p['freeze_sensitive']}, retestable: {p['retestable']}."
    )
    evidence = _reg_evidence(rows[0]["rules"])
    return {"answer": answer, "evidence": evidence}


def disposition_stats() -> Dict:
    """Distribution of dispositions over every closed case in the graph."""
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (e:ExcursionEvent)-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
            RETURN dis.disposition AS disposition, count(*) AS n
            ORDER BY disposition
            """,
        )
    return {
        "answer": "; ".join(f"{r['disposition']}: {r['n']}" for r in rows),
        "evidence": [],
    }
