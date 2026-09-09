"""Decision-service business logic: a thin, import-safe layer over the engine.

Built on one module-level ``RuleEngine`` (the engine re-reads
``rules_config.json`` per construction, so a singleton avoids re-loading on
every request). Sandbox overrides are honoured by resolving a per-request
``ProductSpec`` and evaluating with an engine that carries just that product
overridden — the base config is never mutated.

``classify_evidence`` / ``risk_score`` mirror the demo's ``renderEvidence`` /
``riskInfo`` so the *same* semantics are available over HTTP; wording stays on
the client.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# uvicorn wires handlers onto its own loggers, so this line appears on the
# console next to the access log — a live "audit trail" proving each front-end
# change really round-trips to the Python engine (drag a slider and watch).
log = logging.getLogger("uvicorn.error")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rule_engine.engine import RuleEngine  # noqa: E402
from rule_engine.models import ExcursionEvent, ProductSpec  # noqa: E402

from .schemas import EventIn, GridIn, SpecOverride  # noqa: E402

# Loaded once; used both as the source of stock thresholds and to keep the
# per-request override engines cheap (dict copy, no disk I/O).
ENGINE = RuleEngine()


def valid_product_ids() -> list:
    return sorted(ENGINE.specs)


def resolve_spec(product_id: str, override: SpecOverride | None) -> ProductSpec:
    """Product thresholds with the demo sandbox's overrides merged in."""
    try:
        base = ENGINE.specs[product_id]
    except KeyError:
        raise KeyError(product_id)  # surfaced by main as HTTP 422
    if override is None:
        return base
    return ProductSpec(
        product_id=base.product_id,
        storage_min_c=base.storage_min_c,
        storage_max_c=base.storage_max_c,
        allowable_duration_min=(
            override.allowable_duration_min
            if override.allowable_duration_min is not None else base.allowable_duration_min),
        mkt_threshold_c=(override.mkt_threshold_c
                         if override.mkt_threshold_c is not None else base.mkt_threshold_c),
        retestable=override.retestable if override.retestable is not None else base.retestable,
        freeze_sensitive=base.freeze_sensitive,
    )


def _engine_for(spec: ProductSpec) -> RuleEngine:
    """Engine evaluating ``spec`` in place of the product's stock thresholds."""
    return RuleEngine(specs={**ENGINE.specs, spec.product_id: spec})


def _as_event(product_id: str, temp_c: float, duration_min: float, mkt_c: float,
              packaging: str, stage: str, scenario_id: str) -> ExcursionEvent:
    return ExcursionEvent(
        scenario_id=scenario_id,
        product_id=product_id,
        excursion_temp_c=temp_c,
        duration_min=duration_min,  # int for decide/batch, float mid-point for grid
        mkt_c=mkt_c,
        packaging=packaging,
        stage=stage,
    )


def classify_evidence(spec: ProductSpec, event: EventIn) -> dict:
    """Mirror of the demo's evidence chips — level per input, keyed by row.

    ``freeze`` appears only for freeze-sensitive products, exactly as in the UI.
    """
    lvl: dict = {}
    ev = event.model_dump()
    temp_c = ev["excursion_temp_c"]
    A, T = spec.allowable_duration_min, spec.mkt_threshold_c

    lvl["packaging"] = "breach" if ev["packaging"] == "compromised" else "ok"
    lvl["temp"] = "breach" if temp_c > spec.storage_max_c else "ok"
    if spec.freeze_sensitive:
        lvl["freeze"] = "severe" if temp_c <= 0.0 else "ok"

    if ev["duration_min"] >= 2 * A:
        lvl["duration"] = "severe"
    elif ev["duration_min"] > A:
        lvl["duration"] = "breach"
    elif ev["duration_min"] >= 0.8 * A:
        lvl["duration"] = "near"
    else:
        lvl["duration"] = "ok"

    if ev["mkt_c"] >= T + 3.0:
        lvl["mkt"] = "severe"
    elif ev["mkt_c"] > T:
        lvl["mkt"] = "breach"
    elif ev["mkt_c"] >= T - 0.5:
        lvl["mkt"] = "near"
    else:
        lvl["mkt"] = "ok"
    return lvl


