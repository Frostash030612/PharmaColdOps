"""Compliance QA over the PharmaColdOps knowledge graph (M6).

Answers the demo's "why" questions by traversing the graph and returns the
evidence nodes that back each answer, in the /api/qa contract shape::

    {
      "status":   "ok" | "no_case" | "insufficient_evidence"
                  | "unsupported" | "db_error",
      "answer":   str,                       # assembled from graph facts
      "evidence": [{node_type, node_id, summary}],
    }

``status`` is what lets the front-end tell the four outcome classes apart
without parsing the answer text (proposal §6.5):

- ``ok``                    — the query resolved and carries evidence
- ``no_case``               — no record for this run_id / product (nothing to answer)
- ``insufficient_evidence`` — the record exists but the graph holds no
                              supporting nodes (e.g. the fired rule maps to no
                              citation); answered as "no evidence" rather than
                              inventing one (KG_SCHEMA §4 "无证据不回答")
- ``unsupported``           — question outside the four supported intents
- ``db_error``              — graph unreachable; raised to the API layer, which
                              turns it into HTTP 503

Answer text and evidence summaries quote the source material verbatim
(regulation clauses, SOP steps, facility names) and are therefore in the
language of those documents; only the status/notice wording is localised, in
the front-end.

Queries follow docs/KG_SCHEMA_v1.md: cases are keyed by ``run_id``
(ExcursionEvent PK), disposition facts live on the
``EVENT_LEADS_TO_DISPOSITION`` edge, and per-case chains are written by
:mod:`src.knowledge_graph.writer` when a case is closed over the API.
Connections come from ``knowledge_graph.connect`` (``NEO4J_*`` env vars /
``.env`` / compose defaults).
"""
from __future__ import annotations

from typing import Dict, List

from .connect import get_driver

#: Response statuses — the contract the front-end switches on.
STATUS_OK = "ok"
STATUS_NO_CASE = "no_case"
STATUS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
STATUS_UNSUPPORTED = "unsupported"
STATUS_DB_ERROR = "db_error"

#: The structured intents ``/api/qa`` supports (bounded intent recognition).
QUESTION_TYPES = (
    "why_disposition",
    "audit_chain",
    "product_requirements",
    "cause_context",
    "disposition_stats",
)


def _connect():
    return get_driver()


def _run(driver, query: str, **params) -> List[Dict]:
    return [dict(r) for r in driver.execute_query(query, parameters_=params).records]


def _response(answer: str, evidence: list | None = None, *,
              found: bool = True, needs_evidence: bool = True) -> Dict:
    """Assemble one contract-shaped response, deriving ``status``.

    ``needs_evidence=False`` for answers whose value *is* the aggregate (the
    disposition statistics carry no evidence nodes by design).
    """
    evidence = evidence or []
    if not found:
        return {"status": STATUS_NO_CASE, "answer": answer, "evidence": []}
    status = STATUS_OK if evidence or not needs_evidence else STATUS_INSUFFICIENT_EVIDENCE
    return {"status": status, "answer": answer, "evidence": evidence}


def unsupported_response(question_type: str) -> Dict:
    """The one response the QA router returns for an intent it does not serve."""
    return {
        "status": STATUS_UNSUPPORTED,
        "answer": (
            f"unsupported question type {question_type!r}; "
            f"supported: {', '.join(QUESTION_TYPES)}"
        ),
        "evidence": [],
    }


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


def _reshipment(driver, run_id: str) -> List[Dict]:
    """The case's reshipment order plus its destination facility, if any.

    Both come from edges ``writer.write_case`` actually creates
    (``TRIGGERS_RESHIPMENT``, ``RESHIPS_TO``) — the destination is only present
    when the case carried ``destination_facility_id``.
    """
    return _run(
        driver,
        """
        MATCH (:ExcursionEvent {run_id: $rid})-[:TRIGGERS_RESHIPMENT]->(ro:ReshipmentOrder)
        OPTIONAL MATCH (ro)-[:RESHIPS_TO]->(dest:Facility)
        RETURN ro, dest
        """,
        rid=run_id,
    )


