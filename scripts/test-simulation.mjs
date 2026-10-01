import assert from "node:assert/strict";
import { simulationRequest, simulationFilename, SIMULATION_SCENARIOS } from "../frontend-vue/src/lib/simulation.js";
const form = { scenario: "routine", operating_date: "2026-10-01", seed: "", order_count: 8,
  product_ids: [], origin_facility_ids: [], quantity_min: "", quantity_max: "", window_min: "", window_max: "", fleet_size: "",
  vehicle_capacity: 100, spare_quantity: 0, urgent_slack_min: 0 };
const payload = simulationRequest(form);
assert.equal(payload.seed, null);
assert.equal(payload.quantity_min, null);
assert.equal(payload.product_ids, null);
assert.equal(payload.spare_quantity, 0);
assert.equal(payload.urgent_slack_min, 0);
const customized = simulationRequest({ ...form, seed: "0", fleet_size: "2", product_ids: ["insulin_2_8"], origin_facility_ids: ["D-BUGIS"] });
assert.equal(customized.seed, 0);
assert.equal(customized.fleet_size, 2);
assert.deepEqual(customized.product_ids, ["insulin_2_8"]);
assert.equal(simulationFilename({ metadata: { batch_id: "SIM-123" } }), "SIM-123.json");
assert.equal(simulationFilename({}), "legacy-simulated-batch.json");
assert.equal(SIMULATION_SCENARIOS.length, 5);
console.log("Simulation form normalization, zero values and snapshot filenames passed.");
