"""Audit actual graph coverage. Default mode performs no SQL/Neo4j writes.

--repair replays only missing/incomplete, non-conflicting case chains. Never
clears a graph or deletes extra evidence. DATABASE_URL / CASE_RUNS_FILE /
NEO4J_* choose the same stores as the API. --report refuses to overwrite.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from api import service
from knowledge_graph.coverage import audit_cases
from optimisation.case_repository import read_case_originals, enqueue_graph_records, requeue_graph_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("report already exists; use a new path")
    try:
        records, states = read_case_originals(service.DISPATCH_DATABASE_URL, legacy_file=service.RUNS_FILE)
        result = audit_cases(records, states)
        if args.repair:
            eligible = {c["run_id"] for c in result["cases"] if c["repairable"]}
            enqueue_graph_records(service.DISPATCH_DATABASE_URL, [r for r in records if r["run_id"] in eligible])
            requeue_graph_records(service.DISPATCH_DATABASE_URL, run_ids=sorted(eligible))
            for rid in sorted(eligible):
                service.sync_case_graph(run_id=rid, limit=1, force=True)
            records, states = read_case_originals(service.DISPATCH_DATABASE_URL, legacy_file=service.RUNS_FILE)
            before = result
            result = {**audit_cases(records, states), "repair_attempted": len(eligible), "before_coverage": before["coverage"]}
    except Exception as exc:
        # Do not expose auth connection strings in generated reports.
        result = {"status": "unavailable", "error_type": type(exc).__name__}
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as file:
            file.write(payload + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
