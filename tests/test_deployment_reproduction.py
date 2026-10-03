"""Deployment safety must not depend on native credentials/data or permissive health."""
from contextlib import nullcontext
import json
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap_demo as bootstrap
import configure_demo as config
import runtime_snapshot as snapshot
import check_reproduction as reproduction
from api import deployment, service
from optimisation.dispatch_repository import ensure_schema


@pytest.mark.parametrize("search,default,use,base", [
    ("", "", False, ""), ("", "same-origin", True, ""),
    ("?api=", "same-origin", False, ""), ("?api=same-origin", "", True, ""),
    ("?api=http://localhost:8000/", "same-origin", True, "http://localhost:8000"),
    ("?lang=zh", "same-origin", True, ""),
])
def test_same_origin_and_explicit_offline_are_not_confused(search, default, use, base):
    source = f"import {{resolveApiEndpoint}} from {json.dumps((ROOT/'frontend-vue/src/lib/apiEndpoint.js').as_uri())}; console.log(JSON.stringify(resolveApiEndpoint({json.dumps(search)},{json.dumps(default)})));"
    result = subprocess.run(["node", "--input-type=module", "-e", source], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {"useApi": use, "apiBase": base}


def test_example_config_does_not_enable_placeholder_postgresql():
    assert "DATABASE_URL" not in dotenv_values(ROOT / ".env.example")


def test_neo4j_container_does_not_interpret_password_as_invalid_config_setting():
    neo4j = (ROOT / "deploy/compose.demo.yml").read_text().split("  api:")[0]
    assert not re.search(r"^\s+NEO4J_PASSWORD:", neo4j, re.M)
    assert "$$HEALTHCHECK_PASSWORD" in neo4j


def test_private_generated_config_cannot_overwrite_credentials(tmp_path):
    target = tmp_path / "demo.env"
    config.configure(target)
    values = dotenv_values(target)
    assert len(values["NEO4J_PASSWORD"]) >= 24 and values["DEMO_BIND_ADDRESS"] == "127.0.0.1"
    assert target.stat().st_mode & 0o777 == 0o600
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        config.configure(target)
    assert target.read_bytes() == before
    with pytest.raises(ValueError):
        config.configure(tmp_path / "bad", 70000)


def test_configurable_cors_defaults_to_legacy_dev_but_deployment_can_close_it(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert deployment.cors_origins() == ["*"]
    monkeypatch.setenv("CORS_ORIGINS", "")
    assert deployment.cors_origins() == []
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://example.test")
    assert len(deployment.cors_origins()) == 2


def test_static_mount_keeps_api_first_and_refuses_unbuilt_path(tmp_path, monkeypatch):
    app = FastAPI()
    app.get("/api/health")(lambda: {"status": "ok"})
    (tmp_path / "index.html").write_text("<html>demo</html>")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    deployment.mount_frontend(app)
    client = TestClient(app)
    assert client.get("/").text == "<html>demo</html>"
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/nonexistent").status_code == 404
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError):
        deployment.mount_frontend(FastAPI())


def test_readiness_storage_probe_does_not_create_or_change_database(tmp_path):
    path = tmp_path / "missing.sqlite3"
    assert not deployment.storage_ready(path) and not path.exists()
    ensure_schema(path)
    before = path.read_bytes()
    assert deployment.storage_ready(path)
    assert path.read_bytes() == before


def test_readiness_reports_dependency_failure_without_credentials(tmp_path, monkeypatch):
    path = tmp_path / "dispatch.sqlite3"
    ensure_schema(path)
    monkeypatch.setattr(service, "DISPATCH_DATABASE_URL", str(path))
    monkeypatch.setenv("DEPLOYMENT_REQUIRE_MODELS", "1")
    monkeypatch.setenv("DEPLOYMENT_REQUIRE_GRAPH", "1")
    from ml import runtime
    from knowledge_graph import connect
    monkeypatch.setattr(runtime, "model_info", lambda _: {"status": "unavailable"})
    monkeypatch.setattr(connect, "get_driver", lambda: (_ for _ in ()).throw(RuntimeError("SECRET_PASSWORD")))
    result = deployment.ready_state()
    assert result["status"] == "not_ready" and result["checks"]["storage"] == "ready"
    assert "SECRET_PASSWORD" not in json.dumps(result)
    from api.main import app
    response = TestClient(app).get("/api/ready")
    assert response.status_code == 503 and TestClient(app).get("/api/health").status_code == 200


class FakeGraph:
    def __init__(self, count, marker=None):
        self.count, self.marker, self.writes = count, marker, []

    def execute_query(self, query, **kwargs):
        if "count(n)" in query:
            return SimpleNamespace(records=[{"n": self.count}])
        if "RETURN n.sha256" in query:
            return SimpleNamespace(records=[] if self.marker is None else [{"sha": self.marker}])
        self.writes.append(query)
        return SimpleNamespace(records=[])


def test_graph_bootstrap_never_clears_unmarked_or_changed_existing_graph(monkeypatch):
    for marker in [None, "old"]:
        driver = FakeGraph(120, marker)
        with pytest.raises(RuntimeError, match="refused to clear"):
            bootstrap.seed_graph(driver, "current")
        assert not driver.writes
    driver = FakeGraph(120, "current")
    assert bootstrap.seed_graph(driver, "current") == "existing_matching_seed"
    assert not driver.writes


def test_empty_graph_bootstrap_loads_then_marks_after_success(monkeypatch):
    calls = []
    for name in ["ensure_constraints", "load_static", "load_facility_links", "load_real_shipments"]:
        monkeypatch.setattr(bootstrap, name, lambda _, n=name: calls.append(n))
    driver = FakeGraph(0)
    assert bootstrap.seed_graph(driver, "current") == "initialized_empty_graph"
    assert calls == ["ensure_constraints", "load_static", "load_facility_links", "load_real_shipments"]
    assert len(driver.writes) == 1 and "DeploymentSeed" in driver.writes[0]


def test_graph_restore_replays_missing_but_refuses_conflicting_cases(monkeypatch):
    record = {"run_id": "test"}
    monkeypatch.setattr(bootstrap, "read_case_originals", lambda *_args, **_kwargs: ([record], {}))
    audits = iter([{"status": "failed", "cases": [{"run_id": "test", "coverage": "missing", "repairable": True}]}, {"status": "passed"}])
    monkeypatch.setattr(bootstrap, "audit_cases", lambda *_: next(audits))
    calls = []
    monkeypatch.setattr(bootstrap, "enqueue_graph_records", lambda *_: calls.append("enqueue"))
    monkeypatch.setattr(bootstrap, "requeue_graph_records", lambda *_args, **_kwargs: calls.append("requeue"))
    monkeypatch.setattr(service, "sync_case_graph", lambda **_: calls.append("sync"))
    assert bootstrap.recover_missing_cases() == 1 and calls == ["enqueue", "requeue", "sync"]
    monkeypatch.setattr(bootstrap, "audit_cases", lambda *_: {"status": "failed", "cases": [{"coverage": "conflict", "repairable": False}]})
    calls.clear()
    with pytest.raises(RuntimeError, match="conflicting"):
        bootstrap.recover_missing_cases()
    assert calls == []


def runtime_dir(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    ensure_schema(source / "dispatch.sqlite3")
    with sqlite3.connect(source / "dispatch.sqlite3") as db:
        db.execute("INSERT INTO dispatch_runs(dispatch_id,version,state_json) VALUES ('demo',3,'{}')")
    (source / "runs.jsonl").write_text('{"run_id":"example"}\n')
    return source


def test_snapshot_restore_roundtrip_and_never_overwrite_existing_data(tmp_path):
    source = runtime_dir(tmp_path)
    output = tmp_path / "backup"
    original = (source / "dispatch.sqlite3").read_bytes()
    with pytest.raises(ValueError, match="quiesced"):
        snapshot.backup(source, output, quiesced=False)
    snapshot.backup(source, output, quiesced=True)
    restored = tmp_path / "restored"
    assert snapshot.restore(output, restored)["status"] == "restored"
    assert deployment.storage_ready(restored / "dispatch.sqlite3")
    assert (restored / "runs.jsonl").read_bytes() == (source / "runs.jsonl").read_bytes()
    assert (source / "dispatch.sqlite3").read_bytes() == original
    with pytest.raises(ValueError):
        snapshot.restore(output, restored)
    with pytest.raises(ValueError):
        snapshot.backup(source, output, quiesced=True)


def test_snapshot_tamper_or_path_traversal_is_refused_before_target_creation(tmp_path):
    source = runtime_dir(tmp_path)
    output = tmp_path / "backup"
    snapshot.backup(source, output, quiesced=True)
    (output / "runs.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="integrity"):
        snapshot.restore(output, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["files"]["../escape"] = "x"
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        snapshot.restore(output, tmp_path / "not-created")


def test_reproduction_lock_checker_reports_missing_versions(monkeypatch):
    monkeypatch.setattr(reproduction.importlib.metadata, "version", lambda _: "wrong")
    result = reproduction.check(runtime_only=True)
    assert result["status"] == "failed" and "dependency:scikit-learn" in result["failures"]


def test_reproduction_pins_include_runtime_and_no_unpinned_install_targets():
    values = reproduction.pins(ROOT / "requirements-eval.lock.txt")
    assert values["scikit-learn"] == "1.9.1" and values["pytest"] == "9.1.1"
    assert not {"lightgbm", "xgboost", "osmnx"} & values.keys()
