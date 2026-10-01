import assert from "node:assert/strict";
import { incidentStatus, filterIncidents, summarizeZones, previewMap } from "../frontend-vue/src/lib/incidentWorkflow.js";
import { eventPayload } from "../frontend-vue/src/lib/api.js";

const first = { run_id: "R1", created_at: "2026-10-01T09:00:00", reshipment_required: true,
  processing_status: "pending", event: { dispatch_id: "DAY1", order_id: "O1", destination_facility_id: "H1", facility_id: "D1" } };
const second = { run_id: "R2", created_at: "2026-10-02T10:00:00", processing_status: "closed", event: { destination_facility_id: "H2" } };
const run = { dispatch_id: "DAY1", orders: { "RO-R1": { order_id: "RO-R1", status: "planned" } } };
assert.equal(incidentStatus(first, run), "processing");
run.orders["RO-R1"].status = "delivered";
assert.equal(incidentStatus(first, run), "handled");
assert.equal(incidentStatus(first, { ...run, dispatch_id: "DAY2" }), "pending");
assert.equal(incidentStatus({ ...first, processing_status: "closed" }, run), "closed");
run.orders["RO-R1"].status = "failed";
assert.equal(incidentStatus(first, run), "pending");
run.orders.replacement = { order_id: "replacement", replaces_order_id: "RO-R1", status: "delivered" };
assert.equal(incidentStatus(first, run), "handled");
assert.deepEqual(filterIncidents([first, second], { hospital: "H1", status: "handled" }, run), [first]);
assert.deepEqual(filterIncidents([first, second], { date: "2026-10-02" }), [second]);
assert.deepEqual(filterIncidents([first, second], { sort: "oldest" }), [first, second]);
assert.deepEqual(filterIncidents([first, second]), [second, first]);
assert.deepEqual(summarizeZones([
  { total_distance: 10, served_facilities: 2, target_facilities: 2, routes: [{}, {}] },
  { total_distance: 20, served_facilities: 1, target_facilities: 3, routes: [{}] },
]), { distance: 30, vehicles: 3, served: 3, target: 5 });
assert.deepEqual(summarizeZones([]), { distance: 0, vehicles: 0, served: 0, target: 0 });
const multiMap = previewMap([
  { routes: [{ vehicle_id: "V1" }], geojson: { features: [{ id: "V1" }] } },
  { routes: [{ vehicle_id: "V2" }], geojson: { features: [{ id: "V2" }] } },
]);
assert.deepEqual(multiMap.routes, [{ vehicle_id: "V1" }, { vehicle_id: "V2" }]);
assert.deepEqual(multiMap.geojson, { type: "FeatureCollection", features: [{ id: "V1" }, { id: "V2" }] });
assert.equal(multiMap.metrics.vehicles_used, 2);
assert.deepEqual(eventPayload({ ...first.event, product_id: "vaccine_2_8" }).order_id, "O1");
assert.equal(eventPayload(first.event).facility_id, "D1");
assert.equal(eventPayload(first.event).dispatch_id, "DAY1");
console.log("Incident payload, lifecycle, filters, sorting and multi-zone totals passed.");
