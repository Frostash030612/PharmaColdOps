#!/usr/bin/env python
"""Export REAL downloaded data into the demo's JS data blocks.

Reads the datasets under ``data/`` and emits a self-contained JS snippet
(``frontend/real_data.js``) that ``frontend/index.html`` / ``frontend/index-zh.html`` load:

  * ``SCENARIOS``  — real temperature-excursion events (from the
    Kaggle ``vaccine-distribution-with-temperature-logging`` dataset), mapped
    to the rule engine's input schema and product classes.
  * ``DEPOT`` / ``PHARMACIES`` / ``ROUTES`` — a real Solomon VRPTW instance
    (``data/optimisation/solomon/c101.json``): real customer coordinates,
    demands and time windows, plus two routes (baseline id-order vs a greedy
    nearest-neighbour) with real Euclidean distance and real time-window
    violations.

Honesty notes (also printed in the generated file):
  * ``mkt_c`` is approximated from the single ``thermal_shipper_temp_reading``
    (the source has no MKT column); a true MKT needs the full time series.
  * ``packaging`` is not in the source dataset, so it is fixed to ``intact``.
  * ``stage`` is mapped from the real ``current_hop`` column.
  * Product class is inferred from the temperature band (the source has no
    ``product_id``).

Usage:  python scripts/export_demo_data.py [--out frontend/real_data.js]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rule_engine.engine import RuleEngine  # noqa: E402
from rule_engine.models import ExcursionEvent  # noqa: E402

VACCINE_CSV = ROOT / "data" / "ml" / "vaccine-distribution-temperature" / "input_data.csv"
SOLOMON_JSON = ROOT / "data" / "optimisation" / "solomon" / "c101.json"

# --------------------------------------------------------------------------- #
# stage mapping: real current_hop -> demo stage
# --------------------------------------------------------------------------- #
STAGE_MAP = {
    "air_transit": "airport_dwell",
    "dest_air_cargo": "airport_dwell",
    "source_air_cargo": "airport_dwell",
    "last_mile": "last_mile",
    "dest_reefer_truck": "transit",
    "source_reefer truck": "transit",
    "local_transport": "transit",
    "source_hub": "warehouse",
    "dest_vaccine_storage_unit": "warehouse",
    "dest_discarded_vaccine_storage_unit": "warehouse",
    "immunization_site": "warehouse",
}


def classify_product(temp_c: float) -> str:
    """Infer a product class from the temperature band (source has no product_id)."""
    if temp_c <= -60.0:
        return "mrna_ultracold"   # deep-freeze, in band for -90..-60
    if temp_c < -15.0:
        return "mrna_ultracold"   # thawed above -60
    if temp_c < 2.0:
        return "frozen_m20"       # frozen product thawing above -15
    if temp_c <= 8.0:
        return "vaccine_2_8"      # in band for 2..8
    return "vaccine_2_8"          # warm excursion


def is_in_band(product: str, temp_c: float) -> bool:
    """True when the temperature is inside the product's storage band."""
    if product == "mrna_ultracold":
        return temp_c <= -60.0
    if product == "frozen_m20":
        return -25.0 <= temp_c <= -15.0
    if product == "vaccine_2_8":
        return 2.0 <= temp_c <= 8.0
    return False


def load_events() -> list[dict]:
    with VACCINE_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    events = []
    for r in rows:
        temp = float(r["thermal_shipper_temp_reading"])
        if temp > 15.0 or temp < -90.0:
            continue  # outside any modelled product band
        product = classify_product(temp)
        oob_h = float(r["out_of_bound_temperature_hours"])
        duration = 0 if is_in_band(product, temp) else int(round(oob_h * 60.0))
        events.append({
            "product": product,
            "temp_c": round(temp, 1),
            "duration_min": duration,
            "mkt_c": round(temp, 1),  # approximation — see honesty note
            "stage": STAGE_MAP.get(r["current_hop"], "transit"),
            "packaging": "intact",    # not in source
            "hop": r["current_hop"],
            "location": r["location"],
            "batch_id": r["batch_id"],
        })
    return events


