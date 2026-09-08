#!/usr/bin/env python
"""Audit every dataset under ``data/ml/`` and emit a reproducible report.

For each file this prints / writes:
  * provenance (id, source URL, module role, granularity)
  * shape + duplicate rows
  * one row per column: dtype · null % · cardinality · numeric min/mean/max
  * label balance for the dataset's declared target column(s)
  * top features by |correlation| with the primary target (leakage screen)

The narrative data dictionary is ``data/ml/DATA_DICTIONARY.md`` (hand-written,
committed); this script is the regenerable evidence behind its stats tables.

Honesty first: several of these files are *explicitly synthetic* (their own
``is_synthetic`` / ``*synth*`` flags say so). That is not hidden here — it is
what the whole audit is for.

Usage:  python scripts/audit_datasets.py [--out data/processed/ml_audit_report.md]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ML = ROOT / "data" / "ml"

# --------------------------------------------------------------------------- #
# registry: every local dataset + its declared target/label semantics.
# licence cells say "see source page" unless we verified otherwise.
# --------------------------------------------------------------------------- #
DATASETS = [
    {
        "id": "cold-chain-silent-failure",
        "title": "Cold Chain Shipment Silent Failure (Kaggle)",
        "source": "https://www.kaggle.com/datasets/skarin/cold-chain-shipment-silent-failure-dataset",
        "path": ML / "cold-chain-silent-failure" / "shipment-sensor-dataset.csv",
        "granularity": "per shipment (sensor summary)",
        "module": "风险预测 / 故障分类 (W2 基线主数据集)",
        "target": ["silent_failure"],
        "target_note": {"silent_failure": "1 = silent failure（未触发警报却失效）, 0 = 正常"},
        "note": "Kaggle（需 token 下载）。shipment 级表格分类；23 个特征含已匿名化 feature_x1..x3。",
    },
    {
        "id": "vaccine-distribution-temperature",
        "title": "Vaccine Distribution with Temperature Logging (Kaggle)",
        "source": "https://www.kaggle.com/datasets/manankhanna0/vaccine-distribution-with-temperature-logging",
        "path": ML / "vaccine-distribution-temperature" / "input_data.csv",
        "granularity": "batch × hour sensor log",
        "module": "温度异常检测 / MKT 模拟；demo 场景来源",
        "target": [],
        "target_note": {},
        "note": "Kaggle。无显式标签；`out_of_bound_temperature_hours>0` 可派生异常标记。30 batch / 12 location。",
    },
    {
        "id": "vaccine-cold-chain",
        "title": "Electric Sheep Africa — vaccine-cold-chain (Hugging Face)",
        "source": "https://huggingface.co/datasets/electricsheepafrica/vaccine-cold-chain",
        "path": [ML / "electricsheepafrica__vaccine-cold-chain" / f for f in [
            "vaccine_coldchain_district_hospital.csv",
            "vaccine_coldchain_regional_vaccine_store.csv",
            "vaccine_coldchain_rural_health_post.csv",
        ]],
        "granularity": "facility × month",
        "module": "设施/路线级异常；含 freeze_sensitive / shake_test 等规则引擎同域字段",
        "target": ["temp_in_range_pct", "heat_excursion_detected", "freeze_excursion_detected"],
        "target_note": {
            "temp_in_range_pct": "月内温度达标占比（连续目标，亦可阈值化为标签）",
            "heat_excursion_detected": "1 = 该月记录到热超限", "freeze_excursion_detected": "1 = 该月记录到冻结超限",
        },
        "note": "三个 CSV 是同一 46 列 schema 按 facility_level 分片。Electricsheep Africa 项目（仿真冷链）。",
    },
    {
        "id": "africa-synth-immunization",
        "title": "Africa Synth — Immunization Vaccine Quality (Hugging Face)",
        "source": "https://huggingface.co/datasets/electricsheepafrica/africa-synth-immunization-vaccine-quality-cold-chain-all",
        "path": [ML / "electricsheepafrica__africa-synth-immunization-vaccine-quality-cold-chain-all" / f for f in [
            "vaccine_epi.csv", "vaccine_outreach.csv", "vaccine_private.csv",
        ]],
        "granularity": "facility/服务 × 批 (含 8 种疫苗)",
        "module": "质量标签 / 数据增强（vvm_stage / wasted / potency_compromised）",
        "target": ["wasted", "potency_compromised"],
        "target_note": {
            "wasted": "1 = 疫苗报废", "potency_compromised": "1 = 效力受损",
        },
        "note": "名字即 *synth*（合成）。三个文件按 delivery channel 分片（epi / outreach / private）。",
    },
    {
        "id": "africa-cold-chain-iot",
        "title": "Electric Sheep Africa — cold-chain IoT (Hugging Face)",
        "source": "https://huggingface.co/datasets/electricsheepafrica/africa-cold-chain-iot",
        "path": ML / "electricsheepafrica__africa-cold-chain-iot" / "train-00000-of-00001.parquet",
        "granularity": "attack/事件级（网络安全 + 冷链）",
        "module": "异常事件分类（攻击类型）—— 与主流程较远，作为增强参考",
        "target": ["detected", "label"],
        "target_note": {"detected": "1 = 事件被检测到", "label": "0/1 基准攻击标签"},
        "note": "**is_synthetic 列 = 100%** —— 官方标注全部为合成。含 attack_type/tamper/location_spoofed 等。",
    },
    {
        "id": "clinical-quad-coldchain",
        "title": "ClarusC64 — clinical-quad coldchain (Hugging Face)",
        "source": "https://huggingface.co/datasets/ClarusC64/clinical-quad-coldchain-temp-excursion-transit-delay-potency-loss-v0.1",
        "path": [ML / "ClarusC64__clinical-quad-coldchain-temp-excursion-transit-delay-potency-loss-v0.1" / f for f in [
            "train.csv", "tester.csv",
        ]],
        "granularity": "shipment（每文件仅 10 行）",
        "module": "仅作参考/口头说明（样本量太小不可训练）",
        "target": ["label_potency_loss"],
        "target_note": {"label_potency_loss": "效力损失（回归目标，值域待核）"},
        "note": "每文件 10 行是**它本来的大小**，不是下载 bug。训练不可行。",
    },
]


def _read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def col_stats(df: pd.DataFrame) -> list[dict]:
    rows = []
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            r = {"null%": f"{s.isna().mean()*100:.1f}", "nuniq": s.nunique(dropna=True)}
            if pd.api.types.is_bool_dtype(s) or set(s.dropna().unique()) <= {0, 1}:
                r.update(min="0/1", mean=f"{s.mean():.3f}", max="1")
            else:
                r.update(min=f"{s.min():g}", mean=f"{s.mean():.3g}", max=f"{s.max():g}")
        else:
            r = {"null%": f"{s.isna().mean()*100:.1f}", "nuniq": s.nunique(dropna=True), "min": "", "mean": "", "max": ""}
        rows.append({"col": col, "dtype": str(s.dtype), **r})
    return rows


def audit_file(path: Path, targets: list[str]) -> list[str]:
    df = _read(path)
    out = [f"### `{path.relative_to(ROOT)}`"]
    out.append("")
    out.append(f"- rows `{len(df)}` × cols `{df.shape[1]}` · duplicate rows `{int(df.duplicated().sum())}`")
    out.append("")
    out.append("| column | dtype | null% | cardinality | min | mean | max |")
    out.append("|---|---|---|---|---|---|---|")
    for r in col_stats(df):
        out.append(f"| {r['col']} | {r['dtype']} | {r['null%']} | {r['nuniq']} | {r['min']} | {r['mean']} | {r['max']} |")
    out.append("")

    for t in targets:
        if t not in df.columns:
            continue
        out.append(f"**target `{t}` — balance:** " + ", ".join(
            f"`{k}` = {v} ({v/len(df):.1%})" for k, v in df[t].value_counts(dropna=False).items()))
        out.append("")
        if pd.api.types.is_numeric_dtype(df[t]):
            corr = df.corr(numeric_only=True)[t].drop(labels=[t], errors="ignore").dropna()
            top = corr.reindex(corr.abs().sort_values(ascending=False).index).head(10)
            out.append("**top features by |corr| with target (leakage screen):**")
            out.append("")
            out.append("| feature | r |")
            out.append("|---|---|")
            for k, v in top.items():
                out.append(f"| {k} | {v:+.3f} |")
            out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "processed" / "ml_audit_report.md"))
    args = ap.parse_args()

    out = [
        "# ML 数据集审计报告（脚本生成，可复现）",
        "",
        "> 由 `scripts/audit_datasets.py` 生成。数据字典见 `data/ml/DATA_DICTIONARY.md`（人工维护，含字段含义与诚实说明）。",
        "> 全文统计数据以本报告为准。",
        "",
    ]
    for ds in DATASETS:
        paths = ds["path"] if isinstance(ds["path"], list) else [ds["path"]]
        out.append(f"## {ds['title']}")
        out.append("")
        out.append(f"- source: `{ds['source']}`")
        out.append(f"- granularity: {ds['granularity']} · module: {ds['module']}")
        out.append(f"- note: {ds['note']}")
        out.append("")
        for p in paths:
            out += audit_file(p, ds["target"])
        out.append("---")
        out.append("")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"[wrote {out_path}]  ({out_path.stat().st_size} bytes)")

    # console: dataset × (rows × cols)
    for ds in DATASETS:
        paths = ds["path"] if isinstance(ds["path"], list) else [ds["path"]]
        for p in paths:
            df = _read(p)
            print(f"{ds['id']:<32} {p.name:<45} {len(df):>6} × {df.shape[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
