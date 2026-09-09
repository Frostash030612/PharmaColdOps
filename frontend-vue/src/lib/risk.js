/* Risk index — faithful port of the demo's riskInfo() (deterministic severity
   score derived from the SAME thresholds as the rules). Returns a machine
   cause *code* so the client localises wording (mirrors src/api/service.py
   risk_score → cause_code). Pure. */
import { clamp } from "./format.js";

export function riskInfo(event, s) {
  const band = Math.max(1e-6, s.max - s.min);
  const frozen = s.freezeSensitive && event.excursion_temp_c <= 0;

  /* internal band label as a code — never locale text */
  let tScore = 0, tCode = "inband";
  if (frozen) { tScore = 1.6; tCode = "frozen"; }
  else if (event.excursion_temp_c > s.max) { tScore = Math.min(1.5, (event.excursion_temp_c - s.max) / band); tCode = "abovemax"; }
  else if (event.excursion_temp_c < s.min && s.freezeSensitive) { tScore = Math.min(1.2, (s.min - event.excursion_temp_c) / band); tCode = "belowmin"; }
  // non-freeze-sensitive products (frozen / ultracold) tolerate below-band cold — not scored

  const dScore = Math.min(1.5, event.duration_min / s.allowable);   // same duration criterion as rules 3–5
  const mScore = Math.max(0, Math.min(1.5, (event.mkt_c - s.mktThreshold) / band));
  const pBreach = event.packaging === "compromised" && event.excursion_temp_c > s.max;

  let raw = 0.50 * tScore + 0.28 * dScore + 0.12 * mScore + (pBreach ? 0.10 : 0);
  if (frozen) raw = Math.max(raw, 0.95);     // freeze = rule 1, top severity
  if (pBreach) raw = Math.max(raw, 0.72);    // packaging breach = rule 2

  /* cause priority order mirrors the demo's causes[] so top-cause is identical */
  const causes = [];
  if (frozen) causes.push("frozen");
  if (pBreach) causes.push("packaging");
  if (event.excursion_temp_c > s.max + band * 0.5) causes.push("overtemp");
  if (!frozen && event.duration_min > s.allowable) causes.push("duration");
  if (event.mkt_c > s.mktThreshold) causes.push("mkt");
  if (causes.length === 0 && (event.duration_min >= 0.8 * s.allowable || event.mkt_c >= s.mktThreshold - 0.5))
    causes.push("near");
  if (causes.length === 0) causes.push(tCode === "inband" ? "inband" : "minor");

  return { risk: clamp(Math.round(raw * 100), 3, 99), topCauseCode: causes[0], causeCodes: causes };
}

/* Localised label of a cause code. */
export function causeLabel(code, L) {
  return L.causeText[code] || code;
}
