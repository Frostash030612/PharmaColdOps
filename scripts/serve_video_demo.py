"""Fresh, loopback-only recording environment; never seed the active demo graph.

Requires Docker and the evaluation environment. Owns only the graph container
created by evaluate_qa._graph and its two child process groups. Create the
output's STOP file (or Ctrl-C) to stop it; recordings and case evidence remain.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_qa as qa
from verify_graph_recovery import available_port
from check_deployed_v2_shadow import inventory

IMAGE = "neo4j@sha256:d9cfe82983d27f5a75b3aaae8f316d04f9a698a3b7f6103a508f7caf8362f255"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=int, default=7200)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "data/processed") or output.exists():
        parser.error("use a fresh directory under data/processed; preserve previous captures")
    if not 60 <= args.max_seconds <= 14400:
        parser.error("max-seconds must be between 60 and 14400")
    output.mkdir(parents=True)
    children, logs, info = [], [], {}
    result = {"status": "starting", "scope": "isolated simulated recording, not human review or business data"}
    baseline = inventory("http://127.0.0.1:8080")
    (output / "live-before.json").write_text(json.dumps(baseline), encoding="utf-8")
    try:
        with qa._graph(SimpleNamespace(configured_test_graph=False, image=IMAGE, keep=False), info) as graph:
            from knowledge_graph.build_graph import load_facility_links
            load_facility_links(graph)
            api_port, ui_port = available_port(), available_port()
            api, ui = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"
            runtime = {**os.environ, "NEO4J_URI": info["uri"], "NEO4J_USER": "neo4j",
                       "NEO4J_PASSWORD": "isolated-qa-demo", "KG_SYNC_ENABLED": "1",
                       "DATABASE_URL": str(output / "recording.sqlite3"),
                       "CASE_RUNS_FILE": str(output / "recording.jsonl"),
                       "CORS_ORIGINS": ui, "EVENT_V2_SHADOW_ENABLED": "0", "LOKY_MAX_CPU_COUNT": "1"}
            commands = [([sys.executable, "-m", "uvicorn", "--app-dir", "src", "api.main:app",
                          "--host", "127.0.0.1", "--port", str(api_port)], "api"),
                        (["pnpm", "--dir", "frontend-vue", "dev", "--host", "127.0.0.1",
                          "--port", str(ui_port), "--strictPort"], "ui")]
            try:
                for command, name in commands:
                    log = (output / (name + ".log")).open("x", encoding="utf-8")
                    logs.append(log)
                    children.append(subprocess.Popen(command, cwd=ROOT, env=runtime, stdout=log,
                                                     stderr=subprocess.STDOUT, start_new_session=True))
                with httpx.Client(timeout=10) as client:
                    for url in [api + "/api/health", ui]:
                        deadline = time.monotonic() + 60
                        while True:
                            try:
                                if client.get(url).status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            if time.monotonic() > deadline or any(p.poll() is not None for p in children):
                                raise RuntimeError("recording service did not become healthy")
                            time.sleep(.25)
                    cases = client.get(api + "/api/runs").json()["runs"]
                    if cases:
                        raise RuntimeError("fresh recording store unexpectedly contains cases")
                record = {"api": api, "ui": ui, "url": ui + "/?lang=en&api=" + api,
                          "simulated": True, "business_writes_only_in_recording_instance": True}
                (output / "runtime.json").write_text(json.dumps(record), encoding="utf-8")
                print("RECORDING_READY " + json.dumps(record), flush=True)
                deadline = time.monotonic() + args.max_seconds
                while not (output / "STOP").exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError("recording environment expired")
                    if any(p.poll() is not None for p in children):
                        raise RuntimeError("recording child process exited")
                    time.sleep(.25)
                result["status"] = "stopped"
            finally:
                for process in children:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                for log in logs:
                    log.close()
        after = inventory("http://127.0.0.1:8080")
        result["active_demo_records_and_models_unchanged"] = baseline == after
        (output / "live-after.json").write_text(json.dumps(after), encoding="utf-8")
        if baseline != after:
            raise RuntimeError("active demo inventory changed while recording; inspect before/after")
    except BaseException as error:
        result.update(status="failed", error=str(error))
        raise
    finally:
        result["graph"] = info
        (output / "environment-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
