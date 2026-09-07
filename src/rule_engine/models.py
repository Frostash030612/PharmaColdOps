"""Data models for the PharmaColdOps disposition rule engine."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Disposition(str, Enum):
    """Primary disposition of the affected batch.

    `reshipment` (replenish from an alternative warehouse) is modelled as a
    derived logistics action on `Decision.reshipment_required` rather than a
    batch disposition, and is mapped back to the proposal's five-class label
    for evaluation.
    """

    RELEASE = "release"
    QUARANTINE = "quarantine"
    RETEST = "retest"
    SCRAP = "scrap"


@dataclass(frozen=True)
class ProductSpec:
    """Product stability parameters and allowable excursion thresholds."""

    product_id: str
    storage_min_c: float
    storage_max_c: float
    allowable_duration_min: int  # allowable time above the storage range
    mkt_threshold_c: float       # Mean Kinetic Temperature ceiling
    retestable: bool = True


@dataclass(frozen=True)
class ExcursionEvent:
    """A single temperature-excursion event to be dispositioned."""

    scenario_id: str
    product_id: str
    excursion_temp_c: float
    duration_min: int
    mkt_c: float
    packaging: str  # "intact" | "compromised"
    stage: str      # e.g. "transit", "airport_dwell", "warehouse"


@dataclass(frozen=True)
class Decision:
    """The engine's output for one excursion event."""

    disposition: Disposition
    reshipment_required: bool
    rule_path: str
    evidence: dict
