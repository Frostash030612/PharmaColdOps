"""Explicitly enabled, administrator-owned v2 shadow inference only."""
import json
import os
from pathlib import Path
import threading

from .event_runtime import digest
from .event_gate import assess, fingerprint, validate_policy
from .event_baselines import TARGETS
from .event_simulation import FEATURES, temperature_series
from .event_temporal import VERSION, TEMPORAL_FEATURES, extract_temporal, temporal_probabilities

BUNDLE_SCHEMA = "event-v2-shadow-bundle-v1"
_lock = threading.RLock()
_cache = {}


class ShadowDisabled(ValueError):
    pass


def load_bundle():
    if os.environ.get("EVENT_V2_SHADOW_ENABLED") != "1":
        raise ShadowDisabled("explicit v2 shadow enablement required")
    directory = os.environ.get("EVENT_V2_SHADOW_DIR")
    if not directory: raise ValueError("v2 shadow bundle not configured")
    root = Path(directory)
    meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    if (meta["schema"] != BUNDLE_SCHEMA or meta["feature_schema"] != VERSION or meta["features"] != list(TEMPORAL_FEATURES)
            or meta["targets"] != list(TARGETS) or meta["shadow_only"] is not True
            or meta["automatic_actions_allowed"] is not False or meta["review_required"] is not True
            or meta["policy_sha256"] != fingerprint(meta["policy"])
            or digest(root / "model.joblib") != meta["model_sha256"]
            or digest(root / "demo_samples.json") != meta["demo_samples_sha256"]):
        raise ValueError("v2 shadow integrity/contract mismatch")
    validate_policy(meta["policy"])
    import sklearn
    if meta["sklearn_version"] != sklearn.__version__: raise ValueError("v2 sklearn contract mismatch")
    stamp = (str(root.resolve()), digest(root / "metadata.json"), meta["model_sha256"])
    with _lock:
        if stamp not in _cache:
            import joblib
            # NEVER load a client upload/path. Admin-local, hash-checked only.
            model = joblib.load(root / "model.joblib")
            if list(model.feature_names_in_) != list(TEMPORAL_FEATURES) or model.classes_.tolist() != list(range(len(TARGETS))):
                raise ValueError("v2 model contents incompatible")
            _cache.clear(); _cache[stamp] = model
        return _cache[stamp], meta, root


def info():
    try:
        _, meta, _ = load_bundle()
        return {"status": "shadow_ready", **{k: meta[k] for k in ["schema", "feature_schema", "model_id", "model_sha256",
            "policy_sha256", "study_selection_sha256", "shadow_only", "review_required", "automatic_actions_allowed"]},
            "feature_count": len(TEMPORAL_FEATURES), "scores_uncalibrated": True, "data_synthetic": True}
    except ShadowDisabled:
        return {"status": "disabled", "reason": "event_v2_shadow_disabled", "shadow_only": True, "automatic_actions_allowed": False}
    except Exception:
        return {"status": "unavailable", "reason": "event_v2_shadow_artifact_unavailable", "shadow_only": True, "automatic_actions_allowed": False}


def samples(specs):
    _, meta, root = load_bundle()
    values = json.loads((root / "demo_samples.json").read_text(encoding="utf-8"))
    if not isinstance(values, list) or not 1 <= len(values) <= 40: raise ValueError("bounded demo sample list required")
    from api.schemas import EventContextIn
    ids = set()
    for value in values:
        if set(value) != {"sample_id", "role", "observation"} or value["sample_id"] in ids: raise ValueError("public sample contract mismatch")
        ids.add(value["sample_id"])
        EventContextIn(observation=value["observation"])
    return {"model_id": meta["model_id"], "source": "previously_evaluated_synthetic_demo_not_live_order_or_new_test", "samples": values}


def evaluate(observation, specs):
    features = extract_temporal(observation, specs)
    base = {"schema": BUNDLE_SCHEMA, "feature_schema": VERSION, "event_id": observation["event_id"], "product_id": observation["product_id"],
            "observation_sha256": fingerprint(observation), "features_sha256": fingerprint(features), "feature_count": len(TEMPORAL_FEATURES),
            "shadow_only": True, "review_required": True, "automatic_actions_allowed": False, "data_synthetic": True}
    try:
        model, meta, _ = load_bundle()
        import pandas as pd
        from threadpoolctl import threadpool_limits
        frame = pd.DataFrame([features], columns=TEMPORAL_FEATURES)
        with threadpool_limits(limits=1):
            scores = temporal_probabilities(model, frame)
            result = assess(frame[list(FEATURES)], scores, meta["policy"])[0]
        result = {**result, **base, "model_id": meta["model_id"], "model_sha256": meta["model_sha256"],
                  "policy_sha256": meta["policy_sha256"], "study_selection_sha256": meta["study_selection_sha256"]}
    except Exception as exc:
        disabled = isinstance(exc, ShadowDisabled)
        result = {**base, "status": "disabled" if disabled else "unavailable", "screen_passed": False,
            "candidates": [], "raw_candidates": [], "supported_candidate": None, "scores_uncalibrated": True,
            "reasons": ["event_v2_shadow_disabled" if disabled else "event_v2_shadow_artifact_unavailable"]}
    # Same public prefix for M2 and case binding, never invented scalars.
    from temperature_monitoring import analyse
    series = temperature_series(observation, specs)
    return {**result, "temperature_series": series.model_dump(), "temperature_assessment": analyse(series, specs[observation["product_id"]])}