def why_disposition(run_id: str) -> Dict:
    """Why did case ``run_id`` get its disposition? Answer + regulatory basis + SOPs.

    Evidence is tied to the rule that fired (the writer builds ``CITES`` /
    ``FOLLOWS`` from ``RULE_TO_REGULATIONS`` / ``RULE_TO_SOPS`` by ``rule_no``
    and attaches both to the case), so a case whose rule maps to no citation
    reports ``insufficient_evidence`` instead of borrowing unrelated
    regulations.
    """
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (e:ExcursionEvent {run_id: $rid})-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
            OPTIONAL MATCH (e)-[:CITES]->(r:Regulation)
            OPTIONAL MATCH (e)-[:FOLLOWS]->(sp:SOP)
            RETURN e, d, dis, collect(DISTINCT r) AS cited, collect(DISTINCT sp) AS sops
            """,
            rid=run_id,
        )
    if not rows:
        return _response(f"no decision recorded for run {run_id}", found=False)
    row = rows[0]
    e, d, dis = row["e"], row["d"], row["dis"]
    answer = (
        f"Case {run_id}: {dis['disposition'].upper()} — {d['reason']}. "
        f"Excursion: {e['excursion_temp_c']} °C for {e['duration_min']} min "
        f"(MKT {e['mkt_c']} °C, packaging {e['packaging']}, stage {e['stage']})."
    )
    evidence = _reg_evidence(row["cited"]) + _sop_evidence(row["sops"])
    return _response(answer, evidence)


def audit_chain(run_id: str) -> Dict:
    """Full traceable chain for one case: event → disposition → regulations/SOPs
    (+ cause, occurrence facility, and the reshipment order with its real
    destination when the case carries one).

    Unlike :func:`why_disposition`, a found case always carries its mechanical
    chain (event + disposition), so this reports ``ok`` whenever the case
    exists; ``insufficient_evidence`` is reserved for the compliance-only
    question.
    """
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (e:ExcursionEvent {run_id: $rid})-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
            OPTIONAL MATCH (e)-[:EVENT_CAUSED_BY]->(c:Cause)
            OPTIONAL MATCH (e)-[:EVENT_OCCURRED_AT]->(loc:Facility)
            OPTIONAL MATCH (e)-[:CITES]->(r:Regulation)
            OPTIONAL MATCH (e)-[:FOLLOWS]->(sp:SOP)
            RETURN e, d, dis, c, loc, collect(DISTINCT r) AS cited,
                   collect(DISTINCT sp) AS sops
            """,
            rid=run_id,
        )
        if not rows:
            return _response(f"no decision recorded for run {run_id}", found=False)
        reship = _reshipment(driver, run_id)

    row = rows[0]
    e, d, dis = row["e"], row["d"], row["dis"]
    parts = [
        f"excursion {e['excursion_temp_c']} °C for {e['duration_min']} min "
        f"(MKT {e['mkt_c']} °C, packaging {e['packaging']}, stage {e['stage']})"
    ]
    if row["loc"] is not None:
        parts.append(f"at {row['loc']['name']}")
    parts.append(f"{dis['disposition'].upper()} (rule {d['rule_no']}: {d['reason']})")

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

    for r in reship:
        ro, dest = r["ro"], r["dest"]
        if dest is None:
            parts.append(f"reshipment order {ro['order_id']} (no destination recorded)")
            evidence.append({"node_type": "ReshipmentOrder", "node_id": ro["order_id"],
                             "summary": "reshipment order; destination not recorded"})
            continue
        parts.append(f"reshipment {ro['order_id']} to {dest['name']}")
        evidence.append({"node_type": "ReshipmentOrder", "node_id": ro["order_id"],
                         "summary": f"reshipment order → {dest['name']}"})
        evidence.append({"node_type": "Facility", "node_id": dest["facility_id"],
                         "summary": f"reshipment destination ({dest['name']})"})

    evidence += _reg_evidence(row["cited"]) + _sop_evidence(row["sops"])
    return _response(f"Case {run_id}: " + "; ".join(parts) + ".", evidence)


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
        return _response(f"unknown product {product_id}", found=False)
    p = rows[0]["p"]
    answer = (
        f"{product_id}: storage {p['storage_min_c']}–{p['storage_max_c']} °C, "
        f"allowable excursion {p['allowable_duration_min']} min, MKT ceiling {p['mkt_threshold_c']} °C, "
        f"freeze-sensitive: {p['freeze_sensitive']}, retestable: {p['retestable']}."
    )
    return _response(answer, _reg_evidence(rows[0]["rules"]))


