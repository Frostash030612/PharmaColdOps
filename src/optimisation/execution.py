"""One vehicle schedule shared by previews, the map, ticking and daily mileage."""
from dataclasses import replace

from .dispatch_planner import DISPATCH_ORIGIN
from .dispatch_state import PlannedStop, planned_stops
from .singapore_export import leg_geojson
from .singapore_loader import read_network
from .tracking import LOADING_MIN, schedule_origin, vehicle_track, watched_now


def execution_view(vehicle, state, context, *, network=None, now=None):
    network = network or read_network()
    nodes = {n["facility_id"]: n for n in network["nodes"]}
    orders = {o["order_id"]: o for o in context.get("input", {}).get("orders", ())}
    clock = context.get("clock")
    now = watched_now(clock) if now is None and clock else now
    declared_start = next((v.get("start_facility_id") for v in context.get("input", {}).get("vehicles", ())
                           if v["vehicle_id"] == vehicle.vehicle_id), None)
    start = vehicle.schedule_start_facility_id or vehicle.start_facility_id or declared_start or DISPATCH_ORIGIN
    started = vehicle.schedule_start_min
    stops = vehicle.schedule_stops
    if started is None:
        if vehicle.replan_started_min is not None:
            start = vehicle.replan_start_facility_id or vehicle.current_facility_id
            started = vehicle.replan_started_min
            stops = tuple(PlannedStop("pickup", "", fid, LOADING_MIN)
                          for fid in vehicle.pickup_facility_ids) + tuple(
                              PlannedStop("delivery", oid) for oid in vehicle.replan_order_ids)
        else:
            started = (schedule_origin(clock) + LOADING_MIN if clock else
                       min((o.get("earliest_min", 540) for o in orders.values()), default=540) + LOADING_MIN)
            stops = planned_stops(vehicle)
    elif not stops and (vehicle.remaining_order_ids or vehicle.drive_plan):
        stops = planned_stops(vehicle)
    start_node = nodes[start]["node_id"]
    end_node = vehicle.end_node_id if vehicle.end_node_id is not None else start_node
    sequence, earliest, dwell, details = [], [], [], []
    for stop in stops:
        order = orders.get(stop.order_id, {})
        facility = stop.facility_id if stop.is_pickup else order.get("destination_facility_id")
        if facility not in nodes:
            raise ValueError(f"unknown execution stop {facility!r} for {vehicle.vehicle_id}")
        node = nodes[facility]
        sequence.append(node["node_id"])
        earliest.append(float(node["earliest_min"] if stop.is_pickup else order.get("earliest_min", node["earliest_min"])))
        dwell.append(stop.service_min)
        details.append({"node_id": node["node_id"], "order_id": stop.order_id or None,
                        "kind": stop.kind, "facility_id": facility,
                        "quantity": order.get("quantity", 0) if not stop.is_pickup else 0,
                        "delivered": stop.order_id in vehicle.delivered_order_ids if not stop.is_pickup else False,
                        "earliest_min": earliest[-1],
                        "latest_min": node["latest_min"] if stop.is_pickup else order.get("latest_min", node["latest_min"]),
                        "source_run_id": order.get("source_run_id")})
        details[-1]["service_min"] = stop.service_min
    track = None
    if now is not None and vehicle.status != "failed":
        track = vehicle_track(network, sequence, started, now, end_node=end_node,
                              start_node=start_node, earliest_mins=earliest, service_mins=dwell)
        if vehicle.approach_from_facility_id and now < started:
            approach = vehicle_track(
                network, [start_node], vehicle.approach_depart_min, now,
                start_node=nodes[vehicle.approach_from_facility_id]["node_id"], end_node=start_node)
            track = {**track, **{k: approach[k] for k in (
                "position", "leg_from", "leg_to", "leg_fraction", "leg_depart_min", "leg_arrival_min")},
                "approaching_checkpoint": True}
    elif vehicle.status == "failed" and vehicle.failed_position is not None:
        track = {"position": list(vehicle.failed_position), "leg_from": start_node, "leg_to": start_node,
                 "leg_fraction": 1, "reached_stops": 0, "arrivals": [], "finished": True,
                 "leg_index": 0, "distance_driven_m": 0, "total_distance_m": 0}
    schedule = [start_node, *sequence, end_node]
    legs = []
    for index, (a, b) in enumerate(zip(schedule, schedule[1:])):
        if a == b:
            continue
        detail = details[index] if index < len(details) else {}
        legs.append({**leg_geojson(network, [a, b])[0], "schedule_index": index + 1,
                     "node_id": b, "order_id": detail.get("order_id"),
                     "kind": detail.get("kind"), "delivered": detail.get("delivered", False),
                     "driven": bool(track and not track.get("approaching_checkpoint") and (
                         index < track["leg_index"] or (index == track["leg_index"] and track["leg_fraction"] >= 1)))})
    distance = sum(network["matrix"]["distance_m"][a][b] for a, b in zip(schedule, schedule[1:]))
    driven = vehicle.distance_before_schedule_m + (track or {}).get("distance_driven_m", 0)
    if track and track.get("approaching_checkpoint"):
        a = nodes[vehicle.approach_from_facility_id]["node_id"]
        driven = vehicle.distance_before_schedule_m - network["matrix"]["distance_m"][a][start_node] * (1 - track["leg_fraction"])
    return {"start_facility_id": start, "start_node_id": start_node,
            "started_min": started, "end_node_id": end_node,
            "stops": details, "node_sequence": schedule, "track": track, "legs": legs,
            "remaining_distance_m": distance,
            "total_distance_m": vehicle.distance_before_schedule_m + distance,
            "distance_driven_m": driven}


