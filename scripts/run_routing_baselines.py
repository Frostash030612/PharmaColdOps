#!/usr/bin/env python
"""Run C's W1 routing baselines and write reproducible Markdown results."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from optimisation.greedy import solve_greedy  # noqa: E402
from optimisation.ortools_solver import solve_ortools  # noqa: E402
from optimisation.solomon_loader import load_dir  # noqa: E402


def _row(result) -> str:
    m = result.metrics
    return (
        f"| {result.instance} | {result.algorithm} | {m.vehicles_used} | "
        f"{m.total_distance:.2f} | {m.total_duration:.2f} | "
        f"{m.on_time_rate:.1%} | {m.violation_count} | "
        f"{len(m.unserved_customer_ids)} |"
    )


def _table(results) -> list[str]:
    return [
        "| instance | algorithm | vehicles | distance | duration | on-time | violations | unserved |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
        *[_row(result) for result in results],
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--instances", nargs="*", default=None,
        help="instance labels; default: all six committed Solomon instances",
    )
    parser.add_argument(
        "--with-ortools", action="store_true",
        help="also run OR-Tools (normally use --instances c101 for W1)",
    )
    parser.add_argument("--time-limit", type=int, default=10)
    args = parser.parse_args()

    available = load_dir()
    labels = ([label.upper() for label in args.instances]
              if args.instances else sorted(available))
    unknown = sorted(set(labels) - set(available))
    if unknown:
        parser.error(f"unknown instances: {unknown}")

    greedy = [solve_greedy(available[label]) for label in labels]
    out_dir = ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    greedy_path = out_dir / "greedy_baseline.md"
    greedy_path.write_text("\n".join([
        "# Greedy VRPTW baseline",
        "",
        "Nearest-distance feasible insertion with hard capacity, customer time-window and depot-return checks.",
        "",
        *_table(greedy),
        "",
        "Reproduce: `python scripts/run_routing_baselines.py`",
        "",
    ]), encoding="utf-8")
    print("\n".join(_table(greedy)))
    print(f"\n[wrote {greedy_path}]")

    if args.with_ortools:
        optimized = [solve_ortools(
            available[label], time_limit_seconds=args.time_limit
        ) for label in labels]
        comparison = [item for pair in zip(greedy, optimized) for item in pair]
        compare_path = out_dir / "routing_comparison.md"
        compare_path.write_text("\n".join([
            "# Greedy vs OR-Tools VRPTW",
            "",
            f"OR-Tools time limit: `{args.time_limit}s` per instance.",
            "Distances are Solomon Euclidean units; time includes travel, waiting and service.",
            "",
            *_table(comparison),
            "",
        ]), encoding="utf-8")
        print("\n".join(["", *_table(optimized)]))
        print(f"\n[wrote {compare_path}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