def cause_context(run_id: str | None = None, cause_code: str | None = None) -> Dict:
    """Where does this cause actually show up? Stage × product over closed cases.

    Answers 「该原因最常见场景」(KG_SCHEMA §4). The cause defaults to **this
    case's** own ``EVENT_CAUSED_BY`` code, so callers only need a ``run_id`` and
    never have to keep a second copy of the code in sync; an explicit
    ``cause_code`` is accepted for programmatic use. ``Cause`` is the
    deterministic API cause code (§2), not an ML inference — the aggregation
    therefore describes recorded cases, not a causal claim.
    """
    with _connect() as driver:
        code = cause_code
        if not code:
            known = _run(
                driver,
                """
                MATCH (:ExcursionEvent {run_id: $rid})-[:EVENT_CAUSED_BY]->(c:Cause)
                RETURN c.cause_code AS code
                """,
                rid=run_id,
            )
            if not known:
                return _response(f"no cause recorded for run {run_id}", found=False)
            code = known[0]["code"]

        split = _run(
            driver,
            """
            MATCH (e:ExcursionEvent)-[:EVENT_CAUSED_BY]->(c:Cause {cause_code: $code})
            RETURN e.stage AS stage, e.product_id AS product, count(*) AS n
            ORDER BY n DESC, stage, product
            """,
            code=code,
        )
        if not split:
            return _response(f"no closed case recorded with cause {code}", found=False)
        cases = _run(
            driver,
            """
            MATCH (e:ExcursionEvent)-[:EVENT_CAUSED_BY]->(c:Cause {cause_code: $code})
            RETURN e.run_id AS rid, e.stage AS stage, e.product_id AS product
            ORDER BY e.created_at DESC
            LIMIT 5
            """,
            code=code,
        )

    total = sum(r["n"] for r in split)
    top = split[0]
    answer = (
        f"cause {code}: {total} closed case(s); most often {top['stage']} / "
        f"{top['product']} ({top['n']}). Split: "
        + "; ".join(f"{r['stage']}/{r['product']}={r['n']}" for r in split)
        + "."
    )
    evidence = [
        {"node_type": "Cause", "node_id": code,
         "summary": f"{total} closed case(s) carry this API cause code"},
        *[
            {"node_type": "ExcursionEvent", "node_id": r["rid"],
             "summary": f"{r['stage']} / {r['product']}"}
            for r in cases
        ],
    ]
    return _response(answer, evidence)


def disposition_stats() -> Dict:
    """Distribution of dispositions over every closed case in the graph.

    The aggregate *is* the answer, so no evidence nodes are attached and an
    empty graph reports ``no_case`` rather than ``insufficient_evidence``.
    """
    with _connect() as driver:
        rows = _run(
            driver,
            """
            MATCH (e:ExcursionEvent)-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)
            RETURN dis.disposition AS disposition, count(*) AS n
            ORDER BY disposition
            """,
        )
    if not rows:
        return _response("no closed cases recorded", found=False)
    return _response(
        "; ".join(f"{r['disposition']}: {r['n']}" for r in rows),
        needs_evidence=False,
    )
