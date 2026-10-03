"""Selection discipline, candidate semantics and distinct event ML contract."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from ml.event_simulation import FEATURES
from ml.event_baselines import (TARGETS, choose_thresholds, family_bootstrap, make_pipeline,
    metrics, predict_sets, probabilities, shuffle_family_sets, targets, validate_frame)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate_event_baselines as evaluation
from generate_event_dataset import create


def labels():
    return [{"injected_causes": codes, "observationally_ambiguous": ambiguous} for codes, ambiguous in
            [([], False), ([TARGETS[0]], False), ([TARGETS[0], TARGETS[1]], False),
             ([TARGETS[-1]], False), (["door_left_open"], True), (["staff_error"], True)]]


def frame(rows=30):
    rng = np.random.default_rng(42)
    value = pd.DataFrame({f: rng.normal(size=rows) for f in FEATURES if f != "product_id"})
    value["product_id"] = ["A", "B"] * (rows // 2)
    return value[list(FEATURES)]


@pytest.mark.parametrize("change", ["extra", "missing", "reordered", "infinite", "no_product", "empty"])
def test_predictor_contract_rejects_metadata_or_invalid_input(change):
    value = frame()
    if change == "extra":
        value["family_id"] = "metadata"
    elif change == "missing":
        value = value.drop(columns="known_hot_min")
    elif change == "reordered":
        value = value[list(reversed(FEATURES))]
    elif change == "infinite":
        value.loc[0, "known_hot_min"] = np.inf
    elif change == "no_product":
        value.loc[0, "product_id"] = None
    else:
        value = value.iloc[:0]
    with pytest.raises(ValueError):
        validate_frame(value)


def test_labels_keep_normal_unknown_multi_and_ambiguous():
    truth = targets(labels())
    assert truth.shape == (6, 11)
    assert truth.sum(axis=1).tolist() == [0, 1, 2, 1, 1, 1]
    assert truth[3, -1] == 1
    for codes in [["hidden-plan-code"], [TARGETS[0], TARGETS[0]]]:
        with pytest.raises(ValueError):
            targets([{"injected_causes": codes}])


def test_candidate_metrics_retain_all_denominators_and_penalize_wrong_sets():
    truth = targets(labels())
    scores = truth.astype(float)
    # Same evidence produces both door and staff candidates for either member.
    scores[4:6, TARGETS.index("door_left_open")] = 1
    scores[4:6, TARGETS.index("staff_error")] = 1
    report = metrics(truth, scores, np.full(11, .5), labels())
    assert report["events"] == 6 and report["exact_set_match"] == pytest.approx(4 / 6)
    assert report["subgroups"]["ambiguous"]["events"] == 2
    assert report["subgroups"]["ambiguous"]["exact_set_match"] == 0
    assert report["subgroups"]["ambiguous"]["all_truth_in_candidates"] == 1
    assert report["subgroups"]["ambiguous"]["singleton_prediction_fraction"] == 0
    assert report["normal_false_alarm_rate"] == 0
    assert report["subgroups"]["no_fault"]["all_truth_in_candidates"] is None
    assert report["subgroups"]["multi"]["events"] == 1
    assert report["subgroups"]["unknown_present"]["events"] == 1
    assert report["top3_denominator_fault_labels"] == 6
    scores[0, 0] = 1
    scores[3, 0] = 1
    report = metrics(truth, scores, np.full(11, .5), labels())
    assert report["normal_false_alarm_rate"] == report["unknown_known_candidate_rate"] == 1


def test_absent_subgroups_report_null_not_zero_or_success():
    single = labels()[1:2]
    truth = targets(single)
    result = metrics(truth, truth, np.full(11, .5), single)
    assert result["normal_false_alarm_rate"] is None
    assert result["subgroups"]["multi"]["events"] == 0
    assert result["subgroups"]["multi"]["exact_set_match"] is None


def test_validation_threshold_ties_and_absent_labels():
    truth = np.zeros((2, 11), dtype=int)
    truth[0, 0] = 1
    scores = np.zeros((2, 11))
    scores[:, 0] = [.8, .05]
    thresholds = choose_thresholds(truth, scores)
    assert thresholds[0] == .8 and np.all(thresholds[1:] == .5)
    assert np.array_equal(predict_sets(scores, thresholds), truth)


def test_rare_constant_prior_can_fire_below_grid_minimum():
    truth = np.zeros((20, 11), dtype=int)
    truth[0, 0] = 1
    scores = np.zeros((20, 11))
    scores[:, 0] = .03
    thresholds = choose_thresholds(truth, scores)
    assert thresholds[0] == .03
    assert predict_sets(scores, thresholds)[:, 0].sum() == 20


@pytest.mark.parametrize("bad", [np.full((3, 11), np.nan), np.full((3, 11), 1.1), np.zeros((3, 10))])
def test_bad_probability_shapes_or_values_rejected(bad):
    with pytest.raises(ValueError):
        predict_sets(bad, np.full(11, .5))


@pytest.mark.parametrize("bad", [np.full(11, 0), np.full(10, .5), np.full(11, np.nan)])
def test_invalid_thresholds_rejected(bad):
    with pytest.raises(ValueError):
        predict_sets(np.zeros((3, 11)), bad)


@pytest.mark.parametrize("view", ["full", "context", "temperature"])
@pytest.mark.parametrize("algorithm", ["logistic", "hgb"])
def test_unseen_categories_and_missing_values_use_train_only_transforms(view, algorithm):
    train = frame()
    train.loc[:4, "temperature_offset_mean_c"] = np.nan
    truth = np.tile(np.arange(30)[:, None] % 2, (1, 11))
    model = make_pipeline(view, algorithm)
    with threadpool_limits(limits=1):
        model.fit(train, truth)
        statistics = model.named_steps["observed_only"].named_transformers_["numeric"].named_steps["impute"].statistics_.copy()
        validation = train.copy()
        validation["product_id"] = "UNSEEN"
        validation["known_hot_min"] = 1000000
        validation.loc[0, "known_cold_min"] = np.nan
        scores = probabilities(model, validation)
    assert scores.shape == (30, 11)
    assert np.array_equal(statistics, model.named_steps["observed_only"].named_transformers_["numeric"].named_steps["impute"].statistics_)


def test_shuffle_preserves_family_size_product_and_multilabel_counts():
    indices = [{"family_id": str(i // 2), "product_id": "A" if i < 8 else "B"} for i in range(12)]
    truth = np.zeros((12, 11), dtype=int)
    for i in range(12):
        truth[i, i // 2] = 1
        truth[i, 10] = i // 2 % 2
    shuffled = shuffle_family_sets(truth, indices)
    assert np.array_equal(shuffled, shuffle_family_sets(truth, indices))
    assert not np.array_equal(shuffled, truth)
    for low, high in [(0, 8), (8, 12)]:
        assert np.array_equal(shuffled[low:high].sum(axis=0), truth[low:high].sum(axis=0))
    assert all(np.array_equal(shuffled[i], shuffled[i + 1]) for i in range(0, 12, 2))


def test_bootstrap_is_family_clustered_and_reproducible():
    truth = targets(labels())
    kwargs = dict(repetitions=20, seed=42)
    first = family_bootstrap(truth, truth, np.full(11, .5), ["a", "b", "c", "d", "e", "e"], **kwargs)
    assert first == family_bootstrap(truth, truth, np.full(11, .5), ["a", "b", "c", "d", "e", "e"], **kwargs)
    assert first["families"] == 5 and first["exact_set_match_percentile_95"] == [1, 1]


def test_smoke_run_freezes_selection_before_test_scoring_and_leaves_source_unchanged(tmp_path, monkeypatch):
    dataset, output = tmp_path / "dataset", tmp_path / "experiment"
    manifest = create(dataset, events=180, seed=42)
    before = evaluation.digest(dataset / "manifest.json")
    monkeypatch.setattr(evaluation, "PROBES", {"full_logistic": ("full", "logistic", True),
                                            "train_prior": ("context", "prior", False)})
    original = evaluation.load_role
    opened = []
    def guarded(path, role):
        if role.startswith("test_"):
            assert (output / "selection-frozen.json").exists()
            assert (output / "selected-experimental-model.joblib").exists()
        opened.append(role)
        return original(path, role)
    monkeypatch.setattr(evaluation, "load_role", guarded)
    report = evaluation.run(dataset, output, bootstrap=5)
    assert opened[:2] == ["train", "validation"] and len(opened) == 6
    assert report["status"] == "complete" and report["serving_integration"] is False
    assert report["dataset_unchanged"] and evaluation.digest(dataset / "manifest.json") == before
    for name, fingerprint in manifest["file_sha256"].items():
        assert evaluation.digest(dataset / name) == fingerprint
    assert len(list(output.glob("test_*-full_logistic.jsonl"))) == 4
    frozen = json.loads((output / "selection-frozen.json").read_text())
    assert frozen["promotion"] is False
    with pytest.raises(ValueError, match="fresh"):
        evaluation.run(dataset, output)