def risk_score(spec: ProductSpec, event: EventIn) -> dict:
    """Deterministic severity score + a machine-readable top-cause code.

    A faithful port of the demo's ``riskInfo`` (same weights, same pins) but
    returning a stable ``cause_code`` the client localises — the client's ZH
    causes are Chinese and must not live in Python.
    """
    ev = event.model_dump()
    temp_c = ev["excursion_temp_c"]
    band = max(1e-6, spec.storage_max_c - spec.storage_min_c)
    frozen = spec.freeze_sensitive and temp_c <= 0.0

    if frozen:
        t_score, t_label = 1.6, "frozen"
    elif temp_c > spec.storage_max_c:
        t_score = min(1.5, (temp_c - spec.storage_max_c) / band)
        t_label = "above max"
    elif temp_c < spec.storage_min_c and spec.freeze_sensitive:
        t_score = min(1.2, (spec.storage_min_c - temp_c) / band)
        t_label = "below min"
    else:
        t_score, t_label = 0.0, "in band"

    d_score = min(1.5, ev["duration_min"] / spec.allowable_duration_min)
    m_score = max(0.0, min(1.5, (ev["mkt_c"] - spec.mkt_threshold_c) / band))
    p_breach = ev["packaging"] == "compromised" and temp_c > spec.storage_max_c

    raw = 0.50 * t_score + 0.28 * d_score + 0.12 * m_score + (0.10 if p_breach else 0.0)
    if frozen:
        raw = max(raw, 0.95)
    if p_breach:
        raw = max(raw, 0.72)

    # priority order mirrors riskInfo's causes[] so top-cause is identical
    if frozen:
        cause_code = "frozen"
    elif p_breach:
        cause_code = "packaging"
    elif temp_c > spec.storage_max_c + band * 0.5:
        cause_code = "overtemp"
    elif (not frozen) and ev["duration_min"] > spec.allowable_duration_min:
        cause_code = "duration"
    elif ev["mkt_c"] > spec.mkt_threshold_c:
        cause_code = "mkt"
    elif (ev["duration_min"] >= 0.8 * spec.allowable_duration_min
          or ev["mkt_c"] >= spec.mkt_threshold_c - 0.5):
        cause_code = "near"
    else:
        cause_code = "inband" if t_label == "in band" else "minor"

    score = max(3, min(99, round(raw * 100)))
    return {"score": score, "cause_code": cause_code}


def _spec_dict(spec: ProductSpec) -> dict:
    return {
        "product_id": spec.product_id,
        "storage_min_c": spec.storage_min_c,
        "storage_max_c": spec.storage_max_c,
        "allowable_duration_min": spec.allowable_duration_min,
        "mkt_threshold_c": spec.mkt_threshold_c,
        "retestable": spec.retestable,
        "freeze_sensitive": spec.freeze_sensitive,
    }


def _audit(kind: str, ev, spec=None, decision=None) -> None:
    """One readable console line per request: what came in and what was decided."""
    fields = [f"{kind} {ev.product_id} {ev.excursion_temp_c:g}°C/{ev.duration_min:g}min "
              f"MKT {ev.mkt_c:g}°C {ev.packaging}/{ev.stage}"]
    if spec is not None:
        fields.append(f"spec A={spec.allowable_duration_min:g}min "
                      f"T={spec.mkt_threshold_c:g}°C retest={spec.retestable}")
    if decision is not None:
        fields.append(f"→ {decision.disposition.value} (rule {decision.rule_no})")
    log.info("[audit] " + " ".join(fields))


def decide_view(event: EventIn, override: SpecOverride | None) -> dict:
    """One event → the full semantic decision the demo panels render."""
    spec = resolve_spec(event.product_id, override)
    decision = _engine_for(spec).evaluate(_as_event(
        event.product_id, event.excursion_temp_c, event.duration_min,
        event.mkt_c, event.packaging, event.stage, scenario_id="api"))
    _audit("decide", event, spec, decision)
    return {
        "disposition": decision.disposition.value,
        "rule_no": decision.rule_no,
        "reason": decision.reason,
        "regulation": decision.regulation,
        "reshipment_required": decision.reshipment_required,
        "rule_path": decision.rule_path,
        "event": event.model_dump(),
        "spec": _spec_dict(spec),
        "evidence": classify_evidence(spec, event),
        "risk": risk_score(spec, event),
    }


def grid_view(req: GridIn) -> dict:
    """Decision matrix in the map's cell order: ``rows[row][col]``."""
    spec = resolve_spec(req.product_id, req.spec_override)
    engine = _engine_for(spec)
    rows = []
    for mkt_c in req.mkts:  # descending — row 0 is the top (highest MKT) row
        row = []
        for dur in req.durations:  # ascending along the x-axis
            decision = engine.evaluate(_as_event(
                req.product_id, req.excursion_temp_c, dur, mkt_c,
                req.packaging, req.stage, scenario_id="grid"))
            row.append(decision.disposition.value)
        rows.append(row)
    log.info("[audit] grid %s %d rows × %d cols (spec A=%gmin T=%g°C)",
             req.product_id, len(req.mkts), len(req.durations),
             spec.allowable_duration_min, spec.mkt_threshold_c)
    return {"rows": rows}


def batch_view(events: list) -> dict:
    """Preset scenarios → trimmed decisions (stock thresholds, no overrides)."""
    decisions = []
    for ev in events:
        decision = ENGINE.evaluate(_as_event(
            ev.product_id, ev.excursion_temp_c, ev.duration_min,
            ev.mkt_c, ev.packaging, ev.stage, scenario_id="batch"))
        decisions.append({
            "disposition": decision.disposition.value,
            "rule_no": decision.rule_no,
            "reshipment_required": decision.reshipment_required,
        })
        _audit("batch", ev, None, decision)
    return {"decisions": decisions}
