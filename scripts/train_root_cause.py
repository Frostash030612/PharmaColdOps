#!/usr/bin/env python
"""Root-cause classification skeleton (proposal W3, §6.3).

Predicts the *cause* of a cold-chain excursion from facility / equipment /
monthly-usage context, using the Electric Sheep Africa `vaccine-cold-chain`
simulation (three 10k-row files share one 46-column schema; rows with a heat
or freeze excursion detected carry one of 10 real `excursion_cause` labels).

Reported per proposal §6.3: top-1 accuracy, top-3 accuracy, macro-F1
(baseline = majority class vs class-balanced LightGBM).

Honesty: the whole dataset is a simulation — metrics describe the generator.
The cause labels are correlated with context columns by construction (that is
the simulated "ground truth" of this benchmark), so strong accuracy is
expected and says nothing about a real deployment.

Usage:  python scripts/train_root_cause.py     (lightgbm optional)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ml.evaluate import (SEED, balanced_weights, fill_median,  # noqa: E402
                         fmt, multi_metrics)

DATA = ROOT / "data" / "ml" / "electricsheepafrica__vaccine-cold-chain"
FILES = [
    "vaccine_coldchain_district_hospital.csv",
    "vaccine_coldchain_regional_vaccine_store.csv",
    "vaccine_coldchain_rural_health_post.csv",
]
TARGET = "excursion_cause"

# context features — deliberately exclude columns that *are* the effect
# (temp_in_range_pct / *_excursion_detected / vvm / wastage), keeping the
# facility·equipment·power·monitoring context that plausibly precedes a cause.
CAT = ["facility_level", "region_type", "equipment_type", "equipment_functional",
       "backup_power_available", "monitoring_type", "monitoring_device_present",
       "temp_log_complete", "vaccine_name", "freeze_sensitive", "heat_sensitive"]
NUM = ["equipment_age_years", "power_outage_hours_last_month", "year", "month"]
FEATURES = CAT + NUM


def main() -> int:
    df = pd.concat([pd.read_csv(DATA / f) for f in FILES], ignore_index=True)

    # root-cause task fires only when an excursion was detected
    has_exc = (df["heat_excursion_detected"] == 1) | (df["freeze_excursion_detected"] == 1)
    df = df[has_exc].copy()
    print(f"excursion rows {len(df)}  classes:\n{df[TARGET].value_counts().to_string()}")

    # encode target
    y_raw = df[TARGET].to_numpy()
    classes = np.unique(y_raw)
    y = np.array([np.where(classes == v)[0][0] for v in y_raw])
    # categorical context -> codes; numeric context kept as numbers
    cat_codes = df[CAT].astype("category").apply(lambda s: s.cat.codes)
    X = pd.concat([cat_codes, df[NUM].apply(pd.to_numeric, errors="coerce")],
                  axis=1).reset_index(drop=True)

    # split on row positions first, then median-fill with TRAIN-only constants
    # (fitting fill values on the full frame leaks test rows into the features)
    pos_tr, pos_te = train_test_split(
        np.arange(len(X)), test_size=0.2, stratify=y, random_state=SEED)
    X = fill_median(X, fill=X.iloc[pos_tr].median()).to_numpy(dtype=float)
    Xtr, Xte, ytr, yte = X[pos_tr], X[pos_te], y[pos_tr], y[pos_te]
    sw = balanced_weights(ytr)

    # baseline: always predict the majority class
    maj = np.broadcast_to(
        np.eye(len(classes))[np.bincount(ytr).argmax()], (len(yte), len(classes)))
    rows = [("majority-class", multi_metrics(yte, maj))]

    try:
        from lightgbm import LGBMClassifier
        model = LGBMClassifier(n_estimators=300, learning_rate=0.05,
                               random_state=SEED, verbose=-1)
        model.fit(Xtr, ytr, sample_weight=sw)
        proba = model.predict_proba(Xte)
        rows.append(("LGBM (balanced)", multi_metrics(yte, proba)))
    except ImportError:
        print("[skip] lightgbm not installed")

    keys = ["top1", "top3", "macro_f1"]
    print(f"\nroot-cause  {len(y)} excursion rows  · {len(classes)} classes  · "
          f"split 80/20 stratified, seed={SEED}")
    print("| model | top-1 | top-3 | macro-F1 |")
    print("|---|---|---|---|")
    for name, m in rows:
        print(f"| {name} | {fmt(m, keys)} |")

    md = [
        "# 根因诊断基线（vaccine-cold-chain `excursion_cause`）",
        "",
        f"- {len(y)} 条超限行 × {len(classes)} 个原因类；上下文特征 {len(FEATURES)} 个（设备/电源/监测/疫苗属性）。",
        "- 80/20 分层随机；LGBM 类别平衡权重。",
        "- ⚠️ 仿真数据集，指标描述生成器；原因与上下文列由构造强相关，高准确率属预期。",
        "",
        "| model | top-1 | top-3 | macro-F1 |",
        "|---|---|---|---|",
    ]
    md += [f"| {n} | {fmt(m, keys)} |" for n, m in rows]
    md += ["", "类别与计数见上方脚本输出。", ""]
    out = ROOT / "data" / "processed" / "root_cause_results.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\n[wrote {out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
