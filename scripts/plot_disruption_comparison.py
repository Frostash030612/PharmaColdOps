"""Draw the "perturbation before vs after" figure (``docs/C_配送模块.md`` §4.3).

This is the third layer of the daily-delivery refactor: the first two made the
plan and let a branch event attach to it, this one makes the *consequence* of
that branch visible — how much further each option drives, which orders it
delays, and where it detours.

Nothing here is hand-written data. The script drives the real HTTP API through
the same sequence an operator would (daily batch → create the run → depart →
advance the clock → close a case linked to an order still on a rolling truck →
ask for the branch preview) and draws exactly what comes back. The route lines
are the backend's own ``route_geojson`` / ``baselines[...].route_geojson``, so
"before" and "after" are the lines the system would actually drive, not a
sketch of them.

Why the wall clock has to be driven: the simulated time is *start real time ×
speed* (``tracking.advance_clock``), and a tick only advances it by the real
seconds that passed. The case must be raised while the truck is between stops,
so the clock is stepped until a vehicle is genuinely in transit with work left.

Output: ``docs/figures/dispatch_disruption_comparison.{png,svg}``.

Reproduce from the repository root::

    python scripts/plot_disruption_comparison.py
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fastapi.testclient import TestClient                                    # noqa: E402

from api import service                                                      # noqa: E402
from api.main import app                                                     # noqa: E402
from api.schemas import DecideIn, EventIn                                    # noqa: E402
from optimisation.dispatch_repository import load_context, update_context    # noqa: E402
from optimisation.singapore_loader import read_network                       # noqa: E402

#: The excursion that makes the rescue necessary: a chilled vaccine shipment
#: held far below its range. ``-30 °C`` is what rule 4 turns into ``scrap``.
EXCURSION = {"excursion_temp_c": -30.0, "duration_min": 150, "mkt_c": -31.0,
             "packaging": "intact", "stage": "transit", "product_id": "vaccine_2_8"}

SPEED = 60.0            # simulated minutes per real minute while the clock runs
CLOCK_TARGET_MIN = 590  # raise the case once the truck is between stops

# Palette: "before" is deliberately neutral and dashed, so the options read as
# deviations from it rather than as three equivalent lines.
COLOUR_BEFORE = "#64748b"          # slate
COLOUR_BEST = "#16a34a"            # green - cheapest option
COLOUR_WORST = "#dc2626"           # red - the option that detours
COLOUR_ALT = "#0284c7"             # blue - any further option
COLOUR_ALERT = "#dc2626"
INK = "#0f172a"
MUTED = "#475569"

TIER_COLOURS = [COLOUR_BEST, COLOUR_ALT, "#7c3aed", "#ea580c", COLOUR_WORST]

FONT_STACK = ["PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
              "Noto Sans CJK SC", "SimHei", "DejaVu Sans"]
FONT_MONO = ["Consolas", "DejaVu Sans Mono", "Courier New"]


def backdate_clock(_client, dispatch_id: str, start_min: int) -> None:
    """Make the simulated day already be ``start_min`` when it is read next.

    ``advance_clock`` derives simulated time as ``speed x real seconds`` since
    ``clock['started_real']``, so the only ways to reach a given minute are to
    wait or to move the origin. Tests move the origin; the figure script waits.
    """
    context = load_context(service.DISPATCH_DATABASE_URL, dispatch_id)
    started = datetime.datetime.fromisoformat(context["clock"]["started_real"])
    context["clock"]["started_real"] = (
        started - datetime.timedelta(minutes=start_min / SPEED)).isoformat()
    update_context(service.DISPATCH_DATABASE_URL, dispatch_id, context)


def build_scenario(*, seed: int, hospitals: int, tick_seconds: float,
                   dispatch_db: str, runs_file: Path,
                   start_min: int | None = None, verbose: bool = True) -> dict:
    """Drive the real API until a truck is in transit, then preview the rescue.

    Everything the figure needs comes out of this dict, and every value in it
    came from the service: the case was judged by the rule engine, the offsets
    were computed by the planner, the geometry was exported by the backend.

    ``dispatch_db`` / ``runs_file`` are required rather than defaulted so that a
    caller cannot accidentally drive the scenario into the repository's own
    dispatch database and case log — the figure script and the tests each pass a
    throwaway location.

    ``start_min`` is for tests: simulated time accrues from the wall clock since
    departure, so a caller that cannot afford to wait can back-date the clock's
    start instead of sleeping. Left as ``None`` the clock runs in real time.
    """
    service.DISPATCH_DATABASE_URL = dispatch_db
    service.RUNS_FILE = Path(runs_file)
    client = TestClient(app)

    batch = client.get(
        f"/api/dispatch/daily-orders?hospitals={hospitals}&seed={seed}").json()["plan"]
    dispatch_id = f"PLAN-FIG-{datetime.datetime.now().strftime('%H%M%S%f')}"
    created = client.post("/api/dispatch/runs", json={
        **batch, "dispatch_id": dispatch_id, "command_id": f"create-{dispatch_id}"})
    if created.status_code != 200:
        raise RuntimeError(
            f"could not create the daily run: {created.status_code} {created.text}")
    plan = created.json()

    depart = client.post(f"/api/dispatch/runs/{dispatch_id}/depart",
                         json={"command_id": f"depart-{dispatch_id}", "speed": SPEED})
    depart.raise_for_status()

    if start_min is not None:
        backdate_clock(client, dispatch_id, start_min)

    view: dict = {}
    for step in range(120):
        time.sleep(tick_seconds)
        tick = client.post(f"/api/dispatch/runs/{dispatch_id}/tick",
                           json={"command_id": f"tick-{step}"})
        tick.raise_for_status()
        view = tick.json().get("route_view") or view
        clock = (view.get("clock") or {}).get("sim_start_min")
        if verbose:
            print(f"  tick {step:>3}  clock={clock:.1f}")
        if clock and clock >= CLOCK_TARGET_MIN:
            break
    else:                                                     # pragma: no cover
        raise RuntimeError("the clock never reached the target minute")

    # A truck that is genuinely between stops, with work still ahead of it: the
    # branch is only interesting when something remains to be re-planned.
    target = None
    for route in view.get("routes", []):
        track = route.get("track") or {}
        if route.get("status") != "in_transit" or track.get("finished"):
            continue
        for stop in route.get("stops", []):
            if not stop.get("delivered"):
                target = {"vehicle_id": route["vehicle_id"],
                          "order_id": stop["order_id"],
                          "node_id": stop["node_id"]}
                break
        if target:
            break
    if target is None:                                        # pragma: no cover
        raise RuntimeError("no rolling truck had work left; lower SPEED")

    # Close the case exactly as the app does — the rule engine judges it, the
    # record is appended, and the event names the order it concerns. The one
    # thing set by hand is ``created_at``: the case must be stamped with the same
    # simulated minute the preview will read the fleet position from, otherwise
    # "where the truck is" and "what time the case was raised" disagree. Stamping
    # it with the measured clock (rather than the wall clock) is also what makes
    # the figure reproducible run to run.
    clock_min = int(clock)
    created_at = (datetime.datetime(2026, 9, 18, clock_min // 60, clock_min % 60)
                  .isoformat(timespec="seconds"))
    event = {**EXCURSION, "order_id": target["order_id"]}
    decision = service.decide_view(DecideIn(**event), None)
    record = service._record_run({**decision, "event": event, "created_at": created_at,
                                 "disposition": "scrap", "reshipment_required": True})

    preview = client.post("/api/dispatch/reshipments/preview",
                          json={"run_id": record["run_id"]})
    preview.raise_for_status()
    body = preview.json()

    if verbose:
        print(f"\n  case {record['run_id']} → {record['disposition']} "
              f"(raised at simulated minute {clock_min})")
        print(f"  order source: {body['order_source']}")
        print(f"  rescuing:     {body['order']['order_id']} "
              f"({body['order']['product_id']}, {body['order']['quantity']} units) "
              f"→ {body['order']['destination_facility_id']}")
        for item in body["candidates"]:
            print(f"    {item['kind']:<24} vehicle={item['vehicle_id']:<14} "
                  f"+{item['added_distance_m'] / 1000:>6.2f} km  "
                  f"{len(item['affected_order_ids'])} affected  "
                  f"max delay {max((o['delay_min'] for o in item['affected_orders']),
                                   default=0.0):.1f} min")

    return {"dispatch_id": dispatch_id, "case": record, "preview": body,
            "plan": plan, "view": view, "target": target, "clock_min": clock_min,
            "network": read_network()}


# --- drawing -----------------------------------------------------------------

def _path_of(geojson: dict) -> tuple[list[float], list[float]]:
    coords = (geojson or {}).get("geometry", {}).get("coordinates") or []
    return [c[0] for c in coords], [c[1] for c in coords]


def _node_xy(network: dict, node_ids) -> tuple[list[float], list[float]]:
    by_id = {node["node_id"]: node for node in network["nodes"]}
    lon = [by_id[i]["lon"] for i in node_ids if i in by_id]
    lat = [by_id[i]["lat"] for i in node_ids if i in by_id]
    return lon, lat


def _facility_of(network: dict, node_id: int) -> str:
    for node in network["nodes"]:
        if node["node_id"] == node_id:
            return node["facility_id"]
    return str(node_id)                                       # pragma: no cover


def _short(network: dict, facility_id: str) -> str:
    for node in network["nodes"]:
        if node["facility_id"] == facility_id:
            return facility_id.replace("H-", "").replace("W-", "").replace("D-", "")
    return facility_id


KIND_LABELS = {
    "add_stop_in_transit": "在途余货\n顺路加一站",
    "load_before_departure": "装车前\n带货",
    "return_to_depot": "返仓\n取货",
    "spare_vehicle": "另派\n一辆车",
}


def _plain_kind(kind: str) -> str:
    return KIND_LABELS.get(kind, kind).replace("\n", "")


def _summary(candidate: dict) -> dict:
    delays = [o["delay_min"] for o in candidate.get("affected_orders", [])]
    return {
        "kind": candidate["kind"],
        "vehicle": candidate["vehicle_id"],
        "added_km": candidate["added_distance_m"] / 1000.0,
        "affected": len(candidate["affected_order_ids"]),
        "max_delay": max(delays) if delays else 0.0,
        "newly_late": sum(1 for o in candidate.get("affected_orders", [])
                          if o.get("newly_late")),
        "on_time": candidate["on_time"],
        "pickup": candidate.get("pickup_facility_id"),
        "resequenced": candidate.get("resequenced", False),
        "sequence": candidate.get("node_sequence") or [],
    }


def draw(scenario: dict, out_dir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    plt.rcParams.update({
        "font.sans-serif": FONT_STACK,
        "font.monospace": FONT_MONO,
        "axes.unicode_minus": False,
    })

    network = scenario["network"]
    preview = scenario["preview"]
    baseline_vehicle = scenario["target"]["vehicle_id"]
    baseline = (preview.get("baselines") or {}).get(baseline_vehicle) or {}
    summaries = sorted((_summary(c) for c in preview["candidates"]),
                       key=lambda s: (s["added_km"], s["max_delay"]))

    colour_for = {}
    for index, summary in enumerate(summaries):
        key = (summary["kind"], summary["vehicle"])
        colour_for[key] = (COLOUR_BEST if index == 0
                           else TIER_COLOURS[min(index, len(TIER_COLOURS) - 1)])
    fig = plt.figure(figsize=(7.05, 4.9), dpi=300)
    grid = fig.add_gridspec(1, 2, width_ratios=[1.24, 1.0], wspace=0.10,
                            left=0.05, right=0.975, top=0.835, bottom=0.105)

    owner = preview["order"]["destination_facility_id"]
    owner_node = next(n["node_id"] for n in network["nodes"]
                      if n["facility_id"] == owner)

    # ---- map ----------------------------------------------------------------
    ax_map = fig.add_subplot(grid[0, 0])
    for node in network["nodes"]:
        if node["role"] == "customer":
            ax_map.plot(node["lon"], node["lat"], marker="o", markersize=2.6,
                        color="#cbd5e1", zorder=1)
    ax_map.plot(*(_node_xy(network, [n["node_id"] for n in network["nodes"]
                                     if n["role"] in ("depot", "distribution",
                                                      "third_party")])),
                linestyle="none", marker="s", markersize=5.5,
                markerfacecolor="none", markeredgecolor=COLOUR_BEFORE,
                markeredgewidth=1.1, zorder=3)

    base_lon, base_lat = _path_of(baseline.get("route_geojson"))
    if base_lon:
        ax_map.plot(base_lon, base_lat, color=COLOUR_BEFORE, linewidth=3.4,
                    linestyle=(0, (4, 2)), zorder=4, solid_capstyle="round")
        ax_map.plot(base_lon, base_lat, color="white", linewidth=1.0, zorder=5,
                    linestyle=":", alpha=0.9)

    # Draw the priciest option first and the cheapest last: where two options
    # share a road (a depot round-trip and an onboard drop do), the line left on
    # top is the one that decided the ranking. Only the ranked options are drawn,
    # so the map carries exactly as many lines as the table has rows — a third
    # line nobody can account for is worse than leaving it off.
    ranked = [(s["kind"], s["vehicle"]) for s in summaries]
    for key in reversed(ranked):
        candidate = next(c for c in preview["candidates"]
                         if (c["kind"], c["vehicle_id"]) == key)
        lon, lat = _path_of(candidate.get("route_geojson"))
        if not lon:
            continue
        colour = colour_for[key]
        ax_map.plot(lon, lat, color=colour, linewidth=2.0, alpha=0.95, zorder=6)
        summary = next(s for s in summaries
                       if (s["kind"], s["vehicle"]) == key)
        detour = [n for n in summary["sequence"]
                  if n not in (baseline.get("node_sequence") or [])]
        if detour:
            dx, dy = _node_xy(network, detour)
            ax_map.plot(dx, dy, linestyle="none", marker="o", markersize=7.5,
                        markerfacecolor="white", markeredgecolor=colour,
                        markeredgewidth=1.8, zorder=8)

    current = (baseline.get("node_sequence") or [0])[0]
    cx, cy = _node_xy(network, [current])
    ax_map.plot(cx, cy, marker="o", markersize=8.5, color=INK, zorder=9)
    ax_map.plot(cx, cy, marker="o", markersize=13, color=INK, alpha=0.18, zorder=8)
    ax_map.annotate(f"车当前位置\n{_short(network, _facility_of(network, current))}",
                    xy=(cx[0], cy[0]), xytext=(-6, -26), textcoords="offset points",
                    fontsize=5.6, color=INK, ha="center", zorder=10,
                    bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="#cbd5e1",
                              lw=0.5, alpha=0.92))

    ox, oy = _node_xy(network, [owner_node])
    ax_map.plot(ox, oy, linestyle="none", marker="o", markersize=10,
                markerfacecolor="none", markeredgecolor=COLOUR_ALERT,
                markeredgewidth=1.9, zorder=9)
    ax_map.annotate(f"报废货所属订单\n{_short(network, owner)}",
                    xy=(ox[0], oy[0]), xytext=(4, 16), textcoords="offset points",
                    fontsize=5.6, color=COLOUR_ALERT, ha="left", zorder=10,
                    bbox=dict(boxstyle="round,pad=0.22", fc="white",
                              ec=COLOUR_ALERT, lw=0.5, alpha=0.92))

    ax_map.set_title("改道前 vs 改道后（真实路网几何，来自后端）", fontsize=7.4,
                     color=INK, pad=5)
    ax_map.set_xticks([]); ax_map.set_yticks([])
    for side in ax_map.spines.values():
        side.set_color("#e2e8f0")
    ax_map.set_aspect(1.0 / 0.62)
    ax_map.margins(x=0.02, y=0.02)

    # ---- summary table ------------------------------------------------------
    ax_table = fig.add_subplot(grid[0, 1])
    ax_table.axis("off")
    ax_table.set_xlim(0, 1); ax_table.set_ylim(0, 1)
    ax_table.set_title("每种处置方案的代价（实测）", fontsize=7.4, color=INK,
                       pad=9, y=1.02)

    rows = []
    for summary in summaries:
        label = KIND_LABELS.get(summary["kind"], summary["kind"])
        pickup = (f"\n先到 {_short(network, summary['pickup'])}"
                  if summary["pickup"] else "")
        rows.append((label + pickup, summary))

    y = 0.86
    ax_table.text(0.0, 1.0, "方案", fontsize=5.9, color=MUTED, weight="bold", va="top")
    ax_table.text(0.50, 1.0, "多跑", fontsize=5.9, color=MUTED, weight="bold",
                  ha="right", va="top")
    ax_table.text(0.74, 1.0, "受影响", fontsize=5.9, color=MUTED,
                  weight="bold", ha="right", va="top")
    ax_table.text(1.0, 1.0, "最多迟", fontsize=5.9, color=MUTED,
                  weight="bold", ha="right", va="top")
    ax_table.plot([0.0, 1.0], [0.955, 0.955], color="#e2e8f0", linewidth=0.6)

    for label, summary in rows:
        colour = colour_for[(summary["kind"], summary["vehicle"])]
        ax_table.text(0.0, y, label, fontsize=6.1, color=INK, va="top",
                      linespacing=1.5)
        ax_table.text(0.50, y, f"+{summary['added_km']:.1f} km", fontsize=6.8,
                      color=colour, ha="right", va="top", weight="bold")
        ax_table.text(0.74, y, f"{summary['affected']} 单", fontsize=6.2,
                      color=INK, ha="right", va="top")
        ax_table.text(1.0, y, f"{summary['max_delay']:.0f} min", fontsize=6.8,
                      color=COLOUR_ALERT if summary["max_delay"] > 0 else "#15803d",
                      ha="right", va="top", weight="bold")
        y -= 0.20
        if (label, summary) != rows[-1]:
            ax_table.plot([0.0, 1.0], [y + 0.085, y + 0.085], color="#eef2f7",
                          linewidth=0.5)

    best, worst = summaries[0], summaries[-1]
    saving = worst["added_km"] - best["added_km"]
    verdict = (f"「{_plain_kind(best['kind'])}」比\n「{_plain_kind(worst['kind'])}」少跑 {saving:.1f} km"
               + (f"，且不让任何\n订单多等 {worst['max_delay']:.0f} 分钟。"
                  if worst["max_delay"] > 0 else "。"))
    ax_table.text(0.0, y + 0.055, verdict, fontsize=5.9, color=MUTED, va="top",
                  linespacing=1.55)

    legend = [Line2D([], [], color=COLOUR_BEFORE, linewidth=3.0,
                     linestyle=(0, (4, 2)), label="改道前（原计划）"),
              Line2D([], [], color=COLOUR_BEST, linewidth=2.0,
                     label=f"最省方案（{_plain_kind(best['kind'])}）")]
    if len(summaries) > 1:
        legend.append(Line2D([], [], color=COLOUR_WORST, linewidth=2.0,
                             label=f"最贵方案（{_plain_kind(worst['kind'])}）"))
    legend.append(Line2D([], [], color="none", marker="o", markersize=6,
                         markerfacecolor="white", markeredgecolor=MUTED,
                         markeredgewidth=1.6, label="方案新增的绕行节点"))
    ax_table.legend(handles=legend, loc="lower left", bbox_to_anchor=(-0.02, -0.02),
                    fontsize=5.3, frameon=False, handlelength=2.2,
                    labelspacing=0.5, borderaxespad=0.0)

    fig.suptitle(f"扰动前后对比：一次报废补发，对比最省与最贵的两条走法"
                 f"（后端共给出 {len(preview['candidates'])} 个候选）",
                 fontsize=9.0, color=INK, weight="bold", y=0.985)
    fig.text(0.05, 0.915,
             f"数据来源：真实 API 驱动（{scenario['case']['run_id']}，"
             f"{scenario['case']['disposition']}）· 货源与路线由后端导出 · "
             f"生成于 {datetime.date.today().isoformat()}",
             fontsize=5.6, color=MUTED)
    fig.text(0.05, 0.035,
             "口径：里程为路网静态距离，含空驶与收尾段；受影响订单的 ETA 不计每站装卸停留。"
             "详见 docs/C_配送模块.md §4.3。",
             fontsize=5.3, color=MUTED)

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for suffix in ("png", "svg"):
        path = out_dir / f"dispatch_disruption_comparison.{suffix}"
        fig.savefig(path, format=suffix, facecolor="white")
        written.append(path)
    plt.close(fig)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--hospitals", type=int, default=5)
    parser.add_argument("--tick-seconds", type=float, default=2.5,
                        help="real seconds between clock ticks while advancing time")
    parser.add_argument("--out-dir", type=Path,
                        default=REPO_ROOT / "docs" / "figures")
    parser.add_argument("--dump-json", type=Path, default=None,
                        help="also write the raw API responses, for auditing")
    args = parser.parse_args()

    # Never touch the repository's own state: the case log and the dispatch
    # database go to temporary files, exactly as the test suite does.
    dispatch_db = tempfile.mktemp(suffix=".sqlite3")
    runs_file = Path(tempfile.mktemp(suffix=".jsonl"))

    print("driving the real API: daily batch → depart → advance → close → preview")
    scenario = build_scenario(seed=args.seed, hospitals=args.hospitals,
                              tick_seconds=args.tick_seconds,
                              dispatch_db=dispatch_db, runs_file=runs_file)

    if args.dump_json:
        args.dump_json.write_text(
            json.dumps({"case": scenario["case"], "preview": scenario["preview"],
                        "target": scenario["target"]},
                       ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"raw responses → {args.dump_json}")

    written = draw(scenario, args.out_dir)
    for path in written:
        print(f"figure → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
