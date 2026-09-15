"""Branch events attach to the day's plan, and the operator picks how.

The HTTP contract behind the comparison card (``docs/C_配送模块.md`` §4.2, §4.4-2,
§5 D1, §5 D3): a closed case is previewed read-only, every candidate is offered
with its distance / ETA / knock-on delays, the operator's explicit choice is then
committed, and with no open daily plan the branch is refused with 409 rather than
quietly promoted into an operation of its own.
"""
import tempfile

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from optimisation.singapore_loader import read_network

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_dispatch_db(monkeypatch):
    monkeypatch.setattr(
        service, "DISPATCH_DATABASE_URL", tempfile.mktemp(suffix=".sqlite3"))


def case(run_id="R1", *, destination="H-NUH", product="vaccine_2_8"):
    return {
        "run_id": run_id, "created_at": "2026-09-12T09:30:00",
        "disposition": "scrap", "reshipment_required": True,
        "event": {"product_id": product, "excursion_temp_c": 20.0,
                  "duration_min": 90, "mkt_c": 19.0, "packaging": "intact",
                  "stage": "transit", "destination_facility_id": destination},
    }


@pytest.fixture
def closed_case(monkeypatch):
    """Stand in for a case already archived by /api/case_close."""
    def _use(**kwargs):
        record = case(**kwargs)
        monkeypatch.setattr(service, "find_run", lambda run_id: (
            record if run_id == record["run_id"] else None))
        return record
    return _use


def _create_plan(dispatch_id="PLAN-API-1", *, hospitals=2, seed=3):
    batch = client.get(
        f"/api/dispatch/daily-orders?hospitals={hospitals}&seed={seed}").json()["plan"]
    response = client.post("/api/dispatch/runs", json={
        **batch, "dispatch_id": dispatch_id, "command_id": f"create-{dispatch_id}"})
    assert response.status_code == 200
    return response.json()


def test_a_branch_preview_without_a_days_plan_answers_409(closed_case):
    closed_case()
    response = client.post("/api/dispatch/reshipments/preview", json={"run_id": "R1"})

    assert response.status_code == 409
    assert "daily delivery plan" in response.json()["detail"]


def test_a_branch_commit_without_a_days_plan_answers_409(closed_case):
    closed_case()
    response = client.post("/api/dispatch/reshipments", json={"run_id": "R1"})

    assert response.status_code == 409
    assert service.latest_dispatch_id(service.DISPATCH_DATABASE_URL) is None


def test_preview_offers_the_options_and_the_commit_applies_the_chosen_one(closed_case):
    _create_plan()
    closed_case()
    preview = client.post("/api/dispatch/reshipments/preview",
                          json={"run_id": "R1", "policy": "minimize_vehicles"})

    assert preview.status_code == 200
    body = preview.json()
    assert body["dispatch_id"] == "PLAN-API-1"
    assert body["policy"] == "minimize_vehicles"     # the policy is echoed back
    assert body["order"]["destination_facility_id"] == "H-NUH"
    assert body["candidates"], "a two-hospital plan must leave at least one option"
    for candidate in body["candidates"]:
        assert {"kind", "vehicle_id", "eta_min", "on_time", "distance_m",
                "affected_orders", "starts_new_vehicle"} <= set(candidate)

    chosen = body["selected_candidate"]
    committed = client.post("/api/dispatch/reshipments", json={
        "run_id": "R1", "candidate_kind": chosen["kind"],
        "vehicle_id": chosen["vehicle_id"]})

    assert committed.status_code == 200
    result = committed.json()
    assert result["inserted"] is True
    assert result["candidate_kind"] == chosen["kind"]
    assert result["vehicle_id"] == chosen["vehicle_id"]
    assert result["dispatch_id"] == "PLAN-API-1"
    assert "RO-R1" in result["orders"]


def test_an_unknown_policy_is_rejected_at_the_api_boundary(closed_case):
    _create_plan()
    closed_case()
    response = client.post("/api/dispatch/reshipments/preview",
                           json={"run_id": "R1", "policy": "cheapest"})

    assert response.status_code == 422


def _complete(dispatch_id, created):
    """Depart and deliver every order of ``created`` until the run is finished."""
    assert client.post(f"/api/dispatch/runs/{dispatch_id}/depart",
                       json={"command_id": f"depart-{dispatch_id}"}).status_code == 200
    for order_id, order in created["orders"].items():
        client.post(f"/api/dispatch/runs/{dispatch_id}/deliver-next",
                    json={"vehicle_id": order["vehicle_id"],
                          "command_id": f"deliver-{order_id}"})


