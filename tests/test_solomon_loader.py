"""Loader tests for the six committed Solomon instances (src/optimisation).

Pin the unified data-class shape (nodes / demand / time windows / coords) that
the greedy baseline and solvers will consume, and validate the one name change
the loader makes: the JSON ``cost`` column is the Solomon service time and
must be per-instance constant for customers (90 in C-class, 10 in R/RC-class).
"""
import json
from pathlib import Path

import pytest

from optimisation.models import Node
from optimisation.solomon_loader import (
    SOLOMON_DIR,
    SOLOMON_NAMES,
    load_dir,
    load_instance,
)

# Per-instance-constant customer service time expected for each class.
EXPECTED_SERVICE = {"C": 90, "R": 10, "RC": 10}


@pytest.mark.parametrize("stem", SOLOMON_NAMES)
def test_all_six_instances_load(stem: str):
    inst = load_instance(SOLOMON_DIR / f"{stem}.json")
    assert inst.instance == stem.upper()
    assert inst.vehicle_nr >= 1
    assert inst.capacity >= 1
    # 101 nodes = depot (0) + 100 customers, ids contiguous after sort.
    assert [n.node_id for n in inst.nodes] == list(range(101))
    assert inst.n_customers == 100
    assert inst.depot.is_depot and inst.depot.demand == 0 and inst.depot.service == 0


@pytest.mark.parametrize("stem", SOLOMON_NAMES)
def test_customer_rows_carry_demand_window_coords_and_service(stem: str):
    inst = load_instance(SOLOMON_DIR / f"{stem}.json")
    klass = stem[0].upper()
    for node in inst.customers:
        assert isinstance(node, Node)
        assert node.demand >= 1  # depot excluded ⇒ every customer needs supply
        assert node.demand <= inst.capacity
        assert 0 <= node.earliest <= node.latest <= inst.horizon_end
        # coords present (x,y are the Euclidean distance source for the solvers)
        assert node.x >= 0 and node.y >= 0
        # JSON "cost" is the Solomon service time → per-class constant
        assert node.service == EXPECTED_SERVICE[klass], f"{stem}: service time"
    assert inst.total_demand > inst.capacity  # genuinely needs a fleet of routes


def test_depot_is_first_and_unique_zero_node():
    inst = load_instance(SOLOMON_DIR / "c101.json")
    zeros = [n for n in inst.nodes if n.node_id == 0]
    assert len(zeros) == 1
    assert inst.depot.node_id == 0


def test_load_dir_reads_all_six_keyed_by_label():
    instances = load_dir()
    assert set(instances) == {s.upper() for s in SOLOMON_NAMES}
    # load_dir == per-file load, so callers can mix both entry points safely.
    for label, inst in instances.items():
        assert inst == load_instance(SOLOMON_DIR / f"{label.lower()}.json")


def test_missing_depot_rejected(tmp_path):
    bad = tmp_path / "x.json"
    data = {
        "instance": "X",
        "vehicle-nr": 25,
        "capacity": 200,
        "customers": [{"id": 1, "x": 1, "y": 1, "demand": 1, "earliest": 0, "latest": 10, "cost": 0}],
    }
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="no depot"):
        load_instance(bad)


def test_bad_time_window_rejected(tmp_path):
    bad = tmp_path / "y.json"
    data = {
        "instance": "Y",
        "vehicle-nr": 25,
        "capacity": 200,
        "customers": [
            {"id": 0, "x": 0, "y": 0, "demand": 0, "earliest": 0, "latest": 100, "cost": 0},
            {"id": 1, "x": 1, "y": 1, "demand": 1, "earliest": 50, "latest": 10, "cost": 5},
        ],
    }
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="time window"):
        load_instance(bad)


def test_duplicate_node_id_rejected(tmp_path):
    bad = tmp_path / "z.json"
    row = {"id": 0, "x": 0, "y": 0, "demand": 0, "earliest": 0, "latest": 100, "cost": 0}
    bad.write_text(
        json.dumps({"instance": "Z", "vehicle-nr": 1, "capacity": 10, "customers": [row, row]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate node id"):
        load_instance(bad)
