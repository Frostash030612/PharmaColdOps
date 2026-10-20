"""Delivery safety checks, not a substitute for the human course deliverables."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("submission", ROOT / "scripts/package_submission.py")
submission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(submission)


@pytest.mark.parametrize("name", ["../submission", "/tmp/submission", "x\\y", "", "a.zip"])
def test_submission_cannot_choose_unsafe_member_names(name):
    with pytest.raises(ValueError):
        submission.safe_name(name)


@pytest.mark.parametrize("name", [".env", "deploy/demo.env", "deploy/runtime/models/metadata.json",
                                  "data/audit/runs.jsonl", "data/processed/new/report.json", "models/model.joblib",
                                  "../outside", "a\\outside", "node_modules/a.js"])
def test_source_zip_rejects_private_runtime_and_unsafe_entries(name):
    with pytest.raises(ValueError):
        submission.validate_source([name])


def test_source_zip_keeps_documentation_examples_and_frozen_inputs():
    submission.validate_source([".env.example", "deploy/demo.env.example", "docs/PharmaColdOps-Group-Report.pdf",
                                "data/qa/m6-review-20261003-v3/coordinator/predictions.private.json",
                                "data/processed/PROVENANCE.md", "data/processed/agreement_stats.md"])


def test_missing_human_recordings_remain_missing(tmp_path):
    report = tmp_path / "report.pdf"
    report.write_bytes(b"unit fixture, not a final report")
    _, missing = submission.audit(report, None, None)
    assert missing == ["promotion", "system"]


def test_assembly_preserves_unicode_paths_and_uses_only_the_committed_source(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for key, value in [("user.name", "Unit Fixture"), ("user.email", "fixture@example.invalid")]:
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    (repo / "docs").mkdir()
    (repo / "docs/中文文档.md").write_text("unit fixture only", encoding="utf-8")
    (repo / "member-github.txt").write_text("unit fixture only", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "docs", "member-github.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "unit fixture"], check=True)
    monkeypatch.setattr(submission, "ROOT", repo)
    files = {"member-github": repo / "member-github.txt"}
    for key, suffix in [("report", ".pdf"), ("promotion", ".mp4"), ("system", ".mp4")]:
        files[key] = tmp_path / (key + suffix)
        files[key].write_bytes(b"unit fixture, not actual human deliverable")
    output = tmp_path / "new.zip"
    result = submission.assemble("Unit-Fixture", output, files)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {"member-github.txt", "Unit-Fixture-source.zip", "Unit-Fixture-Group-Report.pdf",
                                            "Unit-Fixture-promotion.mp4", "Unit-Fixture-system.mp4", "manifest.json"}
        assert json.loads(archive.read("manifest.json")) == result
        with ZipFile(io.BytesIO(archive.read("Unit-Fixture-source.zip"))) as source:
            assert "PharmaColdOps/docs/中文文档.md" in source.namelist()
            assert not any(".git/" in name or "promotion.mp4" in name for name in source.namelist())
    with pytest.raises(FileExistsError):
        submission.assemble("Unit-Fixture", output, files)
