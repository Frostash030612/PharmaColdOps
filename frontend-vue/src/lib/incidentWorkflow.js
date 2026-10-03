// Quality disposition and operational progress are deliberately independent.
export const STATUS_COLORS = {
  pending: "#dc2626", processing: "#d97706", handled: "#16a34a", closed: "#64748b",
};

export function incidentStatus(record, run = null) {
  if (record.review_status === 'pending') return 'pending';
  const saved = record.processing_status || (record.reshipment_required ? "pending" : "handled");
  if (saved === "closed" || !(record.effective_reshipment_required ?? record.reshipment_required)) return saved;
  const dispatchId = record.event?.dispatch_id || record.handling_dispatch_id;
  if (!run || (dispatchId && dispatchId !== run.dispatch_id)) return saved;
  let order = run.orders?.[`RO-${record.run_id}`];
  const seen = new Set();
  while (order?.status === "failed" && !seen.has(order.order_id)) {
    seen.add(order.order_id);
    const next = Object.values(run.orders || {}).find((o) => o.replaces_order_id === order.order_id);
    if (!next) break;
    order = next;
  }
  if (!order) return saved;
  return order.status === "delivered" ? "handled"
    : ["failed", "scrapped"].includes(order.status) ? "pending" : "processing";
}

export function filterIncidents(records, { date = "", hospital = "", status = "", sort = "newest" } = {}, run = null) {
  return records.filter((record) => (!date || String(record.created_at || "").slice(0, 10) === date)
    && (!hospital || (record.effective_destination_facility_id || record.event?.destination_facility_id) === hospital)
    && (!status || incidentStatus(record, run) === status))
    .toSorted((a, b) => sort === "oldest"
      ? String(a.created_at).localeCompare(String(b.created_at))
      : String(b.created_at).localeCompare(String(a.created_at)));
}

export function summarizeZones(zones = []) {
  return zones.reduce((totals, zone) => ({
    distance: totals.distance + Number(zone.total_distance || 0),
    vehicles: totals.vehicles + (zone.routes?.length || 0),
    served: totals.served + Number(zone.served_facilities || 0),
    target: totals.target + Number(zone.target_facilities || 0),
  }), { distance: 0, vehicles: 0, served: 0, target: 0 });
}

export function previewMap(zones = []) {
  const totals = summarizeZones(zones);
  return {
    routes: zones.flatMap((zone) => zone.routes || []),
    geojson: { type: "FeatureCollection", features: zones.flatMap((zone) => zone.geojson?.features || []) },
    metrics: { total_distance: totals.distance, vehicles_used: totals.vehicles,
      served_customers: totals.served, target_customers: totals.target,
      time_window_violations: 0, capacity_violations: 0, depot_return_violations: 0,
      vehicle_limit_violations: 0 },
  };
}
