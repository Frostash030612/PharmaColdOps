"""Shared evaluation helpers for the ML module (risk prediction + root cause).

Kept dependency-light on purpose (sklearn + numpy only) so both experiment
scripts stay easy to read and reproduce. All metrics match what the proposal
asks for (§6.3 / §8): F1, ROC-AUC, PR-AUC for the binary risk task; top-1 /
top-3 / macro-F1 for the multi-class root-cause task.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (accuracy_score, average_precision_score,
                             f1_score, precision_score, recall_score,
                             roc_auc_score)

SEED = 42


def fill_median(df):
    """Median-fill the (small) missingness in a frame, column by column."""
    return df.apply(lambda s: s.fillna(s.median()) if s.isna().any() else s)


def balanced_weights(y):
    """Per-sample weights so each class sums to equal total weight."""
    y = np.asarray(y)
    classes, counts = np.unique(y, return_counts=True)
    n = len(y)
    w = np.empty(n)
    for c, cnt in zip(classes, counts):
        w[y == c] = n / (len(classes) * cnt)
    return w


def binary_metrics(y_true, y_proba, thr=0.5):
    """Classification metrics for the risk-prediction task at threshold ``thr``."""
    y_pred = (np.asarray(y_proba) >= thr).astype(int)
    return {
        "acc": accuracy_score(y_true, y_pred),
        "prec": precision_score(y_true, y_pred, zero_division=0),
        "rec": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "auc": roc_auc_score(y_true, y_proba),
        "prauc": average_precision_score(y_true, y_proba),
    }


def best_f1_threshold(y_true, y_proba):
    """Pick the decision threshold that maximises F1 on a validation set."""
    best_t, best_f = 0.5, -1.0
    for t in np.arange(0.05, 0.96, 0.05):
        f = f1_score(y_true, (np.asarray(y_proba) >= t).astype(int), zero_division=0)
        if f > best_f:
            best_f, best_t = f, float(t)
    return best_t


def multi_metrics(y_true, y_proba2d, topk=3):
    """Root-cause task: top-1 accuracy, top-k accuracy, macro-averaged F1."""
    y_true = np.asarray(y_true)
    pred = y_proba2d.argmax(axis=1)
    top1 = accuracy_score(y_true, pred)
    topk_hits = np.argsort(-y_proba2d, axis=1)[:, :topk]
    topk_acc = float(np.mean([y_true[i] in topk_hits[i] for i in range(len(y_true))]))
    macro_f1 = f1_score(y_true, pred, average="macro", zero_division=0)
    return {"top1": top1, f"top{topk}": topk_acc, "macro_f1": macro_f1}


def fmt(m, keys):
    return " | ".join(f"{m[k]:.3f}" for k in keys)
