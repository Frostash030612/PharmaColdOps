/* Backend-mode plumbing — the request bodies / key strings are ported
   byte-for-byte from the demo so the on-the-wire contract is unchanged.
   localFromServer normalises a raw FastAPI response into the shape the panels
   render (semantic codes from the server, wording from the L bundle). Pure. */
import { pathLine } from "./engine.js";

export function decisionKey(current, spec) {
  return [current.product_id, current.excursion_temp_c, current.duration_min,
          current.mkt_c, current.packaging, current.stage,
          spec.allowable, spec.mktThreshold, spec.retestable].join("|");
}

export function specKey(current, spec) {
  return [current.product_id, spec.allowable, spec.mktThreshold, spec.retestable].join("|");
}

export function eventPayload(current) {
  return {
    product_id: current.product_id,
    excursion_temp_c: current.excursion_temp_c,
    duration_min: current.duration_min,
    mkt_c: current.mkt_c,
    packaging: current.packaging,
    stage: current.stage,
    destination_facility_id: current.destination_facility_id || null,
  };
}

export function overridePayload(spec) {
  return {
    allowable_duration_min: spec.allowable,
    mkt_threshold_c: spec.mktThreshold,
    retestable: spec.retestable,
  };
}

export function postJson(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
}

export function checkHealth(base) {
  return fetch(base + "/api/health")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))));
}

/* Backend run archive: newest-first list of every completed /api/decide
   (GET /api/runs, backed by the append-only data/audit/runs.jsonl). */
export function fetchRuns(base, limit = 200) {
  return fetch(base + "/api/runs?limit=" + limit)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))));
}

/* Normalise a backend decision into the render shape: disposition/ruleNo from
   the server, wording from the local tables (mirrors the demo's
   localFromServer). */
export function normalize(srv, L) {
  const t = L.ruleText[srv.rule_no] || { reason: srv.reason, regulation: srv.regulation };
  const sp = srv.spec, ev = srv.event;
  const e = { product_id: ev.product_id, excursion_temp_c: ev.excursion_temp_c,
              duration_min: ev.duration_min, mkt_c: ev.mkt_c,
              packaging: ev.packaging, stage: ev.stage };
  const s = { min: sp.storage_min_c, max: sp.storage_max_c, allowable: sp.allowable_duration_min,
              mktThreshold: sp.mkt_threshold_c, retestable: sp.retestable,
              freezeSensitive: sp.freeze_sensitive };
  return {
    disposition: srv.disposition,
    reshipment: srv.reshipment_required,
    ruleNo: srv.rule_no,
    reason: t.reason,
    regulation: t.regulation,
    rulePath: pathLine(e, s, srv.disposition, t.reason, L),
    risk: srv.risk.score,
    topCause: L.causeText[srv.risk.cause_code] || srv.risk.cause_code,
  };
}