def pick_diverse(events: list[dict], n: int = 18) -> list[dict]:
    """Deterministically pick a spread across product classes + severity."""
    buckets = {
        "vaccine_warm": [e for e in events if e["product"] == "vaccine_2_8" and not is_in_band("vaccine_2_8", e["temp_c"])],
        "vaccine_ok": [e for e in events if e["product"] == "vaccine_2_8" and is_in_band("vaccine_2_8", e["temp_c"])],
        "frozen_thaw": [e for e in events if e["product"] == "frozen_m20"],
        "mrna_thaw": [e for e in events if e["product"] == "mrna_ultracold" and not is_in_band("mrna_ultracold", e["temp_c"])],
        "mrna_ok": [e for e in events if e["product"] == "mrna_ultracold" and is_in_band("mrna_ultracold", e["temp_c"])],
    }
    # take every k-th so the sample stays deterministic and spread out
    picks = []
    for key, want in [
        ("vaccine_warm", 5),
        ("vaccine_ok", 4),
        ("frozen_thaw", 3),
        ("mrna_thaw", 3),
        ("mrna_ok", 3),
    ]:
        pool = buckets[key]
        k = max(1, len(pool) // want)
        picks.extend(pool[::k][:want])
    return picks


def fmt_min_to_hm(mins: int) -> str:
    h, m = divmod(int(round(mins)), 60)
    return f"{h:02d}:{m:02d}"


# --------------------------------------------------------------------------- #
# Solomon VRPTW -> demo routing data
# --------------------------------------------------------------------------- #
def load_solomon(n_customers: int = 10) -> dict:
    d = json.loads(SOLOMON_JSON.read_text(encoding="utf-8"))
    customers = d["customers"]
    depot = next(c for c in customers if c["id"] == 0)
    others = [c for c in customers if c["id"] != 0]
    k = max(1, len(others) // n_customers)  # sample across clusters, not just the first few
    others = others[::k][:n_customers]

    # scale Solomon 0..100 grid into the demo's 360x210 viewBox
    def sx(x):
        return round(40 + float(x) * 2.6, 1)

    def sy(y):
        return round(20 + float(y) * 1.7, 1)

    pharmacies = []
    for c in others:
        pharmacies.append({
            "id": str(c["id"]),
            "label": f"C{c['id']}",
            "name": f"Customer {c['id']}",
            "tw": f"{fmt_min_to_hm(c['earliest'])}–{fmt_min_to_hm(c['latest'])}",
            "demand": int(c["demand"]),
            "x": sx(c["x"]),
            "y": sy(c["y"]),
            "service": int(c["cost"]),
            "earliest": int(c["earliest"]),
            "latest": int(c["latest"]),
            "gx": float(c["x"]),
            "gy": float(c["y"]),
        })

    return {
        "depot": {"x": sx(depot["x"]), "y": sy(depot["y"]), "gx": float(depot["x"]), "gy": float(depot["y"])},
        "pharmacies": pharmacies,
    }


def route_metrics(order_ids: list[str], depot: dict, pharm: dict) -> dict:
    """Real Euclidean distance + real time-window violations for a given order."""
    coords = {"depot": depot, **{p["id"]: p for p in pharm}}
    # travel time = distance (Solomon convention: speed = 1, minutes)
    total_dist = 0.0
    t = 0.0
    viol = 0
    prev = depot
    for pid in order_ids:
        p = coords[pid]
        d = math.hypot(p["gx"] - prev["gx"], p["gy"] - prev["gy"])
        total_dist += d
        t += d
        if t < p["earliest"]:
            t = p["earliest"]  # wait
        if t > p["latest"]:
            viol += 1
        t += p["service"]
        prev = p
    # return to depot
    d = math.hypot(depot["gx"] - prev["gx"], depot["gy"] - prev["gy"])
    total_dist += d
    return {"dist": round(total_dist, 0), "viol": viol}


def _edge(a: dict, b: dict) -> float:
    return math.hypot(a["gx"] - b["gx"], a["gy"] - b["gy"])


def tour_length(order: list[dict], depot: dict) -> float:
    prev = depot
    total = 0.0
    for p in order:
        total += _edge(prev, p)
        prev = p
    return total + _edge(prev, depot)


def two_opt(order: list[dict], depot: dict) -> list[dict]:
    """Simple 2-opt local search: reverse segments to shorten the tour."""
    best = list(order)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + list(reversed(best[i:j + 1])) + best[j + 1:]
                if tour_length(cand, depot) < tour_length(best, depot) - 1e-9:
                    best = cand
                    improved = True
    return best


def greedy_nn(depot: dict, pharm: list[dict]) -> list[dict]:
    order, current = [], depot
    remaining = dict((p["id"], p) for p in pharm)
    while remaining:
        nxt = min(remaining.values(), key=lambda p: _edge(current, p))
        order.append(nxt)
        current = nxt
        del remaining[nxt["id"]]
    return order


def build_routes(depot: dict, pharm: list[dict]) -> dict:
    original = [p for p in pharm]                              # id order (naive baseline)
    optimized = two_opt(greedy_nn(depot, pharm), depot)        # NN + 2-opt
    m_orig = route_metrics([p["id"] for p in original], depot, pharm)
    m_opt = route_metrics([p["id"] for p in optimized], depot, pharm)
    return {
        "optimized": {
            "order": [p["id"] for p in optimized], "dist": f"{m_opt['dist']:g} units",
            "time": f"{round(m_opt['dist']/60, 1):g} h", "cost": f"${m_opt['dist']*1.5:,.0f}",
            "viol": m_opt["viol"], "violNote": f"{m_opt['viol']} time-window miss(es)" if m_opt["viol"] else "",
        },
        "original": {
            "order": [p["id"] for p in original], "dist": f"{m_orig['dist']:g} units",
            "time": f"{round(m_orig['dist']/60, 1):g} h", "cost": f"${m_orig['dist']*1.5:,.0f}",
            "viol": m_orig["viol"], "violNote": f"{m_orig['viol']} time-window miss(es)" if m_orig["viol"] else "",
        },
    }


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def render() -> str:
    engine = RuleEngine()
    events = pick_diverse(load_events())

    lines = [
        "// AUTO-GENERATED by scripts/export_demo_data.py — real data from the downloaded datasets.",
        "// Source: data/ml/vaccine-distribution-temperature/input_data.csv (Kaggle) and",
        "//         data/optimisation/solomon/c101.json (Solomon VRPTW).",
        "// mkt_c is approximated from the single temp reading; packaging fixed to 'intact'.",
        "",
        "const SCENARIOS = [",
    ]
    for i, e in enumerate(events, 1):
        ev = ExcursionEvent(
            scenario_id=f"R{i:02d}", product_id=e["product"],
            excursion_temp_c=e["temp_c"], duration_min=e["duration_min"], mkt_c=e["mkt_c"],
            packaging=e["packaging"], stage=e["stage"],
        )
        disp = engine.evaluate(ev).disposition.value
        lines.append(
            f'  {{ id: "R{i:02d}", product_id: "{ev.product_id}", excursion_temp_c: {e["temp_c"]}, '
            f'duration_min: {e["duration_min"]}, mkt_c: {e["mkt_c"]}, packaging: "intact", '
            f'stage: "{e["stage"]}" }},  // {e["location"]} · {e["hop"]} → {disp}'
        )
    lines.append("];")

    sol = load_solomon()
    lines.append("")
    lines.append(f"const DEPOT = {{ x: {sol['depot']['x']}, y: {sol['depot']['y']} }};")
    lines.append("const PHARMACIES = [")
    for p in sol["pharmacies"]:
        lines.append(
            f'  {{ id: "{p["id"]}", label: "{p["label"]}", name: "{p["name"]}", tw: "{p["tw"]}", '
            f'zone: "2–8 °C", demand: {p["demand"]}, x: {p["x"]}, y: {p["y"]} }},'
        )
    lines.append("];")

    routes = build_routes(sol["depot"], sol["pharmacies"])
    lines.append("")
    lines.append("const ROUTES = {")
    lines.append(f'  optimized: {{ order: {json.dumps(routes["optimized"]["order"])}, dist: "{routes["optimized"]["dist"]}", time: "{routes["optimized"]["time"]}", cost: "{routes["optimized"]["cost"]}", viol: {routes["optimized"]["viol"]}, violNote: "{routes["optimized"]["violNote"]}" }},')
    lines.append(f'  original:  {{ order: {json.dumps(routes["original"]["order"])}, dist: "{routes["original"]["dist"]}", time: "{routes["original"]["time"]}", cost: "{routes["original"]["cost"]}", viol: {routes["original"]["viol"]}, violNote: "{routes["original"]["violNote"]}" }},')
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "frontend" / "real_data.js"))
    args = ap.parse_args()
    js = render()
    Path(args.out).write_text(js + "\n", encoding="utf-8")
    print(js)
    print(f"\n[wrote {args.out}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