def test_a_branch_order_for_a_stop_already_on_the_route_keeps_the_view_alive(closed_case):
    """Found by driving the live API, not by a unit test.

    A resupply for a hospital that is ALREADY on today's route is normal — that
    is exactly what an excursion at a scheduled stop looks like. It leaves the
    vehicle's queue holding that node twice in a row, and the track builder then
    looked up a leg from the node to itself (``"2:2"``), which the committed
    network does not store: the response failed with a 500 and the map, the stop
    list and the delivery all became unreachable at once.
    """
    created = _create_plan("PLAN-REPEAT", hospitals=1)
    destination = next(iter(created["orders"].values()))["destination_facility_id"]
    closed_case(destination=destination)
    assert client.post("/api/dispatch/runs/PLAN-REPEAT/depart",
                       json={"command_id": "depart"}).status_code == 200

    preview = client.post("/api/dispatch/reshipments/preview", json={"run_id": "R1"})
    assert preview.status_code == 200
    # A same-product spare is on board the rolling truck, so serving the branch
    # from it is available — and is the option that creates the repeated stop.
    kinds = {item["kind"]: item for item in preview.json()["candidates"]}
    assert "add_stop_in_transit" in kinds

    committed = client.post("/api/dispatch/reshipments", json={
        "run_id": "R1", "candidate_kind": "add_stop_in_transit",
        "vehicle_id": kinds["add_stop_in_transit"]["vehicle_id"]})

    assert committed.status_code == 200
    body = committed.json()
    assert body["candidate_kind"] == "add_stop_in_transit"
    route = next(r for r in body["route_view"]["routes"]
                 if r["vehicle_id"] == body["vehicle_id"])
    order_ids = [stop["order_id"] for stop in route["stops"]]
    assert len(order_ids) == 2                       # the branch and the plan's own
    assert route["total_distance"] >= 0
    assert body["vehicles"][body["vehicle_id"]]["onboard_spare"] == []


def test_every_candidate_comes_back_drawable(closed_case):
    """The comparison figure is a MAP: candidates must carry their own line.

    ETAs and distances alone cannot be drawn, and without the per-vehicle
    baseline there is nothing to compare against. Found while building the
    "改道前 vs 改道后" overlay (docs/C_配送模块.md §4.3).
    """
    _create_plan()
    closed_case()
    preview = client.post("/api/dispatch/reshipments/preview",
                          json={"run_id": "R1"}).json()

    assert preview["candidates"] and preview["baselines"]
    for candidate in preview["candidates"]:
        line = candidate["route_geojson"]
        assert line["geometry"]["type"] == "LineString"
        assert len(line["geometry"]["coordinates"]) >= 2
        assert line["properties"]["kind"] == candidate["kind"]
        assert candidate["node_sequence"][-1] == 0        # every option ends at the depot
        assert candidate["added_distance_m"] >= 0
    for baseline in preview["baselines"].values():
        assert baseline["route_geojson"]["geometry"]["coordinates"]
        assert baseline["distance_m"] >= 0


def test_the_onboard_option_is_cheaper_than_driving_back_for_stock(closed_case):
    """The whole point of the fourth candidate, expressed in metres.

    Driven from where the vehicle actually is: while the truck is still AT the
    depot, fetching more stock costs nothing extra (it is already there), so the
    option only becomes cheaper AFTER a delivery — which is the situation the
    option exists for.
    """
    dispatch_id = "PLAN-METRES"
    created = _create_plan(dispatch_id, hospitals=2)
    assert client.post(f"/api/dispatch/runs/{dispatch_id}/depart",
                       json={"command_id": "go"}).status_code == 200
    vehicle = next(iter(created["orders"].values()))["vehicle_id"]
    moved = client.post(f"/api/dispatch/runs/{dispatch_id}/deliver-next",
                        json={"vehicle_id": vehicle, "command_id": "d1"}).json()
    assert moved["vehicles"][vehicle]["current_facility_id"] != "W-KN-PIONEER"

    network = read_network()
    planned = {order["destination_facility_id"] for order in created["orders"].values()}
    elsewhere = next(node["facility_id"] for node in network["nodes"]
                     if node["role"] == "customer"
                     and node["facility_id"] not in planned)
    closed_case(destination=elsewhere)

    preview = client.post("/api/dispatch/reshipments/preview", json={"run_id": "R1"}).json()
    by_kind = {item["kind"]: item for item in preview["candidates"]}

    assert {"add_stop_in_transit", "return_to_depot"} <= set(by_kind)
    onboard, depot = by_kind["add_stop_in_transit"], by_kind["return_to_depot"]
    assert onboard["added_distance_m"] < depot["added_distance_m"]
    # …and the difference is exactly the depot detour the truck avoids.
    distance = network["matrix"]["distance_m"]
    current = preview["baselines"][onboard["vehicle_id"]]["current_node_id"]
    destination = onboard["node_sequence"][1]
    avoided = distance[current][0] + distance[0][destination] - distance[current][destination]
    assert depot["sequence_distance_m"] - onboard["sequence_distance_m"] == pytest.approx(
        avoided, abs=1.0)


