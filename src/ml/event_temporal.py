"""V2 observation-only features; same v1 physics and latent occurrence labels.

Time bins are relative to the OBSERVED prefix, never future plan/fault timing.
No-fault is not safety; absent conditional measurements remain null.
"""
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .event_simulation import FEATURES, CHANNELS, extract_features, validate_observation
from .event_baselines import validate_probabilities

VERSION = "event-temporal-study-v2"
BIN_FIELDS = ("temperature_offset_mean", "air_product_gradient_mean", "ambient_mean", "door_fraction",
    "mains_unavailable_fraction", "backup_command_fraction", "backup_running_fraction", "fuel_fraction_mean",
    "compressor_current_fraction_mean", "cooling_duty_fraction_mean", "airflow_fraction_mean", "setpoint_offset_mean",
    "progress_lag_mean", "temperature_coverage", "auxiliary_coverage")
JOINT_FIELDS = ("mains_unavailable_fuel_mean", "mains_unavailable_fuel_q10", "mains_unavailable_fuel_low_known_min",
    "mains_unavailable_fuel_available_known_min", "fuel_on_minus_off_mean", "mains_unavailable_backup_command_fraction",
    "mains_unavailable_backup_running_fraction", "commanded_not_running_known_min", "fuel_after_minus_before_first_mains_loss",
    "compressor_current_when_power_available_mean", "cooling_duty_high_current_low_known_min", "airflow_low_known_min",
    "air_product_gradient_q90", "temperature_gap_count", "first_last_temperature_delta", "setpoint_change_total_abs",
    "fuel_change_total_abs", "airflow_change_total_abs")
TEMPORAL_FEATURES = FEATURES + tuple(f"prefix_bin{b}_{f}" for b in range(4) for f in BIN_FIELDS) + JOINT_FIELDS


