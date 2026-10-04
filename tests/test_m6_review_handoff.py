"""Committed frozen inputs must be sufficient without local generated artifacts.

These checks validate delivery integrity, never supply human gold or scores.
"""
import csv
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_m6_independent as m6

PACK = ROOT / "data/qa/m6-review-20261003-v3"
FINGERPRINT = "78728725328b5b09f59164fc408a31c7d1607c90e656f6673a0924b988eff134"


def rows(relative):
    with (PACK / relative).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def packet():
    return json.loads((PACK / "coordinator/predictions.private.json").read_text(encoding="utf-8"))


def test_frozen_packet_integrity_and_no_claim_of_completed_human_review():
    manifest = packet()
    saved = manifest.pop("packet_sha256")
    assert saved == FINGERPRINT == m6.sha(manifest)
    assert manifest["schema"] == "m6-blind-packet-v1"
    assert manifest["human_gold_available"] is False
    assert len(manifest["questions"]) == len(manifest["responses"]) == 53
    assert len({q["question_id"] for q in manifest["questions"]}) == 53


def test_blind_questions_and_templates_do_not_contain_predictions():
    questions = rows("blind-intent/questions.csv")
    manifest = packet()
    assert len(questions) == 53
    assert set(questions[0]) == {"question_id", "question", "lang", "packet_sha256"}
    expected = {q["question_id"]: q for q in manifest["questions"]}
    assert {q["question_id"] for q in questions} == set(expected)
    for q in questions:
        assert q["packet_sha256"] == FINGERPRINT
        assert (q["question"], q["lang"]) == (expected[q["question_id"]]["question"], expected[q["question_id"]]["lang"])
    for actor in ("A", "B"):
        labels = rows(f"blind-intent/intent-{actor}.csv")
        assert len(labels) == 53
        assert [{k: r[k] for k in questions[0]} for r in labels] == questions
        assert all(not r[k] for r in labels for k in ("annotator_id", "expected_intent", "acceptable_intents", "note"))


def test_answer_snapshot_and_rating_templates_match_the_same_packet():
    manifest = packet()
    responses = json.loads((PACK / "answer-review/responses.json").read_text(encoding="utf-8"))
    hidden = {"predicted_intent", "source", "latency_seconds", "origin"}
    assert responses == [{k: v for k, v in r.items() if k not in hidden} for r in manifest["responses"]]
    expected = {r["question_id"]: r for r in responses}
    for actor in ("A", "B"):
        ratings = rows(f"answer-review/ratings-{actor}.csv")
        assert len(ratings) == 53
        assert {r["question_id"] for r in ratings} == set(expected)
        for r in ratings:
            assert r["packet_sha256"] == FINGERPRINT
            assert r["response_sha256"] == expected[r["question_id"]]["response_sha256"]
            assert all(not r[k] for k in ["annotator_id", *m6.RATINGS, "relevant_evidence_ids", "checked_source_urls", "note"])
    sources = json.loads((PACK / "answer-review/reference-sources.json").read_text(encoding="utf-8"))
    assert all(sources[k] for k in ("regulations", "sops", "rules_config"))
    adjudication = rows("coordinator/adjudication-template.csv")
    assert len(adjudication) == 53
    assert {r["question_id"] for r in adjudication} == set(expected)
    assert all(r["packet_sha256"] == FINGERPRINT for r in adjudication)
    assert all(not r[k] for r in adjudication for k in ("adjudicator_id", "expected_intent", "note"))


def test_only_required_inputs_and_no_credential_fields_are_shipped():
    expected = {
        "README.md", "INSTRUCTIONS.md", "blind-intent/questions.csv",
        "blind-intent/intent-A.csv", "blind-intent/intent-B.csv",
        "answer-review/responses.json", "answer-review/reference-sources.json",
        "answer-review/ratings-A.csv", "answer-review/ratings-B.csv",
        "coordinator/adjudication-template.csv", "coordinator/predictions.private.json",
    }
    assert {p.relative_to(PACK).as_posix() for p in PACK.rglob("*") if p.is_file()} == expected

    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert not re.search(r"password|secret|credential|access_token|api_key", key, re.I)
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
        elif isinstance(value, str):
            assert not re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", value)
            assert not re.search(r"[a-z]+://[^\s/]+:[^\s/@]+@", value, re.I)

    for path in PACK.rglob("*.json"):
        inspect(json.loads(path.read_text(encoding="utf-8")))


def test_blank_committed_templates_are_refused_without_online_queries(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("existing packet scoring must not query the live service")

    monkeypatch.setattr(m6.service, "qa_view", forbidden)
    with pytest.raises(ValueError, match="human annotator identity missing"):
        m6.score(
            PACK / "coordinator/predictions.private.json",
            PACK / "blind-intent/intent-A.csv", PACK / "blind-intent/intent-B.csv",
            PACK / "answer-review/ratings-A.csv", PACK / "answer-review/ratings-B.csv",
        )
