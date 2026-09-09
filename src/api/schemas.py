"""Pydantic request/response models for the disposition API.

Field names mirror the demo's ``current`` event and ``spec`` objects so the
front-end can post them verbatim. ``spec_override`` carries the demo's "rule
configuration" sandbox (left-hand panel); when omitted the product's stock
thresholds from ``rules_config.json`` are used.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SpecOverride(BaseModel):
    """Optional sandbox overrides for one product's decision thresholds."""

    allowable_duration_min: Optional[int] = Field(default=None, gt=0)
    mkt_threshold_c: Optional[float] = None
    retestable: Optional[bool] = None


class EventIn(BaseModel):
    """The six excursion inputs the sandbox edits (mirrors ``current``)."""

    product_id: str
    excursion_temp_c: float
    duration_min: int = Field(ge=0)
    mkt_c: float
    packaging: Literal["intact", "compromised"]
    stage: str = "transit"


class DecideIn(EventIn):
    """One event + optional threshold overrides → full decision view."""

    spec_override: Optional[SpecOverride] = None


class GridIn(BaseModel):
    """One-shot decision matrix for the duration × MKT boundary map.

    The map is spec-driven (26 columns × 18 rows of mid-point cells), so it is
    fetched once per spec change rather than 468 times per slider tick.
    ``durations`` (ascending) and ``mkts`` (descending, top row first) must be
    pre-sorted by the client exactly as it draws the cells.
    """

    product_id: str
    excursion_temp_c: float
    packaging: Literal["intact", "compromised"] = "intact"
    stage: str = "transit"
    spec_override: Optional[SpecOverride] = None
    durations: List[float] = Field(min_length=1)
    mkts: List[float] = Field(min_length=1)


class BatchIn(BaseModel):
    """Preset scenarios → trimmed decisions (disposition is all the UI needs)."""

    events: List[EventIn] = Field(min_length=1)
