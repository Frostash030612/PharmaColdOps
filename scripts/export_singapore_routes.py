#!/usr/bin/env python
"""Solve Singapore matrices and export road GeoJSON and schedules offline."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from optimisation.singapore_loader import SINGAPORE_NETWORK_PATH, read_network, load_singapore_instance
from optimisation.singapore_export import routes_geojson
from optimisation.greedy import solve_greedy
from optimisation.ortools_solver import solve_ortools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', type=Path, default=SINGAPORE_NETWORK_PATH)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'data/processed/singapore')
    parser.add_argument('--time-limit', type=int, default=10)
    args = parser.parse_args()
    network = read_network(args.network)
    instance, leg = load_singapore_instance(args.network)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = [('greedy', solve_greedy(instance, leg_fn=leg)),
               ('ortools', solve_ortools(instance, leg_fn=leg, time_limit_seconds=args.time_limit))]
    for name, result in results:
        for suffix, data in [('geojson', routes_geojson(network, result)), ('json', asdict(result))]:
            (args.out_dir / f'{name}_routes.{suffix}').write_text(
                json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')
        print(name, json.dumps(asdict(result.metrics)), 'feasible=', result.feasible)


if __name__ == '__main__':
    main()
