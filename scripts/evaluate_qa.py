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

    python scripts/evaluate_qa.py                 # own disposable graph + SQL/JSONL
    python scripts/evaluate_qa.py --limit 5       # smoke test
    python scripts/evaluate_qa.py --keep          # retain own graph + SQL/JSONL
    python scripts/evaluate_qa.py --configured-test-graph  # explicit dedicated test server
    python scripts/evaluate_qa.py --report out.json

The report defaults to a NEW temporary evaluation directory, not the old report.
Every check goes through the API service. These are derived contract checks,
not independent clinical/intent accuracy. Exit 0 means checks AND cleanup passed,
1 means check failures, 2 means environment/runtime/cleanup failure.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api import service  # noqa: E402
from api.schemas import EventIn, QAIn  # noqa: E402
from knowledge_graph import connect  # noqa: E402
from knowledge_graph.schema import ensure_constraints  # noqa: E402
from knowledge_graph.build_graph import (  # noqa: E402
    PRODUCT_RULES,
    RULE_TO_REGULATIONS,
    RULE_TO_SOPS,
    load_static,
)
from optimisation.case_repository import read_case_originals  # noqa: E402
from verify_graph_recovery import docker, available_port, await_graph  # noqa: E402

SCENARIOS = ROOT / "data" / "scenarios" / "scenarios.csv"
CONFIG = ROOT / "src" / "rule_engine" / "rules_config.json"


def _driver():
    return connect.get_driver()


def _delete_case(driver, run_id: str, prefix: str) -> None:
    if not run_id.startswith(prefix):
        raise ValueError("refusing to delete a case outside the evaluation namespace")
    def delete(tx):
        tx.run("MATCH (e:ExcursionEvent {run_id:$rid}) DETACH DELETE e", rid=run_id).consume()
        tx.run("MATCH (r:ReshipmentOrder {order_id:$oid}) DETACH DELETE r", oid="RO-" + run_id).consume()
    with driver.session() as session:
        session.execute_write(delete)


def _local_image():
    # Reuse an installed image; never quietly pull a changing tag.
    try:
        return docker("image", "inspect", "neo4j:5-community", "--format", "{{.Id}}")
    except subprocess.CalledProcessError:
        return docker("inspect", "pharmacoldops-neo4j-1", "--format", "{{.Image}}")


@contextmanager
def _graph(args, info):
    container_id = driver = None
    with ExitStack() as stack:
        try:
            if args.configured_test_graph:
                info["mode"] = "explicit_configured_test_graph"
                driver = _driver()  # same resolver as writer and QA
            else:
                image = args.image or _local_image()
                port = available_port()
                password = "isolated-qa-demo"
                container_id = docker("run", "-d", "--name", "pharmacoldops-qa-eval-" + uuid.uuid4().hex[:10],
                    "--memory", "768m", "-p", f"127.0.0.1:{port}:7687", "-e", "NEO4J_AUTH=neo4j/" + password,
                    "-e", "NEO4J_server_memory_heap_initial__size=128m",
                    "-e", "NEO4J_server_memory_heap_max__size=256m",
                    "-e", "NEO4J_server_memory_pagecache_size=64m", image)
                uri = f"bolt://127.0.0.1:{port}"
                info.update(mode="own_isolated_container", container_id=container_id, uri=uri)
                await_graph(uri, password)
                for name, value in [("URI", uri), ("USER", "neo4j"), ("PASSWORD", password)]:
                    stack.enter_context(patch.object(connect, name, value))
                driver = _driver()
                # Only OUR newly created empty graph may be seeded. Never rebuild
                # the graph selected by --configured-test-graph.
                assert driver.execute_query("MATCH (n) RETURN count(n) AS n").records[0]["n"] == 0
                ensure_constraints(driver)
                load_static(driver)
            yield driver
        finally:
            if driver:
                driver.close()
            if container_id:
                info["retained"] = bool(args.keep)
                if not args.keep:
                    info["container_removed"] = False
                    # Immutable ID from our creation, never an existing user name.
                    docker("stop", container_id)
                    docker("rm", "-v", container_id)
                    info["container_removed"] = True


