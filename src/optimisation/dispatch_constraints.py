"""The operational hard constraints for all grouped emergency schedules."""
from .dispatch_planner import DISPATCH_ORIGIN
from .dispatch_state import PlannedStop
from .execution import checkpoint, execution_view
from .singapore_loader import read_network
from .tracking import LOADING_MIN, vehicle_track
from .parking_policy import validate_terminals, validate_end_node


def price_work(state, context, *, vehicle_id, order_ids, current_time_min,
               orders=None, pickup_facility_id=None, loading_min=0,
               starts_new_vehicle=False, removed_order_id=None):
    network = read_network()
    by_facility = {n["facility_id"]: n for n in network["nodes"]}
    by_node = {n["node_id"]: n for n in network["nodes"]}
    inputs = context.get("input", {})
    catalogue = {oid: vars(o) for oid, o in state.orders.items()}
    for order in inputs.get("orders", ()):
        catalogue[order["order_id"]] = {**catalogue.get(order["order_id"], {}), **order}
    catalogue.update(orders or {})
    fleet = next((v for v in inputs.get("vehicles", ()) if v["vehicle_id"] == vehicle_id), None)
    if fleet is None:
        raise ValueError(f"unknown vehicle {vehicle_id!r}")
    vehicle = state.vehicles.get(vehicle_id)
    if starts_new_vehicle:
        anchor = {"facility_id": fleet.get("start_facility_id") or DISPATCH_ORIGIN,
                  "time_min": max(current_time_min, fleet.get("available_from_min", 0)),
                  "distance_m": 0, "history": (), "approach_from": None, "approach_depart": None}
    else:
        anchor = checkpoint(vehicle, state, context, current_time_min, network=network)
    start = by_facility[anchor["facility_id"]]
    started = anchor["time_min"] + loading_min
    pending = []
    if vehicle and not starts_new_vehicle:
        old_view = execution_view(vehicle, state, context, network=network, now=current_time_min)
        for index, stop in enumerate(old_view["stops"]):
            if stop["kind"] != "pickup":
                continue
            track = old_view["track"]
            if track and track.get("service_starts"):
                arrived = track["service_starts"][index]
                dwell = stop["service_min"] - max(0, current_time_min - arrived)
                if current_time_min >= arrived and dwell <= 0:
                    continue
            else:
                dwell = stop["service_min"]
            pending.append(PlannedStop("pickup", "", stop["facility_id"], max(0, dwell)))
    stops = list(pending)
    if pickup_facility_id is not None:
        matching = next((i for i, stop in enumerate(stops) if stop.facility_id == pickup_facility_id), None)
        if matching is None:
            stops.append(PlannedStop("pickup", "", pickup_facility_id, LOADING_MIN))
        else:
            stops[matching] = PlannedStop("pickup", "", pickup_facility_id, max(LOADING_MIN, stops[matching].service_min))
    stops.extend(PlannedStop("delivery", oid) for oid in order_ids)
    sequence, earliest, dwell, windows = [], [], [], []
    for stop in stops:
        order = catalogue.get(stop.order_id, {})
        facility = stop.facility_id if stop.is_pickup else order["destination_facility_id"]
        node = by_facility[facility]
        sequence.append(node["node_id"])
        earliest.append(max(node["earliest_min"], order.get("earliest_min", node["earliest_min"])))
        windows.append(min(node["latest_min"], order.get("latest_min", node["latest_min"])))
        dwell.append(stop.service_min)
    limits = inputs.get("constraints", {})
    terminals = limits.get("terminal_facility_ids") or ()
    validate_terminals(network, terminals)
    if terminals:
        unknown = set(terminals) - set(by_facility)
        if unknown:
            raise ValueError(f"unknown terminal facilities: {sorted(unknown)}")
        last = sequence[-1] if sequence else start["node_id"]
        ends = sorted((by_facility[fid]["node_id"] for fid in terminals),
                      key=lambda end: (network["matrix"]["distance_m"][last][end], end))
    else:
        ends = [vehicle.end_node_id if vehicle and vehicle.end_node_id is not None else
                by_facility[(vehicle.start_facility_id if vehicle else None) or fleet.get("start_facility_id") or DISPATCH_ORIGIN]["node_id"]]
    tracks = [(end, vehicle_track(network, sequence, started, started,
                start_node=start["node_id"], end_node=end, earliest_mins=earliest, service_mins=dwell))
              for end in ends]
    for end in ends:
        validate_end_node(network, end)
    viable = [(end, track) for end, track in tracks if
              max(track["finished_at_min"], by_node[end]["earliest_min"]) <= by_node[end]["latest_min"]]
    end, track = (viable or tracks)[0]
    blocked = []
    fleet_limit = limits.get("max_vehicles")
    if starts_new_vehicle and fleet_limit and len(state.vehicles) + 1 > fleet_limit:
        blocked.append({"code": "fleet_limit_exceeded", "detail": {"limit": fleet_limit}})
    nominal = set(context.get("nominal_order_ids", ()))
    rated_load = sum(catalogue[oid]["quantity"] for oid in order_ids if oid not in nominal)
    if rated_load > fleet["capacity"]:
        blocked.append({"code": "capacity_exceeded", "detail": {"needed_units": rated_load, "capacity_units": fleet["capacity"]}})
    for oid in order_ids:
        if catalogue[oid].get("temperature_zone", fleet["temperature_zone"]) != fleet["temperature_zone"]:
            blocked.append({"code": "temperature_zone_mismatch", "detail": {"order_id": oid}})
    arrivals = {stop.order_id: track["arrivals"][i] for i, stop in enumerate(stops) if not stop.is_pickup}
    # Preserve existing late orders; report their misses but never turn a
    # punctual existing consignment late just to accept an emergency.
    baseline = {}
    if vehicle:
        remaining = tuple(oid for oid in vehicle.remaining_order_ids if oid != removed_order_id)
        facilities = [by_facility[stop.facility_id]["node_id"] for stop in pending] + [
            by_facility[catalogue[oid]["destination_facility_id"]]["node_id"] for oid in remaining]
        old_track = vehicle_track(network, facilities, anchor["time_min"], anchor["time_min"],
                                 start_node=start["node_id"], end_node=end,
                                 earliest_mins=[by_facility[stop.facility_id]["earliest_min"] for stop in pending] + [catalogue[oid]["earliest_min"] for oid in remaining],
                                 service_mins=[stop.service_min for stop in pending] + [0] * len(remaining))
        baseline = dict(zip(remaining, old_track["service_starts"][len(pending):]))
    affected = []
    for i, stop in enumerate(stops):
        eta = track["arrivals"][i]
        if stop.is_pickup and eta > windows[i]:
            blocked.append({"code": "pickup_window_infeasible", "detail": {"facility_id": stop.facility_id}})
        elif not stop.is_pickup:
            previous = baseline.get(stop.order_id)
            late = eta > windows[i] + 1e-9
            if late and (previous is None or previous <= windows[i]):
                blocked.append({"code": "time_window_infeasible", "detail": {
                    "order_id": stop.order_id, "earliest_arrival_min": eta,
                    "latest_min": windows[i], "late_by_min": eta - windows[i]}})
            if previous is not None:
                affected.append({"order_id": stop.order_id, "baseline_eta_min": previous,
                                 "new_eta_min": eta, "delay_min": eta - previous,
                                 "already_late": previous > windows[i],
                                 "newly_late": previous <= windows[i] and late})
    projected = anchor["distance_m"] + track["total_distance_m"]
    cap = limits.get("mileage_limit_m")
    if cap is not None and projected > cap + 1e-6:
        blocked.append({"code": "mileage_limit_exceeded", "detail": {
            "needed_distance_m": projected, "limit_m": cap}})
    served = list(vehicle.delivered_order_ids) if vehicle else []
    destinations = [catalogue[oid]["destination_facility_id"] for oid in (*served, *order_ids)]
    visits = sum(index == 0 or destination != destinations[index - 1] for index, destination in enumerate(destinations))
    if limits.get("max_stops_per_vehicle") and visits > limits["max_stops_per_vehicle"]:
        blocked.append({"code": "stop_limit_exceeded", "detail": {"max_stops_per_vehicle": limits["max_stops_per_vehicle"]}})
    if not viable:
        blocked.append({"code": "closing_window_exceeded", "detail": {"closing_min": by_node[end]["latest_min"]}})
    return {"schedule_start_min": started, "ready_from_min": anchor["time_min"],
            "schedule_start_facility_id": anchor["facility_id"],
            "schedule_stops": [vars(stop) for stop in stops], "end_node_id": end,
            "distance_before_schedule_m": anchor["distance_m"],
            "historical_legs": list(anchor["history"]),
            "approach_from_facility_id": anchor["approach_from"],
            "approach_depart_min": anchor["approach_depart"],
            "distance_m": track["total_distance_m"], "projected_daily_distance_m": projected,
            "arrivals": arrivals, "node_sequence": [start["node_id"], *sequence, end],
            "affected_orders": affected, "affected_order_ids": [o["order_id"] for o in affected],
            "on_time": not blocked, "feasible": not blocked, "blocked_by": blocked}
