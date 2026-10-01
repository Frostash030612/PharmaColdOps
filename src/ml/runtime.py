"""Lazy, read-only model loading. Never train on an API request or load uploads."""
import hashlib
import json
import os
import threading
from pathlib import Path

from .contracts import FEATURES, normalize_features

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data/processed/m4"
_lock = threading.RLock()
_cache = {}


class ModelUnavailable(RuntimeError):
    pass


def load_model(task):
    root = Path(os.environ.get("ML_MODEL_DIR", str(DEFAULT_DIR))) / task
    model_file, meta_file = root / "model.joblib", root / "metadata.json"
    try:
        stamp = (str(root.resolve()), model_file.stat().st_mtime_ns, model_file.stat().st_size,
                 meta_file.stat().st_mtime_ns, meta_file.stat().st_size)
        with _lock:
            if stamp in _cache: return _cache[stamp]
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            if metadata["schema_version"] != 1 or metadata["task"] != task or metadata["features"] != FEATURES[task]:
                raise ValueError("incompatible model contract")
            if hashlib.sha256(model_file.read_bytes()).hexdigest() != metadata["model_sha256"]:
                raise ValueError("model integrity mismatch")
            import sklearn
            import joblib
            if metadata["sklearn_version"] != sklearn.__version__:
                raise ValueError("runtime version mismatch; retrain the local artifact")
            # Only an administrator-controlled local path, hash-checked against
            # its local manifest. Never unpickle any API/user supplied file.
            model = joblib.load(model_file)
            if list(model.feature_names_in_) != FEATURES[task] or model.classes_.tolist() != metadata["classes"]:
                raise ValueError("model contents incompatible")
            _cache.clear() if len(_cache) > 8 else None
            _cache[stamp] = (model, metadata)
            return model, metadata
    except Exception as exc:
        raise ModelUnavailable("M4 artifact missing, invalid or incompatible; run train_m4_models.py in the server environment") from exc


def model_info(task):
    try:
        _, meta = load_model(task)
        return {"status": "ready", **{k: meta[k] for k in ["task", "target", "model_id", "algorithm",
            "model_sha256", "fields", "test_metrics", "threshold", "scope", "data_suspected_or_declared_synthetic"]}}
    except ModelUnavailable:
        return {"status": "unavailable", "task": task, "reason": "artifact_unavailable"}


def predict(context):
    import numpy as np
    import pandas as pd
    from threadpoolctl import threadpool_limits
    task, source = context.task, context.source
    features = normalize_features(task, context.features)
    model, meta = load_model(task)
    if source == "dataset_sample":
        sample = next((s for s in meta["samples"] if s["sample_id"] == context.sample_id), None)
        if sample is None or normalize_features(task, sample["features"]) != features:
            raise ValueError("sample identity and features do not match this model's held-out demo sample")
    elif context.sample_id is not None:
        raise ValueError("manual context cannot claim a dataset sample identity")
    out_of_domain = []
    for field in meta["fields"]:
        key = field["key"]
        if field["kind"] == "category":
            if features[key] not in field["options"]: out_of_domain.append(key)
        elif not field["training_range"][0] <= features[key] <= field["training_range"][1]:
            out_of_domain.append(key)
    base = {"task": task, "target": meta["target"], "model_id": meta["model_id"],
        "model_sha256": meta["model_sha256"], "algorithm": meta["algorithm"], "source": source,
        "sample_id": context.sample_id, "features": features, "advisory_only": True,
        "probabilities_uncalibrated": True,
        "data_suspected_or_declared_synthetic": True, "scope": meta["scope"]}
    if out_of_domain:
        return {**base, "status": "out_of_domain", "unsupported_features": out_of_domain}
    x = pd.DataFrame([features], columns=FEATURES[task])
    with threadpool_limits(limits=1):
        probabilities = model.predict_proba(x)[0]
        index = 1 if task == "risk" else int(np.argmax(probabilities))
        score = float(probabilities[index])
        effects = []
        for key in FEATURES[task]:
            changed = x.copy(); changed[key] = meta["references"][key]
            changed_score = float(model.predict_proba(changed)[0][index])
            effects.append({"feature": key, "value": features[key], "reference": meta["references"][key],
                           "probability_delta": round(score - changed_score, 6)})
    result = {**base, "status": "predicted", "explanation_method": "single_feature_reference_replacement_not_shap_or_causality",
              "explanations": sorted(effects, key=lambda e: -abs(e["probability_delta"]))[:5]}
    if task == "risk":
        result.update(failure_probability=round(score, 6), threshold=meta["threshold"],
                      above_threshold=score >= meta["threshold"])
    else:
        result["top_classes"] = [{"label": meta["classes"][i], "probability": round(float(probabilities[i]), 6)}
                                for i in np.argsort(-probabilities)[:3]]
    return result
