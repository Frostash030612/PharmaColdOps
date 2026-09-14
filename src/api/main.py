"""FastAPI app for the PharmaColdOps disposition service.

Run from the repo root::

    uvicorn --app-dir src api.main:app --port 8000

Open the demo against it:  ``frontend-vue`` served with
``?api=http://127.0.0.1:8000`` (CORS is open for local development).

The route endpoint bridges closed reshipment cases to the fixed Singapore
VRPTW demo. The QA endpoint exposes structured knowledge-graph queries.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import service
from .schemas import (
    BatchIn, CaseCloseIn, DecideIn, DispatchCommandIn, DispatchCreateIn,
    EmergencyAcceptIn, EmergencyPreviewIn,
    DispatchDeliverIn, DispatchPlanIn, DispatchSpeedIn, GridIn, QAIn, QAOut,
    RouteIn, RouteOut,
)

app = FastAPI(
    title="PharmaColdOps disposition API",
    version="0.1.0",
    description=(
        "Decision semantics from the real rule engine (src/rule_engine): "
        "disposition, rule_no, reshipment, risk score + cause code and evidence "
        "classification. Wording stays client-localised."
    ),
)

# Wide-open CORS for local development: the demo may be opened via file://
# (origin "null") or any static server during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "module": "rule_engine",
        "products": service.valid_product_ids(),
    }


@app.get("/api/runs")
def runs(limit: int = 200) -> dict:
    """Case history: newest-first archive of every closed inbound case.

    Backed by the append-only ``data/audit/runs.jsonl`` log (runtime artifact,
    gitignored). Only ``/api/case_close`` appends — ``/api/decide`` previews are
    never archived. The front-end calls this on load and after each close.
    """
    return service.list_runs(limit)


@app.post("/api/decide")
def decide(req: DecideIn):
    try:
        return service.decide_view(req, req.spec_override)
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product_id {req.product_id!r}; valid: {service.valid_product_ids()}",
        )


@app.post("/api/case_close")
def case_close(req: CaseCloseIn):
    """Archive ONE completed inbound case as a run record.

    Recomputes the decision from the posted inputs (deterministic — identical to
    the live /api/decide preview the sandbox was showing) and appends it to the
    runs log. Live decide previews are never archived; only this explicit close
    is, so the history reads one line per closed case.
    """
    try:
        return service.close_case(req, req.spec_override, req.started_at, req.remark)
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product_id {req.product_id!r}; valid: {service.valid_product_ids()}",
        )


@app.post("/api/grid")
def grid(req: GridIn):
    try:
        return service.grid_view(req)
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product_id {req.product_id!r}; valid: {service.valid_product_ids()}",
        )


@app.post("/api/decide_batch")
def decide_batch(req: BatchIn) -> dict:
    return service.batch_view(req.events)


@app.post("/api/route", response_model=RouteOut)
def route(req: RouteIn):
    try:
        return service.route_view(req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown run_id {req.run_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/plan")
def dispatch_plan(req: DispatchPlanIn):
    """Preview daily multi-order routes; no stock or vehicle state is changed."""
    try:
        return service.dispatch_plan_view(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/reshipments")
def route_reshipment_case(req: RouteIn):
    """Commit one closed reshipment case into the shared dispatch operation.

    Unlike ``/api/route`` (a stateless preview that reserves nothing) this
    reserves stock and assigns a vehicle, so the resupply becomes part of the
    same operation the dispatch console and the map show.
    """
    record = service.find_run(req.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {req.run_id!r}")
    try:
        return service.route_reshipment(record)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/runs")
def create_dispatch_run(req: DispatchCreateIn):
    try:
        return service.create_dispatch(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/dispatch/active")
def get_active_dispatch():
    """The resupply operation currently open, if any.

    404 means nothing is in progress — a normal empty state, not a failure.
    """
    try:
        return service.get_active_reshipment_dispatch()
    except KeyError:
        raise HTTPException(status_code=404, detail="no active dispatch operation")


@app.get("/api/dispatch/runs/{dispatch_id}")
def get_dispatch_run(dispatch_id: str):
    try:
        return service.get_dispatch(dispatch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")


@app.post("/api/dispatch/runs/{dispatch_id}/depart")
def depart_dispatch_run(dispatch_id: str, req: DispatchCommandIn):
    try:
        return service.depart_dispatch(dispatch_id, req.command_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/tick")
def tick_dispatch_run(dispatch_id: str):
    """Advance the operation to the simulated clock: record arrivals that are due.

    Safe to poll — each arrival is applied as a normal, idempotent delivery
    command, so ticking twice records nothing twice.
    """
    try:
        return service.tick_dispatch(dispatch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")


@app.post("/api/dispatch/runs/{dispatch_id}/speed")
def set_dispatch_speed(dispatch_id: str, req: DispatchSpeedIn):
    """Switch between real time and accelerated playback mid-run."""
    try:
        return service.set_dispatch_speed(dispatch_id, req.speed)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/deliver-next")
def deliver_dispatch_run(dispatch_id: str, req: DispatchDeliverIn):
    try:
        return service.deliver_dispatch(dispatch_id, req.vehicle_id, req.command_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/emergency-preview")
def preview_emergency_dispatch(dispatch_id: str, req: EmergencyPreviewIn):
    """Compare real resource options; this preview does not reserve or reroute."""
    try:
        return service.emergency_dispatch_preview(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/emergency-accept")
def accept_emergency_dispatch(dispatch_id: str, req: EmergencyAcceptIn):
    try:
        return service.accept_emergency_dispatch(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/qa", response_model=QAOut)
def qa(req: QAIn):
    try:
        return service.qa_view(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
