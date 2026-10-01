"""Build auditable emergency-order candidates from persisted dispatch state."""
from __future__ import annotations

from .dispatch_models import DeliveryOrder, normalise_onboard_spare
from .dispatch_planner import DISPATCH_ORIGIN
from dataclasses import replace

from .dispatch_state import DispatchState, OrderProgress, VehicleProgress
from .singapore_loader import read_network
from .dispatch_constraints import price_work
from .execution import install_schedule

#: How on-time candidates are ranked against each other. Which one is "right"
#: is a business call (fewest disrupted orders vs fewest vehicles), not a
#: technical one, so it is switchable per request and echoed back in the
#: response instead of being buried in the sort key
#: (see ``docs/C_配送模块.md`` §5 D1).
POLICIES = ("minimize_disruption", "minimize_vehicles")
DEFAULT_POLICY = "minimize_disruption"

#: Candidate kinds, in the order the UI presents them. ``add_stop_in_transit``
#: uses stock already on the truck; ``return_to_depot`` fetches more from the
#: depot; ``load_before_departure`` only exists before the fleet rolls;
#: ``spare_vehicle`` opens a vehicle that was not part of this operation.
CANDIDATE_KINDS = (
    "add_stop_in_transit",
    "load_before_departure",
    "return_to_depot",
    "spare_vehicle",
)


def _spare_available(progress: VehicleProgress, order: DeliveryOrder) -> int:
    """Onboard spare matching this order's product and temperature zone."""
    return sum(
        quantity for product_id, zone, quantity in progress.onboard_spare
        if product_id == order.product_id and zone == order.temperature_zone
    )


def _spare_total(progress: VehicleProgress | None) -> int:
    return sum(quantity for _, _, quantity in progress.onboard_spare) if progress else 0


def _consume_spare(progress: VehicleProgress, order: DeliveryOrder) -> tuple[tuple[str, str, int], ...]:
    """Take ``order.quantity`` off the onboard spare, matching product and zone.

    Raises rather than silently going negative: this runs during ``accept``,
    where a mismatch means the state changed after the preview was shown.
    """
    needed = order.quantity
    remaining: list[tuple[str, str, int]] = []
    for product_id, zone, quantity in progress.onboard_spare:
        if (product_id == order.product_id and zone == order.temperature_zone
                and needed > 0):
            taken = min(needed, quantity)
            needed -= taken
            quantity -= taken
        if quantity:
            remaining.append((product_id, zone, quantity))
    if needed:
        raise ValueError("onboard spare changed after emergency preview")
    return tuple(remaining)


def _refuse_paired_run(state: DispatchState) -> None:
    """Rescue splicing is queue-based; a pickup-delivery run is a driven sequence.

    Every branch option works by putting the new order at the head of a truck's
    *order queue* and re-sequencing the tail. A paired run carries an explicit
    stop sequence instead — the map, the clock and ``next_stop`` all read it — so
    splicing only the queue would leave the new order undeliverable while the
    ledger called it assigned. Both entry points refuse together, so the panel
    cannot preview an option that acceptance would then reject (2026-09-16,
    PDPTW step 4).
    """
    paired = sorted(vehicle_id for vehicle_id, vehicle in state.vehicles.items()
                    if vehicle.drive_plan)
    if paired:
        raise ValueError(
            "rescue is not available for a pickup-delivery run yet: such a run drives "
            "an explicit stop sequence, while a rescue re-sequences the order queue. "
            "Re-plan today's batch with routing_model='grouped' to use the rescue flow "
            f"(paired vehicles: {', '.join(paired)})"
        )


