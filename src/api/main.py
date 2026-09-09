"""FastAPI app for the PharmaColdOps disposition service.

Run from the repo root::

    uvicorn --app-dir src api.main:app --port 8000

Open the demo against it:  ``frontend/index.html?api=http://127.0.0.1:8000``
(CORS is open so the demo also works from ``file://``).

Routes marked 501 are reserved for the optimisation (re-routing) and
knowledge-graph QA modules, which this milestone does not expose over HTTP yet.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import service
from .schemas import BatchIn, DecideIn, GridIn

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


@app.post("/api/decide")
def decide(req: DecideIn):
    try:
        return service.decide_view(req, req.spec_override)
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


@app.post("/api/route")
def route() -> None:
    raise HTTPException(
        status_code=501,
        detail="re-routing optimiser is not exposed over HTTP in this milestone",
    )


@app.post("/api/qa")
def qa() -> None:
    raise HTTPException(
        status_code=501,
        detail="knowledge-graph QA is not exposed over HTTP in this milestone",
    )
