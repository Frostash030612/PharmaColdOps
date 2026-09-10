"""Export solved routes using cached road geometry, with no GIS dependency."""
from .models import ReplanResult


def routes_geojson(network: dict, result: ReplanResult) -> dict:
    features = []
    for route in result.routes:
        order = (0, *route.customer_ids, 0)
        coords = []
        for a, b in zip(order, order[1:]):
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
