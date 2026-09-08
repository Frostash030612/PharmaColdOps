#!/usr/bin/env python
"""Full risk-prediction experiment — LogisticRegression / LightGBM / XGBoost.

Runs the complete baseline the proposal promises (W2, §6.3): class-balanced
training weights, threshold selection on a validation split (imbalance-aware,
instead of a blind 0.5), test-set F1 / ROC-AUC / PR-AUC, a feature-set
contrast (interpretable-only vs + anonymous ``feature_x1..x3``), and a SHAP
beeswarm plot for the best tree model.

Honesty notes (repeat these wherever the numbers are cited):
  * The Kaggle dataset has NO timestamp -> a random stratified split, not a
    chronological one. The proposal's "chronological split" cannot be honoured
    on this file; either accept a random split with this caveat, or build the
    time-ordered task on vaccine-distribution (which has ``date``).
  * The file is very likely synthetic (see data/ml/DATA_DICTIONARY.md §1). Any
    AUC here describes the generator, not real-world silent-failure risk.

Usage:  python scripts/train_risk_full.py
        (lightgbm / xgboost / shap are optional imports — install with
         pip install lightgbm xgboost shap)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ml.evaluate import (SEED, balanced_weights, best_f1_threshold,  # noqa: E402
                         binary_metrics, fill_median, fmt)

CSV = ROOT / "data" / "ml" / "cold-chain-silent-failure" / "shipment-sensor-dataset.csv"
FIG = ROOT / "reports" / "ml" / "shap_risk.png"
TARGET = "silent_failure"
ANON = ["feature_x1", "feature_x2", "feature_x3"]

# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
df = fill_median(pd.read_csv(CSV).drop(columns=["shipment_id"]))
y = df[TARGET].to_numpy()
interp = [c for c in df.columns if c != TARGET and c not in ANON]
feature_sets = [("interpretable", interp), ("all", [c for c in df.columns if c != TARGET])]

# 70 / 15 / 15 — train / threshold-validation / test (stratified, on row ids
# so every feature-set variant can slice the same partition)
all_feats = [c for c in df.columns if c != TARGET]
itr, ite = train_test_split(np.arange(len(df)), test_size=0.15,
                            stratify=y, random_state=SEED)
itr, iva = train_test_split(itr, test_size=0.1765,
                            stratify=y[itr], random_state=SEED)  # 0.15 of the 0.85
ytr, yva, yte = y[itr], y[iva], y[ite]
sw = balanced_weights(ytr)


def build_models():
    models = [("LR  (balanced)", LogisticRegression(
        max_iter=2000, random_state=SEED))]
    try:  # optional gradient boosting
        from lightgbm import LGBMClassifier
        models.append(("LGBM (balanced)", LGBMClassifier(
            n_estimators=300, learning_rate=0.05, random_state=SEED, verbose=-1)))
    except ImportError:
        print("[skip] lightgbm not installed")
    try:
        from xgboost import XGBClassifier
        models.append(("XGB  (balanced)", XGBClassifier(
            n_estimators=300, learning_rate=0.05, random_state=SEED,
            eval_metric="logloss")))
    except ImportError:
        print("[skip] xgboost not installed")
    return models


# --------------------------------------------------------------------------- #
# experiment
# --------------------------------------------------------------------------- #
rows, best_tree = [], None
for fs_label, feats in feature_sets:
    tr = df[feats].loc[itr].to_numpy()
    va = df[feats].loc[iva].to_numpy()
    te = df[feats].loc[ite].to_numpy()
    # standardise once per feature set (LR needs it; monotone transform is
    # harmless for trees) — sample weights stay aligned, order unchanged
    sc = StandardScaler().fit(tr)
    tr, va, te = sc.transform(tr), sc.transform(va), sc.transform(te)
    for name, model in build_models():
        model.fit(tr, ytr, sample_weight=sw)
        val_p = model.predict_proba(va)[:, 1]
        thr = best_f1_threshold(yva, val_p)          # imbalance-aware threshold
        te_p = model.predict_proba(te)[:, 1]
        m = binary_metrics(yte, te_p, thr)
        rows.append((fs_label, name, thr, m))
        # remember best tree on the interpretable features (the SHAP story)
        if "LR" not in name and fs_label == "interpretable":
            auc = binary_metrics(yte, te_p).get("auc")
            if best_tree is None or (auc or 0) > (best_tree[0] or 0):
                best_tree = (auc, name, feats, model)

# --------------------------------------------------------------------------- #
# SHAP (best tree model on interpretable features — the report's story)
# --------------------------------------------------------------------------- #
shap_lines = ["- SHAP: lightgbm/xgboost/shap not all installed — plot skipped."]
if best_tree:
    try:
        import shap
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier
        auc0, name0, feats0, _ = best_tree
        # refit on RAW features so the plot is in original units (°C, hours…)
        raw_tr = df[feats0].loc[itr].to_numpy()
        raw_te = df[feats0].loc[ite].to_numpy()
        m0 = (LGBMClassifier(n_estimators=300, learning_rate=0.05,
                             random_state=SEED, verbose=-1) if name0.startswith("LGBM")
              else XGBClassifier(n_estimators=300, learning_rate=0.05,
                                 random_state=SEED, eval_metric="logloss"))
        m0.fit(raw_tr, ytr, sample_weight=sw)
        sv = shap.TreeExplainer(m0).shap_values(raw_te)
        FIG.parent.mkdir(parents=True, exist_ok=True)
        shap.summary_plot(sv, raw_te, feature_names=feats0,
                          show=False, max_display=15)
        plt.tight_layout()
        plt.savefig(FIG, dpi=150, bbox_inches="tight")
        plt.close()
        imp = np.abs(sv).mean(axis=0)
        top = sorted(zip(feats0, imp), key=lambda t: -t[1])[:10]
        shap_lines = [f"- SHAP beeswarm saved to `reports/ml/shap_risk.png` "
                      f"(model: {name0}, interpretable features, raw units).",
                      "- top features by |SHAP|: " +
                      ", ".join(f"{k} ({v:.4f})" for k, v in top)]
    except Exception as exc:  # noqa: BLE001 — plot is best-effort
        shap_lines = [f"- SHAP plot failed (non-fatal): {exc}"]

# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
keys = ["acc", "prec", "rec", "f1", "auc", "prauc"]
print(f"silent-failure  {len(df)} rows  (positive {y.mean():.1%})  "
      f"split 70/15/15 stratified, seed={SEED}")
print("| features | model | thr | acc | prec | rec | F1 | ROC-AUC | PR-AUC |")
print("|---|---|---|---|---|---|---|---|---|")
for fs_label, name, thr, m in rows:
    print(f"| {fs_label} | {name} | {thr:.2f} | {fmt(m, keys)} |")
print("\n".join(shap_lines))

md = [
    "# 风险预测全实验（silent-failure）：LR / LGBM / XGB",
    "",
    f"- `{len(df)}` 行，正类 `{y.mean():.1%}`；切分 70/15/15 分层随机（**无时间戳 → 非时间切分，报告须注明**）。",
    "- 阈值由验证集最大化 F1 选取（非固定 0.5）；全部用类别平衡权重训练。",
    "- ⚠️ 数据疑似合成（DATA_DICTIONARY §1），指标只描述生成器。",
    "",
    "| features | model | thr | acc | prec | rec | F1 | ROC-AUC | PR-AUC |",
    "|---|---|---|---|---|---|---|---|---|",
]
md += [f"| {a} | {b} | {c:.2f} | {d} |" for a, b, c, d in
       [(a, b, c, fmt(d, keys)) for a, b, c, d in rows]]
md += ["", "### SHAP", ""] + shap_lines + [""]
out = ROOT / "data" / "processed" / "risk_model_full_results.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(md), encoding="utf-8")
print(f"\n[wrote {out}]")
