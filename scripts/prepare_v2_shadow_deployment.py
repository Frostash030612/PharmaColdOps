"""Stage TRUSTED local model files for explicit read-only Compose overlay.

Does not stop/restart services, alter passwords, train models or copy case data.
Capture original serving models from the existing container BEFORE using this.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ml.event_v2_runtime import BUNDLE_SCHEMA
from ml.event_temporal import VERSION, TEMPORAL_FEATURES
from ml.event_baselines import TARGETS
from ml.event_gate import fingerprint, validate_policy
from ml.event_runtime import digest
from ml.contracts import FEATURES

BUNDLE_FILES = ("model.joblib", "metadata.json", "demo_samples.json")
M4_FILES = tuple(f"{task}/{name}" for task in ["risk", "cause"] for name in ["model.joblib", "metadata.json"])


def prepare(output, bundle, serving_models, image):
    if output.exists() or output.resolve().is_relative_to(bundle.resolve()) or output.resolve().is_relative_to(serving_models.resolve()):
        raise ValueError("fresh separate deployment staging directory required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._/:-]+", image): raise ValueError("explicit local image/tag required")
    for source, files in [(bundle, BUNDLE_FILES), (serving_models, M4_FILES)]:
        if source.is_symlink() or not source.is_dir(): raise ValueError("trusted regular source directory required")
        for name in files:
            path = source / name
            if path.is_symlink() or not path.is_file(): raise ValueError("regular allowlisted model files required")
    meta = json.loads((bundle / "metadata.json").read_text())
    if (meta["schema"] != BUNDLE_SCHEMA or meta["feature_schema"] != VERSION or meta["features"] != list(TEMPORAL_FEATURES)
        or meta["targets"] != list(TARGETS) or meta["shadow_only"] is not True or meta["review_required"] is not True
        or meta["automatic_actions_allowed"] is not False or meta["policy_sha256"] != fingerprint(meta["policy"])
        or meta["model_sha256"] != digest(bundle / "model.joblib") or meta["demo_samples_sha256"] != digest(bundle / "demo_samples.json")):
        raise ValueError("shadow bundle integrity/contract mismatch")
    validate_policy(meta["policy"])
    if not meta["policy"]["enabled"]: raise ValueError("validation-qualified shadow policy required")
    for task in ["risk", "cause"]:
        info = json.loads((serving_models / task / "metadata.json").read_text())
        if (info["schema_version"] != 1 or info["task"] != task or info["features"] != FEATURES[task]
            or info["model_sha256"] != digest(serving_models / task / "model.joblib")):
            raise ValueError("original serving model contract/integrity mismatch")
    paths = {"EVENT_V2_SHADOW_BUNDLE": str((output / "shadow").resolve()), "PRESERVED_M4_MODELS": str((output / "serving-models").resolve())}
    if any(any(c in path for c in ["$", "\n", "\r", "\x00"]) for path in paths.values()):
        raise ValueError("unsafe Compose env path")
    output.mkdir(parents=True, mode=0o755)
    hashes = {}
    for source, destination, files in [(bundle, output / "shadow", BUNDLE_FILES), (serving_models, output / "serving-models", M4_FILES)]:
        for name in files:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            shutil.copyfile(source / name, target); target.chmod(0o644)
            expected = digest(source / name)
            if digest(target) != expected: raise ValueError("staging copy differs")
            hashes[str(target.relative_to(output))] = expected
    descriptor = os.open(output / "shadow.env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("V2_SHADOW_IMAGE=" + image + "\n")
        for name, value in paths.items(): stream.write(name + "=" + json.dumps(value, ensure_ascii=False) + "\n")
    report = {"schema": "v2-shadow-deployment-staging-v1", "status": "staged_not_deployed", "image": image,
        "files": hashes, "model_sha256": meta["model_sha256"], "model_id": meta["model_id"],
        "mounts_read_only": True, "preserves_original_m4": True, "no_credentials_or_cases_copied": True,
        "scope": "hash validation/copy, not pickle authentication; container preflight required"}
    (output / "staging.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True); parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--serving-models", type=Path, required=True); parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try: report = prepare(args.output, args.bundle, args.serving_models, args.image)
    except (ValueError, OSError, KeyError, TypeError):
        print("Deployment staging refused; no service or credentials changed"); return 1
    print(json.dumps({k: report[k] for k in ["status", "image", "model_id", "mounts_read_only"]})); return 0


if __name__ == "__main__": raise SystemExit(main())
