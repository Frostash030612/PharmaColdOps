#!/usr/bin/env python3
"""Evaluate the /api/qa answer layer against derivable ground truth (M6, W4).

What it measures — every expectation comes from an artifact *other than*
``qa.py`` itself, the same anti-circularity rule the rule-engine gold labels
had to follow (proposal §8.3):

1. **evidence coverage** — for each closed scenario the returned evidence must
   equal the citations / SOPs mapped to the rule the engine actually fired
   (``RULE_TO_REGULATIONS`` / ``RULE_TO_SOPS`` in ``build_graph``);
2. **answer ↔ record agreement** — the answer must carry the case's own
   recorded disposition, reason and excursion numbers;
3. **product-threshold parity** — product answers must equal
   ``src/rule_engine/rules_config.json`` (A's authoritative config);
4. **outcome states** — ``no_case`` and ``unsupported`` must be reported as such;
5. **cross-case isolation** — cases sharing a disposition must not share
   citations (regression guard for the 2026-09-13 ``CITES`` scoping fix).

Inputs are the committed, human-annotated scenario bank
(``data/scenarios/scenarios.csv``, 57 rows). Each scenario is closed through the
real ``service.close_case`` path, so disposition / rule_no / cause come from the
real engine — nothing is hand-written and no expected answer is copied from the
implementation.

Explicitly NOT measured: intent-classification accuracy. That needs a
human-labelled question→intent set (``data/qa/intent_labels.csv``); the shipped
template leaves the expected column empty on purpose, because scoring the
classifier against its own keyword table would be circular.

Usage::

    python scripts/evaluate_qa.py                 # close all scenarios, then clean up
    python scripts/evaluate_qa.py --limit 5       # smoke test
    python scripts/evaluate_qa.py --keep          # keep the cases as demo data
    python scripts/evaluate_qa.py --report out.json

The report is written to ``data/processed/qa_eval_report.json`` by default (a
generated artifact, gitignored per the repo's data convention). Exit code 0 when
every check passes, 1 when any check fails, 2 when the graph is unreachable —
a missing database is never reported as a pass.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api import service  # noqa: E402
from api.schemas import EventIn, QAIn  # noqa: E402
from knowledge_graph import qa as kg_qa  # noqa: E402
from knowledge_graph.build_graph import (  # noqa: E402
    PRODUCT_RULES,
    RULE_TO_REGULATIONS,
    RULE_TO_SOPS,
)
from neo4j import GraphDatabase  # noqa: E402

SCENARIOS = ROOT / "data" / "scenarios" / "scenarios.csv"
CONFIG = ROOT / "src" / "rule_engine" / "rules_config.json"
DEFAULT_REPORT = ROOT / "data" / "processed" / "qa_eval_report.json"

NEO4J_URI = "neo4j://localhost:7687"


def _driver():
    return GraphDatabase.driver(NEO4J_URI, auth=("neo4j", "pharmacoldops"))


def _delete_case(driver, run_id: str) -> None:
    driver.execute_query("MATCH (e:ExcursionEvent {run_id: $rid}) DETACH DELETE e",
                         parameters_={"rid": run_id})
    driver.execute_query("MATCH (ro:ReshipmentOrder {order_id: $oid}) DETACH DELETE ro",
                         parameters_={"oid": f"RO-{run_id}"})


def _scenarios(limit: int | None) -> list[dict]:
    with SCENARIOS.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[:limit] if limit else rows


def _reg_ids(evidence: list) -> set[str]:
    return {e["node_id"] for e in evidence if e["node_type"] == "Regulation"}


def _sop_ids(evidence: list) -> set[str]:
    return {e["node_id"] for e in evidence if e["node_type"] == "SOP"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None, help="only the first N scenarios")
    ap.add_argument("--keep", action="store_true",
                    help="keep the closed cases in the graph (demo data)")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = ap.parse_args(argv[1:])

    try:
        driver = _driver()
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 - anything here means "no graph"
        print(f"Neo4j unreachable at {NEO4J_URI} ({exc}); "
              f"start it with `docker compose up -d` — nothing was evaluated.",
              file=sys.stderr)
        return 2

    scenarios = _scenarios(args.limit)
    failures: list[dict] = []
    closed: list[dict] = []

    def check(ok: bool, kind: str, detail: str, run_id: str | None = None) -> None:
        if not ok:
            failures.append({"check": kind, "detail": detail, "run_id": run_id})

    # ---- 1/2/5: close every scenario through the real case-close path --------
    for row in scenarios:
        event = EventIn(
            product_id=row["product_id"],
            excursion_temp_c=float(row["excursion_temp_c"]),
            duration_min=int(row["duration_min"]),
            mkt_c=float(row["mkt_c"]),
            packaging=row["packaging"],
            stage=row["stage"],
        )
        record = service.close_case(event, None, remark=f"qa-eval {row['scenario_id']}")
        run_id = record["run_id"]
        closed.append({"scenario_id": row["scenario_id"], "run_id": run_id,
                       "rule_no": record["rule_no"],
                       "disposition": record["disposition"]})

        rule_no = record["rule_no"]
        expected_regs = set(RULE_TO_REGULATIONS.get(rule_no, []))
        expected_sops = set(RULE_TO_SOPS.get(rule_no, []))

        why = kg_qa.why_disposition(run_id)
        # 1. evidence coverage: exactly the fired rule's citations, no borrowed ones
        check(why["status"] == "ok", "why_status",
              f"{row['scenario_id']}: status={why['status']}", run_id)
        check(_reg_ids(why["evidence"]) == expected_regs, "evidence_coverage",
              f"{row['scenario_id']} rule {rule_no}: regulations "
              f"{sorted(_reg_ids(why['evidence']))} != {sorted(expected_regs)}", run_id)
        check(_sop_ids(why["evidence"]) == expected_sops, "evidence_coverage",
              f"{row['scenario_id']} rule {rule_no}: SOPs "
              f"{sorted(_sop_ids(why['evidence']))} != {sorted(expected_sops)}", run_id)
        # 2. answer ↔ record agreement
        answer = why["answer"]
        check(record["disposition"].upper() in answer and record["reason"] in answer,
              "answer_matches_record", f"{row['scenario_id']}: disposition/reason missing",
              run_id)
        check(str(row["excursion_temp_c"]) in answer or
              str(float(row["excursion_temp_c"])) in answer, "answer_matches_record",
              f"{row['scenario_id']}: excursion temperature missing", run_id)

        chain = kg_qa.audit_chain(run_id)
        pairs = {(e["node_type"], e["node_id"]) for e in chain["evidence"]}
        check(chain["status"] == "ok", "audit_status",
              f"{row['scenario_id']}: status={chain['status']}", run_id)
        check(("ExcursionEvent", run_id) in pairs and
              ("Disposition", record["disposition"]) in pairs, "audit_chain",
              f"{row['scenario_id']}: event/disposition missing from the chain", run_id)

        cause = kg_qa.cause_context(run_id)
        check(cause["status"] == "ok" and str(row["stage"]) in cause["answer"],
              "cause_context", f"{row['scenario_id']}: status={cause['status']}", run_id)

    # ---- 3: product-threshold parity ---------------------------------------
    products = json.loads(CONFIG.read_text(encoding="utf-8"))["products"]
    for cfg in products:
        pid = cfg["product_id"]
        got = kg_qa.product_requirements(pid)
        expected = set(PRODUCT_RULES["common"]) | (
            set(PRODUCT_RULES["freeze_sensitive"]) if cfg["freeze_sensitive"] else set()
        )
        check(got["status"] == "ok" and str(float(cfg["storage_min_c"])) in got["answer"]
              and str(cfg["allowable_duration_min"]) in got["answer"],
              "product_parity", f"{pid}: thresholds in the answer differ from rules_config.json")
        check(_reg_ids(got["evidence"]) == expected, "product_parity",
              f"{pid}: citations {sorted(_reg_ids(got['evidence']))} != {sorted(expected)}")

    # ---- 4: outcome states --------------------------------------------------
    unknown = "RQAEVAL-" + uuid.uuid4().hex[:8]
    none_case = kg_qa.why_disposition(unknown)
    check(none_case["status"] == "no_case" and none_case["evidence"] == [],
          "state_no_case", f"unknown run reported status={none_case['status']}")
    unsupported = service.qa_view(QAIn(question_type="not_a_supported_intent"))
    check(unsupported["status"] == "unsupported" and unsupported["evidence"] == [],
          "state_unsupported", f"unknown intent reported status={unsupported['status']}")

    # ---- 5: cross-case isolation (report the groups that exercise it) --------
    groups: dict[str, set[int]] = {}
    for case in closed:
        groups.setdefault(case["disposition"], set()).add(case["rule_no"])
    mixed = {d: sorted(r) for d, r in groups.items() if len(r) > 1}

    if not args.keep:
        for case in closed:
            _delete_case(driver, case["run_id"])
    driver.close()

    total_checks = (len(scenarios) * 8) + len(products) * 2 + 2
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios": len(scenarios),
        "checks_run": total_checks,
        "checks_failed": len(failures),
        "failures": failures,
        "dispositions": {d: sorted(r) for d, r in groups.items()},
        "dispositions_with_multiple_rules": mixed,
        "cases_kept_in_graph": bool(args.keep),
        "not_measured": "intent-classification accuracy (needs data/qa/intent_labels.csv, human-labelled)",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    print(f"scenarios closed : {len(scenarios)}")
    print(f"checks           : {total_checks - len(failures)}/{total_checks} passed")
    print(f"dispositions     : {report['dispositions']}")
    print(f"mixed-rule groups: {mixed or '(none — isolation guard not exercised)'}")
    print(f"cases kept       : {args.keep}")
    try:
        shown = args.report.relative_to(ROOT)
    except ValueError:  # a custom --report outside the repo
        shown = args.report
    print(f"report           : {shown}")
    if failures:
        print(f"\nfirst failures:", file=sys.stderr)
        for f in failures[:10]:
            print(f"  [{f['check']}] {f['detail']}", file=sys.stderr)
        return 1
    print("\nall derived checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