def preview_emergency_order(
    state: DispatchState,
    context: dict,
    order: DeliveryOrder,
    *,
    current_time_min: int,
    loading_min: int = 15,
    policy: str = DEFAULT_POLICY,
    spoiled_order_id: str | None = None,
) -> dict:
    """Compare every way this branch order could be served, without changing state.

    The options are exactly the business question "change a running vehicle's
    route, or send another one": reuse a truck that is already rolling
    (``add_stop_in_transit`` from its own spare, or ``return_to_depot`` for more
    stock), load it before it leaves (``load_before_departure``), or open a
    vehicle that is not part of this operation (``spare_vehicle``).
    """
    if policy not in POLICIES:
        raise ValueError(
            f"unknown policy {policy!r}; expected one of {list(POLICIES)}"
        )
    if state.status not in {"accepted", "in_transit"}:
        raise ValueError("emergency orders require an active dispatch")
    # Before anything else looks at the queue: a paired run has no queue to splice.
    _refuse_paired_run(state)
    if order.order_id in state.orders:
        raise ValueError(f"order {order.order_id!r} already exists")

    network = read_network()
    nodes = {node["facility_id"]: node["node_id"] for node in network["nodes"]}
    if order.destination_facility_id not in nodes:
        raise ValueError(f"unknown destination {order.destination_facility_id!r}")
    matrix = network["matrix"]

    def leg(origin: str, destination: str) -> tuple[float, float]:
        try:
            i, j = nodes[origin], nodes[destination]
        except KeyError as exc:
            raise ValueError(f"unknown facility {exc.args[0]!r}") from exc
        return matrix["distance_m"][i][j], matrix["duration_s"][i][j] / 60.0

    order_lookup = _order_lookup(context)
    # Which shipments are physically in a truck right now: an order is on board
    # exactly while it is in a vehicle's remaining queue (B6, 2026-09-16).
    spoiled_on_board = on_board_orders(state)
    input_data = context.get("input", {})
    lots = {item["lot_id"]: item for item in input_data.get("inventory", [])}
    # Which supply points may hand this product over, and which of them actually
    # hold enough of it (B6: the pickup no longer has to be the main warehouse).
    carriers = _carriers_with_stock(order, lots, state)
    stock = max(carriers.values(), default=0)
    if not carriers and not any(_spare_available(v, order) >= order.quantity
                                and v.status == "in_transit" for v in state.vehicles.values()):
        return {
            "feasible": False,
            "order_id": order.order_id,
            "reason": "insufficient_available_inventory",
            "required_quantity": order.quantity,
            "available_quantity": stock,
            "candidates": [],
        }

    vehicles = {item["vehicle_id"]: item for item in input_data.get("vehicles", [])}
    candidates = []
    for vehicle_id, vehicle in vehicles.items():
        if vehicle["temperature_zone"] != order.temperature_zone:
            continue
        progress = state.vehicles.get(vehicle_id)
        # Free capacity, not rated capacity: an in-transit vehicle may already be
        # carrying quantity for its remaining orders — and its onboard spare —
        # which the vehicle's own rated capacity says nothing about. A vehicle
        # that has not been given any work yet has no state entry, so its
        # declared spare is read from the request instead: the fleet description
        # says what is on the truck, and that is true before it departs too.
        declared_spare = normalise_onboard_spare(vehicle.get("onboard_spare", ()))
        onboard = (
            _spare_total(progress) if progress is not None
            else sum(quantity for _, _, quantity in declared_spare)
        ) + (
            sum(state.orders[order_id].quantity for order_id in progress.remaining_order_ids
                if order_id != spoiled_order_id)
            if progress is not None else 0
        )
        free_capacity = vehicle["capacity"] - onboard
        if progress is None and vehicle.get("status", "available") == "available":
            if free_capacity < order.quantity or not carriers:
                continue
            start = vehicle.get("start_facility_id") or DISPATCH_ORIGIN
            pickup = _nearest_carrier(carriers, start, order.destination_facility_id, leg)
            to_pickup_distance, to_pickup_time = leg(start, pickup)
            distance, travel = leg(pickup, order.destination_facility_id)
            depart_at = max(current_time_min, vehicle.get("available_from_min", 0)) + loading_min
            eta = depart_at + to_pickup_time + loading_min + travel
            item = _candidate("spare_vehicle", vehicle_id, eta,
                              to_pickup_distance + distance, order)
            item["pickup_facility_id"] = pickup
            candidates.append(item)
        elif progress is not None and progress.status == "reserved" and (
                progress.current_facility_id in carriers):
            if free_capacity < order.quantity:
                continue
            # Assigned but still at the depot: the cheapest option of all —
            # load this order with the rest before the vehicle ever leaves, so
            # there is no detour, only an extra stop placed first.
            pickup = progress.current_facility_id
            distance, travel = leg(pickup, order.destination_facility_id)
            depart_at = current_time_min + loading_min
            eta = depart_at + travel
            item = _candidate("load_before_departure", vehicle_id, eta, distance, order)
            item["pickup_facility_id"] = pickup
            affected = _affected_orders(
                progress.remaining_order_ids, progress.current_facility_id,
                depart_at, order.destination_facility_id, eta, order_lookup, leg,
            )
            tail, changed = _resequence_tail(
                list(progress.remaining_order_ids),
                order.destination_facility_id, eta, order_lookup, leg,
            )
            item["remaining_order_ids_after"] = tail
            item["resequenced"] = changed
            if changed:
                affected = _affected_orders(
                    progress.remaining_order_ids, progress.current_facility_id,
                    current_time_min, order.destination_facility_id, eta,
                    order_lookup, leg, diverted_order_ids=tail,
                )
            item["affected_order_ids"] = list(progress.remaining_order_ids)
            item["affected_orders"] = affected
            item["on_time"] = item["on_time"] and not any(a["newly_late"] for a in affected)
            candidates.append(item)
        elif progress is not None and progress.status == "in_transit":
            # Option 1 — change this vehicle's route and serve the order from the
            # stock it is already carrying: no depot leg, only the extra stop.
            spare = _spare_available(progress, order)
            if spare >= order.quantity:
                distance, travel = leg(
                    progress.current_facility_id, order.destination_facility_id)
                eta = current_time_min + travel
                item = _candidate("add_stop_in_transit", vehicle_id, eta, distance, order)
                item["onboard_spare_used"] = order.quantity
                affected = _affected_orders(
                    progress.remaining_order_ids, progress.current_facility_id,
                    current_time_min, order.destination_facility_id, eta,
                    order_lookup, leg,
                )
                tail, changed = _resequence_tail(
                    list(progress.remaining_order_ids),
                    order.destination_facility_id, eta, order_lookup, leg,
                )
                item["remaining_order_ids_after"] = tail
                item["resequenced"] = changed
                if changed:
                    affected = _affected_orders(
                        progress.remaining_order_ids, progress.current_facility_id,
                        current_time_min, order.destination_facility_id, eta,
                        order_lookup, leg, diverted_order_ids=tail,
                    )
                item["affected_order_ids"] = list(progress.remaining_order_ids)
                item["affected_orders"] = affected
                item["on_time"] = item["on_time"] and not any(
                    a["newly_late"] for a in affected)
                candidates.append(item)
            # Option 2 — change this vehicle's route but fetch the goods from the
            # depot first. Only offered when the truck can still take them aboard.
            if free_capacity < order.quantity or not carriers:
                continue
            # The kind keeps its historical name, but the stop is now the nearest
            # supply point that holds the product — which is only the depot when
            # the depot is the closest source.
            pickup = _nearest_carrier(carriers, progress.current_facility_id,
                                      order.destination_facility_id, leg)
            to_pickup_distance, to_pickup_time = leg(progress.current_facility_id, pickup)
            delivery_distance, delivery_time = leg(pickup, order.destination_facility_id)
            eta = current_time_min + to_pickup_time + loading_min + delivery_time
            item = _candidate(
                "return_to_depot", vehicle_id, eta,
                to_pickup_distance + delivery_distance, order,
            )
            item["pickup_facility_id"] = pickup
            # A detour must not silently make this vehicle's own remaining
            # orders miss their own delivery windows — re-simulate their
            # arrival with and without the detour and flag any newly-late one.
            # The diverted tour restarts where the vehicle actually is after the
            # emergency drop (the emergency destination), not at the depot it
            # visited on the way.
            affected = _affected_orders(
                progress.remaining_order_ids, progress.current_facility_id,
                current_time_min, order.destination_facility_id, eta,
                order_lookup, leg,
            )
            tail, changed = _resequence_tail(
                list(progress.remaining_order_ids),
                order.destination_facility_id, eta, order_lookup, leg,
            )
            item["remaining_order_ids_after"] = tail
            item["resequenced"] = changed
            if changed:
                affected = _affected_orders(
                    progress.remaining_order_ids, progress.current_facility_id,
                    current_time_min, order.destination_facility_id, eta,
                    order_lookup, leg, diverted_order_ids=tail,
                )
            item["affected_order_ids"] = list(progress.remaining_order_ids)
            item["affected_orders"] = affected
            item["on_time"] = item["on_time"] and not any(a["newly_late"] for a in affected)
            candidates.append(item)

    checked = []
    for item in candidates:
        progress = state.vehicles.get(item["vehicle_id"])
        tail = [oid for oid in item.get("remaining_order_ids_after", ())
                if oid != spoiled_order_id]
        pickups = (list(carriers) if item["kind"] in {"return_to_depot", "spare_vehicle"}
                   else [item.get("pickup_facility_id") if item["kind"] != "add_stop_in_transit" else None])
        variants = []
        for pickup in pickups:
            candidate = {**item, "pickup_facility_id": pickup}
            queue = (order.order_id, *tail)
            priced = price_work(state, context, vehicle_id=item["vehicle_id"], order_ids=queue,
                current_time_min=current_time_min, orders={order.order_id: vars(order)},
                pickup_facility_id=pickup if item["kind"] != "load_before_departure" else None,
                loading_min=loading_min if item["kind"] == "load_before_departure" else 0,
                starts_new_vehicle=item["kind"] == "spare_vehicle", removed_order_id=spoiled_order_id)
            candidate.update(priced)
            candidate["remaining_order_ids_after"] = tail
            candidate["eta_min"] = round(priced["arrivals"][order.order_id], 2)
            candidate["lateness_min"] = round(max(0, candidate["eta_min"] - order.latest_min), 2)
            variants.append(candidate)
        if variants:
            checked.append(min(variants, key=lambda c: (not c["feasible"], c["distance_m"], c["eta_min"])))
    candidates = checked

    baselines = {}
    for item in candidates:
        progress = state.vehicles.get(item["vehicle_id"])
        if progress is not None and item["vehicle_id"] not in baselines:
            original = price_work(state, context, vehicle_id=item["vehicle_id"],
                order_ids=progress.remaining_order_ids, current_time_min=current_time_min)
            baselines[item["vehicle_id"]] = {
                "node_sequence": original["node_sequence"],
                "current_node_id": original["node_sequence"][0],
                "has_work": bool(progress.remaining_order_ids),
            }

    # A candidate that stops at a pickup point hands the scrapped goods over
    # there — the cold-chain reality is "return the spoiled batch, collect the
    # replacement" in one visit, which is why no extra leg is needed. The onboard
    # option makes no stop, so its spoiled goods ride to the vehicle's end node;
    # the field stays empty and the limitation is declared in ``limitations``.
    if spoiled_order_id and spoiled_order_id in spoiled_on_board:
        for item in candidates:
            if item.get("pickup_facility_id"):
                item["quarantine_order_ids"] = [spoiled_order_id]

    candidates.sort(key=lambda item: _rank(item, policy))
    # "Severity" of the case: is the spoiled shipment still in a truck, or was it
    # already handed over at the hospital? The first needs the goods disposed of
    # on the way (the pickup stop doubles as the hand-over point), the second does
    # not — and which one it is comes straight out of the state.
    return {
        "feasible": any(item["on_time"] for item in candidates),
        "order_id": order.order_id,
        #: The order whose goods were scrapped, when it is still in a truck.
        "quarantine_order_id": spoiled_order_id if spoiled_order_id in spoiled_on_board else None,
        "quarantine_vehicle_id": spoiled_on_board.get(spoiled_order_id),
        "current_time_min": current_time_min,
        "policy": policy,
        "available_quantity": stock,
        "selected_candidate": candidates[0] if candidates else None,
        "candidates": candidates,
        "baselines": baselines,
        "limitations": [
            "preview_only",
            "spoiled_goods_handed_over_at_the_pickup_stop_unless_the_onboard_option_is_used",
            "free_flow_travel_time",
            "in_transit_vehicle_returns_to_depot_unless_onboard_spare_covers_the_order",
            "onboard_spare_is_a_load_assumption_not_a_depot_lot",
            "affected_order_etas_ignore_per_stop_service_dwell_time",
        ],
        "reason": None if any(item["feasible"] for item in candidates) else "no_feasible_emergency_schedule",
    }




