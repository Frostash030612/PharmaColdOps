"""FastAPI app for the PharmaColdOps disposition service.

Run from the repo root::

    uvicorn --app-dir src api.main:app --port 8000

Open the demo against it:  ``frontend-vue`` served with
``?api=http://127.0.0.1:8000`` (CORS is open for local development).

The route endpoint bridges closed reshipment cases to the fixed Singapore
VRPTW demo. The QA endpoint exposes structured knowledge-graph queries.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import service
from .schemas import (
    BatchIn, BranchPolicyIn, CaseCloseIn, DecideIn, DispatchCommandIn, DispatchCreateIn,
    DelayAcceptIn, DelayPreviewIn,
    CaseWorkflowIn,
    SimulationBatchIn,
    UrgentPreviewIn, UrgentAcceptIn,
    EmergencyAcceptIn, EmergencyPreviewIn,
    DispatchDeliverIn, DispatchPlanIn, DispatchReplayIn, DispatchSpeedIn, GridIn,
    OvernightPlanIn, QAIn, QAOut,
    OvernightRunPreviewIn, OvernightRunAcceptIn, NextDayIn,
    RouteIn, RouteOut,
    VehicleFailureAcceptIn, VehicleFailurePreviewIn,
)

@asynccontextmanager
async def lifespan(app):
    async def retry_graph():
        while True:
            try:
                await asyncio.to_thread(service.sync_case_graph)
            except Exception:
                logging.getLogger("uvicorn.error").warning("graph outbox retry unavailable", exc_info=True)
            await asyncio.sleep(15)

    task = asyncio.create_task(retry_graph()) if os.environ.get("KG_SYNC_ENABLED", "0") == "1" else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    lifespan=lifespan,
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
    try:
        return service.list_runs(limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/decide")
def decide(req: DecideIn):
    try:
        return service.decide_view(req, req.spec_override)
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product_id {req.product_id!r}; valid: {service.valid_product_ids()}",
        )


@app.get("/api/graph-sync")
def graph_sync_status():
    """Read-only durable delivery status, not a Neo4j connectivity claim."""
    try:
        return service.graph_sync_status(service.DISPATCH_DATABASE_URL)
    except Exception:
        raise HTTPException(status_code=503, detail="case registration storage unavailable")


@app.post("/api/case_close")
def case_close(req: CaseCloseIn):
    """Archive ONE completed inbound case as a run record.

    Recomputes the decision from the posted inputs (deterministic — identical to
    the live /api/decide preview the sandbox was showing) and appends it to the
    runs log. Live decide previews are never archived; only this explicit close
    is, so the history reads one line per closed case.
    """
    try:
        return service.close_case(req, req.spec_override, req.started_at, req.remark, req.registration_id)
    except service.RegistrationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product_id {req.product_id!r}; valid: {service.valid_product_ids()}",
        )


@app.post("/api/runs/{run_id}/workflow")
def update_case_workflow(run_id: str, req: CaseWorkflowIn):
    try:
        return service.update_case_progress(run_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown incident run_id")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


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


@app.post("/api/dispatch/reshipments/preview")
def preview_reshipment_case(req: BranchPolicyIn):
    """Every way this closed case could be served, before committing to one.

    Read-only: nothing is reserved and no state changes. The operator compares
    the options (reuse a running vehicle's own spare, fetch from the depot, load
    before departure, or send another vehicle), picks one, and posts that choice
    to ``/api/dispatch/reshipments``.

    409 means there is no open daily plan to branch from — create today's plan
    first; a branch event is not an operation of its own.
    """
    record = service.find_run(req.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {req.run_id!r}")
    try:
        return service.reshipment_branch_plan(record, policy=req.policy)
    except service.NoActiveDeliveryPlan as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/reshipments")
def route_reshipment_case(req: RouteIn):
    """Commit one closed reshipment case into the day's delivery plan.

    Unlike ``/api/route`` (a stateless preview that reserves nothing) this
    reserves stock and assigns a vehicle, so the resupply becomes part of the
    same operation the dispatch console and the map show. It attaches to the
    OPEN daily plan; without one this answers 409 rather than starting a
    one-order operation of its own (docs/C_配送模块.md §4.4-2).
    """
    record = service.find_run(req.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {req.run_id!r}")
    try:
        return service.route_reshipment(
            record, candidate_kind=req.candidate_kind,
            vehicle_id=req.vehicle_id, policy=req.policy,
        )
    except service.NoActiveDeliveryPlan as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/runs")
def create_dispatch_run(req: DispatchCreateIn):
    try:
        return service.create_dispatch(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/overnight-plan")
def plan_overnight_parking(req: OvernightPlanIn):
    """Where each truck should spend the night, and what that saves tomorrow.

    Read-only: it plans tomorrow's fixed orders once to learn each truck's first
    stop, then picks the allowed parking node closest to it, charging the drive
    against today's mileage cap. Nothing is persisted and no stock is reserved
    (docs/路径规划总逻辑方案.md §4, B5).
    """
    try:
        return service.overnight_plan_view(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/dispatch/active")
def get_active_dispatch():
    """The delivery operation currently open, whichever pathway created it.

    Originally reshipment-only; a "today's delivery plan" created through
    ``POST /api/dispatch/runs`` is a first-class operation too, and the panel has
    to be able to show it (docs/C_配送模块.md §4.1).

    404 means nothing is in progress — a normal empty state, not a failure.
    """
    try:
        return service.get_active_dispatch()
    except KeyError:
        raise HTTPException(status_code=404, detail="no active dispatch operation")


@app.get("/api/dispatch/daily-orders")
def get_daily_orders(hospitals: int = 4, seed: str | None = None,
                     temperature_zone: str = "chilled"):
    """A simulated batch of ordinary hospital orders for today's plan.

    ``seed`` is an integer for a reproducible draw, the literal ``today`` for
    "the batch belonging to today's date" (reproducible within the day, different
    tomorrow — the offline stand-in for a daily delivery feed), or omitted for the
    fixed demo set.  The response is shaped like the body of
    ``POST /api/dispatch/plan`` (or ``/runs``), so the client previews it and then
    confirms it without reshaping anything.  Everything is simulated — see
    ``optimisation.daily_orders.ASSUMPTIONS``, which travels in the response.
    """
    try:
        return service.daily_plan_request(
            hospitals=hospitals, seed=seed, temperature_zone=temperature_zone
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/simulated-orders")
def simulated_orders(req: SimulationBatchIn):
    try:
        return service.simulated_plan_request(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/dispatch/urgent-options")
def urgent_options():
    return service.urgent_options()


@app.post("/api/dispatch/runs/{dispatch_id}/urgent-preview")
def urgent_preview(dispatch_id: str, req: UrgentPreviewIn):
    try:
        return service.preview_urgent_dispatch(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown dispatch run")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/urgent-accept")
def urgent_accept(dispatch_id: str, req: UrgentAcceptIn):
    try:
        return service.accept_urgent_dispatch(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown dispatch run")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/dispatch/runs/{dispatch_id}")
def get_dispatch_run(dispatch_id: str):
    try:
        return service.get_dispatch(dispatch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")


@app.post("/api/dispatch/runs/{dispatch_id}/depart")
def depart_dispatch_run(dispatch_id: str, req: DispatchCommandIn):
    try:
        return service.depart_dispatch(dispatch_id, req.command_id, speed=req.speed)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/dispatch/runs")
def list_dispatch_runs(limit: int = 5):
    """Recent operations, newest first: what can be replayed.

    404-free by design — an empty list simply means nothing has been dispatched.
    """
    return {"runs": service.recent_dispatch_runs(limit)}


@app.post("/api/dispatch/runs/{dispatch_id}/replay")
def replay_dispatch_run(dispatch_id: str, req: DispatchReplayIn):
    """Run the same plan again from the beginning, as a new operation.

    Not time travel: the finished run stays as history and the identical batch is
    planned and departed afresh. Answers 404 for an unknown run and 409 when the
    stored input cannot be replayed; the response names the run it came from
    (``replayed_from``) so the console can say which one is on screen.
    """
    try:
        return service.replay_dispatch(dispatch_id, speed=req.speed,
                                       new_dispatch_id=req.dispatch_id)
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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


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


@app.post("/api/dispatch/runs/{dispatch_id}/failure-preview")
def preview_vehicle_failure_dispatch(dispatch_id: str, req: VehicleFailurePreviewIn):
    """Read-only mechanical-failure rescue assessment for an in-transit vehicle."""
    try:
        return service.vehicle_failure_preview(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/failure-accept")
def accept_vehicle_failure_dispatch(dispatch_id: str, req: VehicleFailureAcceptIn):
    """Mark the selected vehicle failed and send replacement stock in a spare truck."""
    try:
        return service.accept_vehicle_failure_dispatch(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/delay-preview")
def preview_dispatch_delay(dispatch_id: str, req: DelayPreviewIn):
    """Inspect every active route for forecast delivery-window misses.

    Read-only.  The response names the exact current and improved stop queues;
    the operator must call ``delay-accept`` to make a re-sequence real.
    """
    try:
        return service.delay_dispatch_preview(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/delay-accept")
def accept_dispatch_delay(dispatch_id: str, req: DelayAcceptIn):
    """Apply one previewed delay remedy once, after revalidating it."""
    try:
        return service.accept_delay_dispatch(dispatch_id, req)
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


@app.post("/api/dispatch/runs/{dispatch_id}/overnight-preview")
def preview_overnight_dispatch(dispatch_id: str, req: OvernightRunPreviewIn):
    try:
        return service.overnight_dispatch_preview(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/overnight-accept")
def accept_overnight_dispatch(dispatch_id: str, req: OvernightRunAcceptIn):
    try:
        return service.accept_overnight_dispatch(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/dispatch/runs/{dispatch_id}/next-day")
def start_next_dispatch_day(dispatch_id: str, req: NextDayIn):
    try:
        return service.create_next_day(dispatch_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown dispatch_id {dispatch_id!r}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
