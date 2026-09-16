"""Where each truck should park for the night (B5, 2026-09-16).

The rule from the meeting: the day's fixed orders are known in advance, so the
fleet should not simply drive home — at the end of the day each truck parks at a
node that makes *tomorrow* cheap, and tomorrow's plan starts from there.
Sudden orders and scrapped shipments are deliberately ignored here; they are
re-planned when they happen.

Method (v1, greedy — the version ``docs/路径规划总逻辑方案.md`` §4 recommends
first):

1. plan tomorrow's fixed orders once, with every truck assumed to start at the
   warehouse, to learn each truck's **first stop**;
2. for each truck, pick the parking node (from the allowed set) that minimises
   tomorrow's first leg — "park near where tomorrow begins";
3. charge the drive to that parking node against **today's** mileage cap, and
   keep today's position when the reposition would not fit;
4. report both numbers, so "park somewhere sensible" can be compared with
   "just stop where you are".

Known limit (declared, not hidden): the tentative plan is computed once from the
warehouse, so this is a greedy assignment, not a joint optimisation of parking
and tomorrow's routes; and routing *from* a parking node needs per-vehicle start
nodes, which the multi-origin batch (B4) introduces.  This module produces the
decision and the accounting that batch will consume.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .dispatch_models import (
    DeliveryOrder, DispatchConstraints, DispatchVehicle, InventoryLot,
)
from .dispatch_planner import DISPATCH_ORIGIN, plan_delivery_orders
from .singapore_loader import SINGAPORE_NETWORK_PATH, read_network

ASSUMPTIONS = (
    "模拟数据：次日固定订单为演示批次；停靠点只从 constraints.terminal_facility_ids 里选。",
    "停靠位移按 2026-09-16 口径计入当日里程上限（含空驶）。",
    "本版为贪心选址：先用『车都在主仓』试排一次次日计划取首站，再选离首站最近的停靠点；"
    "不做停车与次日路线的联合优化，也不做多日滚动。",
    "次日『从停靠点出发』的排线需要每车起点支持（B4 多起点批次）；本模块先产出并回报该决定。",
    "注意：按三角不等式，停靠位移通常不小于次日省下的首段空驶，因此本决策买到的是**次日更短的首段"
    "与更早出发**，而非两日总里程更省；net_two_day_m 就是这笔账（负值表示总里程反而多一点）。",
)


@dataclass(frozen=True)
class ParkingChoice:
    vehicle_id: str
    from_facility_id: str            # where the truck is now (today's end)
    park_facility_id: str            # where it should spend the night
    reposition_m: int                # driven today to get there
    tomorrow_origin_facility_id: str | None
    deadhead_m: int                  # parking node → tomorrow's pickup point
    stay_deadhead_m: int             # today's position → tomorrow's first stop
    saved_m: int                     # stay_deadhead_m − deadhead_m
    net_m: int                       # saved_m − reposition_m: the honest two-day balance
    note: str = ""                   # why the first choice was not taken


@dataclass(frozen=True)
class OvernightPlan:
    algorithm: str
    choices: tuple[ParkingChoice, ...]
    total_reposition_m: int
    total_deadhead_m: int
    total_stay_deadhead_m: int
    total_saved_m: int
    total_net_m: int
    assumptions: tuple[str, ...] = ASSUMPTIONS


def plan_overnight_parking(
    orders: tuple[DeliveryOrder, ...],
    inventory: tuple[InventoryLot, ...],
    vehicles: tuple[DispatchVehicle, ...],
    *,
    network_path: str | Path = SINGAPORE_NETWORK_PATH,
    constraints: DispatchConstraints | None = None,
    algorithm: str = "greedy",
    today_distance_m: dict[str, int] | None = None,
) -> OvernightPlan:
    """Decide each truck's parking node for tonight.

    ``today_distance_m`` is how far each truck has already driven today; together
    with ``constraints.mileage_limit_m`` it bounds the repositioning drive.
    """
    constraints = constraints or DispatchConstraints()
    network = read_network(network_path)
    node_by_facility = {n["facility_id"]: n["node_id"] for n in network["nodes"]}
    facility_by_node = {v: k for k, v in node_by_facility.items()}
    distance = network["matrix"]["distance_m"]
    today_distance_m = today_distance_m or {}

    unknown = sorted(set(constraints.terminal_facility_ids or ()) - set(node_by_facility))
    if unknown:
        raise ValueError(f"unknown terminal facilities: {unknown}")
    terminals = [node_by_facility[fid] for fid in (constraints.terminal_facility_ids or ())]

    # Tomorrow's tentative plan: every truck assumed to start at the warehouse,
    # so we learn which stop each one would begin with. The real positions are
    # kept aside for the parking decision below — a truck that ended today at a
    # supply point is exactly the case this module exists for, and the planner's
    # single-origin check would otherwise reject it before we get to choose.
    at_origin = tuple(
        replace(vehicle, start_facility_id=DISPATCH_ORIGIN) for vehicle in vehicles
    )
    plan = plan_delivery_orders(
        orders, inventory, at_origin, algorithm=algorithm,
        network_path=network_path, constraints=constraints,
    )
    first_stop: dict[str, int] = {}
    for zone_plan in plan.zone_plans:
        for route in zone_plan.result.routes:
            if not route.customer_ids:
                continue
            vehicle_id = zone_plan.vehicle_ids[route.vehicle_id - 1]
            # The truck must REACH its pickup point before anything else, so that
            # is what tonight's parking has to be close to (B4 made the origin a
            # real route start, 2026-09-16).
            first_stop[vehicle_id] = node_by_facility[zone_plan.origin_facility_id]

    choices: list[ParkingChoice] = []
    for vehicle in vehicles:
        here = node_by_facility.get(vehicle.start_facility_id)
        pickup = first_stop.get(vehicle.vehicle_id)
        note = ""
        if here is None:
            raise ValueError(f"vehicle {vehicle.vehicle_id}: unknown start facility")
        if not terminals:
            park = here
            note = "no_terminal_given"
        elif pickup is None:
            # Nothing to do tomorrow: stay where it is. Driving an idle truck to a
            # nicer spot spends today's mileage for a benefit that does not exist —
            # the first UI run moved one 17.7 km for nothing.
            park = here
            note = "unused_tomorrow"
        else:
            driven = int(today_distance_m.get(vehicle.vehicle_id, 0))
            park = None
            budget_blocked = False
            for candidate in sorted(terminals, key=lambda node: distance[node][pickup]):
                reposition = distance[here][candidate]
                if (constraints.mileage_limit_m is not None
                        and driven + reposition > constraints.mileage_limit_m):
                    budget_blocked = True
                    continue
                park = candidate
                break
            if park is None:
                # Stay put rather than break today's cap; say which limit bit.
                park = here
                note = "mileage_budget_exhausted" if budget_blocked else "kept_position"
            elif budget_blocked and park == here:
                # The truck happens to already stand on an allowed node, so "stay
                # here" was affordable — but the *better* node was out of budget.
                # Without this the operator would think this was the best choice.
                note = "mileage_budget_exhausted"

        deadhead = distance[park][pickup] if pickup is not None else 0
        stay_deadhead = distance[here][pickup] if pickup is not None else 0
        choices.append(ParkingChoice(
            vehicle_id=vehicle.vehicle_id,
            from_facility_id=vehicle.start_facility_id,
            park_facility_id=facility_by_node[park],
            reposition_m=int(distance[here][park]),
            tomorrow_origin_facility_id=(
                None if pickup is None else facility_by_node[pickup]
            ),
            deadhead_m=int(deadhead),
            stay_deadhead_m=int(stay_deadhead),
            saved_m=int(stay_deadhead - deadhead),
            net_m=int(stay_deadhead - deadhead) - int(distance[here][park]),
            note=note,
        ))

    return OvernightPlan(
        algorithm=algorithm,
        choices=tuple(choices),
        total_reposition_m=sum(c.reposition_m for c in choices),
        total_deadhead_m=sum(c.deadhead_m for c in choices),
        total_stay_deadhead_m=sum(c.stay_deadhead_m for c in choices),
        total_saved_m=sum(c.saved_m for c in choices),
        total_net_m=sum(c.net_m for c in choices),
    )
