import { interp } from "./format.js";

const KEYS = {
  mileage_limit_exceeded: "reasonMileage", time_window_infeasible: "reasonTimeWindow",
  capacity_exceeded: "reasonCapacity", closing_window_exceeded: "reasonClosing",
  stop_limit_exceeded: "reasonStops", no_vehicle_available: "reasonNoVehicle",
  placeable_in_isolation: "reasonPlaceable", fleet_limit_exceeded: "reasonFleet",
  pickup_window_infeasible: "reasonPickupWindow", temperature_zone_mismatch: "reasonTemperature",
};

export function dispatchReasonText(reason, text, clock) {
  const d = reason.detail || {};
  const km = (metres) => (Number(metres || 0) / 1000).toFixed(1);
  return interp(text[KEYS[reason.code]] || reason.code, {
    needed: km(d.needed_distance_m), limit: km(d.limit_m),
    earliest: d.earliest_arrival_min == null ? "—" : clock(d.earliest_arrival_min),
    latest: d.latest_min == null ? "—" : clock(d.latest_min),
    late: d.late_by_min == null ? "" : Number(d.late_by_min).toFixed(1),
    units: d.needed_units ?? "", capacity: d.capacity_units ?? "",
    max: d.max_stops_per_vehicle ?? d.limit ?? "",
    closing: d.closing_min == null ? "—" : clock(d.closing_min),
    facility: d.facility_id ?? "", order: d.order_id ?? "",
  });
}
