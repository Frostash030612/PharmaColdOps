"""Select on old train/validation, then generate a new frozen-policy batch.

Same simulator, new random stream and virtual assets; NOT real-world validity,
new cause classes, pure same-device IID, or promotion to serving M4.
"""
import argparse
import csv
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from generate_event_dataset import ROLES, create, digest, canonical
from verify_event_dataset import verify, read_predictors
from evaluate_event_baselines import dump, load_role
from ml.event_baselines import TARGETS, metrics, probabilities
from ml.event_gate import (VERSION, FLOORS, MARGINS, assess, fingerprint, select_policy,
                           screening_metrics, train_envelope)
from ml.event_simulation import FEATURES, temperature_series


def identities(dataset):
    families, assets, profiles = set(), set(), set()
    for role in ROLES:
        with (dataset / role / "index.csv").open(encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                families.add(row["family_id"]); assets.add(row["asset_id"])
        profiles.update(fingerprint(row) for row in read_predictors(dataset / role))
    return families, assets, profiles


def workflow_smoke(observation, bundle):
    """Actual API/repository, temporary cases; graph mirror explicitly stubbed."""
    from fastapi.testclient import TestClient
    from api import service
    from api.main import app
    from optimisation.case_repository import registered_records
    with tempfile.TemporaryDirectory(prefix="event-gate-workflow-") as temporary:
        path = Path(temporary)
        with patch.dict("os.environ", {"EVENT_GATE_DIR": str(bundle)}), \
             patch.object(service, "DISPATCH_DATABASE_URL", str(path / "cases.sqlite3")), \
             patch.object(service, "RUNS_FILE", path / "cases.jsonl"), \
             patch.object(service, "write_case", lambda r: True), \
             patch.object(service, "evidence_snapshot", lambda n: {"status": "not_verified_in_this_workflow_smoke"}):
            body = {"registration_id": "fresh-gate-smoke", "product_id": observation["product_id"], "packaging": "intact",
                    "temperature_context": {"series": temperature_series(observation, service.ENGINE.specs).model_dump(), "window_id": None},
                    "event_context": {"observation": observation}}
            with TestClient(app) as client:
                preview = client.post("/api/ml/event/assess", json=body["event_context"])
                assert preview.status_code == 200 and preview.json()["status"] != "unavailable"
                assert registered_records(service.DISPATCH_DATABASE_URL) == []
                closed = client.post("/api/case_close", json=body)
                assert closed.status_code == 200, closed.text
                original = closed.json()
                assert original["review_status"] == "pending" and original["effective_disposition"] is None
                archived = registered_records(service.DISPATCH_DATABASE_URL)
                retry = client.post("/api/case_close", json=body)
                assert retry.status_code == 200 and retry.json() == original
                blocked = client.post(f"/api/runs/{original['run_id']}/workflow", json={"status": "handled", "expected_version": 0, "remark": "cannot bypass gate"})
                assert blocked.status_code == 409
                reviewed = client.post(f"/api/runs/{original['run_id']}/review", json={"command_id": "fresh-review", "expected_version": original["workflow_version"],
                    "disposition": "release", "reviewer": "Demo gate reviewer", "reason": "Independent demo evidence check; not clinical authorization"})
                assert reviewed.status_code == 200 and reviewed.json()["decision_source"] == "manual_review"
                assert reviewed.json()["effective_disposition"] == "release" and reviewed.json()["review_status"] == "resolved"
                assert registered_records(service.DISPATCH_DATABASE_URL) == archived
    return {"status": "passed", "read_only_preview": True, "mandatory_review": True, "pre_review_handling_blocked": True,
            "idempotent_registration": True, "human_outcome_separate_from_original": True,
            "scope": "real API/SQL workflow in temporary storage; graph mirror stubbed, not KG or authenticated medical review"}


def run(dataset, baseline, output, *, events=6000, seed=20261004):
    if output.exists() or output.resolve().is_relative_to(dataset.resolve()) or output.resolve().is_relative_to(baseline.resolve()):
        raise ValueError("fresh separate gate experiment output required")
    manifest = json.loads((dataset / "manifest.json").read_text())
    if seed == manifest["seed"]:
        raise ValueError("fresh independent random stream required")
    verify(dataset, replay_per_role=2)  # consistency only, not performance selection.
    selection = json.loads((baseline / "selection-frozen.json").read_text())
    source_protocol = json.loads((baseline / "protocol.json").read_text())
    if (selection["dataset_manifest_sha256"] != digest(dataset / "manifest.json")
            or selection["protocol_sha256"] != digest(baseline / "protocol.json")
            or source_protocol["target_order"] != list(TARGETS)
            or source_protocol["features_by_view"]["full"] != list(FEATURES)
            or source_protocol["versions"]["scikit-learn"] != importlib.metadata.version("scikit-learn")
            or selection["selected"] not in {"full_hgb", "full_logistic"}
            or selection["model_sha256"] != digest(baseline / "selected-experimental-model.joblib")):
        raise ValueError("frozen baseline source contract/integrity mismatch")
    source_paths = [Path(__file__), ROOT / "src/ml/event_gate.py", ROOT / "src/ml/event_runtime.py",
                    ROOT / "scripts/generate_event_dataset.py", ROOT / "src/ml/event_simulation.py",
                    ROOT / "scripts/evaluate_event_baselines.py", ROOT / "src/ml/event_baselines.py",
                    ROOT / "scripts/verify_event_dataset.py"]
    protocol = {"schema": VERSION, "old_dataset_manifest_sha256": digest(dataset / "manifest.json"),
        "baseline_selection_sha256": digest(baseline / "selection-frozen.json"), "model_sha256": selection["model_sha256"],
        "fresh_events": events, "fresh_seed": seed, "generator_unchanged": True,
        "selection": {"roles": "old train envelope, old validation screening selection ONLY",
            "floors": list(FLOORS), "margins": list(MARGINS), "min_validation_screen_passed": 30,
            "min_validation_supported_exact_precision": .90, "max_validation_normal_supported_false_alarm": .05,
            "rank": "max coverage, then precision, then higher floor/margin; infeasible => refuse all"},
        "fresh_roles_scored": [r for r in ROLES if r.startswith("test_")],
        "fresh_role_scope": {"test_iid": "nominal parameters, NEW base virtual assets, NOT same-device IID",
            "test_facility": "separate NEW heldout virtual assets", "test_scenario": "unseen excitation, NEW base assets",
            "test_parameter": "challenging ambient/noise/dropout, NEW base assets"},
        "mandatory_review_for_all": True, "shadow_only": True, "automatic_promotion": False,
        "fresh_train_validation_unused_for_fitting_or_selection": True,
        "limitations": ["same uncalibrated simulator; not real-business independent validity or open-set cause validation",
                        "old validation has previously been inspected; selected precision is not an untouched estimate",
                        "min/max envelope is a guard, not guaranteed OOD detection; scores remain uncalibrated",
                        "rejection is not a correct diagnosis and does not erase raw-model false alarms",
                        "human reviewer self-declared in demo; not authenticated clinical authorization"],
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in source_paths}}
    output.mkdir(parents=True)
    dump(output / "protocol.json", protocol)
    train_x, _, _, _ = load_role(dataset, "train")
    val_x, val_y, val_labels, _ = load_role(dataset, "validation")
    model = joblib.load(baseline / "selected-experimental-model.joblib")
    if list(model.feature_names_in_) != list(FEATURES) or model.classes_.tolist() != list(range(len(TARGETS))):
        raise ValueError("baseline model contents incompatible")
    with threadpool_limits(limits=1):
        val_scores = probabilities(model, val_x)
        threshold = selection["thresholds"][selection["selected"]]
        selected_policy, search = select_policy(val_x, val_scores, val_y, val_labels, train_envelope(train_x), threshold)
        bundle = output / "bundle"
        bundle.mkdir()
        shutil.copyfile(baseline / "selected-experimental-model.joblib", bundle / "model.joblib")
        metadata = {"schema": VERSION, "features": list(FEATURES), "targets": list(TARGETS), "shadow_only": True,
                    "sklearn_version": importlib.metadata.version("scikit-learn"), "model_sha256": selection["model_sha256"],
                    "policy": selected_policy, "policy_sha256": fingerprint(selected_policy),
                    "baseline_selection_sha256": protocol["baseline_selection_sha256"]}
        dump(bundle / "metadata.json", metadata)
        frozen = {"protocol_sha256": digest(output / "protocol.json"), "policy_sha256": metadata["policy_sha256"],
                  "bundle_metadata_sha256": digest(bundle / "metadata.json"), "validation_search": search,
                  "validation_selected": screening_metrics(val_y, assess(val_x, val_scores, selected_policy), val_labels)}
        dump(output / "gate-selection-frozen.json", frozen)
        frozen_sha = digest(output / "gate-selection-frozen.json")
        print("gate frozen; generating fresh independent batch", flush=True)
        fresh = output / "fresh-dataset"
        create(fresh, events=events, seed=seed)
        integrity = verify(fresh, replay_per_role=2)
        old_sets, fresh_sets = identities(dataset), identities(fresh)
        overlap = {name: len(first & second) for name, first, second in zip(["families", "virtual_assets", "exact_feature_profiles"], old_sets, fresh_sets)}
        if any(overlap.values()):
            raise ValueError("fresh cohort overlaps old family/asset/exact-profile identities; no resampling to hide failure")
        report = {"status": "complete", "policy": selected_policy, "protocol": protocol, "fresh_integrity": integrity,
                  "old_fresh_overlap": overlap, "selection_sha256": frozen_sha, "test": {}, "promotion": False}
        smoke_observation = None
        for role in protocol["fresh_roles_scored"]:
            print("scoring frozen gate: " + role, flush=True)
            x, y, labels, indices = load_role(fresh, role)
            scores = probabilities(model, x)
            results = assess(x, scores, selected_policy)
            screened = screening_metrics(y, results, labels)
            assert screened["review_required_events"] == len(x) and screened["automatic_actions_allowed_events"] == 0
            report["test"][role] = {"raw_model": metrics(y, scores, threshold, labels), "screened": screened,
                                   "reason_counts": {reason: sum(reason in r["reasons"] for r in results) for reason in sorted({s for r in results for s in r["reasons"]})}}
            with (output / (role + "-decisions.jsonl")).open("x", encoding="utf-8") as stream:
                for index, label, result in zip(indices, labels, results):
                    stream.write(canonical({"event_id": index["event_id"], "family_id": index["family_id"],
                        "truth": label["injected_causes"], "observationally_ambiguous": label["observationally_ambiguous"], **result}) + "\n")
            if smoke_observation is None:
                with (fresh / role / "observations.jsonl").open(encoding="utf-8") as stream:
                    smoke_observation = json.loads(next(stream))
        report["api_workflow_smoke"] = workflow_smoke(smoke_observation, bundle)
        if (digest(output / "gate-selection-frozen.json") != frozen_sha or digest(bundle / "metadata.json") != frozen["bundle_metadata_sha256"]
                or digest(bundle / "model.joblib") != selection["model_sha256"]
                or any(digest(ROOT / p) != h for p, h in protocol["source_sha256"].items())):
            raise ValueError("frozen gate artifact/source changed during scoring")
        for cohort, expected in [(dataset, manifest), (fresh, json.loads((fresh / "manifest.json").read_text()))]:
            for name, h in expected["file_sha256"].items():
                if digest(cohort / name) != h:
                    raise ValueError("dataset changed during scoring")
        dump(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--events", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=20261004)
    args = parser.parse_args()
    report = run(args.dataset, args.baseline, args.output, events=args.events, seed=args.seed)
    print(json.dumps({"status": report["status"], "screen_enabled": report["policy"]["enabled"], "policy_sha256": fingerprint(report["policy"]),
                      "test": {role: {k: values["screened"][k] for k in ["events", "screen_coverage", "supported_exact_precision", "normal_supported_false_alarm_rate"]} for role, values in report["test"].items()}}))


if __name__ == "__main__":
    main()
