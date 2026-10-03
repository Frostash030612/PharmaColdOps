"""Audit evidence must not confuse collisions, memorization, priors or validation."""
import copy
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from ml.contracts import FEATURES
from ml.formal import Dataset
from ml.learnability import (associations, baselines, diagnostic_splits, fdr_bh, fit_probe,
                            fixed_probes, nested_subset, probability_metrics, profile_audit,
                            shuffle_within, validate_split)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_cause_learnability as audit


def fixture():
    n = 36 * 24
    month = np.repeat(np.arange(24253, 24289), 24)
    groups = np.array([f"G{i % 24}" for i in range(n)])
    values = {key: ["yes"] * n for key in FEATURES["cause"]}
    values.update(facility_level=np.where(np.arange(n) % 2, "hospital", "store"),
                  equipment_age_years=np.arange(n) % 12,
                  power_outage_hours_last_month=np.arange(n) % 6,
                  year=(month - 1) // 12, month=(month - 1) % 12 + 1)
    x = pd.DataFrame(values)
    y = np.array([["a", "b", "c"][(i // 24 + i % 24) % 3] for i in range(n)])
    return Dataset("cause", x, y, [f"C{i}" for i in range(n)], groups, month)


def test_collisions_are_empirical_and_do_not_mutate_input():
    x = pd.DataFrame({"v": [1, 1, 2, 3]})
    y = np.array(["a", "b", "a", "b"])
    before = x.copy(deep=True)
    result = profile_audit(x, y)
    assert result["conflicting_profiles"] == 1 and result["rows_in_conflicting_profiles"] == 2
    assert result["observed_minimum_deterministic_errors"] == 1
    assert result["singleton_row_fraction"] == .5
    assert "NOT a population" in result["scope"]
    pd.testing.assert_frame_equal(x, before)


def test_association_has_real_signal_null_constant_and_no_label_change():
    y = np.array(["a", "b"] * 100)
    x = pd.DataFrame({"signal": y, "constant": [1] * len(y), "noise": np.arange(len(y)) % 3})
    original = y.copy()
    values = associations(x, y, permutations=39)
    rows = {r["feature"]: r for r in values["rows"]}
    assert rows["signal"]["fraction_of_label_entropy"] == pytest.approx(1)
    assert rows["signal"]["mi_above_null_mean"] > .6
    assert rows["constant"]["mi_nats"] == 0 and rows["constant"]["permutation_tail_fraction"] == 1
    assert "exchangeability" in values["scope"]
    np.testing.assert_array_equal(y, original)


def test_fdr_arithmetic_and_stratum_preserving_control():
    np.testing.assert_allclose(fdr_bh([.01, .04, .03]), [.03, .04, .04])
    y = np.array(["a", "b", "a", "c", "d"])
    strata = np.array(["x", "x", "y", "y", "single"])
    original = y.copy()
    shuffled = shuffle_within(y, strata, 42)
    for group in np.unique(strata):
        assert sorted(shuffled[strata == group]) == sorted(y[strata == group])
    assert shuffled[-1] == "d"
    np.testing.assert_array_equal(y, original)


@pytest.mark.parametrize("mode", ["random", "facility", "time"])
def test_diagnostic_roles_and_learning_subsets_are_nested_and_reproducible(mode):
    data = fixture()
    splits = [s for s in diagnostic_splits(data) if s[0] == mode]
    again = [s for s in diagnostic_splits(data) if s[0] == mode]
    for (_, repetition, pool, validation), (_, _, other, other_val) in zip(splits, again):
        np.testing.assert_array_equal(pool, other)
        np.testing.assert_array_equal(validation, other_val)
        validate_split(data, pool, validation, mode)
        previous = set()
        for fraction in [.1, .25, .5, 1]:
            part = nested_subset(data, pool, fraction, 100 + repetition, mode)
            assert previous <= set(part) <= set(pool) and not set(part) & set(validation)
            assert set(data.y[part]) == set(data.y)
            previous = set(part)
        assert previous == set(pool)
    if mode == "time":
        months = [set(data.months[s[3]]) for s in splits]
        assert all(not months[i] & months[j] for i in range(3) for j in range(i))


def test_role_leakage_and_invalid_fraction_fail_closed():
    data = fixture()
    with pytest.raises(ValueError, match="overlapping"):
        validate_split(data, np.arange(20), np.arange(10), "random")
    with pytest.raises(ValueError, match="future"):
        validate_split(data, np.arange(20, 30), np.arange(10), "time")
    with pytest.raises(ValueError):
        nested_subset(data, np.arange(100), 0, 42, "random")


def test_baselines_have_seeded_rankings_and_training_only_priors():
    classes = np.array(["a", "b", "c", "d"])
    train = np.array(["a"] * 60 + ["b"] * 20 + ["c"] * 15 + ["d"] * 5)
    validation = np.tile(classes, 100)
    first = baselines(train, validation, classes, 42)
    assert first == baselines(train, validation, classes, 42)
    assert first["empirical_prior"]["top1"] == .25
    assert first["empirical_prior"]["top3"] == .75
    for values in first.values():
        assert values["top3"] >= values["top1"]


def test_fixed_probes_do_not_share_fitted_preprocessors_or_mutate_validation_labels():
    data = fixture()
    mode, _, train, validation = diagnostic_splits(data, repetitions=1)[0]
    changed = copy.deepcopy(data)
    changed.y[validation] = np.random.default_rng(10).permutation(changed.y[validation])
    with threadpool_limits(limits=1):
        estimator = LogisticRegression(max_iter=2000, random_state=42)
        first = fit_probe(data, train, validation, estimator, True)
        second = fit_probe(changed, train, validation, estimator, True)
    assert first["train"] == second["train"]
    assert not hasattr(estimator, "classes_")
    assert set(fixed_probes()) >= {"lr_balanced", "hgb_balanced", "hgb_natural", "extra_trees_capacity"}
    forbidden = copy.deepcopy(data)
    forbidden.x["excursion_cause"] = forbidden.y
    with pytest.raises(ValueError, match="leakage"):
        fit_probe(forbidden, train, validation, estimator, True)


def test_rank_scores_use_fixed_class_support_and_top3_contains_top1():
    classes = np.array(["a", "b", "c", "d"])
    values = probability_metrics(np.array(["a", "b"]), np.array([[.4, .3, .2, .1], [.2, .4, .3, .1]]), classes)
    assert values["top1"] == values["top3"] == 1
    assert values["macro_f1"] == .5  # absent classes still included


def test_effort_allocation_is_declared_budget_rule_not_population_proof():
    summary = {"random": {"extra_trees_capacity": {"paired_baseline_gains": {"macro_f1": .01}, "macro_f1_gap_mean": .8}}}
    rows = [{"mode": "random", "probe": name, "repetition": 0, "fraction": fraction,
             "validation": {"macro_f1": value}}
            for name in ["hgb_fixed_budget"] for fraction, value in [(.25, .14), (1, .13)]]
    result = audit.allocation_decision(summary, rows)
    assert result["priority"] == "event_level_simulation_data_first"
    assert "not a Bayes ceiling" in result["scope"]


def test_fresh_audit_cannot_overwrite_existing_reports(tmp_path):
    output = tmp_path / "old"
    output.mkdir()
    (output / "report.json").write_text('{"old":true}')
    with pytest.raises(ValueError, match="fresh output"):
        audit.run(output)
    assert (output / "report.json").read_text() == '{"old":true}'


def test_conditioning_removes_a_source_alias_without_claiming_label_randomness():
    strata = np.array(["hospital"] * 100 + ["store"] * 100)
    y = np.array(["a"] * 100 + ["b"] * 100)
    x = pd.DataFrame({"source_alias": strata})
    row = associations(x, y, strata=strata, permutations=19)["rows"][0]
    assert row["mi_nats"] > .6 and row["conditional_mi_nats"] == 0
    assert row["conditional_tail_fraction"] == 1


def test_conditional_priors_fit_training_counts_and_fall_back_for_unseen_groups():
    classes = np.array(["a", "b", "c", "d"])
    train = np.array(["a"] * 30 + ["b"] * 10 + ["c"] * 20 + ["d"] * 20)
    levels = np.array(["hospital"] * 40 + ["store"] * 40)
    val_y = np.array(["a", "c", "a"])
    val_levels = np.array(["hospital", "store", "unseen"])
    result = baselines(train, val_y, classes, 42, levels, val_levels)
    assert result["facility_level_prior"]["top1"] == 1
    assert result["facility_level_prior"]["top3"] == 1


def test_invalid_probability_matrix_is_not_scored_as_a_valid_model():
    with pytest.raises(ValueError, match="probability"):
        probability_metrics(["a"], [[1, 1]], ["a", "b"])
