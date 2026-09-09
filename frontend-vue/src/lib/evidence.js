/* Evidence panel — evLevel mirrors frontend/index.html + src/api/service.py
   classify_evidence verbatim; buildEvidenceRows produces the row data. Pure:
   values/limits/labels from (spec, current, L). */
import { fmt, interp } from "./format.js";

/* Semantic level (ok/near/breach/severe) for one evidence row. */
export function evLevel(s, c, key) {
  const A = s.allowable, T = s.mktThreshold;
  if (key === "packaging") return c.packaging === "compromised" ? "breach" : "ok";
  if (key === "temp") return c.excursion_temp_c > s.max ? "breach" : "ok";
  if (key === "freeze") return c.excursion_temp_c <= 0 ? "severe" : "ok";
  if (key === "duration") {
    if (c.duration_min >= 2 * A) return "severe";
    if (c.duration_min > A) return "breach";
    if (c.duration_min >= 0.8 * A) return "near";
    return "ok";
  }
  if (key === "mkt") {
    if (c.mkt_c >= T + 3) return "severe";
    if (c.mkt_c > T) return "breach";
    if (c.mkt_c >= T - 0.5) return "near";
    return "ok";
  }
  return "ok";
}

/* Rows + decision footer lines. `srv` is the raw fresh server decision (or
   null): its evidence levels win while current, else local evLevel (identical
   rules). `d` is the rendered decision (server-normalised or local). */
export function buildEvidence(s, c, srv, d, L) {
  const A = s.allowable, T = s.mktThreshold;
  const lvl = (key) => ((srv && srv.evidence && srv.evidence[key]) || evLevel(s, c, key));

  const rows = [];

  rows.push({
    key: "packaging",
    k: L.evidence.labels.packaging,
    v: L.evidence.packagingVal[c.packaging] || c.packaging,
    limit: "",
    level: lvl("packaging"),
    label: L.evLbl.packaging[lvl("packaging")],
  });
  rows.push({
    key: "temp",
    k: L.evidence.labels.temp,
    v: fmt(c.excursion_temp_c) + " °C",
    limit: interp(L.evidence.limitTemp, { v: fmt(s.max) }),
    level: lvl("temp"),
    label: L.evLbl.temp[lvl("temp")],
  });
  if (s.freezeSensitive) {
    rows.push({
      key: "freeze",
      k: L.evidence.labels.freeze,
      v: fmt(c.excursion_temp_c) + " °C",
      limit: L.evidence.limitFreeze,
      level: lvl("freeze"),
      label: L.evLbl.freeze[lvl("freeze")],
    });
  }
  rows.push({
    key: "duration",
    k: L.evidence.labels.duration,
    v: c.duration_min + " " + L.evidence.durUnit,
    limit: interp(L.evidence.limitDur, { v: A }),
    level: lvl("duration"),
    label: L.evLbl.duration[lvl("duration")],
  });
  rows.push({
    key: "mkt",
    k: L.evidence.labels.mkt,
    v: fmt(c.mkt_c) + " °C",
    limit: interp(L.evidence.limitMkt, { v: fmt(T) }),
    level: lvl("mkt"),
    label: L.evLbl.mkt[lvl("mkt")],
  });

  return {
    rows,
    summary: interp(L.evidence.summary, { no: d.ruleNo, reason: d.reason }),
    reg: interp(L.evidence.reg, { reg: d.regulation }),
  };
}
