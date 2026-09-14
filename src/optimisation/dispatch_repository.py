"""Persistent dispatch state backed by PostgreSQL or local SQLite."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .dispatch_state import DispatchState, state_from_dict, state_to_dict


def _is_postgres(target: str | Path) -> bool:
    return str(target).startswith(("postgresql://", "postgres://"))


def _sqlite_connect(target: str | Path) -> sqlite3.Connection:
    value = str(target)
    if value.startswith("sqlite:///"):
        value = value[len("sqlite:///"):]
        if not value.startswith("/"):
            value = "/" + value
    path = Path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS dispatch_runs ("
        "dispatch_id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
        "state_json TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}')"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(dispatch_runs)")}
    if "context_json" not in columns:
        connection.execute("ALTER TABLE dispatch_runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")
    return connection


def _postgres_connect(target: str | Path):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PostgreSQL requires psycopg; install project requirements") from exc
    connection = psycopg.connect(str(target))
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS dispatch_runs ("
            "dispatch_id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
            "state_json JSONB NOT NULL, context_json JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    connection.commit()
    return connection


def ensure_schema(target: str | Path) -> None:
    connect = _postgres_connect if _is_postgres(target) else _sqlite_connect
    with connect(target):
        pass


def create_run(target: str | Path, dispatch_id: str, state: DispatchState, *, context: dict) -> None:
    state_json = json.dumps(state_to_dict(state))
    context_json = json.dumps(context)
    if _is_postgres(target):
        try:
            with _postgres_connect(target) as db, db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO dispatch_runs (dispatch_id, version, state_json, context_json) "
                    "VALUES (%s, %s, %s::jsonb, %s::jsonb)",
                    (dispatch_id, state.version, state_json, context_json),
                )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise ValueError(f"dispatch {dispatch_id!r} already exists") from exc
            raise
        return
    with _sqlite_connect(target) as db:
        try:
            db.execute(
                "INSERT INTO dispatch_runs (dispatch_id, version, state_json, context_json) VALUES (?, ?, ?, ?)",
                (dispatch_id, state.version, state_json, context_json),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"dispatch {dispatch_id!r} already exists") from exc


def _load_json(target: str | Path, dispatch_id: str, column: str):
    if _is_postgres(target):
        with _postgres_connect(target) as db, db.cursor() as cursor:
            cursor.execute(f"SELECT {column} FROM dispatch_runs WHERE dispatch_id = %s", (dispatch_id,))
            row = cursor.fetchone()
    else:
        with _sqlite_connect(target) as db:
            row = db.execute(f"SELECT {column} FROM dispatch_runs WHERE dispatch_id = ?", (dispatch_id,)).fetchone()
    if row is None:
        raise KeyError(dispatch_id)
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


def load_run(target: str | Path, dispatch_id: str) -> DispatchState:
    return state_from_dict(_load_json(target, dispatch_id, "state_json"))


def load_context(target: str | Path, dispatch_id: str) -> dict:
    return _load_json(target, dispatch_id, "context_json")


def list_dispatch_ids(target: str | Path, prefix: str) -> list[str]:
    """Every dispatch id starting with ``prefix`` (used to find the live one)."""
    pattern = f"{prefix}%"
    if _is_postgres(target):
        with _postgres_connect(target) as db, db.cursor() as cursor:
            cursor.execute(
                "SELECT dispatch_id FROM dispatch_runs WHERE dispatch_id LIKE %s", (pattern,))
            rows = cursor.fetchall()
    else:
        with _sqlite_connect(target) as db:
            rows = db.execute(
                "SELECT dispatch_id FROM dispatch_runs WHERE dispatch_id LIKE ?", (pattern,)
            ).fetchall()
    return [row[0] for row in rows]


def update_context(target: str | Path, dispatch_id: str, context: dict) -> None:
    """Persist a revised context (e.g. a newly inserted order/lot/vehicle).

    Unlike ``update_run`` this carries no optimistic-concurrency check: context
    is reference data for previews (order/lot/vehicle dumps), not the
    authoritative execution state, so the only invariant that matters is that
    it is written in the same request as the ``update_run``/``create_run``
    call that changed it.
    """
    context_json = json.dumps(context)
    if _is_postgres(target):
        with _postgres_connect(target) as db, db.cursor() as cursor:
            cursor.execute(
                "UPDATE dispatch_runs SET context_json = %s::jsonb WHERE dispatch_id = %s",
                (context_json, dispatch_id),
            )
            changed = cursor.rowcount
    else:
        with _sqlite_connect(target) as db:
            changed = db.execute(
                "UPDATE dispatch_runs SET context_json = ? WHERE dispatch_id = ?",
                (context_json, dispatch_id),
            ).rowcount
    if changed != 1:
        raise KeyError(dispatch_id)


def update_run(target: str | Path, dispatch_id: str, state: DispatchState, *, expected_version: int) -> None:
    """Persist only if nobody changed the run after it was read."""
    state_json = json.dumps(state_to_dict(state))
    if _is_postgres(target):
        with _postgres_connect(target) as db, db.cursor() as cursor:
            cursor.execute(
                "UPDATE dispatch_runs SET version = %s, state_json = %s::jsonb, "
                "updated_at = CURRENT_TIMESTAMP WHERE dispatch_id = %s AND version = %s",
                (state.version, state_json, dispatch_id, expected_version),
            )
            changed = cursor.rowcount
    else:
        with _sqlite_connect(target) as db:
            changed = db.execute(
                "UPDATE dispatch_runs SET version = ?, state_json = ? WHERE dispatch_id = ? AND version = ?",
                (state.version, state_json, dispatch_id, expected_version),
            ).rowcount
    if changed != 1:
        raise ValueError("dispatch state changed; reload before retrying")