def extract_temporal(observation, specs):
    validate_observation(observation, specs)
    aggregate = extract_features(observation, specs)
    result = {key: aggregate[key] for key in FEATURES}
    rows = observation["records"]
    start = np.asarray([r["start_min"] for r in rows]); end = np.asarray([r["end_min"] for r in rows])
    duration = end - start
    values = {key: np.asarray([np.nan if r[key] is None else r[key] for r in rows], dtype=float) for key in CHANNELS}
    known = {key: np.isfinite(v) for key, v in values.items()}
    spec = specs[observation["product_id"]]
    centre = (spec.storage_min_c + spec.storage_max_c) / 2

    def mean(value, weights, mask=None):
        selected = np.isfinite(value) & (weights > 0)
        if mask is not None: selected &= mask
        return float(np.average(value[selected], weights=weights[selected])) if selected.any() else None

    def quantile(value, mask, q):
        selected = mask & np.isfinite(value)
        if not selected.any(): return None
        v, w = value[selected], duration[selected]
        order = np.argsort(v, kind="stable")
        index = min(len(order) - 1, int(np.searchsorted(np.cumsum(w[order]), q * w.sum(), side="left")))
        return float(v[order[index]])

    temp, air = values["product_temp_c"], values["air_temp_c"]
    gradient = air - temp
    for b in range(4):
        lower, upper = observation["observation_end_min"] * b / 4, observation["observation_end_min"] * (b + 1) / 4
        weights = np.maximum(0, np.minimum(end, upper) - np.maximum(start, lower))
        features = {
            "temperature_offset_mean": mean(temp - centre, weights), "air_product_gradient_mean": mean(gradient, weights),
            "ambient_mean": mean(values["ambient_temp_c"], weights), "door_fraction": mean(values["door_open"], weights),
            "mains_unavailable_fraction": mean(1 - values["mains_available"], weights),
            "backup_command_fraction": mean(values["backup_command"], weights), "backup_running_fraction": mean(values["backup_running"], weights),
            "fuel_fraction_mean": mean(values["fuel_fraction"], weights),
            "compressor_current_fraction_mean": mean(values["compressor_current_fraction"], weights),
            "cooling_duty_fraction_mean": mean(values["cooling_duty_fraction"], weights),
            "airflow_fraction_mean": mean(values["airflow_fraction"], weights), "setpoint_offset_mean": mean(values["setpoint_c"] - centre, weights),
            "progress_lag_mean": mean(np.maximum(0, start - values["route_progress"] * observation["planned_duration_min"]), weights),
            "temperature_coverage": float(weights[known["product_temp_c"]].sum() / (upper - lower)),
            "auxiliary_coverage": float(np.mean([weights[known[k]].sum() / (upper - lower) for k in CHANNELS[2:]])),
        }
        result.update({f"prefix_bin{b}_{key}": value for key, value in features.items()})
    off = known["mains_available"] & (values["mains_available"] == 0)
    on = known["mains_available"] & (values["mains_available"] == 1)
    fuel = values["fuel_fraction"]
    joint = known["mains_available"] & known["fuel_fraction"]
    off_fuel = mean(fuel, duration, off); on_fuel = mean(fuel, duration, on)
    first_loss = np.flatnonzero(off)
    before = mean(fuel, duration, start < start[first_loss[0]]) if len(first_loss) else None
    after = mean(fuel, duration, start >= start[first_loss[0]]) if len(first_loss) else None
    power_known = known["mains_available"] & known["backup_running"]
    powered = power_known & ((values["mains_available"] == 1) | (values["backup_running"] == 1))

    def minutes(condition, valid):
        return float(duration[condition & valid].sum()) if valid.any() else None

    def changes(key):
        valid = known[key][1:] & known[key][:-1]
        return float(np.abs(np.diff(values[key]))[valid].sum()) if valid.any() else None

    gap = ~known["product_temp_c"]
    observed_temp = temp[known["product_temp_c"]]
    result.update({
        "mains_unavailable_fuel_mean": off_fuel, "mains_unavailable_fuel_q10": quantile(fuel, off, .1),
        "mains_unavailable_fuel_low_known_min": minutes(off & (fuel <= .1), joint),
        "mains_unavailable_fuel_available_known_min": minutes(off & (fuel > .15), joint),
        "fuel_on_minus_off_mean": on_fuel - off_fuel if on_fuel is not None and off_fuel is not None else None,
        "mains_unavailable_backup_command_fraction": mean(values["backup_command"], duration, off),
        "mains_unavailable_backup_running_fraction": mean(values["backup_running"], duration, off),
        "commanded_not_running_known_min": minutes((values["backup_command"] == 1) & (values["backup_running"] == 0), known["backup_command"] & known["backup_running"]),
        "fuel_after_minus_before_first_mains_loss": after - before if before is not None and after is not None else None,
        "compressor_current_when_power_available_mean": mean(values["compressor_current_fraction"], duration, powered),
        "cooling_duty_high_current_low_known_min": minutes((values["cooling_duty_fraction"] > .6) & (values["compressor_current_fraction"] < .2), known["cooling_duty_fraction"] & known["compressor_current_fraction"]),
        "airflow_low_known_min": minutes(values["airflow_fraction"] < .4, known["airflow_fraction"]),
        "air_product_gradient_q90": quantile(gradient, np.isfinite(gradient), .9),
        "temperature_gap_count": int((gap & np.r_[True, ~gap[:-1]]).sum()),
        "first_last_temperature_delta": float(observed_temp[-1] - observed_temp[0]) if len(observed_temp) >= 2 else None,
        "setpoint_change_total_abs": changes("setpoint_c"), "fuel_change_total_abs": changes("fuel_fraction"),
        "airflow_change_total_abs": changes("airflow_fraction"),
    })
    if tuple(result) != TEMPORAL_FEATURES:
        raise ValueError("temporal feature contract drift")
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in result.items()}


def validate_temporal(frame):
    if tuple(frame.columns) != TEMPORAL_FEATURES or frame.empty or frame.product_id.isna().any():
        raise ValueError("exact observation-only temporal contract required")
    if np.isinf(frame.drop(columns="product_id").to_numpy(dtype=float)).any():
        raise ValueError("finite or missing temporal inputs required")


def make_temporal_pipeline():
    preprocess = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median", keep_empty_features=True, add_indicator=True), list(TEMPORAL_FEATURES[1:])),
        ("product", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["product_id"]),
    ])
    estimator = HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15, learning_rate=.1,
        l2_regularization=1, early_stopping=False, random_state=42)
    return Pipeline([("observed_only", preprocess), ("classifier", OneVsRestClassifier(estimator, n_jobs=1))])


def temporal_probabilities(model, frame):
    validate_temporal(frame)
    return validate_probabilities(model.predict_proba(frame))
