#!/usr/bin/env python
"""Solve Singapore matrices and export road GeoJSON and schedules offline."""
import argparse
from dataclasses import asdict
import json
from datetime import datetime, timezone
import hashlib
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
    parser.add_argument('--frontend-out', type=Path, help='Optional compact Vue demo dataset')
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
    if args.frontend_out:
        payload = {
            'schema_version': 1, 'instance': instance.instance,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'network_sha256': hashlib.sha256(args.network.read_bytes()).hexdigest(),
            'time_limit_seconds': args.time_limit, 'nodes': network['nodes'],
            'provenance': network['provenance'], 'assumptions': network['assumptions'],
            'plans': {name: {**asdict(result), 'geojson': routes_geojson(network, result)}
                      for name, result in results},
        }
        args.frontend_out.parent.mkdir(parents=True, exist_ok=True)
        args.frontend_out.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                               separators=(',', ':')) + '\n', encoding='utf-8')
        print('Frontend dataset:', args.frontend_out)



if __name__ == '__main__':
    main()