@contextmanager
def _store(workdir, prefix):
    with ExitStack() as stack:
        stack.enter_context(patch.object(service, "DISPATCH_DATABASE_URL", str(workdir / "cases.sqlite3")))
        stack.enter_context(patch.object(service, "RUNS_FILE", workdir / "runs.jsonl"))
        stack.enter_context(patch.object(service, "_new_run_id", lambda: prefix + uuid.uuid4().hex))
        stack.enter_context(patch.dict(os.environ, {"KG_SYNC_ENABLED": "0"}))
        yield


def _cleanup_local(workdir, prefix, ids):
    path, archive = workdir / "cases.sqlite3", workdir / "runs.jsonl"
    remaining = []
    if archive.exists():
        # Parse everything first; malformed evidence is never silently discarded.
        remaining = [line for line in archive.read_text(encoding="utf-8").splitlines()
                     if line.strip() and json.loads(line)["run_id"] not in ids]
    if path.exists():
        with sqlite3.connect(path) as db:
            rows = db.execute("SELECT run_id FROM case_registrations WHERE registration_id LIKE ?", (prefix + "%",)).fetchall()
            if any(rid not in ids or not rid.startswith(prefix) for (rid,) in rows):
                raise ValueError("cleanup identity ownership mismatch")
            marks = ",".join("?" for _ in ids)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ["case_workflows", "case_graph_outbox", "case_registrations"]:
                if ids and table in tables:
                    db.execute(f"DELETE FROM {table} WHERE run_id IN ({marks})", tuple(ids))
    if archive.exists():
        staged = workdir / "runs.cleanup.tmp"
        staged.write_text("".join(line + "\n" for line in remaining), encoding="utf-8")
        staged.replace(archive)


def _cleanup(driver, workdir, prefix):
    originals, _ = read_case_originals(workdir / "cases.sqlite3", legacy_file=workdir / "runs.jsonl")
    owned = [r for r in originals if str(r.get("registration_id", "")).startswith(prefix)]
    ids = {r["run_id"] for r in owned}
    if any(not rid.startswith(prefix) for rid in ids):
        raise ValueError("cleanup namespace mismatch")
    for rid in sorted(ids):
        _delete_case(driver, rid, prefix)
    # SQL cleanup only after graph cleanup succeeds. A failure preserves the
    # isolated recovery source; it is never reported as a successful evaluation.
    _cleanup_local(workdir, prefix, ids)
    after, states = read_case_originals(workdir / "cases.sqlite3", legacy_file=workdir / "runs.jsonl")
    if any(r["run_id"] in ids for r in after) or any(rid in states for rid in ids):
        raise RuntimeError("evaluation storage cleanup incomplete")
    return {"status": "complete", "cases_removed": len(ids), "sql_outbox_archive_cleared": True}


def _scenarios(limit: int | None) -> list[dict]:
    with SCENARIOS.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[:limit] if limit else rows


def _reg_ids(evidence: list) -> set[str]:
    return {e["node_id"] for e in evidence if e["node_type"] == "Regulation"}


def _sop_ids(evidence: list) -> set[str]:
    return {e["node_id"] for e in evidence if e["node_type"] == "SOP"}


