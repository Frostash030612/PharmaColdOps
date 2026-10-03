"""Read-only pinned environment/input audit. No secrets, writes or graph rebuilds."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def pins(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            values.update(pins(path.parent / line[3:].strip()))
        else:
            name, version = line.split("==")
            values[name] = version
    return values


def check(*, runtime_only=False, frontend=False):
    required = pins(ROOT / ("requirements-runtime.lock.txt" if runtime_only else "requirements-eval.lock.txt"))
    packages, failures = {}, []
    for name, wanted in required.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        packages[name] = {"expected": wanted, "installed": actual}
        if actual != wanted:
            failures.append("dependency:" + name)
    if sys.version_info[:2] != (3, 12):
        failures.append("python_3_12_required")
    tools = {}
    if frontend:
        for tool, expected in [("node", "v24.15.0"), ("pnpm", "12.4.1")]:
            try:
                actual = subprocess.check_output([tool, "--version"], text=True, timeout=15).strip()
            except (OSError, subprocess.SubprocessError):
                actual = None
            tools[tool] = {"expected": expected, "installed": actual}
            if actual != expected:
                failures.append("tool:" + tool)
    paths = ["src/rule_engine/rules_config.json", "data/scenarios/gold_labels.csv",
             "data/optimisation/singapore/network.json", "data/optimisation/product_catalog.csv",
             "data/optimisation/supply_points.json", "frontend-vue/package.json", "frontend-vue/pnpm-lock.yaml",
             "data/ml/cold-chain-silent-failure/shipment-sensor-dataset.csv"]
    paths += [f"data/ml/electricsheepafrica__vaccine-cold-chain/vaccine_coldchain_{n}.csv"
              for n in ["district_hospital", "regional_vaccine_store", "rural_health_post"]]
    hashes = {}
    for path in paths:
        file = ROOT / path
        if not file.is_file():
            failures.append("missing_input:" + path)
        else:
            hashes[path] = hashlib.sha256(file.read_bytes()).hexdigest()
    return {"status": "passed" if not failures else "failed", "python": platform.python_version(),
            "platform": platform.platform(), "packages": packages, "frontend_tools": tools,
            "input_sha256": hashes, "failures": failures,
            "scope": "version/input inventory, not full tests, statistical reproducibility or security certification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-only", action="store_true")
    parser.add_argument("--frontend", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = check(runtime_only=args.runtime_only, frontend=args.frontend)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"status": result["status"], "failures": result["failures"]}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
