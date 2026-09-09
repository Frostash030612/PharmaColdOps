/* Rule engine — faithful port of frontend/index.html's evaluate() (which in turn
   ports src/rule_engine/engine.py). Pure: receives the event, the product spec
   and the locale bundle L; returns semantic codes plus L-localised wording.

   Naming of the decision *is* done here (it is the engine's job, exactly as the
   Python engine returns ``decision.disposition.value``); every word comes from
   L so the same module serves EN and ZH. */
import { fmt, interp } from "./format.js";

/* The six rules, priority order. Returns [disposition_code, rule_no]. */
function pickRule(event, s) {
  if (s.freezeSensitive && event.excursion_temp_c <= 0)
    return ["scrap", 1];
  if (event.packaging === "compromised" && event.excursion_temp_c > s.max)
    return ["scrap", 2];
  if (event.duration_min >= 2 * s.allowable || event.mkt_c >= s.mktThreshold + 3.0)
    return ["scrap", 3];
  if (event.duration_min > s.allowable || event.mkt_c > s.mktThreshold)
    return ["quarantine", 4];
  if (s.retestable && (event.duration_min >= 0.8 * s.allowable || event.mkt_c >= s.mktThreshold - 0.5))
    return ["retest", 5];
  return ["release", 6];
}

/* Just the disposition code — used where wording is irrelevant (grid cells,
   preset-list dots), so 468 grid cells never pay for string building. */
export function dispositionOf(event, s) {
  return pickRule(event, s)[0];
}

/* pathLine(event, spec, dispCode, reason, L) — the "auditable rule path" line.
   NB the disposition inside the line is the code ("scrap"), exactly as the
   vanilla pages printed it, so EN/ZH rule paths both read "→ scrap: …". */
export function pathLine(ev, s, disp, reason, L) {
  return interp(L.templates.pathLine, {
    product: ev.product_id,
    min: fmt(s.min),
    max: fmt(s.max),
    temp: fmt(ev.excursion_temp_c),
    dur: ev.duration_min,
    mkt: fmt(ev.mkt_c),
    allow: s.allowable,
    disp,
    reason,
  });
}

/* Full decision object the panels render. */
export function evaluate(event, s, L) {
  const [disp, ruleNo] = pickRule(event, s);
  const t = L.ruleText[ruleNo];
  return {
    disposition: disp,
    reshipment: disp === "scrap" || disp === "quarantine",
    rulePath: pathLine(event, s, disp, t.reason, L),
    ruleNo,
    reason: t.reason,
    regulation: t.regulation,
  };
}
