"""Descriptive closeout must not bypass the independent-evaluation process."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import summarize_m6_review as descriptive


def inputs(tmp_path):
    # Existing public non-blind worksheets exercise format validation only.
    paths = {"intent_a": ROOT / "data/qa/m6-completed-20261016-intent-A.csv",
             "ratings_a": ROOT / "data/qa/m6-completed-20261016-ratings-A.csv",
             "intent_b": ROOT / "data/qa/m6-review-B-20261023/intent-B.csv",
             "ratings_b": ROOT / "data/qa/m6-review-B-20261023/ratings-B.csv"}
    record = {"schema": "m6-descriptive-closeout-process-v1", "method": "descriptive_comparison",
              "packet_sha256": descriptive.workflow.read_packet(descriptive.workflow.PACKET)["packet_sha256"],
              "annotation_hashes": {k: descriptive.workflow.evaluator.file_sha(p) for k, p in paths.items()},
              "limitations": ["Non-blind fixture inputs. No independent metrics."]}
    path = tmp_path / "process.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return paths, path


def test_descriptive_closeout_retains_distributions_without_gold_or_independent_scores(tmp_path):
    paths, record = inputs(tmp_path)
    before = {k: p.read_bytes() for k, p in paths.items()}
    result = descriptive.summarize(paths, descriptive.workflow.PACKET, record, tmp_path / "out")
    assert result["status"] == "complete_descriptive_review"
    assert result["rows_per_reviewer"] == 53
    assert result["independent_metrics"] is None and result["adjudicated_gold"] is None
    assert result["independent_protocol_complete"] is False
    assert result["process_record_sha256"] == descriptive.workflow.evaluator.file_sha(tmp_path / "out/process-record.json")
    assert "intent_accuracy" not in result and "human_human_kappa" not in result
    assert result["rating_distributions"]["A"]["answer_correctness"] == {"0": 4, "1": 21, "2": 28}
    assert all(sum(counts.values()) == 53 for role in result["rating_distributions"].values() for counts in role.values())
    assert all(p.read_bytes() == before[k] for k, p in paths.items())
    with pytest.raises(FileExistsError):
        descriptive.summarize(paths, descriptive.workflow.PACKET, record, tmp_path / "out")


def test_changed_submitted_file_cannot_reuse_process_hashes(tmp_path):
    paths, record = inputs(tmp_path)
    changed = tmp_path / "ratings.csv"
    changed.write_bytes(paths["ratings_b"].read_bytes() + b"\n")
    paths["ratings_b"] = changed
    with pytest.raises(ValueError, match="hashes differ"):
        descriptive.summarize(paths, descriptive.workflow.PACKET, record, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_wrong_packet_or_missing_limitations_fails_before_creating_report(tmp_path):
    paths, record = inputs(tmp_path)
    value = json.loads(record.read_text())
    value["limitations"] = []
    record.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="limitations"):
        descriptive.summarize(paths, descriptive.workflow.PACKET, record, tmp_path / "out")
    value["packet_sha256"] = "other"
    record.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="different packet"):
        descriptive.summarize(paths, descriptive.workflow.PACKET, record, tmp_path / "out")


def test_descriptive_report_is_not_an_independent_process_record(tmp_path):
    paths, record = inputs(tmp_path)
    result = descriptive.summarize(paths, descriptive.workflow.PACKET, record, tmp_path / "out")
    with pytest.raises(ValueError, match="different packet/schema"):
        descriptive.workflow.validate_process(result, {"packet_sha256": result["packet_sha256"]}, {}, {})
