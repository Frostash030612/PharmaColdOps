"""Offline event-mechanism baselines, separate from the serving M4 contract.

All eleven fault indicators are retained. Empty truth means no injected fault,
NOT product safety. Predictions are candidate sets, NOT causal/disposal proof.
"""
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_recall_fscore_support
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.event_simulation import CAUSES, FEATURES

TARGETS = (*CAUSES, "unmodeled_disturbance")
CONTEXT = FEATURES[:6] + ("longest_temperature_gap_min",)
TEMPERATURE = FEATURES[:5] + FEATURES[6:16]
VIEWS = {"full": FEATURES, "context": CONTEXT, "temperature": TEMPERATURE}
THRESHOLDS = (.10, .20, .30, .40, .50, .60, .70, .80)
PROBES = {
    "full_logistic": ("full", "logistic", True),
    "full_hgb": ("full", "hgb", True),
    "temperature_hgb": ("temperature", "hgb", False),
    "context_hgb": ("context", "hgb", False),
    "shuffled_full_hgb": ("full", "hgb", False),
    "train_prior": ("context", "prior", False),
}


def validate_frame(frame):
    if tuple(frame.columns) != FEATURES or frame.empty:
        raise ValueError("exact nonempty event predictor contract required; no metadata/labels")
    if frame["product_id"].isna().any():
        raise ValueError("product_id required")
    numeric = frame.drop(columns="product_id").to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise ValueError("infinite predictors forbidden")


def targets(labels):
    matrix = np.zeros((len(labels), len(TARGETS)), dtype=int)
    for row, label in enumerate(labels):
        codes = label["injected_causes"]
        if len(codes) != len(set(codes)) or any(c not in TARGETS for c in codes):
            raise ValueError("unique supported injected causes required")
        for code in codes:
            matrix[row, TARGETS.index(code)] = 1
    return matrix


def make_pipeline(view, algorithm, seed=42):
    fields = VIEWS[view]
    numeric = [f for f in fields if f != "product_id"]
    transform = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median", keep_empty_features=True,
                                                       add_indicator=True)), ("scale", StandardScaler())]), numeric),
        ("product", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["product_id"]),
    ])
    if algorithm == "logistic":
        estimator = LogisticRegression(C=1, max_iter=1000, random_state=seed)
    elif algorithm == "hgb":
        # No hidden internal random split or early-stopping selection.
        estimator = HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15,
            learning_rate=.1, l2_regularization=1, early_stopping=False, random_state=seed)
    else:
        raise ValueError("unsupported baseline algorithm")
    return Pipeline([("observed_only", transform), ("classifier", OneVsRestClassifier(estimator, n_jobs=1))])


def probabilities(model, frame):
    validate_frame(frame)
    return validate_probabilities(model.predict_proba(frame))


def validate_probabilities(scores):
    scores = np.asarray(scores, dtype=float)
    if scores.ndim != 2 or scores.shape[1] != len(TARGETS) or not np.isfinite(scores).all() or (scores < 0).any() or (scores > 1).any():
        raise ValueError("finite eleven-label probabilities in [0,1] required")
    return scores


def choose_thresholds(validation_truth, validation_scores):
    scores = validate_probabilities(validation_scores)
    if np.shape(validation_truth) != scores.shape or not len(scores):
        raise ValueError("nonempty aligned validation required")
    # Independent F1 maximization also maximizes macro-F1 over this fixed grid.
    # On ties choose higher threshold; absent validation classes retain .5.
    chosen = []
    for column in range(len(TARGETS)):
        truth = validation_truth[:, column]
        if not truth.any():
            chosen.append(.5)
        else:
            candidates = THRESHOLDS
            # Constant positive prior must have both fire/no-fire choices even
            # for rare labels below grid minimum. No test data is consulted.
            values = np.unique(scores[:, column])
            if len(values) == 1 and values[0] > 0:
                candidates = (*THRESHOLDS, float(values[0]))
            chosen.append(max(candidates, key=lambda t: (f1_score(truth, scores[:, column] >= t, zero_division=0), t)))
    return np.asarray(chosen)


def predict_sets(scores, thresholds):
    scores = validate_probabilities(scores)
    thresholds = np.asarray(thresholds, dtype=float)
    if thresholds.shape != (len(TARGETS),) or not np.isfinite(thresholds).all() or (thresholds <= 0).any() or (thresholds > 1).any():
        raise ValueError("eleven finite thresholds in (0,1] required")
    return (scores >= thresholds).astype(int)


