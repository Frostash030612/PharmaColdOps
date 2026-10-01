import assert from "node:assert/strict";
import { minuteOfDay, urgentPayload, warehouseOptions } from "../frontend-vue/src/lib/urgent.js";
assert.equal(minuteOfDay("09:30"), 570);
assert.equal(minuteOfDay("", true), null);
assert.throws(() => minuteOfDay("24:00"));
assert.throws(() => minuteOfDay("09:99"));
const body = urgentPayload({request_id:"u-1", product_id:"vaccine_2_8", origin_facility_id:"W-WESTGATE",
  destination_facility_id:"H-SGH", earliest_time:"", latest_time:"17:00", policy:"minimize_disruption"});
assert.equal(body.latest_min, 1020);
assert.equal(body.earliest_min, null);
assert.equal("quantity" in body, false);
assert.equal("inventory" in body, false);
const nodes = [{role:"depot",facility_id:"W"},{role:"distribution",facility_id:"D"},
  {role:"third_party",facility_id:"T"},{role:"customer",facility_id:"H"}];
assert.deepEqual(warehouseOptions(nodes).map(n=>n.facility_id), ["W","D","T"]);
console.log("Urgent time/payload and warehouse-only parking options passed.");
