"""Leakage-audited M4 experiments, deliberately separate from serving artifacts."""
from dataclasses import dataclass
import hashlib
import json
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import expit, logit, softmax
from sklearn.dummy import DummyClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, log_loss
from sklearn.model_selection import StratifiedKFold, StratifiedGroupKFold, train_test_split, GroupShuffleSplit, TimeSeriesSplit

from .contracts import FEATURES
from .evaluate import balanced_weights, best_f1_threshold, binary_metrics, multi_metrics
from .training import make_pipeline

CAUSE_CONTEXT = ["facility_level", "region_type", "equipment_type", "equipment_age_years", "vaccine_name", "freeze_sensitive", "heat_sensitive"]


@dataclass
class Dataset:
    task: str
    x: pd.DataFrame
    y: np.ndarray
    ids: list[str]
    groups: np.ndarray | None = None
    months: np.ndarray | None = None

    def __post_init__(self):
        if len(self.x) != len(self.y) or len(self.ids) != len(self.y) or len(set(self.ids)) != len(self.ids):
            raise ValueError("samples must have unique, aligned source identities")
        if self.groups is not None and len(self.groups) != len(self.y):
            raise ValueError("group identities must align with samples")
        if self.months is not None and len(self.months) != len(self.y):
            raise ValueError("month identities must align with samples")


def outer_splits(data, mode, folds=5, seed=42):
    ids = np.arange(len(data.y))
    if mode == "random":
        return list(StratifiedKFold(folds, shuffle=True, random_state=seed).split(ids, data.y))
    if mode == "facility":
        if data.groups is None or len(np.unique(data.groups)) < folds:
            raise ValueError("insufficient facility groups")
        return list(StratifiedGroupKFold(folds, shuffle=True, random_state=seed).split(ids, data.y, data.groups))
    if mode == "time":
        if data.months is None:
            raise ValueError("timestamps absent; prospective time split unavailable")
        months = np.unique(data.months)
        if len(months) <= folds:
            raise ValueError("insufficient calendar months")
        return [(ids[np.isin(data.months, months[a])], ids[np.isin(data.months, months[b])])
                for a, b in TimeSeriesSplit(folds).split(months)]
    raise ValueError("unknown split mode")


def inner_splits(data, outer_train, mode, seed):
    """60% fit, 20% calibration, 20% selection; every role disjoint."""
    if mode == "time":
        months = np.unique(data.months[outer_train])
        cut1, cut2 = int(len(months) * .6), int(len(months) * .8)
        if cut1 < 1 or cut2 <= cut1 or cut2 >= len(months):
            raise ValueError("insufficient past months for three independent inner roles")
        return tuple(outer_train[np.isin(data.months[outer_train], block)]
                     for block in [months[:cut1], months[cut1:cut2], months[cut2:]])
    if mode == "facility":
        groups = data.groups[outer_train]
        a, b = next(GroupShuffleSplit(1, test_size=.4, random_state=seed).split(outer_train, groups=groups))
        fit, remaining = outer_train[a], outer_train[b]
        c, d = next(GroupShuffleSplit(1, test_size=.5, random_state=seed + 1).split(remaining, groups=data.groups[remaining]))
        return fit, remaining[c], remaining[d]
    fit, remaining = train_test_split(outer_train, test_size=.4, stratify=data.y[outer_train], random_state=seed)
    calibration, selection = train_test_split(remaining, test_size=.5, stratify=data.y[remaining], random_state=seed + 1)
    return fit, calibration, selection


def audit_partition(data, parts, mode):
    roles = ["fit", "calibration", "selection", "test"]
    arrays = [np.asarray(p, dtype=int) for p in parts]
    classes = set(np.unique(data.y))
    for p in arrays:
        if len(p) == 0 or len(set(p)) != len(p) or p.min() < 0 or p.max() >= len(data.y):
            raise ValueError("empty, repeated or out-of-range partition")
        if set(np.unique(data.y[p])) != classes:
            raise ValueError("every role must contain all target classes")
    for i in range(4):
        for j in range(i):
            if set(arrays[i]) & set(arrays[j]):
                raise ValueError("row leakage between partition roles")
            if mode == "facility" and set(data.groups[arrays[i]]) & set(data.groups[arrays[j]]):
                raise ValueError("facility leakage between partition roles")
    if mode == "time" and not all(data.months[arrays[i]].max() < data.months[arrays[i+1]].min() for i in range(3)):
        raise ValueError("future month leakage between partition roles")
    xhash = pd.util.hash_pandas_object(data.x, index=False).to_numpy()
    training = np.concatenate(arrays[:3])
    overlap = np.isin(xhash[arrays[-1]], xhash[training])
    domain = {}
    for key in data.x.columns:
        a, b = data.x.iloc[arrays[0]][key], data.x.iloc[arrays[-1]][key]
        if pd.api.types.is_numeric_dtype(a):
            domain[key] = int(((b < a.min()) | (b > a.max())).sum())
        else:
            domain[key] = int((~b.isin(a.unique())).sum())
    return {"status": "passed", "mode": mode, "sizes": dict(zip(roles, map(len, arrays))),
            "row_overlap": 0, "group_overlap": 0 if mode == "facility" else None,
            "chronological_roles": mode == "time", "test_predictor_duplicates_in_inner_data": int(overlap.sum()),
            "test_feature_domain_mismatch_counts": domain,
            "offline_scoring_includes_shifts_serving_may_reject": True,
            "partition_sha256": hashlib.sha256(json.dumps([p.tolist() for p in arrays]).encode()).hexdigest()}


