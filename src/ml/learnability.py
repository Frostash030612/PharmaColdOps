"""Exploratory cause-data audit, not fresh independent performance or causal proof."""
import hashlib
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, mutual_info_score
from sklearn.model_selection import GroupShuffleSplit, StratifiedShuffleSplit

from .contracts import FEATURES
from .formal import CAUSE_CONTEXT
from .evaluate import balanced_weights
from .training import make_pipeline


def profile_audit(x, y):
    """Empirical collisions are NOT a population/Bayes learnability bound."""
    if len(x) != len(y) or not len(y):
        raise ValueError("aligned nonempty data required")
    frame = x.copy()
    frame["_target"] = np.asarray(y)
    counts = frame.groupby(list(x.columns), dropna=False, observed=True)["_target"].value_counts()
    groups = counts.groupby(level=list(range(x.shape[1])))
    sizes = groups.sum()
    conflicts = groups.size() > 1
    minimum_errors = int((sizes - groups.max()).sum())
    return {
        "rows": len(y), "profiles": len(sizes), "singleton_profiles": int((sizes == 1).sum()),
        "singleton_row_fraction": float((sizes == 1).sum() / len(y)),
        "duplicate_extra_rows": int(len(y) - len(sizes)),
        "conflicting_profiles": int(conflicts.sum()),
        "rows_in_conflicting_profiles": int(sizes[conflicts].sum()),
        "observed_minimum_deterministic_errors": minimum_errors,
        "observed_error_floor_fraction": minimum_errors / len(y),
        "scope": "same observed feature profile; singleton-heavy empirical counts, NOT a population error floor",
    }


