export function minuteOfDay(value, optional = false) {
  if (optional && !value) return null;
  const match = /^(\d{2}):(\d{2})$/.exec(value || "");
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) throw new Error("Invalid same-day delivery time");
  return Number(match[1]) * 60 + Number(match[2]);
}

export function urgentPayload(form) {
  return { request_id: form.request_id, product_id: form.product_id,
    origin_facility_id: form.origin_facility_id, destination_facility_id: form.destination_facility_id,
    earliest_min: minuteOfDay(form.earliest_time, true), latest_min: minuteOfDay(form.latest_time), policy: form.policy };
}

export function warehouseOptions(nodes) {
  return nodes.filter((node) => ["depot", "distribution", "third_party"].includes(node.role));
}
