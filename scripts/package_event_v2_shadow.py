"""Package a frozen local study as opt-in shadow, never train/promote a model."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from generate_event_dataset import digest
from evaluate_event_baselines import dump
from event_v2_data import TEST
from ml.event_gate import fingerprint, validate_policy
from ml.event_baselines import TARGETS
from ml.event_temporal import VERSION, TEMPORAL_FEATURES
from ml.event_v2_runtime import BUNDLE_SCHEMA
from api.schemas import EventContextIn


def package(study, output):
    if output.exists() or output.resolve().is_relative_to(study.resolve()): raise ValueError("fresh separate shadow output required")
    report = json.loads((study / "report.json").read_text())
    frozen = json.loads((study / "selection-frozen.json").read_text())
    manifest = json.loads((study / "data/manifest.json").read_text())
    if (report["status"] != "complete" or report["schema"] != VERSION or frozen["schema"] != VERSION
            or report["selected"] != "mixed_temporal" or frozen["selected"] != "mixed_temporal"
            or report["selection_sha256"] != digest(study / "selection-frozen.json")
            or frozen["protocol_sha256"] != digest(study / "protocol.json")
            or report["dataset_manifest_sha256"] != digest(study / "data/manifest.json")
            or manifest["schema"] != VERSION or manifest["status"] != "complete"
            or digest(study / "mixed_temporal.joblib") != frozen["model_sha256"]["mixed_temporal"]):
        raise ValueError("complete frozen temporal v2 study required")
    policy = frozen["policies"]["mixed_temporal"]; validate_policy(policy)
    if policy["enabled"] is not True: raise ValueError("validation-qualified candidate screen required; do not relax gate")
    samples = []
    for role in TEST:
        file = study / "data" / role / "observations.jsonl"
        if digest(file) != manifest["roles"][role]["file_sha256"][file.name]: raise ValueError("demo observation integrity mismatch")
        products = set()
        with file.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream):
                observation = json.loads(line)
                if observation["product_id"] in products: continue
                EventContextIn(observation=observation)
                products.add(observation["product_id"])
                samples.append({"sample_id": f"{role}-{number:04d}", "role": role, "observation": observation})
    if not 1 <= len(samples) <= 40: raise ValueError("bounded public demo samples required")
    output.mkdir(parents=True)
    shutil.copyfile(study / "mixed_temporal.joblib", output / "model.joblib")
    dump(output / "demo_samples.json", samples)
    model_sha = digest(output / "model.joblib")
    metadata = {"schema": BUNDLE_SCHEMA, "feature_schema": VERSION, "features": list(TEMPORAL_FEATURES), "targets": list(TARGETS),
        "model_id": "event-temporal-v2-" + model_sha[:12], "model_sha256": model_sha,
        "sklearn_version": report["protocol"]["versions"]["sklearn"], "policy": policy, "policy_sha256": fingerprint(policy),
        "study_selection_sha256": digest(study / "selection-frozen.json"), "demo_samples_sha256": digest(output / "demo_samples.json"),
        "review_required": True, "automatic_actions_allowed": False, "shadow_only": True,
        "scope": "previously evaluated synthetic study demo; uncalibrated, not medical/causal authorization; no automatic actions"}
    dump(output / "metadata.json", metadata)
    return {"status": "packaged_not_enabled", "model_id": metadata["model_id"], "samples": len(samples), "model_sha256": model_sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(package(args.study,args.output)))


if __name__ == "__main__": main()
