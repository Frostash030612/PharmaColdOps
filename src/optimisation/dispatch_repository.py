"""Small SQLite repository for accepted dispatch execution state."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .dispatch_state import DispatchState, state_from_dict, state_to_dict


def _connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS dispatch_runs ("
        "dispatch_id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
        "state_json TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}')"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(dispatch_runs)")}
    if "context_json" not in columns:
        connection.execute(
            "ALTER TABLE dispatch_runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'"
        )
    return connection


def create_run(
    path: str | Path, dispatch_id: str, state: DispatchState, *, context: dict
) -> None:
    with _connect(path) as db:
        try:
            db.execute(
                "INSERT INTO dispatch_runs "
                "(dispatch_id, version, state_json, context_json) VALUES (?, ?, ?, ?)",
                (dispatch_id, state.version, json.dumps(state_to_dict(state)), json.dumps(context)),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"dispatch {dispatch_id!r} already exists") from exc


def load_run(path: str | Path, dispatch_id: str) -> DispatchState:
    with _connect(path) as db:
        row = db.execute(
            "SELECT state_json FROM dispatch_runs WHERE dispatch_id = ?", (dispatch_id,)
        ).fetchone()
    if row is None:
        raise KeyError(dispatch_id)
    return state_from_dict(json.loads(row[0]))


def load_context(path: str | Path, dispatch_id: str) -> dict:
    with _connect(path) as db:
        row = db.execute(
            "SELECT context_json FROM dispatch_runs WHERE dispatch_id = ?", (dispatch_id,)
        ).fetchone()
    if row is None:
        raise KeyError(dispatch_id)
    return json.loads(row[0])


def update_run(
    path: str | Path,
    dispatch_id: str,
    state: DispatchState,
    *,
    expected_version: int,
) -> None:
    """Persist only if nobody changed the run after it was read."""
    with _connect(path) as db:
        changed = db.execute(
            "UPDATE dispatch_runs SET version = ?, state_json = ? "
            "WHERE dispatch_id = ? AND version = ?",
            (state.version, json.dumps(state_to_dict(state)), dispatch_id, expected_version),
        ).rowcount
    if changed != 1:
        raise ValueError("dispatch state changed; reload before retrying")
