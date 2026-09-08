#!/usr/bin/env python
"""Risk-prediction baseline (silent-failure dataset) — one run, report numbers.

Trains a LogisticRegression (after standard scaling) on the Kaggle Cold Chain
Shipment Silent Failure dataset and prints F1 / ROC-AUC / PR-AUC on a
stratified hold-out. Two feature sets are compared to make the honesty story
explicit:

  * ``interpretable``  — business-readable columns only (drops the anonymous
    ``feature_x1..x3``): what the report's SHAP narrative will talk about.
  * ``all``           — interpretable + ``feature_x1..x3``.

The data has no timestamp column, so the split is random-stratified (no
temporal split is possible) — the report must state this.

This is the LogisticRegression *baseline* (proposal §6.3 / W2). LightGBM /
XGBoost are trained separately by member B for the final experiment table; if
lightgbm is installed this script also reports it for free.

The dataset itself appears to be synthetically generated (see
data/ml/DATA_DICTIONARY.md §1): any metric here measures the model on that
generator, NOT real-world silent-failure prediction. Never cite these numbers
as deployment performance.

Usage:  python scripts/train_risk_model.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "ml" / "cold-chain-silent-failure" / "shipment-sensor-dataset.csv"

ANON = ["feature_x1", "feature_x2", "feature_x3"]
DROP = ["shipment_id"]
TARGET = "silent_failure"
RNG = 42

try:
    from sklearn.base import clone
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (accuracy_score, average_precision_score,
                                 f1_score, precision_score, recall_score,
                                 roc_auc_score)
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
except ImportError as e:  # pragma: no cover
    sys.exit(f"[ERROR] scikit-learn not installed: {e}\nRun: pip install scikit-learn")


def metrics(y_true, y_score):
    y_pred = (y_score >= 0.5).astype(int)
    return {
        "acc": accuracy_score(y_true, y_pred),
        "prec": precision_score(y_true, y_pred, zero_division=0),
        "rec": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "auc": roc_auc_score(y_true, y_score),
        "prauc": average_precision_score(y_true, y_score),
    }


def main() -> int:
    df = pd.read_csv(CSV)
    df = df.drop(columns=[c for c in DROP if c in df])
    # small missingness on two columns → median fill
    df = df.apply(lambda s: s.fillna(s.median()) if s.isna().any() else s)

    y = df[TARGET].to_numpy()
    base = [c for c in df.columns if c != TARGET]
    interp = [c for c in base if c not in ANON]

    Xtr, Xte, ytr, yte = train_test_split(
        df[base], y, test_size=0.2, stratify=y, random_state=RNG)
    ytr_p, yte_p = ytr.mean(), yte.mean()
    model = LogisticRegression(max_iter=2000, random_state=RNG)

    rows, bl = [], metrics(yte, np.full(len(yte), yte_p))  # majority-class baseline
    for label, feats in [("interpretable", interp), ("all", base)]:
        pipe = make_pipeline(StandardScaler(), clone(model)).fit(Xtr[feats], ytr)
        m = metrics(yte, pipe.predict_proba(Xte[feats])[:, 1])
        rows.append((label, m))
        # lightgbm, only if installed (member B will run the full GBM table)
        try:
            import lightgbm as lgb  # noqa: PLC0415
            gbm = lgb.LGBMClassifier(
                n_estimators=200, learning_rate=0.05, random_state=RNG, verbose=-1)
            gbm.fit(Xtr[feats], ytr)
            g = metrics(yte, gbm.predict_proba(Xte[feats])[:, 1])
            rows.append((label + "+LGBM", g))
        except ImportError:
            pass

    header = f"| model | acc | prec | rec | F1 | ROC-AUC | PR-AUC |"
    print(f"silent-failure  {len(df)} rows  (positive {y.mean():.1%})  split 80/20 stratified, seed={RNG}")
    print("baseline (majority-class):  " + "  ".join(f"{k}={v:.3f}" for k, v in bl.items()))
    print(header)
    print("|---|---|---|---|---|---|---|")
    for label, m in rows:
        print(f"| {label} | " + " | ".join(f"{m[k]:.3f}" for k in
              ["acc", "prec", "rec", "f1", "auc", "prauc"]) + " |")

    out = ROOT / "data" / "processed" / "risk_model_results.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    md = [
        "# 风险预测基线结果（silent-failure）",
        "",
        f"- 数据：`{len(df)}` 行 × {Xtr.shape[1]} 特征，正类 `{y.mean():.1%}`（不平衡）。",
        f"- 划分：80/20 分层随机（数据无时间戳，无法做时间切分——报告需注明）。",
        f"- 基线（多数类）：`{bl['f1']:.3f}` F1 · `{bl['prauc']:.3f}` PR-AUC。",
        "- ⚠️ 该 Kaggle 数据集**疑似合成**（见 DATA_DICTIONARY §1）：以下指标只在生成器上有效，**不代表真实世界的静默失效预测**。",
        "",
        header,
        "|---|---|---|---|---|---|---|",
    ]
    md += [f"| {l} | " + " | ".join(f"{m[k]:.3f}" for k in
            ["acc", "prec", "rec", "f1", "auc", "prauc"]) + " |" for l, m in rows]
    md += ["", "复现：`python scripts/train_risk_model.py`", ""]
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\n[wrote {out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
