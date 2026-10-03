"""Event-level engineering simulator; NOT manufacturer stability or causal validation.

Hidden fault schedules drive shared actuators/thermal dynamics. Observations are
noisy, incomplete prefixes. Feature extraction sees ONLY public observations.
Latent injected faults are not scrap labels or guaranteed temperature excursions.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math

import numpy as np

from temperature_monitoring import Interval, TemperatureSeries, mkt

VERSION = "event-mechanism-simulation-v1"
CAUSES = (
    "power_outage", "generator_fuel_stockout", "equipment_breakdown", "thermostat_failure",
    "door_left_open", "staff_error", "transport_delay", "ice_pack_not_conditioned",
    "overloading", "no_monitoring_device",
)
TEMPLATES = ("pulse", "sustained", "intermittent")
UNSEEN_TEMPLATES = ("ramp", "two_pulses")
CHANNELS = (
    "product_temp_c", "air_temp_c", "ambient_temp_c", "door_open", "mains_available",
    "backup_command", "backup_running", "fuel_fraction", "compressor_current_fraction",
    "cooling_duty_fraction", "setpoint_c", "airflow_fraction", "humidity_pct", "route_progress",
)
FEATURES = (
    "product_id", "planned_duration_min", "observed_duration_min", "sample_cadence_min", "temperature_coverage_ratio",
    "auxiliary_coverage_ratio", "temperature_offset_mean_c", "temperature_offset_min_c",
    "temperature_offset_max_c", "temperature_std_c", "max_rise_c_per_min", "max_drop_c_per_min",
    "known_hot_min", "known_cold_min", "longest_temperature_gap_min", "known_only_mkt_offset_c",
    "ambient_mean_c", "door_open_known_min", "longest_door_open_known_min", "mains_unavailable_known_min",
    "longest_mains_unavailable_known_min", "backup_command_known_min", "backup_running_known_min",
    "fuel_fraction_mean", "compressor_current_fraction_mean", "cooling_duty_fraction_mean",
    "setpoint_offset_mean_c", "airflow_fraction_mean", "air_product_gradient_mean_c",
    "humidity_mean_pct", "progress_lag_mean_min", "warming_with_door_open_fraction",
    "warming_with_mains_unavailable_fraction",
)


def stable_seed(*values):
    return int.from_bytes(hashlib.sha256(json.dumps(values, sort_keys=True).encode()).digest()[:8], "big")


def opaque_id(kind, *values):
    return kind + "-" + hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class Asset:
    asset_id: str
    leak_per_min: float
    cooling_gain: float
    lag_min: float
    airflow: float
    sensor_bias_c: float


@dataclass(frozen=True)
class Fault:
    code: str
    onset_min: float
    duration_min: float
    intensity: float
    polarity: int = 1
    subtype: str = "default"


@dataclass(frozen=True)
class Plan:
    family_id: str
    event_id: str
    product_id: str
    asset: Asset
    seed: int
    horizon_min: int
    cutoff_min: float
    cadence_min: int
    template: str
    regime: str
    ambient_c: float
    dropout: float
    noise_c: float
    faults: tuple[Fault, ...]
    ambiguity: bool = False


def make_asset(asset_id, seed):
    rng = np.random.default_rng(stable_seed(seed, asset_id, "asset"))
    return Asset(asset_id, float(rng.uniform(.002, .006)), float(rng.uniform(1.6, 2.5)),
                 float(rng.uniform(8, 20)), float(rng.uniform(.65, 1)), float(rng.normal(0, .15)))


def activity(fault, template, t):
    elapsed = t - fault.onset_min
    if elapsed < 0:
        return 0.0
    duration = fault.duration_min
    if template == "sustained":
        value = 1.0
    elif template == "pulse":
        value = float(elapsed < duration)
    elif template == "intermittent":
        value = float(elapsed < duration * 2 and elapsed % max(8, duration / 3) < max(4, duration / 6))
    elif template == "ramp":
        value = min(1, elapsed / duration) if elapsed < duration * 2 else 0
    elif template == "two_pulses":
        value = float(elapsed < duration * .4 or duration * 1.1 <= elapsed < duration * 1.6)
    else:
        raise ValueError("unknown excitation template")
    return value * fault.intensity


def validate_plan(plan, specs):
    numeric = [plan.cutoff_min, plan.ambient_c, plan.dropout, plan.noise_c,
               plan.asset.leak_per_min, plan.asset.cooling_gain, plan.asset.lag_min,
               plan.asset.airflow, plan.asset.sensor_bias_c]
    if not all(math.isfinite(v) for v in numeric):
        raise ValueError("finite simulation parameters required")
    if plan.product_id not in specs or plan.template not in TEMPLATES + UNSEEN_TEMPLATES:
        raise ValueError("unknown product/template")
    if plan.regime not in {"nominal", "challenging"} or not 30 <= plan.horizon_min <= 720:
        raise ValueError("invalid regime/horizon")
    if not 0 < plan.cutoff_min <= plan.horizon_min or not 1 <= plan.cadence_min <= 30:
        raise ValueError("invalid observation prefix/cadence")
    if not 0 <= plan.dropout < 1 or not 0 <= plan.noise_c <= 5:
        raise ValueError("invalid measurement policy")
    if not .0001 <= plan.asset.leak_per_min <= .1 or not 1 <= plan.asset.lag_min <= 100:
        raise ValueError("invalid asset dynamics")
    if not 1 <= plan.asset.cooling_gain <= 4 or not .05 <= plan.asset.airflow <= 1 or not -5 <= plan.asset.sensor_bias_c <= 5:
        raise ValueError("invalid asset gain/airflow/bias")
    for fault in plan.faults:
        if not all(math.isfinite(v) for v in [fault.onset_min, fault.duration_min, fault.intensity]):
            raise ValueError("finite hidden fault parameters required")
        if fault.code not in CAUSES + ("external_heat", "sensor_bias") or fault.duration_min <= 0 or fault.intensity <= 0:
            raise ValueError("invalid hidden fault")
        if not 0 <= fault.onset_min < plan.horizon_min or fault.polarity not in {-1, 1}:
            raise ValueError("invalid fault timing/polarity")


def simulate(plan, specs):
    validate_plan(plan, specs)
    spec = specs[plan.product_id]
    centre = (spec.storage_min_c + spec.storage_max_c) / 2
    width = spec.storage_max_c - spec.storage_min_c
    rng = np.random.default_rng(plan.seed)
    n = plan.horizon_min + 1
    # Random arrays sampled BEFORE applying fault identity. Shared seed/actuator
    # schedules permit genuine observational twins, not label-driven sensor codes.
    ambient_noise = rng.normal(0, .5, n)
    process_noise = rng.normal(0, .025, n)
    temperature_noise = rng.normal(0, plan.noise_c, (n, 3))
    analogue_noise = rng.normal(0, .025, (n, len(CHANNELS)))
    dropout_draw = rng.random((n, len(CHANNELS)))
    binary_flip = rng.random((n, len(CHANNELS))) < .015
    benign_logger_gap = np.zeros(n, dtype=bool)
    if rng.random() < .2:
        start = int(rng.uniform(.15, .65) * plan.horizon_min)
        benign_logger_gap[start:start + int(rng.integers(20, 81))] = True
    background_doors = np.zeros(n)
    for _ in range(3):
        start = int(rng.integers(5, max(6, plan.horizon_min - 6)))
        background_doors[start:start + int(rng.integers(1, 5))] = 1
    benign_grid = rng.random(n) < .012
    backup_reliable = bool(rng.random() > .1)
    background_fuel = float(rng.uniform(.01, .95))
    buffer_offset = float(rng.normal(0, width * .10))
    controller_bias = float(rng.normal(0, width * .06))
    air, payload = centre + controller_bias, centre + buffer_offset * .3
    progress = 0.0
    records = []
    for minute in range(n):
        effects = {code: 0.0 for code in CAUSES + ("external_heat", "sensor_bias")}
        staff_door = staff_setpoint = staff_buffer = cold_buffer = target_shift = 0.0
        for fault in plan.faults:
            level = activity(fault, plan.template, minute)
            effects[fault.code] += level
            if fault.code == "staff_error":
                if fault.subtype == "door":
                    staff_door += level
                elif fault.subtype == "setpoint":
                    staff_setpoint += level * fault.polarity
                else:
                    staff_buffer += level * fault.polarity
            elif fault.code == "thermostat_failure":
                target_shift += level * fault.polarity
            elif fault.code == "ice_pack_not_conditioned":
                cold_buffer += level * fault.polarity
        door = bool(background_doors[minute] or effects["door_left_open"] > 0 or staff_door > 0)
        mains = not (benign_grid[minute] or effects["power_outage"] > .1 or effects["generator_fuel_stockout"] > .1)
        backup_command = not mains
        fuel = 0.0 if effects["generator_fuel_stockout"] > .1 else background_fuel
        backup_running = backup_command and backup_reliable and fuel > .12
        powered = mains or backup_running
        ambient = plan.ambient_c + 2 * math.sin(minute / 45) + ambient_noise[minute] + effects["external_heat"] * 10
        target = centre + controller_bias + (target_shift + staff_setpoint) * max(4, width * .8)
        duty = float(np.clip(.45 + (air - target) / max(2, width * .4), 0, 1))
        efficiency = float(np.clip(1 - effects["equipment_breakdown"] * .85, 0, 1))
        airflow = float(np.clip(plan.asset.airflow * (1 - effects["overloading"] * .7), .08, 1))
        cooling = plan.asset.leak_per_min * max(5, plan.ambient_c - centre) * plan.asset.cooling_gain
        heating = plan.asset.leak_per_min * (ambient - air) * (1 + 7 * door + effects["transport_delay"] * .4)
        buffer = centre + buffer_offset + (cold_buffer + staff_buffer) * max(3, width)
        buffer_flux = (buffer - air) * .012 * math.exp(-minute / 180)
        if minute:
            air += heating - cooling * duty * powered * efficiency * airflow + buffer_flux + process_noise[minute]
            payload += (air - payload) * airflow / plan.asset.lag_min
            progress += max(0, 1 - min(1, effects["transport_delay"])) / plan.horizon_min
        current = duty * powered * (.15 + .85 * efficiency)
        humidity = float(np.clip(55 + door * 12 + ambient_noise[minute] * 3, 0, 100))
        if minute % plan.cadence_min or minute >= plan.cutoff_min:
            continue
        values = [payload, air, ambient, int(door), int(mains), int(backup_command), int(backup_running),
                  fuel, current, duty, target, airflow, humidity, min(1, progress)]
        for index in range(3):
            values[index] += temperature_noise[minute, index] + (plan.asset.sensor_bias_c if index < 2 else 0)
        # An unmodeled measurement bias can resemble genuine warming without
        # actually changing payload temperature. It is NOT a potency label.
        values[0] += effects["sensor_bias"] * 4
        for index in range(3, len(CHANNELS)):
            if index in (3, 4, 5, 6):
                values[index] = 1 - values[index] if binary_flip[minute, index] else values[index]
            elif index not in (10, 12):
                values[index] = float(np.clip(values[index] + analogue_noise[minute, index], 0, 1))
            else:
                values[index] += analogue_noise[minute, index]
        missing = dropout_draw[minute] < plan.dropout
        if benign_logger_gap[minute]:
            missing[:2] = True  # acquisition interruption != confirmed absent device
        if effects["no_monitoring_device"] > .1:
            missing[:2] |= dropout_draw[minute, :2] < .92
        row = {"start_min": float(minute), "end_min": min(float(minute + plan.cadence_min), plan.cutoff_min)}
        row.update({channel: None if missing[index] else round(float(values[index]), 6) for index, channel in enumerate(CHANNELS)})
        records.append(row)
    observation = {"schema": VERSION, "source": "simulated", "event_id": plan.event_id,
                   "product_id": plan.product_id, "planned_duration_min": plan.horizon_min, "observation_end_min": plan.cutoff_min,
                   "sample_cadence_min": plan.cadence_min, "records": records}
    return observation


def validate_observation(observation, specs):
    allowed = {"schema", "source", "event_id", "product_id", "planned_duration_min", "observation_end_min", "sample_cadence_min", "records"}
    if set(observation) != allowed or observation["schema"] != VERSION or observation["source"] != "simulated":
        raise ValueError("only declared observation fields accepted; hidden labels/parameters refused")
    if observation["product_id"] not in specs or not observation["records"]:
        raise ValueError("known product and nonempty records required")
    if not 0 < observation["observation_end_min"] <= observation["planned_duration_min"] <= 720:
        raise ValueError("invalid known plan/prefix bounds")
    previous = 0.0
    for row in observation["records"]:
        if set(row) != set(CHANNELS) | {"start_min", "end_min"}:
            raise ValueError("unknown observation channel")
        if not previous == row["start_min"] < row["end_min"] <= observation["observation_end_min"]:
            raise ValueError("observations must cover ordered prefix, never future values")
        for key in CHANNELS:
            value = row[key]
            if value is not None and (not math.isfinite(value) or isinstance(value, bool)):
                raise ValueError("invalid observed value")
            if value is not None:
                if key in CHANNELS[3:7] and value not in (0, 1):
                    raise ValueError("binary sensor channel must be 0/1/null")
                if key in {"fuel_fraction", "compressor_current_fraction", "cooling_duty_fraction", "airflow_fraction", "route_progress"} and not 0 <= value <= 1:
                    raise ValueError("fraction sensor outside 0..1")
                if key.endswith("_temp_c") and not -273.15 < value <= 200:
                    raise ValueError("temperature observation outside contract")
        previous = row["end_min"]
    if previous != observation["observation_end_min"]:
        raise ValueError("prefix coverage bounds inconsistent")


def temperature_series(observation, specs):
    validate_observation(observation, specs)
    return TemperatureSeries(source="simulated", observation_end_min=observation["observation_end_min"],
        intervals=[Interval(start_min=r["start_min"], end_min=r["end_min"], temp_c=r["product_temp_c"]) for r in observation["records"]])


def extract_features(observation, specs):
    """Pure observation-prefix transform; does not accept a Plan or label sidecar."""
    validate_observation(observation, specs)
    rows = observation["records"]
    spec = specs[observation["product_id"]]
    centre = (spec.storage_min_c + spec.storage_max_c) / 2
    durations = np.array([r["end_min"] - r["start_min"] for r in rows])
    values = {key: np.array([np.nan if r[key] is None else r[key] for r in rows]) for key in CHANNELS}
    known = {key: np.isfinite(v) for key, v in values.items()}
    horizon = observation["observation_end_min"]

    def mean(key):
        mask = known[key]
        return float(np.average(values[key][mask], weights=durations[mask])) if mask.any() else None

    def minutes(key, expected):
        return float(durations[known[key] & (values[key] == expected)].sum()) if known[key].any() else None

    def longest(mask):
        largest = current = 0.0
        for present, duration in zip(mask, durations):
            current = current + duration if present else 0
            largest = max(current, largest)
        return float(largest)

    temp = values["product_temp_c"]; mask = known["product_temp_c"]
    slope = np.full(len(rows), np.nan)
    for index in range(1, len(rows)):
        if mask[index - 1] and mask[index]:
            slope[index] = (temp[index] - temp[index - 1]) / (rows[index]["start_min"] - rows[index - 1]["start_min"])
    warm = np.isfinite(slope) & (slope > .02)
    series = temperature_series(observation, specs)
    kinetic = mkt(series.intervals, series.activation_energy_kj_mol)
    mean_temp = mean("product_temp_c")
    result = {
        "product_id": observation["product_id"], "planned_duration_min": observation["planned_duration_min"], "observed_duration_min": horizon,
        "sample_cadence_min": observation["sample_cadence_min"], "temperature_coverage_ratio": float(durations[mask].sum() / horizon),
        "auxiliary_coverage_ratio": float(np.mean([durations[known[k]].sum() / horizon for k in CHANNELS[2:]])),
        "temperature_offset_mean_c": mean_temp - centre if mean_temp is not None else None,
        "temperature_offset_min_c": float(temp[mask].min() - centre) if mask.any() else None,
        "temperature_offset_max_c": float(temp[mask].max() - centre) if mask.any() else None,
        "temperature_std_c": float(np.sqrt(np.average((temp[mask] - mean_temp) ** 2, weights=durations[mask]))) if mask.any() else None,
        "max_rise_c_per_min": float(max(0, np.nanmax(slope))) if np.isfinite(slope).any() else None,
        "max_drop_c_per_min": float(max(0, -np.nanmin(slope))) if np.isfinite(slope).any() else None,
        "known_hot_min": float(durations[mask & (temp > spec.storage_max_c)].sum()) if mask.any() else None,
        "known_cold_min": float(durations[mask & (temp < spec.storage_min_c)].sum()) if mask.any() else None,
        "longest_temperature_gap_min": longest(~mask), "known_only_mkt_offset_c": kinetic - centre if kinetic is not None else None,
        "ambient_mean_c": mean("ambient_temp_c"), "door_open_known_min": minutes("door_open", 1),
        "longest_door_open_known_min": longest(known["door_open"] & (values["door_open"] == 1)) if known["door_open"].any() else None,
        "mains_unavailable_known_min": minutes("mains_available", 0),
        "longest_mains_unavailable_known_min": longest(known["mains_available"] & (values["mains_available"] == 0)) if known["mains_available"].any() else None,
        "backup_command_known_min": minutes("backup_command", 1), "backup_running_known_min": minutes("backup_running", 1),
        "fuel_fraction_mean": mean("fuel_fraction"), "compressor_current_fraction_mean": mean("compressor_current_fraction"),
        "cooling_duty_fraction_mean": mean("cooling_duty_fraction"),
        "setpoint_offset_mean_c": mean("setpoint_c") - centre if mean("setpoint_c") is not None else None,
        "airflow_fraction_mean": mean("airflow_fraction"), "humidity_mean_pct": mean("humidity_pct"),
    }
    both = known["air_temp_c"] & mask
    result["air_product_gradient_mean_c"] = float(np.average(values["air_temp_c"][both] - temp[both], weights=durations[both])) if both.any() else None
    both = known["route_progress"]
    result["progress_lag_mean_min"] = float(np.average([max(0, rows[i]["start_min"] - values["route_progress"][i] * observation["planned_duration_min"]) for i in np.flatnonzero(both)], weights=durations[both])) if both.any() else None
    for key, channel, expected in [("warming_with_door_open_fraction", "door_open", 1),
                                  ("warming_with_mains_unavailable_fraction", "mains_available", 0)]:
        valid = np.isfinite(slope) & known[channel]
        result[key] = float(durations[warm & valid & (values[channel] == expected)].sum() / durations[valid].sum()) if valid.any() else None
    if set(result) != set(FEATURES):
        raise ValueError("predictor allowlist drift")
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in result.items()}


def hidden_labels(plan):
    # Fault occurrence comes from the hidden schedule, never a temperature rule.
    occurred = [fault for fault in plan.faults if any(activity(fault, plan.template, t) > 0
                for t in np.arange(0, plan.cutoff_min, 1))]
    codes = sorted({fault.code if fault.code in CAUSES else "unmodeled_disturbance" for fault in occurred})
    kind = "no_fault" if not codes else "unknown" if "unmodeled_disturbance" in codes else "single" if len(codes) == 1 else "multi"
    return {"event_id": plan.event_id, "family_id": plan.family_id, "injected_causes": codes,
            "label_kind": kind, "single_class_target": codes[0] if len(codes) == 1 else "no_fault" if not codes else None,
            "observationally_ambiguous": plan.ambiguity,
            "scope": "injected simulated mechanism occurrence within prefix; not temperature attribution/scrap/potency/human gold",
            "hidden_plan": asdict(plan)}


def twin(plan):
    if len(plan.faults) != 1 or plan.faults[0].code != "door_left_open":
        raise ValueError("door-only plan required for explicit ambiguity twin")
    fault = replace(plan.faults[0], code="staff_error", subtype="door")
    return replace(plan, event_id=opaque_id("EV", plan.event_id, "alternate-observer-equivalent"), faults=(fault,), ambiguity=True)