def fdr_bh(pvalues):
    values = np.asarray(pvalues, dtype=float)
    order = np.argsort(values)
    adjusted = values[order] * len(values) / np.arange(1, len(values) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result = np.empty_like(adjusted)
    result[order] = np.minimum(adjusted, 1)
    return result


def shuffle_within(y, strata, seed):
    """Copies labels; singleton strata remain unchanged, report limited power."""
    y, strata = np.asarray(y), np.asarray(strata)
    result = y.copy()
    rng = np.random.default_rng(seed)
    for value in np.unique(strata):
        indices = np.flatnonzero(strata == value)
        result[indices] = rng.permutation(y[indices])
    return result


def associations(x, y, *, permutations=99, seed=42, strata=None):
    if permutations < 1:
        raise ValueError("positive permutation count required")
    y = np.asarray(y)
    codes = pd.factorize(y, sort=True)[0]
    counts = np.bincount(codes)
    frequencies = counts / counts.sum()
    entropy = float(-(frequencies * np.log(frequencies)).sum())
    encoded, binning = {}, {}
    for key in x.columns:
        value = x[key]
        if pd.api.types.is_numeric_dtype(value) and value.nunique() > 12:
            value = pd.qcut(value, 10, duplicates="drop")
            binning[key] = "full-cohort unlabeled quantile bins, up to 10; descriptive only"
        else:
            binning[key] = "observed discrete values"
        encoded[key] = pd.factorize(value, sort=True)[0]
    rng = np.random.default_rng(seed)
    nulls = {key: [] for key in x.columns}
    strata = np.asarray(strata) if strata is not None else np.zeros(len(y), dtype=int)
    if len(strata) != len(y):
        raise ValueError("strata must align with labels")
    blocks = [np.flatnonzero(strata == group) for group in np.unique(strata)]
    conditional = lambda a, b: sum(len(i) / len(y) * mutual_info_score(a[i], b[i]) for i in blocks)
    conditional_nulls = {key: [] for key in x.columns}
    for _ in range(permutations):
        shuffled = rng.permutation(codes)
        blocked = shuffle_within(codes, strata, seed + 1000 + _)
        for key, values in encoded.items():
            nulls[key].append(mutual_info_score(values, shuffled))
            conditional_nulls[key].append(conditional(values, blocked))
    rows = []
    for key, values in encoded.items():
        score = float(mutual_info_score(values, codes))
        null = np.asarray(nulls[key])
        conditional_score = float(conditional(values, codes))
        conditional_null = np.asarray(conditional_nulls[key])
        rows.append({"feature": key, "unique_values": int(x[key].nunique()), "constant": x[key].nunique() == 1,
                     "mi_nats": score, "fraction_of_label_entropy": score / entropy if entropy else 0,
                     "null_mean_mi": float(null.mean()), "null_p95_mi": float(np.quantile(null, .95)),
                     "mi_above_null_mean": score - float(null.mean()),
                     "permutation_tail_fraction": float((1 + (null >= score - 1e-12).sum()) / (permutations + 1)),
                     "conditional_mi_nats": conditional_score,
                     "conditional_null_mean_mi": float(conditional_null.mean()),
                     "conditional_mi_above_null_mean": conditional_score - float(conditional_null.mean()),
                     "conditional_tail_fraction": float((1 + (conditional_null >= conditional_score - 1e-12).sum()) / (permutations + 1)),
                     "binning": binning[key]})
    for row, q in zip(rows, fdr_bh([r["permutation_tail_fraction"] for r in rows])):
        row["bh_adjusted_tail_fraction"] = float(q)
    for row, q in zip(rows, fdr_bh([r["conditional_tail_fraction"] for r in rows])):
        row["conditional_bh_adjusted_tail_fraction"] = float(q)
    return {"target_entropy_nats": entropy, "permutations": permutations, "rows": rows,
            "scope": "exploratory marginal association, not causality or feature-selection evidence; row exchangeability not established",
            "conditional_scope": "weighted within supplied source strata; not adjusted for all possible confounding",
            "multiple_comparison_note": "BH arithmetic supplied; monthly/group dependence prevents unqualified significance claims"}


def diagnostic_splits(data, repetitions=3, seed=42):
    if repetitions < 1 or repetitions > 3:
        raise ValueError("one to three predeclared repetitions supported")
    indices = np.arange(len(data.y))
    months = np.unique(data.months)
    if len(months) < 24:
        raise ValueError("24 months required for fixed rolling windows")
    splits = []
    for repetition in range(repetitions):
        rng_seed = seed + repetition
        train, validation = next(StratifiedShuffleSplit(1, test_size=.25, random_state=rng_seed).split(indices, data.y))
        splits.append(("random", repetition, train, validation))
        train, validation = next(GroupShuffleSplit(1, test_size=.25, random_state=rng_seed).split(indices, groups=data.groups))
        splits.append(("facility", repetition, train, validation))
        # Distinct six-month validation blocks: last 18..12, 12..6, 6..0.
        end = len(months) - (2 - repetition) * 6
        start = end - 6
        train = indices[data.months < months[start]]
        validation = indices[np.isin(data.months, months[start:end])]
        splits.append(("time", repetition, train, validation))
    for mode, _, train, validation in splits:
        validate_split(data, train, validation, mode)
    return splits


def validate_split(data, train, validation, mode):
    if not len(train) or not len(validation) or set(train) & set(validation):
        raise ValueError("empty or overlapping diagnostic roles")
    if mode == "facility" and set(data.groups[train]) & set(data.groups[validation]):
        raise ValueError("group leakage")
    if mode == "time" and data.months[train].max() >= data.months[validation].min():
        raise ValueError("future leakage")
    if set(data.y[train]) != set(data.y) or set(data.y[validation]) != set(data.y):
        raise ValueError("all declared classes required in both diagnostic roles")


def nested_subset(data, train, fraction, seed, mode):
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be (0,1]")
    train = np.asarray(train)
    rng = np.random.default_rng(seed)
    if mode == "facility":
        units = rng.permutation(np.unique(data.groups[train]))
        selected = train[np.isin(data.groups[train], units[:max(1, int(np.ceil(len(units) * fraction)))])]
    else:
        blocks = []
        for label in np.unique(data.y[train]):
            block = rng.permutation(train[data.y[train] == label])
            blocks.append(block[:max(1, int(np.ceil(len(block) * fraction)))])
        selected = np.concatenate(blocks)
    if set(data.y[selected]) != set(data.y):
        raise ValueError("subset misses target classes")
    return np.sort(selected)


def ranked_metrics(y, ranks, classes):
    y, ranks, classes = np.asarray(y), np.asarray(ranks), np.asarray(classes)
    if ranks.shape != (len(y), len(classes)):
        raise ValueError("rank matrix shape inconsistent")
    if not np.array_equal(np.sort(ranks, axis=1), np.tile(np.arange(len(classes)), (len(y), 1))):
        raise ValueError("each rank row must be a class permutation")
    predicted = classes[ranks[:, 0]]
    return {"top1": float(accuracy_score(y, predicted)),
            "macro_f1": float(f1_score(y, predicted, labels=classes, average="macro", zero_division=0)),
            "top3": float(np.mean([label in classes[row[:3]] for label, row in zip(y, ranks)]))}


def probability_metrics(y, probabilities, classes):
    probabilities = np.asarray(probabilities)
    if probabilities.shape != (len(y), len(classes)) or not np.isfinite(probabilities).all() or (probabilities < 0).any() or not np.allclose(probabilities.sum(axis=1), 1):
        raise ValueError("invalid probability matrix")
    return ranked_metrics(y, np.argsort(-probabilities, axis=1, kind="stable"), classes)


def baselines(y_train, y_validation, classes, seed, train_strata=None, validation_strata=None):
    classes = np.asarray(classes)
    counts = np.asarray([(np.asarray(y_train) == label).sum() for label in classes])
    if not counts.all():
        raise ValueError("all classes required")
    priors = counts / counts.sum()
    n = len(y_validation)
    ranks = np.tile(np.argsort(-priors, kind="stable"), (n, 1))
    result = {"empirical_prior": ranked_metrics(y_validation, ranks, classes)}
    # Exponential races give a seeded weighted random ranking without replacement;
    # Top-1 and Top-3 are consistent, not arbitrary ties in one-hot dummy outputs.
    for name, probability in [("stratified_random", priors), ("uniform_random", np.ones(len(classes)) / len(classes))]:
        rng = np.random.default_rng(seed)
        keys = -np.log(np.maximum(rng.random((n, len(classes))), 1e-12)) / probability
        result[name] = ranked_metrics(y_validation, np.argsort(keys, axis=1, kind="stable"), classes)
    if train_strata is not None:
        if len(train_strata) != len(y_train) or validation_strata is None or len(validation_strata) != n:
            raise ValueError("conditional prior roles must align")
        tables = {}
        for group in np.unique(train_strata):
            selected = np.asarray(y_train)[np.asarray(train_strata) == group]
            frequencies = np.asarray([(selected == label).sum() for label in classes], dtype=float)
            tables[group] = (frequencies + 1) / (len(selected) + len(classes))
        probabilities = np.asarray([tables.get(group, priors) for group in validation_strata])
        result["facility_level_prior"] = probability_metrics(y_validation, probabilities, classes)
        balanced = probabilities / priors
        balanced /= balanced.sum(axis=1, keepdims=True)
        result["facility_level_balanced_prior"] = probability_metrics(y_validation, balanced, classes)
        rng = np.random.default_rng(seed)
        keys = -np.log(np.maximum(rng.random((n, len(classes))), 1e-12)) / probabilities
        result["facility_level_random_prior"] = ranked_metrics(y_validation, np.argsort(keys, axis=1, kind="stable"), classes)
    return result


def fixed_probes():
    return {
        "lr_balanced": (LogisticRegression(C=1, max_iter=2000, random_state=42), True),
        "hgb_balanced": (HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=15, learning_rate=.08, random_state=42), True),
        "hgb_natural": (HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=15, learning_rate=.08, random_state=42), False),
        "hgb_fixed_budget": (HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=15, learning_rate=.08, early_stopping=False, random_state=42), True),
        "extra_trees_capacity": (ExtraTreesClassifier(n_estimators=200, min_samples_leaf=1, random_state=42, n_jobs=1), False),
    }


