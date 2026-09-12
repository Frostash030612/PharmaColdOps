"""Pydantic request/response models for the disposition API.

Field names mirror the demo's ``current`` event and ``spec`` objects so the
front-end can post them verbatim. ``spec_override`` carries the demo's "rule
configuration" sandbox (left-hand panel); when omitted the product's stock
thresholds from ``rules_config.json`` are used.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SpecOverride(BaseModel):
    """Optional sandbox overrides for one product's decision thresholds."""

    allowable_duration_min: Optional[int] = Field(default=None, gt=0)
    mkt_threshold_c: Optional[float] = None
    retestable: Optional[bool] = None


class EventIn(BaseModel):
    """Excursion inputs, optionally linked to known routing facilities."""

    product_id: str
    excursion_temp_c: float
    duration_min: int = Field(ge=0)
    mkt_c: float
    packaging: Literal["intact", "compromised"]
    stage: str = "transit"
    facility_id: Optional[str] = None
    destination_facility_id: Optional[str] = None


class DecideIn(EventIn):
    """One event + optional threshold overrides → full decision view."""

    spec_override: Optional[SpecOverride] = None


class CaseCloseIn(DecideIn):
    """Close an inbound case → compute + archive ONE run record.

    ``/api/decide`` previews are never archived; only this explicit close writes
    to the runs log. ``started_at`` (ISO, when the case was opened) and
    ``remark`` are optional case metadata stored with the record.
    """

    started_at: Optional[str] = None
    remark: Optional[str] = None


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


class RouteIn(BaseModel):
    """Route a reshipment attached to one already-closed case."""

    run_id: str
    algorithm: Literal["greedy", "ortools"] = "greedy"


class RouteOut(BaseModel):
    order_id: str
    algorithm: str
    vehicles_used: int
    total_distance: float
    on_time_rate: float
    served_customers: int
    time_window_violations: int
    capacity_violations: int
    depot_return_violations: int
    vehicle_limit_violations: int
    routes: list[dict]
    geojson: dict


class QAIn(BaseModel):
    """Structured KG query; natural-language classification is client-side."""

    question_type: Literal[
        "why_disposition", "audit_chain", "product_requirements", "disposition_stats"
    ]
    run_id: Optional[str] = None
    product_id: Optional[str] = None

    @model_validator(mode="after")
    def require_query_identifier(self):
        if self.question_type in {"why_disposition", "audit_chain"} and not self.run_id:
            raise ValueError(f"run_id is required for {self.question_type}")
        if self.question_type == "product_requirements" and not self.product_id:
            raise ValueError("product_id is required for product_requirements")
        return self