def on_board_orders(state: DispatchState) -> dict[str, str]:
    """``order_id -> vehicle_id`` for goods that are physically still on a truck.

    No new bookkeeping: an order is on board exactly while it is in a vehicle's
    remaining queue. Once it is delivered it is in ``delivered_order_ids`` and the
    goods are at the hospital — which is the other half of the scrap decision
    (2026-09-16, B6).
    """
    return {order_id: vehicle.vehicle_id
            for vehicle in state.vehicles.values()
            for order_id in vehicle.remaining_order_ids}


def _carriers_with_stock(order, lots, state) -> dict[str, int]:
    """Supply points that may hand this product over, with how much they hold.

    A point counts only if the supply table says it carries this product **and**
    the request's own ledger has enough of it available — the table declares what
    a node may supply, the ledger says what is actually there. Both matter, and a
    demo quantity in the table is not stock.
    """
    from .catalog import read_supply_points, supplies_product

    allowed = {point.facility_id for point in read_supply_points()
               if supplies_product(point, order.product_id)}
    stock: dict[str, int] = {}
    for lot_id, lot in lots.items():
        if (lot["product_id"] != order.product_id
                or lot["temperature_zone"] != order.temperature_zone
                or lot.get("status", "available") != "available"
                or lot["facility_id"] not in allowed):
            continue
        stock[lot["facility_id"]] = stock.get(lot["facility_id"], 0) + \
            state.available_by_lot.get(lot_id, 0)
    return {facility: units for facility, units in stock.items()
            if units >= order.quantity}


