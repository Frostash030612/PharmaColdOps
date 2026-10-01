export const SIMULATION_SCENARIOS = ["routine", "urgent", "multi_source", "capacity_shortage", "legacy"];

export function simulationRequest(form) {
  const optional = (value) => value === "" || value == null ? null : Number(value);
  return {
    scenario: form.scenario, operating_date: form.operating_date || null,
    seed: optional(form.seed), order_count: Number(form.order_count),
    product_ids: form.product_ids?.length ? [...form.product_ids] : null,
    origin_facility_ids: form.origin_facility_ids?.length ? [...form.origin_facility_ids] : null,
    quantity_min: optional(form.quantity_min), quantity_max: optional(form.quantity_max),
    window_min: optional(form.window_min), window_max: optional(form.window_max),
    fleet_size: optional(form.fleet_size), vehicle_capacity: Number(form.vehicle_capacity),
    spare_quantity: Number(form.spare_quantity), urgent_slack_min: Number(form.urgent_slack_min),
  };
}

export function simulationFilename(batch) {
  return `${batch.metadata?.batch_id || "legacy-simulated-batch"}.json`;
}