def checkpoint(vehicle, state, context, now, *, network=None):
    """Continue to the current road leg's endpoint before changing a route.

    This keeps the marker continuous without inventing new GPS nodes. The
    outstanding consignment is still in the queue and is never auto-delivered
    merely because the endpoint becomes a re-planning anchor.
    """
    network = network or read_network()
    view = execution_view(vehicle, state, context, network=network, now=now)
    track = view["track"]
    if track is None or not context.get("clock"):
        return {"facility_id": vehicle.current_facility_id, "time_min": float(now),
                "distance_m": vehicle.distance_before_schedule_m, "history": vehicle.historical_legs,
                "approach_from": None, "approach_depart": None}
    facilities = {n["node_id"]: n["facility_id"] for n in network["nodes"]}
    if track.get("approaching_checkpoint"):
        return {"facility_id": view["start_facility_id"], "time_min": view["started_min"],
                "distance_m": vehicle.distance_before_schedule_m, "history": vehicle.historical_legs,
                "approach_from": vehicle.approach_from_facility_id,
                "approach_depart": vehicle.approach_depart_min}
    moving = 0 < track["leg_fraction"] < 1
    facility = facilities[track["leg_to"]] if track["leg_fraction"] > 0 else facilities[track["leg_from"]]
    distance = view["distance_driven_m"]
    if moving:
        distance += network["matrix"]["distance_m"][track["leg_from"]][track["leg_to"]] * (1 - track["leg_fraction"])
    history = (*vehicle.historical_legs, *(leg for leg in view["legs"]
               if leg["driven"] or (moving and leg["schedule_index"] == track["leg_index"] + 1)))
    return {"facility_id": facility,
            "time_min": max(float(now), track["leg_arrival_min"] if moving else view["started_min"]),
            "distance_m": distance, "history": history,
            "approach_from": facilities[track["leg_from"]] if moving else None,
            "approach_depart": track["leg_depart_min"] if moving else None}


def install_schedule(vehicle, candidate):
    """Persist exactly the schedule that was priced and validated."""
    return replace(vehicle,
        ready_from_min=float(candidate.get("ready_from_min", candidate["schedule_start_min"])),
        schedule_start_min=float(candidate["schedule_start_min"]),
        schedule_start_facility_id=candidate["schedule_start_facility_id"],
        schedule_stops=tuple(PlannedStop(**stop) for stop in candidate["schedule_stops"]),
        distance_before_schedule_m=float(candidate.get("distance_before_schedule_m", 0)),
        historical_legs=tuple(candidate.get("historical_legs", ())),
        approach_from_facility_id=candidate.get("approach_from_facility_id"),
        approach_depart_min=candidate.get("approach_depart_min"))