def _nearest_carrier(carriers: dict[str, int], from_facility: str,
                     to_facility: str, leg) -> str | None:
    """The pickup point that costs this vehicle the least extra driving.

    Judged on the **whole detour** - where the truck is now, out to the source,
    then on to the hospital - not on the distance to either end alone. Picking the
    source closest to the truck can send it past a nearer one and back.
    """
    if not carriers:
        return None
    return min(carriers, key=lambda facility: (
        leg(from_facility, facility)[0] + leg(facility, to_facility)[0]))


def _order_lookup(context: dict) -> dict:
    """order_id -> original request dict (destination/time-window/quantity)."""
    return {item["order_id"]: item for item in context.get("input", {}).get("orders", [])}


def _simulate_arrivals(start_facility: str, start_time: float, order_ids: tuple[str, ...],
                        order_lookup: dict, leg) -> dict[str, float]:
    """Free-flow arrival time at each destination, visiting order_ids in queue
    order. No per-stop service dwell is modelled here, matching the same
    approximation the candidate ETAs above already use."""
    arrivals: dict[str, float] = {}
    at_facility, at_time = start_facility, start_time
    for order_id in order_ids:
        destination = order_lookup[order_id]["destination_facility_id"]
        _, travel = leg(at_facility, destination)
        at_time += travel
        arrivals[order_id] = at_time
        at_facility = destination
    return arrivals


