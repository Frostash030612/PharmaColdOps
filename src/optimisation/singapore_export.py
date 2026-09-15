"""Export solved routes using cached road geometry, with no GIS dependency."""
from .models import ReplanResult


def leg_geojson(network: dict, node_ids: list[int]) -> list[dict]:
    """One entry per consecutive pair of ``node_ids``, with its road polyline.

    The map needs the legs separately, not one merged line: a route drawn as a
    single stroke cannot show which part has already been driven. A pair of equal
    nodes (a branch order for a hospital already on the route) yields no leg —
    there is no road from a place to itself.
    """
    legs = []
    for a, b in zip(node_ids, node_ids[1:]):
        if a == b:
            continue
        segment = network['leg_geometry'].get(f'{a}:{b}')
        if not segment or len(segment) < 2:
            raise ValueError(f'missing road geometry for {a}:{b}')
        legs.append({'from': a, 'to': b, 'coords': segment})
    return legs


def sequence_distance_m(network: dict, node_ids: list[int]) -> float:
    """Road distance along ``node_ids``, from the committed matrix."""
    distance = network['matrix']['distance_m']
    return float(sum(distance[a][b] for a, b in zip(node_ids, node_ids[1:])))


def sequence_geojson(network: dict, node_ids: list[int], **properties) -> dict:
    """A single LineString through ``node_ids``, for overlaying one option."""
    coords: list = []
    for leg in leg_geojson(network, node_ids):
        coords.extend(leg['coords'] if not coords else leg['coords'][1:])
    return {'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {**properties, 'node_order': list(node_ids)}}


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
