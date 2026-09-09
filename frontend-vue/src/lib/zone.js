/* Decision boundary map (duration × MKT) — the spec-driven 26×18 grid. The cell
   axes are computed in ONE place (cellAxes) and shared by the /api/grid POST
   body and the local render, so the 468-cell server response always lines up
   with the local grid. SVG geometry ported verbatim from renderZonePlot. Pure. */
import { fmt, clamp } from "./format.js";
import { DISPO_COLOR, DISPO_ORDER } from "../data/products.js";
import { dispositionOf } from "./engine.js";

/* Column midpoints (durations, ascending) and row midpoints (mkts, descending
   so row 0 is the top / highest-MKT row) — same formulas as service.py's grid. */
export function cellAxes(spec) {
  const A = spec.allowable, T = spec.mktThreshold;
  const xMin = 0, xMax = 2.5 * A, yMin = T - 6, yMax = T + 4;
  const cols = 26, rows = 18;
  const durations = Array.from({ length: cols }, (_, c) => xMin + (c + 0.5) / cols * (xMax - xMin));
  const mkts = Array.from({ length: rows }, (_, r) => yMax - (r + 0.5) / rows * (yMax - yMin));
  return { xMin, xMax, yMin, yMax, cols, rows, durations, mkts };
}

/* `srvGrid` = server rows[row][col] or null (fall back to local evaluation).
   `currentDisp` = disposition code of the live event (dot colour). */
export function zoneSvg(spec, current, srvGrid, currentDisp, L) {
  const A = spec.allowable, T = spec.mktThreshold;
  const { xMin, xMax, yMin, yMax, cols, rows, durations, mkts } = cellAxes(spec);
  const W = 380, H = 250, padL = 46, padR = 14, padT = 14, padB = 32;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const X = (d) => padL + (d - xMin) / (xMax - xMin) * plotW;
  const Y = (m) => padT + (yMax - m) / (yMax - yMin) * plotH;

  const cw = plotW / cols, ch = plotH / rows;
  let rects = "";
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const d = durations[c];
      const m = mkts[r];
      const ev = { product_id: current.product_id, excursion_temp_c: spec.max, duration_min: d, mkt_c: m, packaging: "intact", stage: "transit" };
      const disp = srvGrid ? srvGrid[r][c] : dispositionOf(ev, spec);
      rects += `<rect x="${(padL + c * cw).toFixed(1)}" y="${(padT + r * ch).toFixed(1)}" width="${(cw + 0.6).toFixed(1)}" height="${(ch + 0.6).toFixed(1)}" fill="${DISPO_COLOR[disp]}" fill-opacity="0.14"/>`;
    }
  }

  const vlines = [[0.8 * A, "#cbd5e1"], [A, "#94a3b8"], [2 * A, "#64748b"]];
  const hlines = [[T - 0.5, "#cbd5e1"], [T, "#94a3b8"], [T + 3, "#64748b"]];
  let lines = "";
  vlines.forEach(([x, col]) => { lines += `<line x1="${X(x).toFixed(1)}" y1="${padT}" x2="${X(x).toFixed(1)}" y2="${padT + plotH}" stroke="${col}" stroke-width="1" stroke-dasharray="4 4"/>`; });
  hlines.forEach(([y, col]) => { lines += `<line x1="${padL}" y1="${Y(y).toFixed(1)}" x2="${padL + plotW}" y2="${Y(y).toFixed(1)}" stroke="${col}" stroke-width="1" stroke-dasharray="4 4"/>`; });

  const px = X(clamp(current.duration_min, xMin, xMax)).toFixed(1);
  const py = Y(clamp(current.mkt_c, yMin, yMax)).toFixed(1);
  const point = `<circle cx="${px}" cy="${py}" r="6.5" fill="#fff" stroke="${DISPO_COLOR[currentDisp]}" stroke-width="3"/>`;

  let ticks = `<text x="${padL + plotW / 2}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#64748b" font-family="inherit">${L.zone.xAxis}</text>`;
  ticks += `<text x="12" y="${padT + plotH / 2}" text-anchor="middle" font-size="11" fill="#64748b" font-family="inherit" transform="rotate(-90 12 ${padT + plotH / 2})">${L.zone.yAxis}</text>`;
  ticks += `<text x="${X(0)}" y="${padT + plotH + 16}" text-anchor="middle" font-size="10" fill="#94a3b8" font-family="inherit">0</text>`;
  ticks += `<text x="${X(A)}" y="${padT + plotH + 16}" text-anchor="middle" font-size="10" fill="#64748b" font-family="inherit">${fmt(A, 0)}</text>`;
  ticks += `<text x="${X(2 * A)}" y="${padT + plotH + 16}" text-anchor="middle" font-size="10" fill="#64748b" font-family="inherit">${fmt(2 * A, 0)}</text>`;
  ticks += `<text x="${padL - 6}" y="${Y(yMin) + 3}" text-anchor="end" font-size="10" fill="#94a3b8" font-family="inherit">${fmt(yMin, 0)}</text>`;
  ticks += `<text x="${padL - 6}" y="${Y(T) + 3}" text-anchor="end" font-size="10" fill="#64748b" font-family="inherit">${fmt(T, 0)}</text>`;
  ticks += `<text x="${padL - 6}" y="${Y(yMax) + 3}" text-anchor="end" font-size="10" fill="#64748b" font-family="inherit">${fmt(yMax, 0)}</text>`;

  const svg = `<svg class="zone-svg" viewBox="0 0 ${W} ${H}">${rects}${lines}${point}${ticks}</svg>`;

  const legendItems = DISPO_ORDER.filter((k) => k !== "retest" || spec.retestable);
  const legendHtml = legendItems
    .map((k) => `<span><i style="background:${DISPO_COLOR[k]}"></i>${L.dispo[k].label}</span>`)
    .join("");

  const rule1 = current.packaging === "compromised" && current.excursion_temp_c > spec.max;
  const note = rule1 ? L.zone.noteOverride : L.zone.noteNormal;

  return { svg, legendHtml, note };
}
