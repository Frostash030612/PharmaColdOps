/* Geometry + timeline helpers for the branch-option comparison popup.

   Two questions the operator asks when choosing between reshipment options:
     "where does the truck actually drive?"      -> the map + node sequence
     "who else gets delayed, and by how much?"   -> the timeline
   Both are derived here from one branch payload so the popup and any other view
   cannot drift apart. Pure functions: no Vue, no Leaflet. */

/* One option's drawable overlays: the vehicle's route before the change as a
   dashed grey line, this option's route in the option's own colour. */
export function candidateOverlays(payload, candidate) {
  if (!candidate) return [];
  const baseline = payload?.baselines?.[candidate.vehicle_id];
  const lines = [];
  if (baseline?.route_geojson) {
    lines.push({ id: "before", geojson: baseline.route_geojson, color: "#94a3b8",
                 dashed: true, weight: 3, labelKey: "beforeRoute" });
  }
  if (candidate.route_geojson) {
    lines.push({ id: "after", geojson: candidate.route_geojson, color: "#dc2626",
                 weight: 5, labelKey: "afterRoute" });
  }
  return lines;
}

/* The stops this option touches: the case's own hospital plus the first stop it
   inserts, so the map can ring them. */
export function candidateNodeIds(payload, candidate, nodeIdByFacility) {
  const touched = new Set();
  const destination = payload?.order?.destination_facility_id;
  if (destination && nodeIdByFacility) {
    const id = nodeIdByFacility[destination];
    if (id != null) touched.add(id);
  }
  if (candidate?.node_sequence?.length > 1) touched.add(candidate.node_sequence[1]);
  return [...touched];
}

/* How this option compares with the option the backend ranked first. Negative
   means "better than the recommendation" (cheaper / earlier). */
export function candidateDeltas(candidate, best) {
  if (!candidate || !best) return null;
  const affected = (candidate.affected_orders || []).length;
  const worstDelay = Math.max(0, ...(candidate.affected_orders || []).map((a) => a.delay_min || 0));
  return {
    addedDistanceM: (candidate.added_distance_m || 0) - (best.added_distance_m || 0),
    etaMin: (candidate.eta_min || 0) - (best.eta_min || 0),
    affected: affected - (best.affected_orders || []).length,
    /* The number that actually decides it: how late the worst-hit order lands. */
    worstDelayMin: worstDelay - Math.max(0, ...(best.affected_orders || []).map((a) => a.delay_min || 0)),
  };
}

const clock = (min) => {
  if (min == null || Number.isNaN(min)) return "—";
  const m = Math.round(min);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

/* A small time chart for one option: every order this option delays gets a grey
   bar (its ETA before the change) and a coloured bar (its ETA after). Orders
   that are pushed into lateness turn red, so "which option is best" is answered
   by the picture rather than by reading numbers. */
export function buildTimeline(payload, candidate, width = 560, rowHeight = 26, padLeft = 74) {
  const orders = candidate?.affected_orders || [];
  const eta = candidate?.eta_min;
  const plotW = width - padLeft - 24;
  const rows = Math.max(orders.length, 1);
  const height = rows * rowHeight + 34;

  const values = [];
  orders.forEach((o) => { values.push(o.baseline_eta_min, o.new_eta_min); });
  if (eta != null) values.push(eta);
  values.push(payload?.current_time_min ?? 540);
  const lo = Math.min(...values.filter((v) => v != null));
  const hi = Math.max(...values.filter((v) => v != null));
  const span = Math.max(hi - lo, 30);          // keep a sane axis for one order
  const x = (min) => padLeft + ((min - lo) / span) * plotW;

  const ticks = [];
  const step = span > 240 ? 120 : span > 120 ? 60 : 30;
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
    ticks.push({ min: t, x: x(t), label: clock(t) });
  }

  const bars = orders.map((o, i) => {
    const y = 16 + i * rowHeight;
    const from = x(o.baseline_eta_min);
    const to = x(o.new_eta_min);
    return {
      orderId: o.order_id,
      label: String(o.order_id).replace(/^DO-DAILY-|^RO-/, ""),
      y,
      x0: Math.min(from, to),
      x1: Math.max(from, to),
      beforeX: from,
      afterX: to,
      delayMin: o.delay_min || 0,
      newlyLate: !!o.newly_late,
      alreadyLate: !!o.already_late,
      color: o.newly_late ? "#dc2626" : o.delay_min > 0 ? "#d97706" : "#0d9488",
    };
  });

  return {
    width, height, padLeft, plotW, ticks, bars,
    /* Where this option's affected hospital is reached. */
    etaX: eta != null ? x(eta) : null,
    etaLabel: eta != null ? clock(eta) : null,
    nowX: x(payload?.current_time_min ?? 540),
    lo, hi,
  };
}

export const clockLabel = clock;
