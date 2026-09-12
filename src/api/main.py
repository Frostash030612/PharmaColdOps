"""FastAPI app for the PharmaColdOps disposition service.

Run from the repo root::

    uvicorn --app-dir src api.main:app --port 8000

Open the demo against it:  ``frontend/index.html?api=http://127.0.0.1:8000``
(CORS is open so the demo also works from ``file://``).

The route endpoint bridges closed reshipment cases to the fixed Singapore
VRPTW demo. The QA endpoint exposes structured knowledge-graph queries.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import service
from .schemas import BatchIn, CaseCloseIn, DecideIn, DispatchPlanIn, GridIn, QAIn, RouteIn, RouteOut

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


@app.post("/api/qa")
def qa(req: QAIn):
    try:
        return service.qa_view(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
