"""Drain the durable graph outbox without re-evaluating any case.

Environment: DATABASE_URL, CASE_RUNS_FILE, NEO4J_URI/USER/PASSWORD.
--legacy imports existing JSONL originals. --rebuild requeues previously
synced records after a deliberate static graph rebuild. Neither deletes data.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from api import service
from optimisation.case_repository import enqueue_graph_records, requeue_graph_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--force", action="store_true", help="bypass failure backoff, not active leases")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if args.legacy and service.RUNS_FILE.exists():
        records = {}
        for line in service.RUNS_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)  # malformed legacy input fails visibly; never silently omitted
            records.setdefault(record["run_id"], record)
        enqueue_graph_records(service.DISPATCH_DATABASE_URL, records.values())
    if args.rebuild:
        print(f"Requeued {requeue_graph_records(service.DISPATCH_DATABASE_URL)} synced records")
    try:
        while True:
            result = service.sync_case_graph(limit=args.limit, force=args.force)
            print(json.dumps(result), flush=True)
            if not args.watch:
                return 0 if result["queue"]["pending"] + result["queue"]["processing"] == 0 else 1
            time.sleep(15)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
