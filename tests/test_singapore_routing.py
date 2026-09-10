"""Synthetic directed fixtures test mechanics; real OSM integration is separate."""
import json
import importlib.util
from pathlib import Path

import pytest

from optimisation.singapore_loader import load_singapore_instance, validate_network, SINGAPORE_NETWORK_PATH
from optimisation.singapore_export import routes_geojson
from optimisation.routing import evaluate_route
from optimisation.greedy import solve_greedy
from optimisation.ortools_solver import solve_ortools


@pytest.fixture
def network():
    return {'schema_version': 1, 'instance': 'SYNTHETIC_TEST', 'vehicle_nr': 2, 'capacity': 10,
            'nodes': [{'node_id': i, 'role': 'depot' if i == 0 else 'customer',
                       'lat': 1.3, 'lon': 103.8, 'demand': 0 if i == 0 else 4,
                       'earliest_min': 0 if i == 0 else 10, 'latest_min': 100,
                       'service_min': 0 if i == 0 else 2} for i in range(3)],
            'matrix': {'distance_m': [[0, 1000, 5000], [4000, 0, 2000], [3000, 6000, 0]],
                       'duration_s': [[0, 300, 1800], [240, 0, 420], [180, 1200, 0]]}}


def load(tmp_path, network):
    path = tmp_path / 'network.json'
    path.write_text(json.dumps(network))
    return load_singapore_instance(path)


def test_units_direction_waiting_service_and_return(tmp_path, network):
    instance, leg = load(tmp_path, network)
    assert leg(instance.nodes[0], instance.nodes[1]) == (1, 5)
    assert leg(instance.nodes[1], instance.nodes[0]) == (4, 4)
    route = evaluate_route(instance, [1, 2], leg_fn=leg)
    assert route.total_distance == 6
    assert route.duration == 24  # 5 drive + 5 wait + 2 service + 7 drive + 2 service + 3 return
    assert route.total_load == 8
    assert route.stops[1].arrival == 19
    assert route.feasible


@pytest.mark.parametrize('solver', [solve_greedy, solve_ortools])
def test_solvers_use_matrix_even_when_coordinates_are_zero(tmp_path, network, solver):
    instance, leg = load(tmp_path, network)
    kwargs = {'time_limit_seconds': 1} if solver is solve_ortools else {}
    result = solver(instance, leg_fn=leg, **kwargs)
    assert result.feasible
    assert result.metrics.served_customers == 2
    assert result.metrics.total_distance > 0
    for route in result.routes:
        assert route == evaluate_route(instance, route.customer_ids, vehicle_id=route.vehicle_id, leg_fn=leg)


@pytest.mark.parametrize('mutation', [
    lambda n: n['matrix']['distance_m'].pop(),
    lambda n: n['matrix']['duration_s'][0].pop(),
    lambda n: n['matrix']['duration_s'][0].__setitem__(1, float('inf')),
    lambda n: n['matrix']['distance_m'][0].__setitem__(1, -1),
    lambda n: n['matrix']['duration_s'][0].__setitem__(0, 1),
    lambda n: n['nodes'][0].__setitem__('demand', 1),
    lambda n: n['nodes'][1].__setitem__('node_id', 5),
    lambda n: n['nodes'][1].__setitem__('earliest_min', 101),
    lambda n: n.__setitem__('capacity', 0),
    lambda n: n['nodes'][1].__setitem__('service_min', -1),
])
def test_invalid_network_rejected(network, mutation):
    mutation(network)
    with pytest.raises(ValueError, match='fixture.json'):
        validate_network(network, 'fixture.json')


def test_geojson_closed_tour_and_disconnection(tmp_path, network):
    instance, leg = load(tmp_path, network)
    points = [[103.8, 1.3], [103.81, 1.31], [103.82, 1.32]]
    network['leg_geometry'] = {f'{i}:{j}': [points[i], points[j]] for i in range(3) for j in range(3) if i != j}
    result = solve_greedy(instance, leg_fn=leg)
    geojson = routes_geojson(network, result)
    coords = geojson['features'][0]['geometry']['coordinates']
    assert coords[0] == coords[-1] == points[0]
    for segment in network['leg_geometry'].values():
        segment[0] = [0, 0]
    with pytest.raises(ValueError, match='disconnected'):
        routes_geojson(network, result)


def test_builder_uses_fastest_path_edges_for_both_metrics():
    nx = pytest.importorskip('networkx')
    path = Path(__file__).resolve().parents[1] / 'scripts/build_singapore_network.py'
    spec = importlib.util.spec_from_file_location('sg_builder', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    graph = nx.MultiDiGraph()
    for i in range(3):
        graph.add_node(i, x=103.8+i*.01, y=1.3)
    graph.add_edge(0, 1, length=10, travel_time=100)
    graph.add_edge(0, 1, length=50, travel_time=20)
    graph.add_edge(0, 2, length=100, travel_time=1)
    graph.add_edge(2, 1, length=100, travel_time=1)
    graph.add_edge(1, 0, length=80, travel_time=8)
    matrix, geom = module.matrix_from_graph(graph, [{'osm_node': 0, 'name': 'A'}, {'osm_node': 1, 'name': 'B'}])
    assert matrix['distance_m'][0][1] == 200
    assert matrix['duration_s'][0][1] == 2
    assert matrix['distance_m'][1][0] == 80
    assert len(geom['0:1']) == 3
    graph.remove_edge(1, 0)
    with pytest.raises(ValueError, match='Unreachable'):
        module.matrix_from_graph(graph, [{'osm_node': 0, 'name': 'A'}, {'osm_node': 1, 'name': 'B'}])


@pytest.mark.skipif(not SINGAPORE_NETWORK_PATH.exists(), reason='Real OSM network not yet generated; run build_singapore_network.py online')
def test_real_network():
    instance, leg = load_singapore_instance()
    for result in (solve_greedy(instance, leg_fn=leg), solve_ortools(instance, leg_fn=leg, time_limit_seconds=2)):
        assert result.metrics.served_customers + len(result.metrics.unserved_customer_ids) == instance.n_customers
        # Wide-window demonstration is intentionally feasible, unlike arbitrary input.
        assert result.feasible
