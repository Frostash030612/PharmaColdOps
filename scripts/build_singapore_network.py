#!/usr/bin/env python
"""Build real OSM road matrices once; downstream solvers/export are offline.

Requires OSMnx only at build time. Cache is ignored by git. No unreachable leg
or synthetic fallback is written. Every leg uses one fastest directed path.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from optimisation.singapore_loader import validate_network


def matrix_from_graph(graph, nodes):
    """Use exactly the same multigraph edges for costs and full road geometry."""
    import networkx as nx
    n = len(nodes)
    distances = [[0.0] * n for _ in nodes]
    durations = [[0.0] * n for _ in nodes]
    geometries = {}
    for i, origin in enumerate(nodes):
        _, paths = nx.single_source_dijkstra(graph, origin['osm_node'], weight='travel_time')
        for j, target in enumerate(nodes):
            if i == j:
                continue
            if target['osm_node'] not in paths:
                raise ValueError(f"Unreachable: {origin['name']} -> {target['name']}")
            path = paths[target['osm_node']]
            coords = []
            for u, v in zip(path, path[1:]):
                edge = min(graph[u][v].values(), key=lambda e: e['travel_time'])
                distances[i][j] += float(edge['length'])
                durations[i][j] += float(edge['travel_time'])
                start = [float(graph.nodes[u]['x']), float(graph.nodes[u]['y'])]
                end = [float(graph.nodes[v]['x']), float(graph.nodes[v]['y'])]
                segment = ([list(c[:2]) for c in edge['geometry'].coords]
                           if 'geometry' in edge else [start, end])
                # Some graph sources store geometry in reverse orientation.
                if sum((segment[-1][k]-start[k])**2 for k in (0, 1)) < sum((segment[0][k]-start[k])**2 for k in (0, 1)):
                    segment.reverse()
                coords.extend(segment if not coords else segment[1:])
            if not coords:
                p = graph.nodes[origin['osm_node']]
                coords = [[float(p['x']), float(p['y'])]] * 2
            geometries[f'{i}:{j}'] = coords
        print(f'Computed paths from {i + 1}/{n}: {origin["name"]}', flush=True)
    return {'distance_m': distances, 'duration_s': durations}, geometries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facilities', type=Path, default=ROOT / 'data/optimisation/singapore/facilities.json')
    parser.add_argument('--out', type=Path, default=ROOT / 'data/optimisation/singapore/network.json')
    parser.add_argument('--overpass-url', default='https://overpass-api.de/api')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'data/processed/singapore_cache')
    args = parser.parse_args()
    import osmnx as ox
    config_bytes = args.facilities.read_bytes()
    config = json.loads(config_bytes)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    ox.settings.cache_folder = args.cache_dir / 'http'
    ox.settings.use_cache = True
    ox.settings.requests_timeout = 180
    ox.settings.log_console = True
    ox.settings.overpass_url = args.overpass_url
    ox.settings.max_query_area_size = 500_000_000
    ox.settings.http_user_agent = 'PharmaColdOps academic road-network build (OSMnx)'
    graph_path = args.cache_dir / 'singapore_drive.graphml'
    if graph_path.exists():
        print('Loading cached drive graph', flush=True)
        graph = ox.io.load_graphml(graph_path)
    else:
        print('Downloading Singapore drive graph (may take several minutes)', flush=True)
        graph = ox.graph.graph_from_place('Singapore', network_type='drive')
        graph = ox.routing.add_edge_speeds(graph, fallback=30)
        graph = ox.routing.add_edge_travel_times(graph)
        graph.graph['built_at_utc'] = datetime.now(timezone.utc).isoformat()
        ox.io.save_graphml(graph, graph_path)
    print(f'Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges', flush=True)
    nodes = []
    import time
    for idx, facility in enumerate(config['nodes']):
        print(f'Geocoding {facility["name"]}', flush=True)
        match = ox.geocoder.geocode_to_gdf(facility['query'], which_result=1).iloc[0]
        lat, lon = float(match['lat']), float(match['lon'])
        expected_name = facility['name'].lower().replace('’', "'")
        matched_name = str(match['display_name']).split(',')[0].lower().replace('’', "'")
        if facility['role'] == 'customer' and (match['type'] != 'hospital' or expected_name not in matched_name):
            raise ValueError(f'Expected hospital, got {match["type"]}: {match["display_name"]}')
        if not (1.1 <= lat <= 1.5 and 103.5 <= lon <= 104.2):
            raise ValueError(f'Geocoder result outside Singapore: {facility["name"]}')
        # Projected nearest_nodes uses scipy KDTree, not optional scikit-learn.
        # Graph coordinates are unprojected; small facility count permits an
        # exact great-circle scan without adding another runtime dependency.
        ids = list(graph.nodes)
        distances = ox.distance.great_circle(lat, lon,
            [graph.nodes[k]['y'] for k in ids], [graph.nodes[k]['x'] for k in ids])
        nearest = int(distances.argmin())
        snap_m = float(distances[nearest])
        if snap_m > 1000:
            raise ValueError(f'{facility["name"]}: road snap too far ({snap_m:.0f}m)')
        nodes.append({**facility, 'node_id': idx, 'lat': lat, 'lon': lon,
                      'osm_node': int(ids[nearest]), 'snap_distance_m': snap_m,
                      'geocoder_display_name': str(match['display_name']),
                      'geocoder_type': str(match['type'])})
        time.sleep(1.1)  # respect public Nominatim's one-request/second limit
    matrix, geometry = matrix_from_graph(graph, nodes)
    output = {**config, 'schema_version': 1, 'nodes': nodes, 'matrix': matrix,
              'leg_geometry': geometry, 'generated_at': datetime.now(timezone.utc).isoformat(),
              'provenance': {'source': 'OpenStreetMap via OSMnx / Overpass / Nominatim',
                'attribution': '© OpenStreetMap contributors',
                'license_url': 'https://www.openstreetmap.org/copyright',
                'osmnx_version': ox.__version__, 'path_weight': 'travel_time',
                'graph_built_at': graph.graph.get('built_at_utc'),
                'graph_nodes': len(graph.nodes), 'graph_edges': len(graph.edges),
                'facilities_sha256': hashlib.sha256(config_bytes).hexdigest(),
                'speed_fallback_kph': 30,
                'travel_time_model': 'free-flow speed estimates, not live traffic',
                'scope': 'OSM drive graph, largest weak component; not all private roads or truck restrictions'}}
    validate_network(output, str(args.out))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix('.tmp')
    temporary.write_text(json.dumps(output, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temporary.replace(args.out)
    print(f'Wrote {args.out}', flush=True)


if __name__ == '__main__':
    main()
