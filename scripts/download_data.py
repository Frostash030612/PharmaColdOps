#!/usr/bin/env python
"""Download the PharmaColdOps datasets into ``data/raw/``.

Downloads sources that need NO login first:

  1. Hugging Face datasets (``datasets`` library)  -> ``data/raw/huggingface/<name>/``
  2. Solomon VRPTW instances (CervEdin mirror)     -> ``data/raw/cvrplib/``

Kaggle datasets (Cold Chain Shipment Silent Failure; Vaccine Distribution with
Temperature Logging) require a Kaggle API token and are intentionally NOT
handled here — see PROGRESS.md for the manual steps.

Usage:
    python scripts/download_data.py             # everything (no login)
    python scripts/download_data.py --hf-only   # Hugging Face only
    python scripts/download_data.py --vrp-only  # CVRPLIB only
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

HF_DATASETS = [
    "electricsheepafrica/vaccine-cold-chain",
    "electricsheepafrica/africa-synth-immunization-vaccine-quality-cold-chain-all",
    "electricsheepafrica/africa-cold-chain-iot",
    "ClarusC64/clinical-quad-coldchain-temp-excursion-transit-delay-potency-loss-v0.1",
]

# Solomon VRPTW instances (CervEdin JSON mirror), class x time-window type.
SOLOMON_INSTANCES = [
    ("c", "1", "c101"), ("c", "2", "c201"),
    ("r", "1", "r101"), ("r", "2", "r201"),
    ("rc", "1", "rc101"), ("rc", "2", "rc201"),
]
SOLOMON_BASE_URL = (
    "https://raw.githubusercontent.com/CervEdin/solomon-vrptw-benchmarks/main/"
    "{cls}/{typ}/{inst}.json"
)


def _manifest_header() -> list[str]:
    return [
        "# PharmaColdOps data manifest",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "| source | status | detail |",
        "|---|---|---|",
    ]


def download_hf(manifest: list[str]) -> None:
    try:
        from huggingface_hub import hf_hub_download, list_repo_files
    except ImportError:
        print("[ERROR] 'huggingface_hub' not installed. Run: pip install huggingface_hub")
        manifest.append("| huggingface | SKIP | huggingface_hub not installed |")
        return

    for name in HF_DATASETS:
        slug = name.replace("/", "__")
        out_dir = RAW / "huggingface" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            files = [
                f for f in list_repo_files(name, repo_type="dataset")
                if f.endswith((".csv", ".parquet", ".json"))
            ]
        except Exception as exc:  # noqa: BLE001
            print(f"[SKIP] {name}: list failed: {exc}")
            manifest.append(f"| {name} | FAILED | {exc} |")
            continue
        if not files:
            print(f"[SKIP] {name}: no data files")
            manifest.append(f"| {name} | SKIP | no data files |")
            continue

        saved = []
        for f in files:
            try:
                cached = hf_hub_download(repo_id=name, filename=f, repo_type="dataset")
                target = out_dir / Path(f).name
                target.write_bytes(Path(cached).read_bytes())
                saved.append(Path(f).name)
            except Exception as exc:  # noqa: BLE001
                print(f"[SKIP] {name}/{f}: {exc}")
                saved.append(f"{Path(f).name}=FAILED")
        print(f"[OK] {name} -> {out_dir}")
        manifest.append(f"| {name} | OK | {len(files)} file(s): " + ", ".join(saved) + " |")


def download_vrp(manifest: list[str]) -> None:
    try:
        import requests
    except ImportError:
        print("[ERROR] 'requests' not installed. Run: pip install requests")
        manifest.append("| cvrplib | SKIP | requests not installed |")
        return

    out_dir = RAW / "cvrplib"
    out_dir.mkdir(parents=True, exist_ok=True)
    for cls, typ, inst in SOLOMON_INSTANCES:
        url = SOLOMON_BASE_URL.format(cls=cls, typ=typ, inst=inst)
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            (out_dir / f"{inst}.json").write_bytes(resp.content)
            print(f"[OK] cvrplib/{inst}")
            manifest.append(f"| cvrplib/{inst} | OK | Solomon VRPTW (JSON) |")
        except Exception as exc:  # noqa: BLE001
            print(f"[SKIP] cvrplib/{inst}: {exc}")
            manifest.append(f"| cvrplib/{inst} | FAILED | {exc} |")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-only", action="store_true")
    ap.add_argument("--vrp-only", action="store_true")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    manifest = _manifest_header()

    if not args.vrp_only:
        download_hf(manifest)
    if not args.hf_only:
        download_vrp(manifest)

    (RAW / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print("\nWrote manifest ->", RAW / "MANIFEST.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