def test_route_view_exposes_legs_so_progress_can_be_drawn(day_plan):
    """A route drawn as one stroke cannot show what has already been driven."""
    dispatch_id = day_plan("PLAN-LEGS", hospitals=1)
    service.depart_dispatch(dispatch_id, "depart")
    created = service.get_dispatch(dispatch_id)
    route = created["route_view"]["routes"][0]
    order_id = route["stops"][0]["order_id"]

    assert len(route["legs"]) == 2                       # depot → stop → depot
    outbound, inbound = route["legs"]
    assert outbound["order_id"] == order_id
    assert outbound["delivered"] is False
    assert outbound["coords"] and inbound["coords"]

    delivered = service.deliver_dispatch(dispatch_id, route["vehicle_id"], "deliver-1")
    legs = delivered["route_view"]["routes"][0]["legs"]
    assert legs[0]["delivered"] is True                  # this stop is behind us
    assert legs[0]["order_id"] == order_id
    assert legs[1]["delivered"] is False                 # the way home is still ahead


def test_the_open_plan_wins_over_a_finished_one_however_the_ids_sort(closed_case):
    """Found by driving the live API, not by a unit test.

    The daily-batch button names plans ``PLAN-<yyyymmdd>`` while the console uses
    ``PLAN-<epoch seconds>``. Choosing "the live plan" by the biggest trailing
    number therefore let a finished plan (epoch 1.7e9) shadow the open one
    (date 2.0e7), and every branch event was refused with "no daily plan is open"
    while the panel was showing one.
    """
    _complete("PLAN-9999999999", _create_plan("PLAN-9999999999", hospitals=1))
    _create_plan("PLAN-1", hospitals=1)
    closed_case()

    preview = client.post("/api/dispatch/reshipments/preview", json={"run_id": "R1"})

    assert preview.status_code == 200
    assert preview.json()["dispatch_id"] == "PLAN-1"


def test_load_before_departure_is_an_acceptable_choice():
    """Regression: the accept schema listed only two of the three kinds.

    A preview offered ``load_before_departure`` for a vehicle still at the depot
    and the accept endpoint then answered 422 for the candidate it had just
    proposed — the operator was shown an option the API refused to apply.
    """
    request = {
        "orders": [{
            "order_id": "DO-NUH", "product_id": "vaccine_2_8",
            "destination_facility_id": "H-NUH", "quantity": 20,
            "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled"}],
        "inventory": [{
            "lot_id": "LOT-1", "product_id": "vaccine_2_8",
            "facility_id": "W-KN-PIONEER", "available_quantity": 50,
            "temperature_zone": "chilled"}],
        "vehicles": [{
            "vehicle_id": "V-CHILL-1", "capacity": 100,
            "temperature_zone": "chilled", "start_facility_id": "W-KN-PIONEER"}],
        "algorithm": "greedy", "dispatch_id": "DSP-LOADING",
        "command_id": "create-loading",
    }
    assert client.post("/api/dispatch/runs", json=request).status_code == 200
    order = {
        "order_id": "DO-URGENT", "product_id": "vaccine_2_8",
        "destination_facility_id": "H-KKH", "quantity": 20,
        "earliest_min": 540, "latest_min": 1020, "temperature_zone": "chilled",
    }
    preview = client.post("/api/dispatch/runs/DSP-LOADING/emergency-preview",
                          json={"current_time_min": 545, "order": order}).json()
    kinds = {item["kind"] for item in preview["candidates"]}
    assert "load_before_departure" in kinds

    accepted = client.post("/api/dispatch/runs/DSP-LOADING/emergency-accept", json={
        "current_time_min": 545, "candidate_kind": "load_before_departure",
        "vehicle_id": "V-CHILL-1", "command_id": "accept-loading", "order": order})

    assert accepted.status_code == 200
    body = accepted.json()
    # Loaded, not on the road: the fleet has not departed yet.
    assert body["orders"]["DO-URGENT"]["status"] == "planned"
    assert body["vehicles"]["V-CHILL-1"]["remaining_order_ids"][0] == "DO-URGENT"


def test_onboard_spare_survives_a_state_reload():
    """A state written by one process and read by another must agree on the load.

    ``onboard_spare`` crosses the JSON boundary in both directions, and a state
    persisted before the field existed must still load (as "carries nothing
    extra") instead of breaking every existing run.
    """
    from optimisation.dispatch_state import state_from_dict, state_to_dict
    from optimisation.dispatch_state import DispatchState, VehicleProgress

    state = DispatchState(
        version=3, status="in_transit", orders={},
        vehicles={"V-1": VehicleProgress(
            "V-1", "W-KN-PIONEER", (), onboard_spare=(("vaccine_2_8", "chilled", 30),))},
        available_by_lot={}, reserved_by_order={},
    )
    assert state_from_dict(state_to_dict(state)) == state

    legacy = state_to_dict(state)
    del legacy["vehicles"]["V-1"]["onboard_spare"]      # a pre-2026-09-15 row
    assert state_from_dict(legacy).vehicles["V-1"].onboard_spare == ()