def _affected_orders(remaining_order_ids: tuple[str, ...], current_facility_id: str,
                     current_time_min: int, detour_facility_id: str, detour_eta: float,
                     order_lookup: dict, leg, diverted_order_ids=None) -> list[dict]:
    """Compare each remaining order's arrival with vs without the detour.

    ``newly_late`` is true only when the detour is what pushes a previously
    on-time order past its own ``latest_min`` — an order already running late
    before this decision is reported via ``already_late`` instead, so the
    detour is not blamed for a delay it did not cause.
    """
    baseline = _simulate_arrivals(current_facility_id, current_time_min,
                                  remaining_order_ids, order_lookup, leg)
    # The diverted tour may also have been RE-SEQUENCED (see _resequence_tail):
    # the delay a remaining order suffers is the one it suffers on the route that
    # will actually be driven, not on the old queue order.
    diverted = _simulate_arrivals(detour_facility_id, detour_eta,
                                  diverted_order_ids or remaining_order_ids,
                                  order_lookup, leg)
    affected = []
    for order_id in remaining_order_ids:
        latest = order_lookup[order_id]["latest_min"]
        was_late = baseline[order_id] > latest
        affected.append({
            "order_id": order_id,
            "baseline_eta_min": round(baseline[order_id], 2),
            "new_eta_min": round(diverted[order_id], 2),
            "delay_min": round(diverted[order_id] - baseline[order_id], 2),
            "already_late": was_late,
            "newly_late": (not was_late) and diverted[order_id] > latest,
        })
    return affected



