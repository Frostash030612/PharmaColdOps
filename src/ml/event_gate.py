"""Conservative candidate screening, never disposition or execution authority."""
import hashlib
import json

import numpy as np

from .event_baselines import TARGETS, predict_sets, validate_frame, validate_probabilities
from .event_simulation import FEATURES

VERSION = "event-review-gate-v1"
FLOORS = (.70, .80, .90, .95, .99)
MARGINS = (.20, .40)
SHARED = {"door_left_open", "thermostat_failure", "ice_pack_not_conditioned", "staff_error"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def train_envelope(frame):
    validate_frame(frame)
    return {"products": sorted(frame.product_id.unique().tolist()),
            "ranges": {key: [float(frame[key].min()), float(frame[key].max())] if frame[key].notna().any() else None
                       for key in FEATURES if key != "product_id"}}


def policy(envelope, thresholds, *, floor=.90, margin=.40, enabled=True):
    predict_sets(np.zeros((1, len(TARGETS))), thresholds)
    if floor not in FLOORS or margin not in MARGINS:
        raise ValueError("predeclared candidate gate grid required")
    return {"schema": VERSION, "envelope": envelope, "candidate_thresholds": list(map(float, thresholds)),
            "score_floor": floor, "minimum_margin": margin, "enabled": enabled,
            "minimum_temperature_coverage": .80, "minimum_auxiliary_coverage": .80,
            "minimum_observed_min": 60, "unknown_score_ceiling": .20,
            "review_required": True, "automatic_actions_allowed": False}


def validate_policy(value):
    expected = set(policy({"products": [], "ranges": {}}, [.5] * len(TARGETS)))
    if set(value) != expected or value["schema"] != VERSION or value["review_required"] is not True or value["automatic_actions_allowed"] is not False:
        raise ValueError("mandatory review policy contract required")
    if type(value["enabled"]) is not bool or value["score_floor"] not in FLOORS or value["minimum_margin"] not in MARGINS:
        raise ValueError("invalid screening policy")
    if (value["minimum_temperature_coverage"], value["minimum_auxiliary_coverage"], value["minimum_observed_min"], value["unknown_score_ceiling"]) != (.8, .8, 60, .2):
        raise ValueError("fixed evidence guard contract required")
    predict_sets(np.zeros((1, len(TARGETS))), value["candidate_thresholds"])
    envelope = value["envelope"]
    if set(envelope) != {"products", "ranges"} or not envelope["products"] or any(not isinstance(p, str) for p in envelope["products"]):
        raise ValueError("training product envelope required")
    if set(envelope["ranges"]) != set(FEATURES) - {"product_id"}:
        raise ValueError("exact training numeric envelope required")
    for bounds in envelope["ranges"].values():
        if bounds is not None and (len(bounds) != 2 or not np.isfinite(bounds).all() or bounds[0] > bounds[1]):
            raise ValueError("finite ordered training range required")


def assess(frame, scores, value):
    validate_frame(frame)
    validate_policy(value)
    scores = validate_probabilities(scores)
    if len(frame) != len(scores):
        raise ValueError("aligned scores and public predictors required")
    raw = predict_sets(scores, value["candidate_thresholds"])
    results = []
    for (_, row), probabilities, active in zip(frame.iterrows(), scores, raw):
        reasons, unsupported, missing = [], [], []
        if not value["enabled"]:
            reasons.append("validation_screen_not_qualified")
        if row.product_id not in value["envelope"]["products"]:
            unsupported.append("product_id")
        for key, bounds in value["envelope"]["ranges"].items():
            if row[key] is None or np.isnan(row[key]):
                missing.append(key)
            elif bounds is None or not bounds[0] <= row[key] <= bounds[1]:
                unsupported.append(key)
        if missing:
            reasons.append("missing_predictors")
        if unsupported:
            reasons.append("outside_training_envelope")
        if row.temperature_coverage_ratio < value["minimum_temperature_coverage"] or row.auxiliary_coverage_ratio < value["minimum_auxiliary_coverage"]:
            reasons.append("insufficient_observation_coverage")
        if row.observed_duration_min < value["minimum_observed_min"]:
            reasons.append("short_observation_prefix")
        candidates = [name for name, present in zip(TARGETS, active) if present]
        expanded = set(candidates)
        if expanded & SHARED:
            # Staff subtype shares door/setpoint/buffer physics. Never infer
            # human intent from these measured mechanisms alone.
            expanded |= SHARED if "staff_error" in expanded else {"staff_error"}
            reasons.append("shared_mechanism_semantic_ambiguity")
        if probabilities[-1] >= value["unknown_score_ceiling"] or TARGETS[-1] in candidates:
            reasons.append("possible_unmodeled_disturbance")
        if not candidates:
            reasons.append("no_supported_cause_not_proof_of_safety")
        elif len(candidates) > 1:
            reasons.append("multiple_plausible_causes")
        ranked = np.argsort(-probabilities, kind="stable")
        strongest, second = float(probabilities[ranked[0]]), float(probabilities[ranked[1]])
        if strongest < value["score_floor"]:
            reasons.append("low_model_score")
        if strongest - second < value["minimum_margin"]:
            reasons.append("small_score_margin")
        accepted = not reasons
        results.append({"schema": VERSION, "status": "candidate_only" if accepted else "abstained",
            "screen_passed": accepted, "review_required": True, "automatic_actions_allowed": False,
            "raw_candidates": candidates, "candidates": [name for name in TARGETS if name in expanded],
            "supported_candidate": candidates[0] if accepted else None,
            "reasons": reasons, "unsupported_features": unsupported, "missing_features": missing,
            "scores_uncalibrated": True, "scores": dict(zip(TARGETS, probabilities.tolist())),
            "scope": "simulated mechanism candidates only; not causal confirmation, product safety or disposition authority"})
    return results


def screening_metrics(truth, results, labels):
    truth = np.asarray(truth)
    if truth.shape != (len(results), len(TARGETS)) or not len(results) or not np.isin(truth, [0, 1]).all():
        raise ValueError("aligned binary evaluation targets required")
    accepted = np.array([r["screen_passed"] for r in results], dtype=bool)
    predicted = np.zeros_like(truth)
    for i, result in enumerate(results):
        if result["screen_passed"]:
            predicted[i, TARGETS.index(result["supported_candidate"])] = 1
    correct = np.all(predicted == truth, axis=1) & accepted
    def subset(mask):
        n, passed, matched = int(mask.sum()), int((mask & accepted).sum()), int((mask & correct).sum())
        return {"events": n, "screen_passed": passed, "correct_supported": matched,
                "screen_coverage": passed / n if n else None,
                "supported_exact_precision": matched / passed if passed else None,
                "correct_supported_fraction_all_events": matched / n if n else None}
    normal = truth.sum(axis=1) == 0
    groups = {"no_fault": normal, "unknown_present": truth[:, -1] == 1, "multi": truth.sum(axis=1) > 1,
              "ambiguous": np.array([label["observationally_ambiguous"] for label in labels])}
    return {**subset(np.ones(len(truth), dtype=bool)), "subgroups": {k: subset(mask) for k, mask in groups.items()},
            "normal_supported_false_alarm_rate": float(accepted[normal].mean()) if normal.any() else None,
            "review_required_events": sum(r["review_required"] is True for r in results),
            "automatic_actions_allowed_events": sum(r["automatic_actions_allowed"] is True for r in results),
            "scope": "screen rejection is NOT correct diagnosis; all events require human review"}


def select_policy(frame, scores, truth, labels, envelope, thresholds):
    rows = []
    for floor in FLOORS:
        for margin in MARGINS:
            candidate = policy(envelope, thresholds, floor=floor, margin=margin)
            metrics = screening_metrics(truth, assess(frame, scores, candidate), labels)
            eligible = (metrics["screen_passed"] >= 30 and metrics["supported_exact_precision"] >= .90
                        and metrics["normal_supported_false_alarm_rate"] is not None and metrics["normal_supported_false_alarm_rate"] <= .05)
            rows.append({"floor": floor, "margin": margin, "eligible": eligible, "metrics": metrics})
    qualified = [r for r in rows if r["eligible"]]
    best = sorted(qualified, key=lambda r: (-r["metrics"]["screen_passed"], -r["metrics"]["supported_exact_precision"], -r["floor"], -r["margin"]))[0] if qualified else None
    selected = policy(envelope, thresholds, floor=best["floor"] if best else .99,
                      margin=best["margin"] if best else .40, enabled=best is not None)
    return selected, rows
