"""Pydantic request/response models for the disposition API.

Field names mirror the demo's ``current`` event and ``spec`` objects so the
front-end can post them verbatim. ``spec_override`` carries the demo's "rule
configuration" sandbox (left-hand panel); when omitted the product's stock
thresholds from ``rules_config.json`` are used.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

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
    #: Which transport order this excursion concerns (2026-09-16). The simulated
    #: input already knows it, and the order carries the product, the receiving
    #: hospital and the quantity — so the rescue no longer has to guess a
    #: destination from a dropdown or a quantity from the node's demo demand.
    order_id: Optional[str] = None


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
    """Route a reshipment attached to one already-closed case.

    ``candidate_kind``/``vehicle_id`` are optional: given, the bridge applies
    exactly that option (the operator's pick from the comparison card); omitted,
    it takes the best one under ``policy``.
    """

    run_id: str
    algorithm: Literal["greedy", "ortools"] = "greedy"
    candidate_kind: Optional[CandidateKind] = None
    vehicle_id: Optional[str] = None
    policy: CandidatePolicy = "minimize_disruption"


class BranchPolicyIn(BaseModel):
    """Read-only branch preview: which case, ranked how."""

    run_id: str
    policy: CandidatePolicy = "minimize_disruption"


class RouteOut(BaseModel):
    order_id: str
    algorithm: str
    vehicles_used: int
    total_distance: float
    on_time_rate: float
    served_customers: int
    target_customers: int
    time_window_violations: int
    capacity_violations: int
    depot_return_violations: int
    vehicle_limit_violations: int
    routes: list[dict]
    geojson: dict


class DispatchOrderIn(BaseModel):
    order_id: str
    product_id: str
    #: Where the goods are picked up. Omitted ⇒ the planner's default origin, so
    #: every existing payload keeps working (2026-09-16, B1b).
    origin_facility_id: Optional[str] = None
    destination_facility_id: str
    quantity: int = Field(gt=0)
    earliest_min: int = Field(ge=0)
    latest_min: int = Field(ge=0)
    temperature_zone: Literal["chilled", "frozen", "ultracold"]
    source_run_id: Optional[str] = None


class InventoryLotIn(BaseModel):
    lot_id: str
    product_id: str
    facility_id: str
    available_quantity: int = Field(ge=0)
    temperature_zone: Literal["chilled", "frozen", "ultracold"]
    status: Literal["available", "reserved", "quarantine", "scrap"] = "available"


class OnboardSpareIn(BaseModel):
    """Stock a vehicle carries beyond its assigned orders (a load assumption)."""

    product_id: str
    temperature_zone: Literal["chilled", "frozen", "ultracold"]
    quantity: int = Field(gt=0)


class DispatchVehicleIn(BaseModel):
    vehicle_id: str
    capacity: int = Field(gt=0)
    temperature_zone: Literal["chilled", "frozen", "ultracold"]
    start_facility_id: str
    available_from_min: int = Field(default=0, ge=0)
    status: Literal["available", "in_transit", "failed"] = "available"
    onboard_spare: List[OnboardSpareIn] = Field(default_factory=list)


class DispatchConstraintsIn(BaseModel):
    """Hard operating limits; omitted fields keep the legacy behaviour."""

    max_vehicles: Optional[int] = Field(default=None, ge=1)
    max_stops_per_vehicle: Optional[int] = Field(default=None, ge=1)
    #: Whole distance one vehicle may drive in a day (metres): empty
    #: repositioning, loaded legs and the closing leg all count (2026-09-16).
    mileage_limit_m: Optional[int] = Field(default=None, ge=1)
    #: Parking nodes. When set, routes are open — each one ends at the nearest of
    #: these instead of driving back to the depot, and no return leg is charged.
    terminal_facility_ids: Optional[List[str]] = None
    #: "grouped" (default): one fleet per source, so a truck serves orders from a
    #: single source. "pickup_delivery": one fleet per zone and a truck may collect
    #: from several sources on one route (PDPTW, 2026-09-16; needs algorithm=ortools).
    routing_model: Literal["grouped", "pickup_delivery"] = "grouped"


#: Every way a branch order can be served. Previously this literal listed only
#: two of the three implemented kinds, so the API answered 422 for the
#: ``load_before_departure`` candidate it had just offered in a preview.
CandidateKind = Literal[
    "add_stop_in_transit", "load_before_departure", "return_to_depot", "spare_vehicle",
]

#: How candidates are ranked. A business choice (protect running orders vs
#: protect the fleet), so it travels with the request and is echoed back.
CandidatePolicy = Literal["minimize_disruption", "minimize_vehicles"]


class DispatchPlanIn(BaseModel):
    orders: List[DispatchOrderIn] = Field(min_length=1)
    inventory: List[InventoryLotIn]
    vehicles: List[DispatchVehicleIn]
    algorithm: Literal["greedy", "ortools"] = "greedy"
    constraints: DispatchConstraintsIn = Field(default_factory=DispatchConstraintsIn)


class DispatchCreateIn(DispatchPlanIn):
    dispatch_id: str
    command_id: str


class OvernightPlanIn(DispatchPlanIn):
    """Tomorrow's fixed orders + how far each truck already drove today.

    The overnight decision needs both: tomorrow's first stops decide *where* to
    park, today's remaining mileage budget decides *whether* the truck may still
    drive there (2026-09-16, B5).
    """

    today_distance_m: Dict[str, int] = Field(default_factory=dict)


class DispatchCommandIn(BaseModel):
    command_id: str
    #: Departure speed. Present here because the service has always accepted it
    #: and silently dropping a field the caller sent is worse than honouring it;
    #: omit to keep the default, 0 to leave the clock frozen at the start.
    speed: Optional[float] = Field(default=None, ge=0)


class DispatchSpeedIn(BaseModel):
    """How fast simulated time runs: 0 freezes it, 60 = a minute per second."""

    speed: float = Field(ge=0)


class DispatchReplayIn(BaseModel):
    """Run the same plan again, optionally at a given speed, optionally renamed."""

    speed: float = Field(default=60.0, ge=0)
    dispatch_id: Optional[str] = None


class DispatchDeliverIn(DispatchCommandIn):
    vehicle_id: str


class EmergencyPreviewIn(BaseModel):
    order: DispatchOrderIn
    current_time_min: int = Field(ge=0)
    policy: CandidatePolicy = "minimize_disruption"


class EmergencyAcceptIn(EmergencyPreviewIn):
    candidate_kind: CandidateKind
    vehicle_id: str
    command_id: str


class EvidenceOut(BaseModel):
    """One evidence node exactly as the front-end renders it."""

    node_type: str
    node_id: str
    summary: str


class QAIn(BaseModel):
    """Structured KG query; natural-language classification is client-side.

    ``question_type`` is a plain string so an unsupported intent comes back as a
    contract-shaped ``status="unsupported"`` answer instead of a 4xx — the
    front-end can then render one localised notice per outcome class.
    """

    question_type: str
    run_id: Optional[str] = None
    product_id: Optional[str] = None
    cause_code: Optional[str] = None

    @model_validator(mode="after")
    def require_query_identifier(self):
        if self.question_type in {"why_disposition", "audit_chain"} and not self.run_id:
            raise ValueError(f"run_id is required for {self.question_type}")
        if self.question_type == "product_requirements" and not self.product_id:
            raise ValueError("product_id is required for product_requirements")
        if self.question_type == "cause_context" and not (self.run_id or self.cause_code):
            raise ValueError("run_id or cause_code is required for cause_context")
        return self


class QAOut(BaseModel):
    """One KG answer plus the evidence nodes that back it.

    ``status`` distinguishes the outcome classes the front-end must not conflate
    (proposal §6.5): ``ok``, ``no_case``, ``insufficient_evidence``,
    ``unsupported``. A database failure is reported as HTTP 503 instead (the
    ``db_error`` class); ``answer`` and ``evidence`` text quotes the source
    documents verbatim.
    """

    status: Literal["ok", "no_case", "insufficient_evidence", "unsupported"]
    answer: str
    evidence: list[EvidenceOut]
