"""Export solved routes using cached road geometry, with no GIS dependency."""
from .models import ReplanResult


def sequences_geojson(network: dict, sequences: dict[str, list[int]]) -> dict:
    """Road geometry for depot→…→depot, from plain per-vehicle node sequences.

    ``routes_geojson`` below draws a freshly solved ``ReplanResult``; this draws
    what the *live dispatch state* says each vehicle still has to do, so the map
    shows the operation actually in progress rather than a detached re-solve.
    """
    features = []
    for vehicle_id, node_ids in sorted(sequences.items()):
        if not node_ids:
            continue
        order = (0, *node_ids, 0)
        coords: list = []
        for a, b in zip(order, order[1:]):
            if a == b:
                # The same node twice in a row — a branch order for a hospital
                # that is already on this route. There is no road from a place
                # to itself, so there is no segment to draw; the stop itself is
                # still on the route (see the stop list, not the polyline).
                continue
            segment = network['leg_geometry'][f'{a}:{b}']
            if len(segment) < 2:
                raise ValueError(f'missing road geometry for {a}:{b}')
            coords.extend(segment if not coords else segment[1:])
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {'vehicle_id': vehicle_id, 'node_order': list(order)},
        })
    return {
        'type': 'FeatureCollection', 'features': features,
        'attribution': network.get('provenance', {}).get('attribution', ''),
    }


def routes_geojson(network: dict, result: ReplanResult) -> dict:
    features = []
    for route in result.routes:
        order = (0, *route.customer_ids, 0)
        coords = []
        for a, b in zip(order, order[1:]):
            if a == b:
                continue          # zero-length leg: no geometry to draw
            segment = network['leg_geometry'][f'{a}:{b}']
            if len(segment) < 2:
                raise ValueError(f'missing road geometry for {a}:{b}')
            if coords and coords[-1] != segment[0]:
                raise ValueError(f'disconnected road geometry for {a}:{b}')
            coords.extend(segment if not coords else segment[1:])
        features.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coords},
                         'properties': {'vehicle_id': route.vehicle_id, 'algorithm': result.algorithm,
                                        'node_order': list(order), 'distance_km': route.total_distance,
                                        'duration_min': route.duration, 'load': route.total_load,
                                        'feasible': route.feasible}})
    return {'type': 'FeatureCollection', 'features': features,
            'attribution': network.get('provenance', {}).get('attribution', ''),
            'instance': result.instance, 'feasible': result.feasible,
            'unserved_customer_ids': list(result.metrics.unserved_customer_ids)}