def _evaluate(args, prefix, progress=None):
    scenarios = _scenarios(args.limit)
    failures: list[dict] = []
    closed: list[dict] = []
    progress = progress if progress is not None else {}
    progress.update(checks_run=0, checks_failed=0, created_cases=closed, failures=failures)

    checks_run = 0
    def check(ok: bool, kind: str, detail: str, run_id: str | None = None) -> None:
        nonlocal checks_run
        checks_run += 1
        progress["checks_run"] = checks_run
        if not ok:
            failures.append({"check": kind, "detail": detail, "run_id": run_id})
            progress["checks_failed"] = len(failures)

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
        record = service.close_case(event, None, remark=f"qa-eval {row['scenario_id']}",
                                    registration_id=prefix + row["scenario_id"])
        run_id = record["run_id"]
        closed.append({"scenario_id": row["scenario_id"], "run_id": run_id,
                       "rule_no": record["rule_no"],
                       "disposition": record["disposition"]})

        rule_no = record["rule_no"]
        expected_regs = set(RULE_TO_REGULATIONS.get(rule_no, []))
        expected_sops = set(RULE_TO_SOPS.get(rule_no, []))

        why = service.qa_view(QAIn(question_type="why_disposition", run_id=run_id))
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

        chain = service.qa_view(QAIn(question_type="audit_chain", run_id=run_id))
        pairs = {(e["node_type"], e["node_id"]) for e in chain["evidence"]}
        check(chain["status"] == "ok", "audit_status",
              f"{row['scenario_id']}: status={chain['status']}", run_id)
        check(("ExcursionEvent", run_id) in pairs and
              ("Disposition", record["disposition"]) in pairs, "audit_chain",
              f"{row['scenario_id']}: event/disposition missing from the chain", run_id)

        cause = service.qa_view(QAIn(question_type="cause_context", run_id=run_id))
        check(cause["status"] == "ok" and str(row["stage"]) in cause["answer"],
              "cause_context", f"{row['scenario_id']}: status={cause['status']}", run_id)

    # ---- 3: product-threshold parity ---------------------------------------
    products = json.loads(CONFIG.read_text(encoding="utf-8"))["products"]
    for cfg in products:
        pid = cfg["product_id"]
        got = service.qa_view(QAIn(question_type="product_requirements", product_id=pid))
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
    none_case = service.qa_view(QAIn(question_type="why_disposition", run_id=unknown))
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

    report = {
        "status": "failed" if failures else "passed",
        "evaluation_type": "derived_contract_checks_not_domain_or_intent_accuracy",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios": len(scenarios),
        "checks_run": checks_run,
        "checks_failed": len(failures),
        "failures": failures,
        "dispositions": {d: sorted(r) for d, r in groups.items()},
        "dispositions_with_multiple_rules": mixed,
        "cases_kept_in_graph": bool(args.keep),
        "created_cases": closed,
        "not_measured": "intent-classification accuracy (needs data/qa/intent_labels.csv, human-labelled)",
    }
    return report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, help="positive scenario limit")
    ap.add_argument("--keep", action="store_true", help="retain own graph and isolated SQL/JSONL")
    ap.add_argument("--configured-test-graph", action="store_true", help="explicitly use a dedicated, seeded test graph resolved by NEO4J_*; never reseed it")
    ap.add_argument("--image", help="installed Neo4j 5 image (default: reuse local image)")
    ap.add_argument("--workdir", type=Path, help="NEW evaluation directory; existing paths refused")
    ap.add_argument("--report", type=Path, help="NEW report file (default: workdir/report.json)")
    args = ap.parse_args(argv[1:])
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be positive")
    if args.report and args.report.exists():
        ap.error("report already exists; choose a new path")
    workdir = (args.workdir or Path(tempfile.mkdtemp(prefix="pharma-qa-eval-")) / "evaluation").resolve()
    if workdir.exists():
        ap.error("workdir already exists; choose a new directory")
    workdir.mkdir(parents=True)
    prefix = "RQAEVAL-" + uuid.uuid4().hex + "-"
    report = {"status": "error", "checks_run": 0, "checks_failed": 0}
    graph, cleanup = {}, {"status": "not_started"}
    with _store(workdir, prefix):
        try:
            with _graph(args, graph) as driver:
                try:
                    report = _evaluate(args, prefix, report)
                finally:
                    originals, _ = read_case_originals(workdir / "cases.sqlite3", legacy_file=workdir / "runs.jsonl")
                    manifest = [r for r in originals if str(r.get("registration_id", "")).startswith(prefix)]
                    (workdir / "cases.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                    cleanup = {"status": "retained"} if args.keep else _cleanup(driver, workdir, prefix)
        except Exception as exc:
            report.update(status="error", error_type=type(exc).__name__)
            if cleanup["status"] == "not_started":
                cleanup = {"status": "incomplete_or_no_graph", "evidence_retained": True}
    report.update(workdir=str(workdir), evaluation_prefix=prefix, graph=graph, cleanup=cleanup)
    destination = args.report or workdir / "report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps({k: report[k] for k in ["status", "checks_run", "checks_failed", "cleanup"]}))
    print(f"report: {destination}")
    return 2 if report["status"] == "error" else 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
