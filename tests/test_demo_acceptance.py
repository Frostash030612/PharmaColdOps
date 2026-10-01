"""Whole workflows must pass without rewriting committed dispatch state."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_demo_acceptance import run_acceptance


def test_repeatable_full_demo_in_isolated_storage(tmp_path):
    first = run_acceptance(tmp_path / "first")
    second = run_acceptance(tmp_path / "second")
    assert first["status"] == second["status"] == "passed"
    assert first["checks"] == second["checks"]
    assert first["snapshots"]["generated"] == second["snapshots"]["generated"]
    assert first["snapshots"]["delay_preview"] == second["snapshots"]["delay_preview"]
    assert first["graph_mode"] == "not_verified"


def test_acceptance_does_not_overwrite_evidence(tmp_path):
    with pytest.raises(FileExistsError):
        run_acceptance(tmp_path)
