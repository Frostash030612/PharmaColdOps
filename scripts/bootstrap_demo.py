"""Initialize ONLY a fresh deployment graph; never rebuild an existing graph.

An existing graph must have our matching seed fingerprint. Migrations/rebuilds
are explicit separate operations. SQLite is authoritative; fresh graph recovery
audits and replays only missing, non-conflicting case chains.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api import service
from knowledge_graph.connect import get_driver
from knowledge_graph.schema import ensure_constraints
from knowledge_graph.build_graph import load_static, load_facility_links, load_real_shipments
from knowledge_graph.coverage import audit_cases
from ml.runtime import model_info
from optimisation.case_action_guard import case_action_guard
from optimisation.dispatch_repository import ensure_schema
from optimisation.case_repository import read_case_originals, enqueue_graph_records, requeue_graph_records


def seed_fingerprint():
    paths = ["src/rule_engine/rules_config.json", "src/knowledge_graph/build_graph.py",
             "data/optimisation/singapore/network.json",
             "data/ml/cold-chain-silent-failure/shipment-sensor-dataset.csv"]
    values = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def seed_graph(driver, fingerprint):
    count = driver.execute_query("MATCH (n) RETURN count(n) AS n").records[0]["n"]
    if count:
        markers = driver.execute_query("MATCH (n:DeploymentSeed {id:'demo-v1'}) RETURN n.sha256 AS sha").records
        if len(markers) != 1 or markers[0]["sha"] != fingerprint:
            raise RuntimeError("nonempty or changed graph without matching deployment seed; refused to clear/reseed")
        return "existing_matching_seed"
    ensure_constraints(driver)
    # load_static clears nodes, therefore ONLY invoke after the empty-graph guard.
    load_static(driver)
    load_facility_links(driver)
    load_real_shipments(driver)
    driver.execute_query("CREATE (:DeploymentSeed {id:'demo-v1',sha256:$sha})", sha=fingerprint)
    return "initialized_empty_graph"


def recover_missing_cases():
    records, states = read_case_originals(service.DISPATCH_DATABASE_URL, legacy_file=service.RUNS_FILE)
    if not records:
        return 0
    before = audit_cases(records, states)
    if before["status"] == "unavailable":
        raise RuntimeError("graph coverage audit unavailable")
    eligible = {c["run_id"] for c in before["cases"] if c["repairable"]}
    if any(c["coverage"] != "complete" and not c["repairable"] for c in before["cases"]):
        raise RuntimeError("conflicting case graph requires manual review; refused overwrite")
    enqueue_graph_records(service.DISPATCH_DATABASE_URL, [r for r in records if r["run_id"] in eligible])
    requeue_graph_records(service.DISPATCH_DATABASE_URL, run_ids=sorted(eligible))
    for rid in sorted(eligible):
        service.sync_case_graph(run_id=rid, limit=1, force=True)
    records, states = read_case_originals(service.DISPATCH_DATABASE_URL, legacy_file=service.RUNS_FILE)
    if audit_cases(records, states)["status"] != "passed":
        raise RuntimeError("case replay incomplete")
    return len(eligible)


def main():
    password = os.environ.get("NEO4J_PASSWORD", "")
    if len(password) < 12 or password == "CHANGE_ME_BEFORE_START":
        raise RuntimeError("configure a unique deployment password first")
    if any(model_info(task)["status"] != "ready" for task in ["risk", "cause"]):
        raise RuntimeError("trusted M4 models missing/incompatible; build/train before starting")
    ensure_schema(service.DISPATCH_DATABASE_URL)
    service.RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with case_action_guard(service.DISPATCH_DATABASE_URL):
        with get_driver() as driver:
            mode = seed_graph(driver, seed_fingerprint())
        replayed = recover_missing_cases()
    print(json.dumps({"status": "ready", "graph_mode": mode, "cases_replayed": replayed}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Never print DB connection strings or credentials.
        print(f"Bootstrap failed ({type(exc).__name__}); inspect configuration/seed compatibility. No automatic graph reset.", file=sys.stderr)
        raise SystemExit(1)
