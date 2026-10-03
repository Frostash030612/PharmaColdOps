"""Opt-in administrator-owned SHADOW bundle; no uploaded models or training."""
import json
import os
from pathlib import Path
import threading

from .event_simulation import FEATURES, extract_features
from .event_gate import VERSION, assess, fingerprint, validate_policy
from .event_baselines import TARGETS, probabilities

_lock = threading.RLock()
_cache = {}


def digest(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bundle():
    directory = os.environ.get("EVENT_GATE_DIR")
    if not directory:
        raise ValueError("event shadow bundle not configured")
    root = Path(directory)
    model_file, metadata_file = root / "model.joblib", root / "metadata.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    if (metadata["schema"] != VERSION or metadata["features"] != list(FEATURES) or metadata["targets"] != list(TARGETS)
            or metadata["shadow_only"] is not True or metadata["policy_sha256"] != fingerprint(metadata["policy"])
            or metadata["model_sha256"] != digest(model_file)):
        raise ValueError("event bundle contract/integrity mismatch")
    validate_policy(metadata["policy"])
    import sklearn
    if metadata["sklearn_version"] != sklearn.__version__:
        raise ValueError("event bundle runtime incompatible")
    stamp = (str(root.resolve()), digest(metadata_file), metadata["model_sha256"])
    with _lock:
        if stamp not in _cache:
            import joblib
            model = joblib.load(model_file)  # ONLY administrator-controlled local path.
            if list(model.feature_names_in_) != list(FEATURES) or model.classes_.tolist() != list(range(len(TARGETS))):
                raise ValueError("event model contents incompatible")
            _cache.clear()
            _cache[stamp] = model
        return _cache[stamp], metadata


def evaluate(observation, specs):
    # Invalid observations are input errors, never hidden by availability fallback.
    features = extract_features(observation, specs)
    observation_sha = fingerprint(observation)
    base = {"event_id": observation["event_id"], "product_id": observation["product_id"],
            "observation_sha256": observation_sha, "features_sha256": fingerprint(features),
            "shadow_only": True, "review_required": True, "automatic_actions_allowed": False}
    try:
        model, metadata = load_bundle()
        import pandas as pd
        from threadpoolctl import threadpool_limits
        frame = pd.DataFrame([features], columns=FEATURES)
        with threadpool_limits(limits=1):
            result = assess(frame, probabilities(model, frame), metadata["policy"])[0]
        return {**result, **base, "model_sha256": metadata["model_sha256"], "policy_sha256": metadata["policy_sha256"]}
    except Exception:
        # Failure cannot downgrade the required human gate or substitute old M4.
        return {**base, "schema": VERSION, "status": "unavailable", "screen_passed": False,
                "supported_candidate": None, "candidates": [], "raw_candidates": [],
                "reasons": ["event_shadow_artifact_unavailable"], "scores_uncalibrated": True}
