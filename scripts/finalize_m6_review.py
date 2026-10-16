"""Coordinate a frozen two-person M6 review without filling human judgements.

Missing inputs produce a pending inventory and a blank process-record template.
Complete files still require declared sealing/source checks before official scoring.
The declarations are self-reported; this tool cannot authenticate people or history.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_m6_independent as evaluator

PACKET = ROOT / "data/qa/m6-review-20261003-v3/coordinator/predictions.private.json"
MARKERS = {
    "docs/M6独立评估.md": ["M6_COORDINATOR_RESULT"],
    "docs/FINAL_REPORT_EN.md": ["M6_HUMAN_RESULTS", "M6_ABSTRACT_STATUS"],
}


def read_packet(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    saved = value.pop("packet_sha256")
    if evaluator.sha(value) != saved or value.get("schema") != "m6-blind-packet-v1":
        raise ValueError("invalid frozen packet or fingerprint")
    if value.get("unit_fixture_not_real_human_evaluation"):
        raise ValueError("unit fixtures cannot become a formal handoff report")
    value["packet_sha256"] = saved
    return value


def template(manifest, annotations, paths):
    reviewers = {}
    for role in ("A", "B"):
        intent, ratings = f"intent_{role.lower()}", f"ratings_{role.lower()}"
        first = next(iter(annotations[intent].values()))["annotator_id"] if intent in annotations else ""
        reviewers[role] = {"annotator_id": first, "human_confirmed": None,
                           "independent_intent_confirmed": None, "sources_consulted_confirmed": None,
                           "intent_sealed_at": "", "ratings_submitted_at": "",
                           "intent_sha256": evaluator.file_sha(paths[intent]) if intent in annotations else "",
                           "ratings_sha256": evaluator.file_sha(paths[ratings]) if ratings in annotations else ""}
    return {"schema": "m6-human-review-process-v1", "packet_sha256": manifest["packet_sha256"],
            "coordinator_id": "", "answers_disclosed_at": "", "reviewers": reviewers,
            "notes": "Record actual history and consulted replacement sources. Do not invent missing seal times."}


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("review timestamps require an explicit timezone")
    return result


def validate_process(record, manifest, annotations, paths):
    if record.get("schema") != "m6-human-review-process-v1" or record.get("packet_sha256") != manifest["packet_sha256"]:
        raise ValueError("process record belongs to a different packet/schema")
    if not record.get("coordinator_id", "").strip():
        raise ValueError("coordinator identity is missing")
    disclosed = timestamp(record.get("answers_disclosed_at", ""))
    actors = []
    for role in ("A", "B"):
        data = record.get("reviewers", {}).get(role, {})
        actor = next(iter(annotations[f"intent_{role.lower()}"].values()))["annotator_id"]
        if data.get("annotator_id") != actor:
            raise ValueError("process reviewer does not match submitted annotations")
        actors.append(actor)
        if any(data.get(key) is not True for key in ["human_confirmed", "independent_intent_confirmed", "sources_consulted_confirmed"]):
            raise ValueError("human independence or actual source consultation has not been confirmed")
        if timestamp(data.get("intent_sealed_at", "")) > disclosed:
            raise ValueError("intent labels must be sealed before answers are disclosed")
        if timestamp(data.get("ratings_submitted_at", "")) < disclosed:
            raise ValueError("answer ratings cannot precede answer disclosure")
        for phase in ("intent", "ratings"):
            key = f"{phase}_{role.lower()}"
            if data.get(phase + "_sha256") != evaluator.file_sha(paths[key]):
                raise ValueError("sealed annotation hash differs from submitted file")
        rating_actor = next(iter(annotations[f"ratings_{role.lower()}"].values()))["annotator_id"]
        if rating_actor != actor:
            raise ValueError("phase reviewer identities must agree")
    if len(set(actors)) != 2:
        raise ValueError("independent reviewers must differ")


def disagreements(a, b, manifest):
    questions = {q["question_id"]: q["question"] for q in manifest["questions"]}
    return [{"question_id": qid, "question": questions[qid],
             "label_A": a[qid]["expected_intent"], "acceptable_A": a[qid].get("acceptable_intents", ""),
             "note_A": a[qid].get("note", ""), "label_B": b[qid]["expected_intent"],
             "acceptable_B": b[qid].get("acceptable_intents", ""), "note_B": b[qid].get("note", "")}
            for qid in a if (a[qid]["expected_intent"], a[qid].get("acceptable_intents", ""))
            != (b[qid]["expected_intent"], b[qid].get("acceptable_intents", ""))]


def summary(result):
    return ("Frozen v1 independent evaluation on supplied human annotations: "
            f"{result['rows']} questions, {result['unambiguous_denominator']} in the single-label denominator, "
            f"{result['ambiguous_excluded_explicitly']} explicitly ambiguous exclusions. "
            f"Intent accuracy {result['intent_accuracy']:.4f}; macro-F1 "
            f"{result['intent_classification_report']['macro avg']['f1-score']:.4f}; "
            f"human-human kappa {result['human_human_kappa']}. "
            f"Both-raters answer adequacy {result['independent_answer_adequacy_rate_both_raters']:.4f}. "
            "Detailed ordinal evidence scores, NA counts and denominators are retained in report.json. "
            "Reviewer identity, independence, timestamps and source consultation are self-declared, not authenticated. "
            "These results concern the unchanged 2026-10-03 frozen answers, not the repaired current router or natural user-population accuracy.")


def replace_block(text, marker, content):
    start, end = f"<!-- {marker}_START -->", f"<!-- {marker}_END -->"
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) >= text.index(end):
        raise ValueError("missing or duplicate machine-owned report markers")
    return text[:text.index(start)+len(start)] + "\n\n" + content + "\n\n" + text[text.index(end):]


def update_docs(result):
    replacements = {}
    for relative, markers in MARKERS.items():
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            content = summary(result) if marker != "M6_ABSTRACT_STATUS" else (
                "M6's frozen v1 answers now have supplied two-reviewer annotations and a self-declared process record. "
                "Section 6.5 reports denominators and results. This does not independently validate the repaired current system.")
            text = replace_block(text, marker, content)
        replacements[path] = text
    # Resolve every marker before writing any file. This does not render Office artifacts.
    for path, text in replacements.items():
        path.write_text(text, encoding="utf-8")


def run(paths, packet, output, process_record=None, adjudication=None, apply_docs=False):
    if output.exists():
        raise FileExistsError("fresh output required")
    manifest = read_packet(packet)
    annotations, missing = {}, []
    for key, path in paths.items():
        if path is None or not path.is_file():
            missing.append(key)
        else:
            annotations[key] = evaluator.read_annotations(path, manifest, "intent" if key.startswith("intent") else "ratings")
    output.mkdir(parents=True)
    evaluator.dump(output / "process-record-template.json", template(manifest, annotations, paths))
    conflicts = []
    if "intent_a" in annotations and "intent_b" in annotations:
        conflicts = disagreements(annotations["intent_a"], annotations["intent_b"], manifest)
        evaluator.csv_write(output / "intent-disagreements.csv", ["question_id", "question", "label_A", "acceptable_A", "note_A", "label_B", "acceptable_B", "note_B"], conflicts)
        evaluator.csv_write(output / "adjudication-template.csv", ["question_id", "packet_sha256", "adjudicator_id", "expected_intent", "note"],
                            [{"question_id": row["question_id"], "packet_sha256": manifest["packet_sha256"],
                              "adjudicator_id": "", "expected_intent": "", "note": ""} for row in conflicts])
    result = {"status": "awaiting_inputs", "missing": missing, "validated_files": list(annotations),
              "packet_sha256": manifest["packet_sha256"], "intent_disagreement_count": len(conflicts), "human_metrics": None}
    if not missing:
        if process_record is None:
            result["status"] = "awaiting_process_record"
        else:
            record = json.loads(process_record.read_text(encoding="utf-8"))
            validate_process(record, manifest, annotations, paths)
            if conflicts and adjudication is None:
                result["status"] = "awaiting_human_adjudication"
            else:
                result = evaluator.score(packet, paths["intent_a"], paths["intent_b"], paths["ratings_a"], paths["ratings_b"], adjudication)
                if result["packet_sha256"] != manifest["packet_sha256"]:
                    raise ValueError("packet changed during finalization")
                for role in ("A", "B"):
                    for phase in ("intent", "ratings"):
                        path = paths[f"{phase}_{role.lower()}"]
                        if result["annotation_hashes"][str(path)] != record["reviewers"][role][phase + "_sha256"]:
                            raise ValueError("annotations changed after process validation")
                result["process_record_sha256"] = evaluator.file_sha(process_record)
                result["process_declarations_self_reported"] = True
                evaluator.dump(output / "report.json", result)
                (output / "report-section.md").write_text(summary(result) + "\n", encoding="utf-8")
                if apply_docs:
                    update_docs(result)
    evaluator.dump(output / "status.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=PACKET)
    parser.add_argument("--intent-a", type=Path, default=ROOT / "data/qa/m6-completed-20261016-intent-A.csv")
    parser.add_argument("--ratings-a", type=Path, default=ROOT / "data/qa/m6-completed-20261016-ratings-A.csv")
    parser.add_argument("--intent-b", type=Path)
    parser.add_argument("--ratings-b", type=Path)
    parser.add_argument("--process-record", type=Path)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--update-docs", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {key: getattr(args, key) for key in ("intent_a", "intent_b", "ratings_a", "ratings_b")}
    try:
        result = run(paths, args.packet, args.output, args.process_record, args.adjudication, args.update_docs)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"M6 review cannot be finalized: {error}\n")
    print(json.dumps({"status": result["status"], "missing": result.get("missing", []),
                      "scope": "frozen answers; self-reported human process; not repaired-router accuracy"}))
    return 0 if result["status"] == "scored_on_supplied_human_annotations" else 1


if __name__ == "__main__":
    raise SystemExit(main())
