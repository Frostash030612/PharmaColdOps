"""Optional demo deployment plumbing. No public-auth or clinical guarantees."""
import os
from pathlib import Path
import sqlite3

from fastapi.staticfiles import StaticFiles


def cors_origins():
    value = os.environ.get("CORS_ORIGINS")
    return ["*"] if value is None else [v.strip() for v in value.split(",") if v.strip()]


def mount_frontend(app):
    value = os.environ.get("FRONTEND_DIST")
    if value:
        directory = Path(value).resolve()
        if not (directory / "index.html").is_file():
            raise RuntimeError("FRONTEND_DIST must contain a built index.html")
        # Called after all API routes; never hide API health/errors behind HTML.
        app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")


def storage_ready(target):
    """Read-only connection probe. Does not create/migrate a runtime database."""
    if str(target).startswith(("postgresql://", "postgres://")):
        import psycopg
        with psycopg.connect(str(target), connect_timeout=3) as db:
            with db.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT 1")
    else:
        value = str(target)
        if value.startswith("sqlite:///"):
            value = "/" + value[len("sqlite:///"):].lstrip("/")
        path = Path(value).resolve()
        if not path.is_file() or not os.access(path.parent, os.W_OK):
            return False
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return False
            db.execute("SELECT count(*) FROM dispatch_runs").fetchone()
    return True


def ready_state():
    from . import service
    from ml import runtime
    from knowledge_graph.connect import get_driver
    checks = {}
    try:
        checks["storage"] = "ready" if storage_ready(service.DISPATCH_DATABASE_URL) else "unavailable"
    except Exception:
        checks["storage"] = "unavailable"
    require_models = os.environ.get("DEPLOYMENT_REQUIRE_MODELS", "0") == "1"
    if require_models:
        for task in ["risk", "cause"]:
            checks["model_" + task] = runtime.model_info(task)["status"]
    if os.environ.get("EVENT_V2_SHADOW_ENABLED") == "1":
        from ml import event_v2_runtime
        checks["event_v2_shadow"] = "ready" if event_v2_runtime.info()["status"] == "shadow_ready" else "unavailable"
    require_graph = os.environ.get("DEPLOYMENT_REQUIRE_GRAPH", "0") == "1"
    if require_graph:
        try:
            with get_driver() as driver:
                ids = {r["id"] for r in driver.execute_query("MATCH (p:Product) RETURN p.product_id AS id").records}
                checks["graph"] = "ready" if set(service.valid_product_ids()) <= ids else "unavailable"
        except Exception:
            checks["graph"] = "unavailable"
    ready = all(v == "ready" for v in checks.values())
    return {"status": "ready" if ready else "not_ready", "checks": checks,
            "scope": "demo dependency readiness, not authentication/clinical/production certification"}
