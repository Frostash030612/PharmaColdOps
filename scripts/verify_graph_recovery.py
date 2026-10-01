"""Real stop/restart acceptance, using ONLY a container created by this script.

Creates its own Neo4j, API, SQLite and JSONL. Never stops an existing project
container, rebuilds the project graph or calls manual graph sync to recover.
Requires Docker and project Python dependencies. Evidence survives cleanup.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def await_graph(uri, password, *, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with GraphDatabase.driver(uri, auth=("neo4j", password), connection_timeout=2,
                                     connection_acquisition_timeout=3, max_transaction_retry_time=3) as driver:
                driver.verify_connectivity()
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError("isolated Neo4j did not become reachable")


def verify(output, image):
    output.mkdir(parents=True, exist_ok=False)
    container_id, api = None, None
    log = (output / "api.log").open("w", encoding="utf-8")
    try:
        password = "isolated-recovery-demo"
        graph_port = available_port()
        container_id = docker("run", "-d", "--name", "pharmacoldops-kg-check-" + uuid.uuid4().hex[:10],
            "--memory", "768m", "-p", f"127.0.0.1:{graph_port}:7687", "-e", "NEO4J_AUTH=neo4j/" + password,
            "-e", "NEO4J_server_memory_heap_initial__size=128m",
            "-e", "NEO4J_server_memory_heap_max__size=256m",
            "-e", "NEO4J_server_memory_pagecache_size=64m", image)
        port = docker("port", container_id, "7687/tcp").rsplit(":", 1)[1]
        uri = "bolt://127.0.0.1:" + port
        await_graph(uri, password)
        env = {**os.environ, "DATABASE_URL": str(output / "dispatch.sqlite3"),
            "CASE_RUNS_FILE": str(output / "runs.jsonl"), "NEO4J_URI": uri,
            "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": password, "KG_SYNC_ENABLED": "1"}
        with (output / "seed.log").open("w", encoding="utf-8") as seed_log:
            subprocess.run([sys.executable, "-m", "src.knowledge_graph.build_graph"], cwd=ROOT,
                           env=env, stdout=seed_log, stderr=subprocess.STDOUT, check=True, timeout=60)
        base = "http://127.0.0.1:" + str(available_port())
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "--app-dir", "src", "api.main:app",
            "--host", "127.0.0.1", "--port", base.rsplit(":", 1)[1]], cwd=ROOT,
            env=env, stdout=log, stderr=subprocess.STDOUT)
        with httpx.Client(base_url=base, timeout=30) as client:
            deadline = time.monotonic() + 15
            while True:
                if api.poll() is not None: raise RuntimeError("isolated API exited")
                try:
                    if client.get("/api/health").status_code == 200: break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline: raise RuntimeError("isolated API did not start")
                time.sleep(.2)
            docker("stop", container_id)
            payload = {"registration_id": "real-outage", "product_id": "vaccine_2_8",
                "excursion_temp_c": 20, "duration_min": 90, "mkt_c": 19, "packaging": "intact",
                "stage": "transit", "facility_id": "D-HOUGANG", "destination_facility_id": "H-NUH",
                "started_at": "2026-10-01T09:00:00", "remark": "isolated actual graph outage"}
            response = client.post("/api/case_close", json=payload)
            assert response.status_code == 200, response.text
            original = response.json()
            rid = original["run_id"]
            first_queue = client.get("/api/graph-sync").json()
            assert first_queue["pending"] == 1 and first_queue["synced"] == 0, first_queue
            pending_qa = client.post("/api/qa", json={"question_type": "audit_chain", "run_id": rid})
            assert pending_qa.status_code == 503
            docker("start", container_id)
            await_graph(uri, password)
            deadline = time.monotonic() + 45
            while True:
                queue = client.get("/api/graph-sync").json()
                if queue["synced"] == 1 and queue["pending"] == queue["processing"] == 0: break
                if time.monotonic() > deadline: raise RuntimeError("automatic retry did not drain outbox")
                time.sleep(1)
            # No manual sync invocation occurred above: lifespan worker recovered.
            repeated = client.post("/api/case_close", json=payload)
            assert repeated.status_code == 200 and repeated.json()["run_id"] == rid
            assert repeated.json()["disposition"] == original["disposition"]
            assert repeated.json()["graph_evidence"] == original["graph_evidence"]
            assert client.get("/api/runs").json()["count"] == 1
            qa = client.post("/api/qa", json={"question_type": "audit_chain", "run_id": rid})
            assert qa.status_code == 200 and qa.json()["status"] == "ok", qa.text
            evidence = {(e["node_type"], e["node_id"]) for e in qa.json()["evidence"]}
            assert {("Facility", "D-HOUGANG"), ("Facility", "H-NUH"), ("ReshipmentOrder", "RO-" + rid)} <= evidence
            with GraphDatabase.driver(uri, auth=("neo4j", password)) as driver:
                count = driver.execute_query("MATCH (e:ExcursionEvent {run_id:$id}) RETURN count(e) AS n", id=rid).records[0]["n"]
                orders = driver.execute_query("MATCH (r:ReshipmentOrder {order_id:$id}) RETURN count(r) AS n", id="RO-" + rid).records[0]["n"]
            assert count == orders == 1
            subprocess.run([sys.executable, "scripts/check_case_graph.py", "--report", str(output / "coverage.json")],
                           cwd=ROOT, env=env, check=True, timeout=30)
            report = {"status": "passed", "actual_stop_restart": True, "automatic_recovery": True,
                "outage_registration_http": response.status_code, "pending_qa_http": pending_qa.status_code,
                "first_queue": first_queue, "recovered_queue": queue, "run_id": rid,
                "same_identity_retry": True, "graph_event_count": count, "reshipment_count": orders,
                "qa": qa.json()}
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report
    finally:
        if api:
            api.terminate()
            try: api.wait(timeout=10)
            except subprocess.TimeoutExpired:
                api.kill(); api.wait(timeout=5)
        log.close()
        if container_id:
            # Immutable ID returned by OUR successful creation, never a user name.
            subprocess.run(["docker", "stop", container_id], stdout=subprocess.DEVNULL, check=False, timeout=40)
            with (output / "neo4j.log").open("w", encoding="utf-8") as graph_log:
                subprocess.run(["docker", "logs", container_id], stdout=graph_log, stderr=subprocess.STDOUT, check=False, timeout=15)
            (output / "container-state.json").write_text(docker("inspect", container_id, "--format", "{{json .State}}"), encoding="utf-8")
            subprocess.run(["docker", "rm", "-v", container_id], stdout=subprocess.DEVNULL, check=False, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="neo4j:5-community")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (args.output or Path(tempfile.mkdtemp(prefix="pharma-kg-outage-")) / "acceptance").resolve()
    try:
        verify(output, args.image)
    except Exception as exc:
        print(f"FAIL ({type(exc).__name__}: {exc}); evidence retained at {output}", file=sys.stderr)
        return 1
    print(f"PASS: real outage, automatic recovery, idempotent retry, full QA; {output / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
