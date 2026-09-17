"""§4.3 (third layer): the perturbation figure's data contract.

The figure itself is drawn by ``scripts/plot_disruption_comparison.py``, which is
a plotting script and is not exercised here. What *is* worth locking is the
contract it depends on, because every clause of the "before vs after" claim is a
separate promise made by the backend:

* a branch preview of a rolling fleet really does offer more than one way;
* each option carries the geometry it would drive and how much further that is
  than simply carrying on — computed from the same sequence, not from an ETA;
* the "before" line is the vehicle's own remaining route, starting where it
  actually is rather than at the depot.

If any of those silently degrades, the figure would keep rendering — with a
plausible-looking lie in it. So the invariants are asserted here instead.

The scenario is driven through the real API surface, then the plotted numbers are
recomputed from the committed network.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# The figure script is a script, not a package module — it lives in scripts/
# beside the other reproducible-report generators. Import it the same way those
# are run: by putting its directory on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from optimisation.singapore_export import sequence_distance_m      # noqa: E402
from optimisation.singapore_loader import read_network             # noqa: E402

from plot_disruption_comparison import build_scenario              # noqa: E402

NETWORK = read_network()


@pytest.fixture(scope="module")
def scenario():
    """One driven scenario, shared: driving the clock is the slow part.

    ``start_min`` back-dates the simulated day so the test reaches the same state
    the figure script reaches by waiting — the scenario itself is identical, only
    the waiting is skipped. The dispatch database and case log are throwaway
    files, so running the suite never writes into the repository's own.
    """
    return build_scenario(seed=3, hospitals=5, tick_seconds=0.05, start_min=49,
                          dispatch_db=tempfile.mktemp(suffix=".sqlite3"),
                          runs_file=Path(tempfile.mktemp(suffix=".jsonl")),
                          verbose=False)


def test_a_rolling_fleet_is_offered_more_than_one_way(scenario):
    candidates = scenario["preview"]["candidates"]
    assert len(candidates) >= 2, "a comparison figure needs something to compare"
    assert scenario["preview"]["order_source"] == "linked_order"
    assert scenario["case"]["disposition"] == "scrap"


def test_the_before_line_starts_where_the_truck_is_not_at_the_depot(scenario):
    baseline = scenario["preview"]["baselines"][scenario["target"]["vehicle_id"]]
    # The work being compared is what is still ahead of the truck, so the line
    # begins at its current node — a baseline starting at the depot would make
    # every option look like a detour from a place nobody is.
    assert baseline["node_sequence"][0] != 0
    assert baseline["route_geojson"]["geometry"]["coordinates"]


def test_every_option_says_how_much_further_it_drives(scenario):
    preview = scenario["preview"]
    for candidate in preview["candidates"]:
        baseline = preview["baselines"].get(candidate["vehicle_id"])
        assert candidate["route_geojson"]["geometry"]["coordinates"]
        if baseline is None:
            continue
        expected = (sequence_distance_m(NETWORK, candidate["node_sequence"])
                    - sequence_distance_m(NETWORK, baseline["node_sequence"]))
        assert candidate["added_distance_m"] == pytest.approx(expected, abs=0.2)
        assert candidate["sequence_distance_m"] == pytest.approx(
            sequence_distance_m(NETWORK, candidate["node_sequence"]), abs=0.2)


def test_the_knock_on_delays_are_attributed_to_real_orders(scenario):
    for candidate in scenario["preview"]["candidates"]:
        assert candidate["affected_order_ids"] == [
            item["order_id"] for item in candidate["affected_orders"]]
        for item in candidate["affected_orders"]:
            assert item["delay_min"] >= 0
            assert item["newly_late"] <= (item["delay_min"] > 0)