#: How many improvement passes the re-sequencing may make. The tail is one
#: vehicle's remaining stops (a handful), so this is a safety rail, not a cost.
RESEQUENCE_PASSES = 8


def _resequence_tail(tail_ids: list[str], start_facility: str, start_time: float,
                     order_lookup: dict, leg) -> tuple[list[str], bool]:
    """Re-order one vehicle's remaining stops to shorten the diverted tour.

    Inserting a rescue order used to leave the rest of the queue untouched, so a
    truck could be sent back and forth across the island because of where the new
    stop happened to land. This is a bounded 2-opt over the remaining stops.

    Only swaps that keep every **currently on-time** order on time are accepted:
    an order already running late may stay late (that is the situation the
    operator is already in), but the diversion must not be what pushes a fresh
    one over its window. Returns ``(sequence, changed)``.
    """
    if len(tail_ids) < 2:
        return list(tail_ids), False

    def arrivals(sequence: list[str]) -> dict[str, float]:
        return _simulate_arrivals(start_facility, start_time, tuple(sequence),
                                  order_lookup, leg)

    original = list(tail_ids)
    original_arrivals = arrivals(original)
    on_time_before = {
        order_id for order_id in original
        if original_arrivals[order_id] <= order_lookup[order_id]["latest_min"]
    }

    def total_time(sequence: list[str], times: dict[str, float]) -> float:
        return times[sequence[-1]] if sequence else start_time

    def acceptable(sequence: list[str]) -> tuple[bool, dict[str, float]]:
        times = arrivals(sequence)
        for order_id in on_time_before:
            if times[order_id] > order_lookup[order_id]["latest_min"]:
                return False, times
        return True, times

    best = original
    best_times = original_arrivals
    best_cost = total_time(best, best_times)
    improved = True
    passes = 0
    while improved and passes < RESEQUENCE_PASSES:
        improved = False
        passes += 1
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                trial = best[:i] + list(reversed(best[i:j + 1])) + best[j + 1:]
                ok, times = acceptable(trial)
                if not ok:
                    continue
                cost = total_time(trial, times)
                if cost < best_cost - 1e-9:
                    best, best_times, best_cost = trial, times, cost
                    improved = True
    return best, best != original


def _rank(item: dict, policy: str) -> tuple:
    """Ordering key for one candidate under the requested policy.

    Both policies put "can this actually be delivered on time" first, and only
    then disagree about the price: ``minimize_disruption`` protects the orders
    already on board, ``minimize_vehicles`` protects the fleet by preferring a
    vehicle this operation already has over opening another one.
    """
    if policy == "minimize_vehicles":
        return (not item["on_time"], item["starts_new_vehicle"],
                len(item["affected_order_ids"]), item["eta_min"], item["distance_m"])
    return (not item["on_time"], len(item["affected_order_ids"]),
            item["eta_min"], item["distance_m"])


def _candidate(kind: str, vehicle_id: str, eta: float, distance: float, order: DeliveryOrder) -> dict:
    arrival = max(eta, order.earliest_min)
    return {
        "kind": kind,
        "vehicle_id": vehicle_id,
        "eta_min": round(arrival, 2),
        "on_time": arrival <= order.latest_min,
        "lateness_min": round(max(0.0, arrival - order.latest_min), 2),
        "distance_m": round(distance, 2),
        "affected_order_ids": [],
        #: Every candidate carries the same keys, so a comparison UI never has to
        #: branch on a missing field: a spare vehicle affects nobody already on
        #: board, and says so with an empty list.
        "affected_orders": [],
        #: A spare vehicle was not part of this operation; every other kind
        #: redirects a vehicle that was already going somewhere for this run.
        "starts_new_vehicle": kind == "spare_vehicle",
        #: The queue this vehicle would be left with, and whether that is a
        #: different ORDER from today's (B6 second half, 2026-09-16). A spare
        #: vehicle has no queue to re-order.
        "remaining_order_ids_after": [],
        "resequenced": False,
        #: Where the goods come from. ``None`` = they are already on board (the
        #: in-transit spare option) or the vehicle is standing on them.
        "pickup_facility_id": None,
        #: Scrapped orders this option hands over at its pickup stop (empty for a
        #: case whose goods never left the hospital).
        "quarantine_order_ids": [],
    }


