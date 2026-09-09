/* Temperature timeline — faithful port of the demo's renderTimeline() SVG
   string builder. Pure: geometry is locale-independent except the axis/badge
   words and badge geometry, which come from L.timeline. Returns the ready SVG
   innerHTML plus the scrub/readout values the component binds. */
import { fmt, clamp, interp } from "./format.js";

export function genProfile(event, spec) {
  const base = spec.min + (spec.max - spec.min) * 0.4;
  const peak = event.excursion_temp_c;
  const dur = event.duration_min;
  const ramp = Math.max(6, Math.round(dur * 0.35));
  const total = Math.max(60, dur + ramp * 2 + 20);
  const n = 220;
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = total * i / n;
    let temp;
    if (t < ramp) temp = base + (peak - base) * (t / ramp);
    else if (t < ramp + dur) temp = peak;
    else if (t < ramp + dur + ramp) temp = peak + (base - peak) * ((t - ramp - dur) / ramp);
    else temp = base;
    const noise = Math.sin(t * 0.9 + 1.3) * 0.3 + Math.sin(t * 0.33 + 0.5) * 0.25;
    pts.push({ t, temp: temp + noise });
  }
  return { pts, total, base, peak };
}

export function buildCurvePaths(pts, spec) {
  const segs = [];
  let cur = [], curIn = null;
  for (const p of pts) {
    const inBand = p.temp >= spec.min && p.temp <= spec.max;
    if (curIn === null) curIn = inBand;
    if (inBand !== curIn) { segs.push({ inBand: curIn, pts: cur }); cur = []; curIn = inBand; }
    cur.push(p);
  }
  segs.push({ inBand: curIn, pts: cur });
  return segs;
}

export function timelineSvg(current, spec, nowTime, L) {
  const prof = genProfile(current, spec);
  const t = clamp(nowTime, 0, prof.total);
  const W = 640, H = 190, padL = 46, padR = 14, padT = 24, padB = 30;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const yMin = Math.min(spec.min, prof.base, prof.peak) - 2;
  const yMax = Math.max(spec.max, prof.base, prof.peak) + 2;
  const X = (tt) => padL + (tt / prof.total) * plotW;
  const Y = (v) => padT + (yMax - v) / (yMax - yMin) * plotH;

  // safe band
  let s = `<rect x="${padL}" y="${Y(spec.max).toFixed(1)}" width="${plotW}" height="${(Y(spec.min) - Y(spec.max)).toFixed(1)}" fill="#16a34a" fill-opacity="0.07"/>`;
  s += `<line x1="${padL}" y1="${Y(spec.min).toFixed(1)}" x2="${padL + plotW}" y2="${Y(spec.min).toFixed(1)}" stroke="#16a34a" stroke-width="1" stroke-dasharray="3 3" opacity="0.5"/>`;
  s += `<line x1="${padL}" y1="${Y(spec.max).toFixed(1)}" x2="${padL + plotW}" y2="${Y(spec.max).toFixed(1)}" stroke="#16a34a" stroke-width="1" stroke-dasharray="3 3" opacity="0.5"/>`;

  // curve coloured by in/out of band
  const segs = buildCurvePaths(prof.pts, spec);
  let curves = "";
  for (const seg of segs) {
    const color = seg.inBand ? "#16a34a" : "#dc2626";
    const dpath = seg.pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.temp).toFixed(1)}`).join("");
    curves += `<path d="${dpath}" fill="none" stroke="${color}" stroke-width="2.3"/>`;
  }

  // elapsed shading + now cursor
  const nx = X(t).toFixed(1);
  let cursor = `<rect x="${padL}" y="${padT}" width="${(nx - padL).toFixed(1)}" height="${plotH}" fill="#0f2a4a" fill-opacity="0.03"/>`;
  cursor += `<line x1="${nx}" y1="${padT}" x2="${nx}" y2="${padT + plotH}" stroke="#0f2a4a" stroke-width="1.6"/>`;

  const idx = Math.round(t / prof.total * (prof.pts.length - 1));
  const nowTemp = prof.pts[idx].temp;
  const anomaly = nowTemp > spec.max || nowTemp < spec.min;
  cursor += `<circle cx="${nx}" cy="${Y(nowTemp).toFixed(1)}" r="5" fill="${anomaly ? "#dc2626" : "#0f2a4a"}"/>`;

  let badge = "";
  if (anomaly) {
    const g = L.timeline.badge;
    badge = `<g><rect x="${W - g.xOffset}" y="4" width="${g.w}" height="20" rx="10" fill="#dc2626"/><text x="${W - g.textOffset}" y="18" text-anchor="middle" fill="#fff" font-size="11" font-weight="700" font-family="inherit">${L.timeline.excursion}</text></g>`;
  }

  let labels = `<text x="${padL}" y="${(Y(spec.max) - 4).toFixed(1)}" font-size="10" fill="#16a34a" font-family="inherit">${interp(L.timeline.maxLabel, { v: fmt(spec.max, 0) })}</text>`;
  labels += `<text x="${padL}" y="${(Y(spec.min) + 11).toFixed(1)}" font-size="10" fill="#16a34a" font-family="inherit">${interp(L.timeline.minLabel, { v: fmt(spec.min, 0) })}</text>`;
  labels += `<text x="${padL + plotW / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="#64748b" font-family="inherit">${L.timeline.axis}</text>`;

  const svg = `<svg class="zone-svg" viewBox="0 0 ${W} ${H}">${s}${curves}${cursor}${badge}${labels}</svg>`;

  return {
    svg,
    readout: interp(L.timeline.readout, { now: nowTime.toFixed(0), total: prof.total.toFixed(0) }),
    scrubPct: (t / prof.total * 100).toFixed(0),
    total: prof.total,
    profile: prof,
  };
}