def fit_probe(data, train, validation, estimator, weighted, labels=None):
    if not set(data.x.columns) <= set(FEATURES["cause"]):
        raise ValueError("undeclared predictor or target leakage")
    y = data.y[train] if labels is None else np.asarray(labels)
    if len(y) != len(train) or set(y) != set(data.y):
        raise ValueError("training labels do not match role/classes")
    model = make_pipeline("cause", estimator, list(data.x.columns))
    kwargs = {"classifier__sample_weight": balanced_weights(y)} if weighted else {}
    model.fit(data.x.iloc[train], y, **kwargs)
    classes = np.unique(data.y)
    if not np.array_equal(model.classes_, classes):
        raise ValueError("class order changed")
    fitted = model.named_steps["classifier"]
    diagnostics = {"actual_iterations": int(np.max(fitted.n_iter_)) if hasattr(fitted, "n_iter_") else None,
                   "automatic_early_stopping_used": bool(fitted.do_early_stopping_) if hasattr(fitted, "do_early_stopping_") else None}
    return {"fit_diagnostics": diagnostics, "train": probability_metrics(y, model.predict_proba(data.x.iloc[train]), classes),
            "validation": probability_metrics(data.y[validation], model.predict_proba(data.x.iloc[validation]), classes)}


def subset_sha(indices):
    return hashlib.sha256(json.dumps(np.asarray(indices).tolist()).encode()).hexdigest()
