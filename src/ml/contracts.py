"""Explicit benchmark input contracts; excursion fields are NOT model features."""
import math

RISK_FIELDS = {
    "transit_days": (0, 365), "door_opens": (0, 10000),
    "temp_mean_c": (-100, 100), "temp_max_c": (-100, 100), "temp_min_c": (-100, 100),
    "temp_std_c": (0, 100), "temp_recovery_rate": (0, 1),
    "rh_mean": (0, 1), "rh_std": (0, 1), "rh_max": (0, 1),
    "leg_count": (1, 1000), "sensor_gap_hours": (0, 8760), "vibration_index": (0, 100),
}
CAUSE_CATEGORICAL = ["facility_level", "region_type", "equipment_type", "equipment_functional",
    "backup_power_available", "monitoring_type", "monitoring_device_present", "temp_log_complete",
    "vaccine_name", "freeze_sensitive", "heat_sensitive"]
CAUSE_NUMERIC = {"equipment_age_years": (0, 100), "power_outage_hours_last_month": (0, 744),
                 "year": (2000, 2100), "month": (1, 12)}
INTEGER_FIELDS = {"door_opens", "leg_count", "year", "month"}
FEATURES = {"risk": list(RISK_FIELDS), "cause": CAUSE_CATEGORICAL + list(CAUSE_NUMERIC)}


def normalize_features(task, values):
    if set(values) != set(FEATURES[task]):
        raise ValueError("model requires exactly its declared transport/context features; event MKT, order quantity and target labels are not accepted")
    numeric = RISK_FIELDS if task == "risk" else CAUSE_NUMERIC
    result = {}
    for key in FEATURES[task]:
        value = values[key]
        if key in numeric:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{key} must be a finite number")
            lo, hi = numeric[key]
            if not lo <= value <= hi or (key in INTEGER_FIELDS and value != int(value)):
                raise ValueError(f"{key} is outside the declared input bounds")
            result[key] = int(value) if key in INTEGER_FIELDS else float(value)
        else:
            if not isinstance(value, str) or not value.strip() or len(value) > 100:
                raise ValueError(f"{key} must be a nonempty benchmark category")
            result[key] = value
    if task == "risk":
        if not result["temp_min_c"] <= result["temp_mean_c"] <= result["temp_max_c"]:
            raise ValueError("temperature summary must satisfy min <= mean <= max")
        if result["rh_mean"] > result["rh_max"]:
            raise ValueError("humidity mean cannot exceed maximum")
    return result
