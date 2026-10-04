"""Loopback-only read-only live update acceptance; NEVER register test cases."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_base(base):
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("explicit loopback HTTP endpoint only")


def request(base, path, body=None):
    req = Request(base.rstrip("/") + path, data=json.dumps(body, allow_nan=False).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        value = response.read().decode()
        return json.loads(value) if "application/json" in response.headers.get("Content-Type", "") else value


def inventory(base):
    models = request(base, "/api/ml/models")
    return {"models": {task: {k: models[task][k] for k in ["status", "model_id", "model_sha256"]} for task in ["risk", "cause"]},
        "case_response": request(base, "/api/runs?limit=200"), "dispatch_response": request(base, "/api/dispatch/runs?limit=200")}


def check(base, baseline):
    validate_base(base)
    before = inventory(base)
    if before != baseline["inventory"]: raise ValueError("existing cases/dispatch/model identities differ from preserved baseline")
    checks = []
    ready = request(base, "/api/ready")
    if ready["status"] != "ready" or ready["checks"].get("event_v2_shadow") != "ready": raise ValueError("shadow readiness missing")
    checks.append("all dependencies including shadow ready")
    info = request(base, "/api/ml/event/v2/info")
    if info["status"] != "shadow_ready" or info["feature_count"] != 111 or info["automatic_actions_allowed"] is not False or info["review_required"] is not True:
        raise ValueError("shadow contract missing")
    checks.append("independent 111-feature shadow contract")
    html = request(base, "/")
    asset = re.search(r'src="([^"]+\.js)"', html).group(1)
    asset = "/" + asset.removeprefix("./").lstrip("/")
    if not asset.startswith("/assets/"): raise ValueError("same-origin built asset required")
    script = request(base, asset)
    if "event_v2_context" not in script or "same-origin" not in script: raise ValueError("updated same-origin v2 frontend missing")
    checks.append("new frontend served with same-origin API")
    samples = request(base, "/api/ml/event/v2/samples")["samples"]
    results = []
    for sample in samples:
        if set(sample) != {"sample_id", "role", "observation"}: raise ValueError("private sample fields exposed")
        value = request(base, "/api/ml/event/v2/assess", {"observation": sample["observation"]})
        if (value["status"] not in {"candidate_only", "abstained"} or value["model_sha256"] != info["model_sha256"]
            or value["policy_sha256"] != info["policy_sha256"] or value["review_required"] is not True or value["automatic_actions_allowed"] is not False):
            raise ValueError("inference or review authority mismatch")
        results.append({"sample_id": sample["sample_id"], "status": value["status"], "candidates": value["candidates"],
                        "scores": value["scores"], "observation_sha256": value["observation_sha256"]})
    checks.append("all public demo samples inferred without automatic actions")
    after = inventory(base)
    if before != after: raise ValueError("read-only checks altered live records")
    checks += ["old M4 model identities preserved", "case and dispatch responses unchanged before/after"]
    return {"status": "passed", "base": base, "checks": checks, "shadow": info, "samples_checked": len(results),
        "statuses": {status: sum(r["status"] == status for r in results) for status in ["candidate_only", "abstained"]},
        "results_sha256": stable(results), "case_response_sha256": stable(after["case_response"]),
        "dispatch_response_sha256": stable(after["dispatch_response"]), "old_models": after["models"],
        "scope": "live update/read-only synthetic demo replay, not new model accuracy or clinical authority"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--capture-before", action="store_true")
    args = parser.parse_args()
    if args.report.exists(): parser.error("fresh report required")
    validate_base(args.base)
    if args.capture_before:
        value = {"schema": "v2-live-update-baseline-v1", "status": "captured", "inventory": inventory(args.base)}
    else:
        if args.baseline is None: parser.error("preserved baseline required")
        value = check(args.base, json.loads(args.baseline.read_text()))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream: json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    args.report.chmod(0o600)
    print(json.dumps({k: value[k] for k in ["status", "samples_checked", "statuses", "results_sha256"] if k in value}))


if __name__ == "__main__": main()
