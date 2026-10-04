"""Read-only container/host inference check, no case registration or graph I/O.

Can be piped to python stdin with PYTHONPATH=/app/src in a disposable image.
Only use trusted administrator-owned model directories.
"""
import hashlib
import json
import os

from ml import event_v2_runtime, runtime
from rule_engine.engine import RuleEngine


def check():
    state = event_v2_runtime.info()
    if state["status"] != "shadow_ready": raise RuntimeError("shadow not ready")
    originals = {}
    for task in ["risk", "cause"]:
        info = runtime.model_info(task)
        if info["status"] != "ready": raise RuntimeError("original model not ready")
        originals[task] = {key: info[key] for key in ["model_id", "model_sha256"]}
    specs = RuleEngine().specs
    samples = event_v2_runtime.samples(specs)["samples"]
    results = []
    for sample in samples:
        result = event_v2_runtime.evaluate(sample["observation"], specs)
        if result["status"] not in {"candidate_only", "abstained"} or result["review_required"] is not True or result["automatic_actions_allowed"] is not False:
            raise RuntimeError("invalid shadow result/review boundary")
        results.append({"sample_id": sample["sample_id"], "status": result["status"], "candidates": result["candidates"],
                        "scores": result["scores"], "observation_sha256": result["observation_sha256"]})
    serialized = json.dumps(results, sort_keys=True, allow_nan=False)
    return {"status": "passed", "uid": os.getuid() if hasattr(os, "getuid") else None,
        "shadow_model_id": state["model_id"], "shadow_model_sha256": state["model_sha256"], "policy_sha256": state["policy_sha256"],
        "original_models": originals, "samples_checked": len(results),
        "statuses": {status: sum(r["status"] == status for r in results) for status in ["candidate_only", "abstained"]},
        "results_sha256": hashlib.sha256(serialized.encode()).hexdigest(), "scope": "read-only synthetic demo inference; not new accuracy or clinical proof"}


if __name__ == "__main__":
    try:
        print(json.dumps(check(), ensure_ascii=False, allow_nan=False))
    except Exception:
        print(json.dumps({"status": "failed", "reason": "runtime/model/mount check failed; no case writes"}))
        raise SystemExit(1)
