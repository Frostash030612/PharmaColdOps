"""M2: explicit, piecewise-constant temperature intervals, not sensor claims.

Each interval is [start_min, end_min). No interpolation, extrapolation, or
implicit sample cadence. Null temperatures and uncovered gaps remain unknown.
MKT uses time weights and log-sum-exp; this is a demo engineering calculation,
not a product-specific stability model or proof against freezing damage.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Literal

from pydantic import BaseModel, Field, model_validator

METHOD = "m2-interval-arrhenius-v1"
GAS_CONSTANT = 8.31446261815324  # J / (mol K)


class Interval(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    start_min: float = Field(ge=0, le=10080)
    end_min: float = Field(gt=0, le=10080)
    temp_c: float | None = Field(default=None, gt=-273.15, le=200)

    @model_validator(mode="after")
    def positive_duration(self):
        if self.end_min <= self.start_min:
            raise ValueError("interval end must be after start")
        return self


class TemperatureSeries(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    source: Literal["simulated", "manual_simulated"] = "manual_simulated"
    observation_end_min: float = Field(gt=0, le=10080)
    activation_energy_kj_mol: float = Field(default=83.144, ge=20, le=200)
    intervals: list[Interval] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def ordered_intervals(self):
        previous = 0.0
        for interval in self.intervals:
            if interval.start_min < previous:
                raise ValueError("intervals must be ordered and non-overlapping")
            if interval.end_min > self.observation_end_min:
                raise ValueError("interval exceeds observation horizon")
            previous = interval.end_min
        return self


class TemperatureContext(BaseModel):
    model_config = {"extra": "forbid"}
    series: TemperatureSeries
    window_id: str = Field(pattern=r"^window-[0-9]{3,5}$")
    method: Literal["m2-interval-arrhenius-v1"] = METHOD


class AnalyseIn(BaseModel):
    model_config = {"extra": "forbid"}
    product_id: str
    series: TemperatureSeries


class SimulateIn(BaseModel):
    model_config = {"extra": "forbid"}
    product_id: str
    scenario: Literal["normal", "hot", "cold", "mixed", "gap"] = "hot"
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    observation_end_min: int = Field(default=120, ge=30, le=1440)
    interval_min: int = Field(default=5, ge=1, le=60)

    @model_validator(mode="after")
    def adequate_resolution(self):
        if self.interval_min > self.observation_end_min / 6:
            raise ValueError("simulation requires at least six intervals")
        return self


def mkt(intervals: list[Interval], activation_energy_kj_mol: float) -> float | None:
    known = [i for i in intervals if i.temp_c is not None]
    if not known:
        return None
    duration = math.fsum(i.end_min - i.start_min for i in known)
    a = activation_energy_kj_mol * 1000 / GAS_CONSTANT
    terms = [math.log(i.end_min - i.start_min) - math.log(duration) - a / (i.temp_c + 273.15) for i in known]
    pivot = max(terms)
    log_mean = pivot + math.log(math.fsum(math.exp(t - pivot) for t in terms))
    return -a / log_mean - 273.15


def analyse(series: TemperatureSeries, spec) -> dict:
    """Maximal contiguous runs of hot/cold intervals; gaps always split runs."""
    groups: list[tuple[str, list[Interval]]] = []
    gaps = []
    previous = 0.0
    active = None
    for interval in series.intervals:
        if interval.start_min > previous:
            gaps.append({"start_min": previous, "end_min": interval.start_min})
            active = None
        if interval.temp_c is None:
            gaps.append({"start_min": interval.start_min, "end_min": interval.end_min})
            active = None
        else:
            kind = "hot" if interval.temp_c > spec.storage_max_c else "cold" if interval.temp_c < spec.storage_min_c else None
            if kind is None:
                active = None
            elif active is not None and active[0] == kind:
                active[1].append(interval)
            else:
                active = (kind, [interval])
                groups.append(active)
        previous = interval.end_min
    if previous < series.observation_end_min:
        gaps.append({"start_min": previous, "end_min": series.observation_end_min})
    known_min = math.fsum(i.end_min - i.start_min for i in series.intervals if i.temp_c is not None)
    complete = not gaps
    windows = []
    for n, (kind, intervals) in enumerate(groups, 1):
        temperatures = [i.temp_c for i in intervals]
        duration = intervals[-1].end_min - intervals[0].start_min
        extreme = max(temperatures) if kind == "hot" else min(temperatures)
        # Existing M3 knows a freezing rule only, not arbitrary cold exposure.
        supported = kind == "hot" or (spec.freeze_sensitive and extreme <= 0)
        windows.append({
            "window_id": f"window-{n:03d}", "kind": kind,
            "start_min": intervals[0].start_min, "end_min": intervals[-1].end_min,
            "duration_exact_min": duration, "min_c": min(temperatures), "max_c": max(temperatures),
            "event": {"excursion_temp_c": extreme, "duration_min": math.ceil(duration),
                      "mkt_c": mkt(intervals, series.activation_energy_kj_mol)},
            "registration_allowed": complete and supported,
            "blocked_reason": "incomplete_coverage" if not complete else "cold_rule_not_supported" if not supported else None,
        })
    source_hash = hashlib.sha256(json.dumps(series.model_dump(), sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {
        "method": METHOD, "source": series.source, "source_hash": source_hash,
        "activation_energy_kj_mol": series.activation_energy_kj_mol, "gas_constant_j_mol_k": GAS_CONSTANT,
        "storage_min_c": spec.storage_min_c, "storage_max_c": spec.storage_max_c,
        "observation_end_min": series.observation_end_min, "known_duration_min": known_min,
        "coverage_complete": complete, "coverage_ratio": known_min / series.observation_end_min,
        "missing_intervals": gaps, "known_only_mkt_c": mkt(series.intervals, series.activation_energy_kj_mol),
        "total_hot_min": math.fsum(w["duration_exact_min"] for w in windows if w["kind"] == "hot"),
        "total_cold_min": math.fsum(w["duration_exact_min"] for w in windows if w["kind"] == "cold"),
        "windows": windows,
        "limitations": ["simulated_not_sensor_data", "activation_energy_demo_assumption",
                        "mkt_not_freezing_safety", "decision_scope_selected_window_not_cumulative"],
    }


def simulate(req: SimulateIn, spec) -> TemperatureSeries:
    rng = random.Random(req.seed)
    horizon = req.observation_end_min
    centre = (spec.storage_min_c + spec.storage_max_c) / 2
    width = spec.storage_max_c - spec.storage_min_c
    intervals = []
    for start in range(0, horizon, req.interval_min):
        fraction = start / horizon
        temp = centre + rng.uniform(-width * .08, width * .08)
        if .25 <= fraction < .55 and req.scenario in {"hot", "mixed", "gap"}:
            temp = spec.storage_max_c + width * .6 + rng.uniform(0, width * .1)
        if .65 <= fraction < .85 and req.scenario in {"cold", "mixed"}:
            temp = min(-1.0, spec.storage_min_c - width * .6) - rng.uniform(0, width * .1)
        if start <= horizon * .45 < min(horizon, start + req.interval_min) and req.scenario == "gap":
            temp = None
        intervals.append(Interval(start_min=start, end_min=min(horizon, start + req.interval_min),
                                  temp_c=None if temp is None else round(temp, 4)))
    return TemperatureSeries(source="simulated", observation_end_min=horizon, intervals=intervals)