def probability_matrix(p):
    p = np.asarray(p, dtype=float)
    if p.ndim != 2 or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any() or not np.allclose(p.sum(axis=1), 1):
        raise ValueError("invalid class probability matrix")
    return np.clip(p, 1e-12, 1 - 1e-12) / np.clip(p, 1e-12, 1 - 1e-12).sum(axis=1, keepdims=True)


def reliability(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    ids = np.minimum((p * bins).astype(int), bins - 1)
    rows = []
    for i in range(bins):
        mask = ids == i
        if mask.any():
            rows.append({"bin": i, "count": int(mask.sum()), "mean_probability": float(p[mask].mean()), "observed_frequency": float(y[mask].mean())})
    ece = sum(r["count"] / len(y) * abs(r["mean_probability"] - r["observed_frequency"]) for r in rows)
    return {"bins": rows, "ece_10": ece, "binning": "fixed_equal_width"}


def metrics(task, y, p, threshold=.5):
    p = probability_matrix(p); y = np.asarray(y, dtype=int)
    if task == "risk":
        result = binary_metrics(y, p[:, 1], threshold)
        brier = np.mean((p[:, 1] - y) ** 2)
    else:
        result = multi_metrics(y, p)
        brier = np.mean(np.sum((p - np.eye(p.shape[1])[y]) ** 2, axis=1))
    calibration_curve = reliability(y, p[:, 1]) if task == "risk" else reliability((p.argmax(axis=1) == y).astype(int), p.max(axis=1))
    result.update(log_loss=float(log_loss(y, p, labels=np.arange(p.shape[1]))), brier=float(brier),
                  ece_10=calibration_curve["ece_10"])
    return {k: float(v) for k, v in result.items()}


class ProbabilityCalibrator:
    def __init__(self, method):
        self.method = method

    def fit(self, p, y):
        p = probability_matrix(p); y = np.asarray(y, dtype=int)
        if self.method == "sigmoid":
            if p.shape[1] != 2: raise ValueError("binary sigmoid calibrator requires two classes")
            self.model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000).fit(logit(p[:, 1]).reshape(-1, 1), y)
        elif self.method == "isotonic":
            if p.shape[1] != 2: raise ValueError("binary isotonic calibrator requires two classes")
            self.model = IsotonicRegression(out_of_bounds="clip").fit(p[:, 1], y)
        elif self.method == "temperature":
            logits = np.log(p)
            loss = lambda log_t: log_loss(y, softmax(logits / np.exp(log_t), axis=1), labels=np.arange(p.shape[1]))
            result = minimize_scalar(loss, bounds=(-3, 3), method="bounded")
            if not result.success: raise ValueError("temperature calibration failed")
            self.temperature = float(np.exp(result.x))
        elif self.method != "none":
            raise ValueError("unknown calibration method")
        return self

    def transform(self, p):
        p = probability_matrix(p)
        if self.method == "none": return p
        if self.method == "sigmoid":
            positive = self.model.predict_proba(logit(p[:, 1]).reshape(-1, 1))[:, 1]
            return probability_matrix(np.column_stack([1-positive, positive]))
        if self.method == "isotonic":
            positive = self.model.predict(p[:, 1])
            return probability_matrix(np.column_stack([1-positive, positive]))
        return softmax(np.log(p) / self.temperature, axis=1)


class FormalPredictor:
    """Frozen representative fold model, not a deployment artifact."""
    def __init__(self, model, calibrator):
        self.model, self.calibrator = model, calibrator
        self.classes_ = model.classes_
        self.feature_names_in_ = model.feature_names_in_

    def predict_proba(self, x):
        return self.calibrator.transform(self.model.predict_proba(x))


