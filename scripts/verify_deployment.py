"""Real HTTP/restart/outage/backup-restore acceptance in TWO OWN Compose projects.

Never operates on an existing project, native volume or host runtime database.
Build separately, or pass --build. Default cleans only resources labelled with
the generated project IDs. Outputs preserve evidence; passwords never printed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/compose.demo.yml"


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, path, body=None, expected=200, headers=None):
    payload = json.dumps(body).encode() if body is not None else None
    req = Request(base + path, data=payload, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        response = urlopen(req, timeout=25)
    except HTTPError as exc:
        response = exc
    with response:
        content = response.read().decode("utf-8")
        if response.status != expected:
            raise RuntimeError(f"HTTP acceptance failed: {path} returned {response.status}, expected {expected}")
        value = json.loads(content) if "application/json" in response.headers.get("Content-Type", "") else content
        return value, dict(response.headers)


def wait(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, URLError, RuntimeError):
            pass
        time.sleep(1)
    raise RuntimeError("deployment dependency recovery timed out")


def verify(output, *, build=False, image="pharmacoldops-demo:local"):
    output.mkdir(parents=True, exist_ok=False)
    project = "pharmacoldops-verify-" + uuid.uuid4().hex[:10]
    projects = [project, project + "-restore"]
    password = secrets.token_hex(24)
    endpoints = {p: "http://127.0.0.1:" + str(port()) for p in projects}
    env_files = {}
    for p in projects:
        path = output / (p + ".env")
        with path.open("x", encoding="utf-8") as stream:
            stream.write(f"NEO4J_PASSWORD={password}\nDEMO_PORT={endpoints[p].rsplit(':',1)[1]}\nDEMO_BIND_ADDRESS=127.0.0.1\nDEMO_IMAGE={image}\n")
        path.chmod(0o600)
        env_files[p] = path
    logs = output / "compose.log"
    snapshot_volume = project + "_snapshots"
    export_container = project + "-snapshot-export"
    checks = []
    report = {"status": "running", "owned_projects": projects, "checks": checks, "cleanup": {},
              "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in [COMPOSE, ROOT / "Dockerfile", ROOT / "requirements-runtime.lock.txt", Path(__file__)]}}
    (output / "ownership.json").write_text(json.dumps(report, indent=2))

    def compose(p, *args):
        # Environment overrides only our explicit configuration; never inherit
        # COMPOSE_PROJECT_NAME, DATABASE_URL or a user's deployment password.
        env = {k: v for k, v in os.environ.items() if k not in
               {"COMPOSE_PROJECT_NAME", "NEO4J_PASSWORD", "DEMO_PORT", "DEMO_BIND_ADDRESS", "DEMO_IMAGE", "NEO4J_IMAGE"}}
        command = ["docker", "compose", "--env-file", str(env_files[p]), "-p", p, "-f", str(COMPOSE), *args]
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
        with logs.open("a", encoding="utf-8") as stream:
            stream.write(result.stdout.replace(password, "[REDACTED]"))
        if result.returncode:
            raise RuntimeError("owned Compose operation failed; see redacted compose.log")
        return result.stdout

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
        print("PASS", name, flush=True)

    def up(p):
        compose(p, "up", "-d", "--no-build", "--wait", "--wait-timeout", "180")

    try:
        compose(project, "config", "--quiet")
        if build:
            compose(project, "build", "api")
        report["application_image_id"] = subprocess.check_output(
            ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
        up(project)
        base = endpoints[project]
        get = lambda path: request(base, path)[0]
        html = get("/")
        check("built frontend served", isinstance(html, str) and '<div id="app"' in html)
        asset = re.search(r'src="([^"]+\.js)"', html).group(1)
        script = get("/" + asset.removeprefix("./").lstrip("/"))
        check("frontend same-origin default built", "same-origin" in script)
        check("readiness checks dependencies", get("/api/ready")["status"] == "ready")
        _, headers = request(base, "/api/health", headers={"Origin": "https://untrusted.example"})
        check("cross-origin wildcard disabled", not any(k.lower() == "access-control-allow-origin" for k in headers))
        models = get("/api/ml/models")
        check("both regenerated serving models available", all(models[t]["status"] == "ready" for t in ["risk", "cause"]))
        report["serving_models"] = {t: {k: models[t][k] for k in ["model_id", "model_sha256", "algorithm"]} for t in models}
        for task in ["risk", "cause"]:
            sample = get("/api/ml/samples/" + task)["samples"][0]
            inference, _ = request(base, "/api/ml/predict", {"task": task, "source": "dataset_sample", **sample})
            check(task + " actual inference", inference["status"] == "predicted" and inference["advisory_only"])
        event = {"registration_id": "DEPLOY-CASE-1", "product_id": "vaccine_2_8", "excursion_temp_c": 5,
                 "duration_min": 5, "mkt_c": 5, "packaging": "intact", "stage": "transit",
                 "facility_id": "W-WESTGATE", "destination_facility_id": "H-NUH"}
        first, _ = request(base, "/api/case_close", event)
        rid = first["run_id"]
        repeat, _ = request(base, "/api/case_close", event)
        check("registration retry idempotent", repeat["run_id"] == rid)
        qa, _ = request(base, "/api/qa", {"question_type": "audit_chain", "run_id": rid})
        check("actual case graph query", qa["status"] == "ok")
        batch = get("/api/dispatch/daily-orders?hospitals=3&seed=42")
        plan_body = dict(batch["plan"])
        plan_body.update(dispatch_id="DEPLOY-PLAN", command_id="deploy-create", algorithm="greedy")
        planned, _ = request(base, "/api/dispatch/runs", plan_body)
        check("dispatch state created over HTTP", planned["dispatch_id"] == "DEPLOY-PLAN")
        compose(project, "restart", "api")
        wait(lambda: get("/api/ready")["status"] == "ready")
        check("cases survive actual API restart", any(r["run_id"] == rid for r in get("/api/runs")["runs"]))
        check("dispatch survives actual API restart", get("/api/dispatch/runs/DEPLOY-PLAN")["version"] == planned["version"])
        check("model snapshots unchanged on restart", get("/api/ml/models")["risk"]["model_id"] == models["risk"]["model_id"])
        compose(project, "stop", "neo4j")
        check("liveness independent of graph outage", get("/api/health")["status"] == "ok")
        check("readiness refuses actual graph outage", request(base, "/api/ready", expected=503)[0]["status"] == "not_ready")
        event["registration_id"] = "DEPLOY-CASE-OUTAGE"
        pending, _ = request(base, "/api/case_close", event)
        check("registration retained during graph outage", get("/api/graph-sync")["pending"] >= 1)
        request(base, "/api/qa", {"question_type": "audit_chain", "run_id": pending["run_id"]}, expected=503)
        checks.append("QA refuses unavailable graph")
        compose(project, "start", "neo4j")
        wait(lambda: get("/api/ready")["status"] == "ready")
        wait(lambda: get("/api/graph-sync")["pending"] == get("/api/graph-sync")["processing"] == 0)
        recovered, _ = request(base, "/api/qa", {"question_type": "audit_chain", "run_id": pending["run_id"]})
        check("automatic outbox recovery after graph start", recovered["status"] == "ok")
        compose(project, "stop", "api")
        snapshots = output / "snapshots"
        snapshots.mkdir()
        subprocess.run(["docker", "volume", "create", "--label", "pharmacoldops.owner=" + project,
                        snapshot_volume], check=True, capture_output=True, text=True)
        volume = snapshot_volume + ":/snapshots"
        compose(project, "run", "-T", "--interactive=false", "--rm", "--no-deps", "--user", "0:0", "--entrypoint", "python", "-v", volume,
                "api", "scripts/runtime_snapshot.py", "backup", "--source", "/runtime/audit", "--output", "/snapshots/first", "--quiesced")
        subprocess.run(["docker", "create", "--name", export_container, "--mount",
                        "type=volume,source=" + snapshot_volume + ",target=/snapshots,readonly", image,
                        "python", "-c", "pass"], check=True, capture_output=True, text=True)
        subprocess.run(["docker", "cp", export_container + ":/snapshots/first", str(snapshots)], check=True)
        check("quiesced database/archive backup created", (snapshots / "first/manifest.json").is_file())
        restored_project = projects[1]
        compose(restored_project, "run", "-T", "--interactive=false", "--rm", "--no-deps", "--user", "0:0", "--entrypoint", "python", "-v", volume,
                "api", "scripts/runtime_snapshot.py", "restore", "--snapshot", "/snapshots/first", "--target", "/runtime/audit")
        up(restored_project)
        restored_base = endpoints[restored_project]
        restored_get = lambda path: request(restored_base, path)[0]
        restored_ids = {r["run_id"] for r in restored_get("/api/runs")["runs"]}
        check("both original assessments restored to fresh volume", {rid, pending["run_id"]} <= restored_ids)
        check("dispatch version restored to fresh volume", restored_get("/api/dispatch/runs/DEPLOY-PLAN")["version"] == planned["version"])
        for case_id in [rid, pending["run_id"]]:
            value, _ = request(restored_base, "/api/qa", {"question_type": "audit_chain", "run_id": case_id})
            check("fresh graph case replay " + case_id, value["status"] == "ok")
        check("restored queue fully confirmed", restored_get("/api/graph-sync")["pending"] == restored_get("/api/graph-sync")["processing"] == 0)
        for p in projects:
            report.setdefault("image_ids", {})[p] = compose(p, "images", "--format", "json").strip()
        report.update(status="passed", check_count=len(checks), recovered_case_ids=sorted(restored_ids))
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="failed", failure_type=type(exc).__name__, check_count=len(checks))
        for p in projects:
            try:
                compose(p, "logs", "--no-color", "--tail", "80")
            except Exception:
                pass
        raise
    finally:
        subprocess.run(["docker", "rm", export_container], capture_output=True, text=True)
        for p in reversed(projects):
            try:
                compose(p, "down", "--volumes", "--remove-orphans")
                report["cleanup"][p] = "removed_owned_project_and_volumes"
            except Exception:
                report["cleanup"][p] = "failed_preserved_for_inspection"
                report["status"] = "failed"
        removed = subprocess.run(["docker", "volume", "rm", snapshot_volume], capture_output=True, text=True)
        if removed.returncode and "no such volume" not in removed.stderr.lower():
            report["status"] = "failed"
            report["cleanup"][snapshot_volume] = "failed_preserved_for_inspection"
        else:
            report["cleanup"][snapshot_volume] = "removed_owned_snapshot_volume"
        (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--image", default="pharmacoldops-demo:local")
    args = parser.parse_args()
    try:
        report = verify(args.output, build=args.build, image=args.image)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Deployment acceptance failed ({type(exc).__name__}); partial evidence retained, no native resources touched")
        return 1
    print(f"{report['status']}: {report['check_count']} checks; {args.output / 'report.json'}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
