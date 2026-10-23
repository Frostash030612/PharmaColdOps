"""Close a descriptive M6 review without claiming independent human metrics.

The original independent score/finalize gates remain unchanged. Inputs and output
belong in private handoff storage; this command never edits reviewer judgements.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import finalize_m6_review as workflow


def summarize(paths, packet, process_record, output):
    if output.exists():
        raise FileExistsError("fresh output required")
    manifest = workflow.read_packet(packet)
    annotations = {
        key: workflow.evaluator.read_annotations(path, manifest, "intent" if key.startswith("intent") else "ratings")
        for key, path in paths.items()
    }
    actors = {}
    for role in ("a", "b"):
        actor = next(iter(annotations["intent_" + role].values()))["annotator_id"]
        if next(iter(annotations["ratings_" + role].values()))["annotator_id"] != actor:
            raise ValueError("phase reviewer identities must agree")
        actors[role] = actor
    if actors["a"] == actors["b"]:
        raise ValueError("reviewer identities must differ")
    record = json.loads(process_record.read_text(encoding="utf-8"))
    if record.get("schema") != "m6-descriptive-closeout-process-v1" or record.get("packet_sha256") != manifest["packet_sha256"]:
        raise ValueError("process record belongs to a different packet/schema")
    hashes = {key: workflow.evaluator.file_sha(path) for key, path in paths.items()}
    if record.get("annotation_hashes") != hashes:
        raise ValueError("process record annotation hashes differ")
    if record.get("method") != "descriptive_comparison" or not record.get("limitations"):
        raise ValueError("descriptive method and limitations must be explicit")
    conflicts = workflow.disagreements(annotations["intent_a"], annotations["intent_b"], manifest)
    count = len(manifest["questions"])
    distributions = {}
    intent_counts = {}
    for role in ("a", "b"):
        distributions[role.upper()] = {
            key: dict(sorted(Counter(row[key] for row in annotations["ratings_" + role].values()).items()))
            for key in workflow.evaluator.RATINGS
        }
        intent_counts[role.upper()] = dict(sorted(Counter(row["expected_intent"] for row in annotations["intent_" + role].values()).items()))
    result = {
        "schema": "m6-descriptive-review-v1", "status": "complete_descriptive_review",
        "method": "descriptive_comparison", "rows_per_reviewer": count,
        "packet_sha256": manifest["packet_sha256"], "annotation_hashes": hashes,
        "process_record_sha256": workflow.evaluator.file_sha(process_record),
        "process_declarations_self_reported": True,
        "intent_label_counts": intent_counts, "rating_distributions": distributions,
        "intent_comparison": {"matching_label_and_set": count - len(conflicts),
                              "unresolved_disagreements": len(conflicts)},
        "independent_metrics": None, "adjudicated_gold": None,
        "independent_protocol_complete": False,
        "limitations": record["limitations"],
    }
    output.mkdir(parents=True)
    workflow.evaluator.dump(output / "report.json", result)
    # Preserve the exact bytes that process_record_sha256 describes, including
    # whitespace and the trailing newline in the submitted process record.
    (output / "process-record.json").write_bytes(process_record.read_bytes())
    workflow.evaluator.csv_write(output / "intent-disagreements.csv",
        ["question_id", "question", "label_A", "acceptable_A", "note_A", "label_B", "acceptable_B", "note_B"], conflicts)
    workflow.evaluator.csv_write(output / "adjudication-template.csv",
        ["question_id", "packet_sha256", "adjudicator_id", "expected_intent", "note"],
        [{"question_id": row["question_id"], "packet_sha256": manifest["packet_sha256"],
          "adjudicator_id": "", "expected_intent": "", "note": ""} for row in conflicts])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=workflow.PACKET)
    parser.add_argument("--intent-a", type=Path, default=workflow.ROOT / "data/qa/m6-completed-20261016-intent-A.csv")
    parser.add_argument("--ratings-a", type=Path, default=workflow.ROOT / "data/qa/m6-completed-20261016-ratings-A.csv")
    parser.add_argument("--intent-b", type=Path, required=True)
    parser.add_argument("--ratings-b", type=Path, required=True)
    parser.add_argument("--process-record", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("intent_a", "ratings_a", "intent_b", "ratings_b")}
    result = summarize(paths, args.packet, args.process_record, args.output)
    print(json.dumps({"status": result["status"], "rows": result["rows_per_reviewer"],
                      "intent_comparison": result["intent_comparison"], "independent_metrics": None}))


if __name__ == "__main__":
    main()