def evaluate_fold(data, parts, estimators, mode):
    audit = audit_partition(data, parts, mode)
    fit, calibration, selection, test = parts
    classes = np.unique(data.y)
    code = {c: i for i, c in enumerate(classes)}
    y = np.array([code[c] for c in data.y])
    results, candidates = [], []
    start = time.perf_counter()
    for name, estimator in estimators:
        model = make_pipeline(data.task, estimator, list(data.x.columns))
        model.fit(data.x.iloc[fit], data.y[fit], classifier__sample_weight=balanced_weights(data.y[fit]))
        if not np.array_equal(model.classes_, classes): raise ValueError("class order differs from declared task")
        p = model.predict_proba(data.x.iloc[selection])
        score = metrics(data.task, y[selection], p)
        criterion = score["prauc"] if data.task == "risk" else score["macro_f1"]
        candidate_threshold = best_f1_threshold(y[selection], p[:, 1]) if data.task == "risk" else None
        results.append({"algorithm": name, "selection_metrics_raw": score, "selection_threshold": candidate_threshold,
                        "estimator_parameters": estimator.get_params(deep=False)})
        candidates.append((criterion, name, model, candidate_threshold))
    _, algorithm, model, _ = max(candidates, key=lambda c: c[0])
    pcal, pselection = model.predict_proba(data.x.iloc[calibration]), model.predict_proba(data.x.iloc[selection])
    methods = ["none", "sigmoid", "isotonic"] if data.task == "risk" else ["none", "temperature"]
    calibrators, cal_scores = [], []
    for method in methods:
        calibrator = ProbabilityCalibrator(method).fit(pcal, y[calibration])
        score = metrics(data.task, y[selection], calibrator.transform(pselection))
        criterion = score["brier"] if data.task == "risk" else score["log_loss"]
        calibrators.append((criterion, method, calibrator))
        method_threshold = best_f1_threshold(y[selection], calibrator.transform(pselection)[:, 1]) if data.task == "risk" else None
        parameters = ({"coefficient": calibrator.model.coef_.tolist(), "intercept": calibrator.model.intercept_.tolist()} if method == "sigmoid" else
                      {"input_thresholds": calibrator.model.X_thresholds_.tolist(), "output_thresholds": calibrator.model.y_thresholds_.tolist()} if method == "isotonic" else
                      {"temperature": calibrator.temperature} if method == "temperature" else {})
        cal_scores.append({"method": method, "selection_metrics": score, "selection_threshold": method_threshold, "parameters": parameters})
    _, cal_method, calibrator = min(calibrators, key=lambda c: c[0])
    predictor = FormalPredictor(model, calibrator)
    threshold = best_f1_threshold(y[selection], predictor.predict_proba(data.x.iloc[selection])[:, 1]) if data.task == "risk" else None
    raw_threshold = best_f1_threshold(y[selection], pselection[:, 1]) if data.task == "risk" else None
    raw, calibrated = model.predict_proba(data.x.iloc[test]), predictor.predict_proba(data.x.iloc[test])
    prior = DummyClassifier(strategy="prior").fit(data.x.iloc[fit], data.y[fit])
    baseline = prior.predict_proba(data.x.iloc[test])
    raw_metrics = metrics(data.task, y[test], raw, raw_threshold)
    calibrated_metrics = metrics(data.task, y[test], calibrated, threshold)
    # Majority/prior baseline uses 0.5, not a tuned all-positive F1 shortcut.
    baseline_metrics = metrics(data.task, y[test], baseline)
    candidate_test = {name: metrics(data.task, y[test], fitted.predict_proba(data.x.iloc[test]), thr)
                      for _, name, fitted, thr in candidates}
    calibration_test = {method: metrics(data.task, y[test], cal.transform(raw),
        best_f1_threshold(y[selection], cal.transform(pselection)[:, 1]) if data.task == "risk" else None)
        for _, method, cal in calibrators}
    predicted = (calibrated[:, 1] >= threshold).astype(int) if data.task == "risk" else calibrated.argmax(axis=1)
    record = {"algorithm": algorithm, "candidates": results, "calibration_candidates": cal_scores,
              "calibration": cal_method, "threshold": threshold, "raw_threshold": raw_threshold,
              "audit": audit, "raw_metrics": raw_metrics, "calibrated_metrics": calibrated_metrics, "baseline_metrics": baseline_metrics,
              "candidate_test_metrics": candidate_test, "calibration_test_metrics": calibration_test,
              "test_confusion": confusion_matrix(y[test], predicted, labels=np.arange(len(classes))).tolist(),
              "test_class_report": classification_report(y[test], predicted, labels=np.arange(len(classes)), target_names=[str(c) for c in classes], output_dict=True, zero_division=0),
              "elapsed_seconds": time.perf_counter()-start}
    return record, predictor, {"indices": test, "y": y[test], "raw": raw, "calibrated": calibrated, "baseline": baseline, "predicted": predicted}


def summarize(folds):
    return {section: {key: {"mean": float(np.mean([f[section][key] for f in folds])),
                           "std": float(np.std([f[section][key] for f in folds], ddof=1)) if len(folds)>1 else None}
                      for key in folds[0][section]} for section in ["raw_metrics", "calibrated_metrics", "baseline_metrics"]}