def _fraction(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def metrics(truth, scores, thresholds, labels):
    scores = validate_probabilities(scores)
    truth = np.asarray(truth, dtype=int)
    if truth.shape != scores.shape or len(labels) != len(truth) or not len(truth) or not np.isin(truth, [0, 1]).all():
        raise ValueError("aligned nonempty binary targets required")
    predicted = predict_sets(scores, thresholds)
    exact = np.all(truth == predicted, axis=1)
    p, r, f, support = precision_recall_fscore_support(truth, predicted, average=None, zero_division=0)
    counts = truth.sum(axis=1)
    groups = {"no_fault": counts == 0, "single": counts == 1, "multi": counts > 1,
              "unknown_present": truth[:, -1] == 1,
              "ambiguous": np.asarray([l["observationally_ambiguous"] for l in labels], dtype=bool)}
    report = {"events": len(truth), "exact_set_match": float(exact.mean()),
              "macro_f1_11": float(f.mean()), "micro_f1": float(f1_score(truth, predicted, average="micro", zero_division=0)),
              "hamming_loss": float((truth != predicted).mean()),
              "candidate_count_mean": float(predicted.sum(axis=1).mean()),
              "per_label": {name: {"support": int(support[i]), "predicted": int(predicted[:, i].sum()),
                  "precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i])} for i, name in enumerate(TARGETS)},
              "subgroups": {}}
    for name, mask in groups.items():
        n = int(mask.sum())
        correct_labels = int((truth[mask] * predicted[mask]).sum())
        total_labels = int(truth[mask].sum())
        report["subgroups"][name] = {"events": n,
            "exact_set_match": _fraction(int(exact[mask].sum()), n),
            "truth_label_recall": _fraction(correct_labels, total_labels),
            "all_truth_in_candidates": _fraction(int(np.all(predicted[mask] >= truth[mask], axis=1).sum()), n) if total_labels else None,
            "singleton_prediction_fraction": _fraction(int((predicted[mask].sum(axis=1) == 1).sum()), n)}
    normal = groups["no_fault"]
    unknown = groups["unknown_present"]
    report["normal_false_alarm_rate"] = _fraction(int((predicted[normal].sum(axis=1) > 0).sum()), int(normal.sum()))
    report["unknown_known_candidate_rate"] = _fraction(int((predicted[unknown, :-1].sum(axis=1) > 0).sum()), int(unknown.sum()))
    order = np.argsort(-scores, axis=1, kind="stable")
    top3 = np.zeros_like(truth)
    np.put_along_axis(top3, order[:, :3], 1, axis=1)
    report["top3_truth_label_recall"] = _fraction(int((truth * top3).sum()), int(truth.sum()))
    report["top3_denominator_fault_labels"] = int(truth.sum())
    report["top3_denominator_nonempty_events"] = int((counts > 0).sum())
    return report


def shuffle_family_sets(truth, indices, seed=42):
    """Negative control at whole-family level, preserving twin/multi structure.

    Permute families within product and family size. Exchangeability is not
    proven: this is a descriptive shortcut control, not a hypothesis p-value.
    """
    groups = {}
    for row, index in enumerate(indices):
        groups.setdefault(index["family_id"], []).append(row)
    strata = {}
    for rows in groups.values():
        strata.setdefault((indices[rows[0]]["product_id"], len(rows)), []).append(rows)
    result = truth.copy()
    rng = np.random.default_rng(seed)
    for families in strata.values():
        for destination, origin in zip(families, rng.permutation(len(families))):
            result[destination] = truth[families[origin]]
    return result


def family_bootstrap(truth, scores, thresholds, family_ids, repetitions=300, seed=42):
    if repetitions < 1 or len(family_ids) != len(truth):
        raise ValueError("aligned families and positive bootstrap repetitions required")
    groups = {}
    for row, family in enumerate(family_ids):
        groups.setdefault(family, []).append(row)
    members = list(groups.values())
    predicted = predict_sets(scores, thresholds)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(repetitions):
        rows = np.concatenate([members[i] for i in rng.integers(len(members), size=len(members))])
        values.append([f1_score(truth[rows], predicted[rows], average="macro", zero_division=0),
                       np.all(truth[rows] == predicted[rows], axis=1).mean()])
    bounds = np.quantile(values, [.025, .975], axis=0)
    return {"repetitions": repetitions, "families": len(members), "seed": seed,
            "macro_f1_11_percentile_95": bounds[:, 0].tolist(), "exact_set_match_percentile_95": bounds[:, 1].tolist(),
            "scope": "conditional synthetic-family resampling; no training/selection/generator or real-world uncertainty"}