def accept_emergency_order(
    state: DispatchState,
    context: dict,
    order: DeliveryOrder,
    *,
    current_time_min: int,
    candidate_kind: str,
    vehicle_id: str,
    command_id: str,
    policy: str = DEFAULT_POLICY,
    spoiled_order_id: str | None = None,
) -> DispatchState:
    """Revalidate and apply one previewed emergency option exactly once."""
    if command_id in state.applied_commands:
        return state
    preview = preview_emergency_order(
        state, context, order, current_time_min=current_time_min, policy=policy,
        spoiled_order_id=spoiled_order_id,
    )
    candidate = next((item for item in preview["candidates"] if (
        item["kind"] == candidate_kind and item["vehicle_id"] == vehicle_id
    )), None)
    if candidate is None or not candidate["on_time"]:
        raise ValueError("selected emergency candidate is unavailable or late")

    lots = {item["lot_id"]: item for item in context["input"]["inventory"]}
    available = dict(state.available_by_lot)
    if candidate_kind == "add_stop_in_transit":
        # The goods are the vehicle's own spare, so nothing leaves the depot
        # ledger. The reserve is recorded against an ONBOARD- pseudo lot so the
        # order is still traceable to what served it — a load assumption rather
        # than a depot lot, as the preview's ``limitations`` states.
        allocations = [(f"ONBOARD-{vehicle_id}", order.quantity)]
    else:
        # Reserve at the pickup point this candidate was priced with, not at a
        # hard-coded warehouse: the operator compared options that fetch from
        # different places, and the ledger has to follow the choice.
        pickup = candidate.get("pickup_facility_id") or DISPATCH_ORIGIN
        needed = order.quantity
        allocations = []
        for lot_id, lot in lots.items():
            if (lot["product_id"] != order.product_id
                    or lot["temperature_zone"] != order.temperature_zone
                    or lot["facility_id"] != pickup
                    or lot.get("status", "available") != "available"):
                continue
            take = min(needed, available.get(lot_id, 0))
            if take:
                available[lot_id] -= take
                needed -= take
                allocations.append((lot_id, take))
            if needed == 0:
                break
        if needed:
            raise ValueError("inventory changed after emergency preview")

    vehicles = dict(state.vehicles)
    if candidate_kind == "spare_vehicle":
        # A spare only rolls if the operation is already under way. On a run
        # that has not departed it waits at the depot with the rest — letting
        # it leave alone would flip the whole run to "in transit" while other
        # vehicles are still loading, and they could then never depart.
        # It keeps whatever spare the fleet description gives it: sending a
        # vehicle on its first task must not erase what is already on board.
        declared = next((item for item in context["input"]["vehicles"]
                         if item["vehicle_id"] == vehicle_id), {})
        start = declared.get("start_facility_id") or DISPATCH_ORIGIN
        pickup = candidate.get("pickup_facility_id")
        vehicles[vehicle_id] = VehicleProgress(
            vehicle_id, start, (order.order_id,),
            status="in_transit" if state.status == "in_transit" else "reserved",
            onboard_spare=normalise_onboard_spare(declared.get("onboard_spare", ())),
            pickup_facility_ids=(() if pickup in (None, start) else (pickup,)),
        )
    else:
        # Every remaining kind puts this order at the head of the vehicle's
        # queue; the vehicle's own status is unchanged, because loading before
        # departure does not put a vehicle on the road and a detour does not
        # take one off it. Only the onboard option changes what it carries.
        vehicle = vehicles[vehicle_id]
        # The candidate knows the queue it previewed (the rescue order first, then
        # the re-sequenced tail). Applying anything else would make the accepted
        # plan differ from the one the operator compared.
        tail = candidate.get("remaining_order_ids_after") or list(vehicle.remaining_order_ids)
        changes: dict = {
            "remaining_order_ids": (order.order_id, *tail)
        }
        pickup = candidate.get("pickup_facility_id")
        if pickup is not None and pickup != vehicle.current_facility_id:
            # The truck has to go and get the goods first; record that leg so the
            # clock and the map know about it (B6).
            changes["pickup_facility_ids"] = (pickup, *vehicle.pickup_facility_ids)
        if candidate_kind == "add_stop_in_transit":
            changes["onboard_spare"] = _consume_spare(vehicle, order)
        vehicles[vehicle_id] = replace(vehicle, **changes)
    # The order is only under way if the vehicle carrying it is; forcing
    # "in_transit" here would report an undeparted delivery as on the road.
    order_status = "in_transit" if vehicles[vehicle_id].status == "in_transit" else "planned"
    orders = {**state.orders, order.order_id: OrderProgress(
        order.order_id, order.product_id, order.destination_facility_id,
        order.quantity, vehicle_id, order_status,
    )}
    # A scrapped shipment must not be delivered. Take it out of the truck's queue
    # and record what happened to it: removing it (rather than marking it
    # delivered) also keeps the clock honest, because the tick counts the orders a
    # vehicle still has to serve. "Scrapped" is a terminal state — it is neither
    # pending nor delivered, and the audit trail keeps it either way.
    if spoiled_order_id and spoiled_order_id in orders:
        spoiled = orders[spoiled_order_id]
        carrier = vehicles.get(spoiled.vehicle_id)
        # Only goods that are STILL in the truck can be written off. A shipment
        # already delivered stays "delivered": it really was handed over, and
        # rewriting that would erase the fact the replacement exists because of.
        if carrier is not None and spoiled_order_id in carrier.remaining_order_ids:
            vehicles[spoiled.vehicle_id] = replace(
                carrier,
                remaining_order_ids=tuple(
                    oid for oid in carrier.remaining_order_ids
                    if oid != spoiled_order_id),
            )
            orders[spoiled_order_id] = replace(spoiled, status="scrapped")

    # The run is under way once any vehicle is; an accepted-but-undeparted run
    # must stay "accepted" so depart() still has something to do.
    status = "in_transit" if any(
        item.status == "in_transit" for item in vehicles.values()
    ) else state.status
    # A later quality-event branch must also update an accepted delay schedule.
    # Otherwise the order table gains a new queue but the tracker continues to
    # drive the old fixed tail and can never reach the inserted order.
    for carrier_id, carrier in tuple(vehicles.items()):
        previous = state.vehicles.get(carrier_id)
        if (previous is not None and carrier.replan_started_min is not None
                and carrier.remaining_order_ids != previous.remaining_order_ids):
            vehicles[carrier_id] = replace(
                carrier, replan_started_min=float(current_time_min),
                replan_start_facility_id=carrier.current_facility_id,
                replan_order_ids=carrier.remaining_order_ids)
        if (previous is not None and carrier_id != vehicle_id
                and carrier.remaining_order_ids != previous.remaining_order_ids):
            cleanup = price_work(state, context, vehicle_id=carrier_id,
                order_ids=carrier.remaining_order_ids, current_time_min=current_time_min,
                removed_order_id=spoiled_order_id)
            vehicles[carrier_id] = install_schedule(
                replace(vehicles[carrier_id], end_node_id=cleanup["end_node_id"]), cleanup)
    vehicles[vehicle_id] = install_schedule(
        replace(vehicles[vehicle_id], end_node_id=candidate["end_node_id"]), candidate)
    return replace(
        state,
        version=state.version + 1,
        status=status,
        orders=orders,
        vehicles=vehicles,
        available_by_lot=available,
        reserved_by_order={
            **state.reserved_by_order, order.order_id: tuple(allocations)
        },
        applied_commands=(*state.applied_commands, command_id),
    )
