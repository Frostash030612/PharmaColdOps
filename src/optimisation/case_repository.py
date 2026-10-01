"""Durable first-write-wins case registration for SQLite and PostgreSQL.

JSONL is a backwards-compatible mirror, not the idempotency authority.
Different registration keys may intentionally contain identical incidents.
"""
import json
import time
import uuid
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from .dispatch_repository import _is_postgres, _postgres_connect, _sqlite_connect


class RegistrationConflict(ValueError):
    pass


@contextmanager
def _connection(target):
    postgres = _is_postgres(target)
    db = (_postgres_connect if postgres else _sqlite_connect)(target)
    try:
        with db:
            with db.cursor() if postgres else _cursor(db) as cursor:
                if postgres:
                    cursor.execute("SELECT pg_advisory_xact_lock(741932801)")
                cursor.execute("CREATE TABLE IF NOT EXISTS case_registrations ("
                    "registration_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, "
                    "run_id TEXT NOT NULL UNIQUE, record_json TEXT NOT NULL)")
                cursor.execute("CREATE TABLE IF NOT EXISTS case_graph_outbox ("
                    "run_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
                    "attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at DOUBLE PRECISION NOT NULL DEFAULT 0, "
                    "claim_token TEXT, last_error TEXT, synced_at DOUBLE PRECISION)")
                # Upgrade existing installations without trusting a past best-effort
                # mirror. Replaying immutable records is safe under Neo4j MERGE.
                cursor.execute("INSERT INTO case_graph_outbox (run_id,record_json) "
                    "SELECT run_id,record_json FROM case_registrations WHERE 1=1 "
                    "ON CONFLICT (run_id) DO NOTHING")
                yield cursor
    finally:
        db.close()


@contextmanager
def _cursor(db):
    cursor = db.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def lookup_registration(target, registration_id, request_sha256):
    marker = "%s" if _is_postgres(target) else "?"
    with _connection(target) as cursor:
        cursor.execute(f"SELECT request_sha256,record_json FROM case_registrations WHERE registration_id={marker}", (registration_id,))
        row = cursor.fetchone()
    if row is None:
        return None
    if row[0] != request_sha256:
        raise RegistrationConflict("registration_id already belongs to different incident inputs; retry the original draft")
    return json.loads(row[1])


def register_once(target, registration_id, request_sha256, record):
    marker = "%s" if _is_postgres(target) else "?"
    with _connection(target) as cursor:
        cursor.execute(f"INSERT INTO case_registrations VALUES ({marker},{marker},{marker},{marker}) "
                       "ON CONFLICT (registration_id) DO NOTHING",
                       (registration_id, request_sha256, record["run_id"], json.dumps(record, ensure_ascii=False)))
        created = cursor.rowcount == 1
        cursor.execute(f"SELECT request_sha256,record_json FROM case_registrations WHERE registration_id={marker}", (registration_id,))
        row = cursor.fetchone()
        if row[0] != request_sha256:
            raise RegistrationConflict("registration_id already belongs to different incident inputs; retry the original draft")
        # Same transaction as the registration: a crash after commit cannot lose
        # the obligation to mirror this original assessment.
        cursor.execute(f"INSERT INTO case_graph_outbox (run_id,record_json) VALUES ({marker},{marker}) "
                       "ON CONFLICT (run_id) DO NOTHING", (json.loads(row[1])["run_id"], row[1]))
        return json.loads(row[1]), created


def registered_records(target):
    with _connection(target) as cursor:
        cursor.execute("SELECT record_json FROM case_registrations")
        return [json.loads(row[0]) for row in cursor.fetchall()]


def enqueue_graph_records(target, records):
    """Explicit legacy backfill; never replace the first immutable payload."""
    marker = "%s" if _is_postgres(target) else "?"
    with _connection(target) as cursor:
        for record in records:
            cursor.execute(f"INSERT INTO case_graph_outbox (run_id,record_json) VALUES ({marker},{marker}) "
                           "ON CONFLICT (run_id) DO NOTHING",
                           (record["run_id"], json.dumps(record, ensure_ascii=False)))


def graph_sync_status(target, run_id=None):
    marker = "%s" if _is_postgres(target) else "?"
    with _connection(target) as cursor:
        if run_id:
            cursor.execute(f"SELECT status,attempts,last_error,synced_at FROM case_graph_outbox WHERE run_id={marker}", (run_id,))
            row = cursor.fetchone()
            return dict(zip(["status", "attempts", "last_error", "synced_at"], row)) if row else None
        cursor.execute("SELECT status,COUNT(*) FROM case_graph_outbox GROUP BY status")
        return {**dict.fromkeys(["pending", "processing", "synced"], 0), **dict(cursor.fetchall())}


def claim_graph_records(target, *, limit=50, run_id=None, force=False):
    """Leased CAS claims; crashed workers are eligible again after 60 seconds."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    marker = "%s" if _is_postgres(target) else "?"
    now = time.time()
    claims = []
    with _connection(target) as cursor:
        due = f"next_attempt_at <= {marker}"
        # Force bypasses failure backoff, never another worker's live lease.
        if force:
            due = f"(status='pending' OR next_attempt_at <= {marker})"
        where = f"status <> 'synced' AND {due}"
        params = [now]
        if run_id:
            where += f" AND run_id={marker}"
            params.append(run_id)
        cursor.execute(f"SELECT run_id,record_json FROM case_graph_outbox WHERE {where} ORDER BY next_attempt_at,run_id LIMIT {marker}", (*params, limit))
        for rid, payload in cursor.fetchall():
            token = uuid.uuid4().hex
            cursor.execute(f"UPDATE case_graph_outbox SET status='processing',claim_token={marker}, "
                           f"attempts=attempts+1,next_attempt_at={marker} WHERE run_id={marker} AND {where}",
                           (token, now + 60, rid, *params))
            if cursor.rowcount == 1:
                claims.append({"run_id": rid, "record": json.loads(payload), "token": token})
    return claims


def finish_graph_claim(target, claim, *, success, error=None):
    marker = "%s" if _is_postgres(target) else "?"
    now = time.time()
    with _connection(target) as cursor:
        # Late completion from an expired worker cannot overwrite a newer claim.
        cursor.execute(f"UPDATE case_graph_outbox SET status={marker},last_error={marker}, "
                       f"synced_at={marker},next_attempt_at={marker},claim_token=NULL "
                       f"WHERE run_id={marker} AND claim_token={marker}",
                       ("synced" if success else "pending", None if success else (error or "graph write failed")[:500],
                        now if success else None, 0 if success else now + 15, claim["run_id"], claim["token"]))
        return cursor.rowcount == 1


def requeue_graph_records(target, *, run_ids=None):
    """Explicit recovery after a graph rebuild; never clears business records."""
    with _connection(target) as cursor:
        query = "UPDATE case_graph_outbox SET status='pending',next_attempt_at=0,synced_at=NULL WHERE status='synced'"
        if run_ids is not None:
            if not run_ids:
                return 0
            marker = "%s" if _is_postgres(target) else "?"
            query += " AND run_id IN (" + ",".join(marker for _ in run_ids) + ")"
            cursor.execute(query, tuple(run_ids))
        else:
            cursor.execute(query)
        return cursor.rowcount


def read_case_originals(target, *, legacy_file=None):
    """Read-only coverage inventory: no schema migration, queue or DB creation.

    Relational originals win over JSONL; immutable outbox payloads cover legacy
    imports that never had a registration row. Malformed legacy data is refused.
    """
    originals, states = {}, {}
    if legacy_file and Path(legacy_file).exists():
        for line in Path(legacy_file).read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                originals.setdefault(record["run_id"], record)
    if _is_postgres(target):
        import psycopg
        db = psycopg.connect(str(target))
        db.execute("SET TRANSACTION READ ONLY")
        table_query = "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()"
    else:
        value = str(target)
        if value.startswith("sqlite:///"):
            value = "/" + value[len("sqlite:///"):].lstrip("/")
        path = Path(value)
        if not path.exists():
            return list(originals.values()), states
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        table_query = "SELECT name FROM sqlite_master WHERE type='table'"
    try:
        with db.cursor() if _is_postgres(target) else _cursor(db) as cursor:
            cursor.execute(table_query)
            tables = {row[0] for row in cursor.fetchall()}
            if "case_graph_outbox" in tables:
                cursor.execute("SELECT run_id,record_json,status FROM case_graph_outbox")
                for rid, payload, status in cursor.fetchall():
                    originals[rid] = json.loads(payload)
                    states[rid] = status
            if "case_registrations" in tables:
                cursor.execute("SELECT run_id,record_json FROM case_registrations")
                for rid, payload in cursor.fetchall():
                    originals[rid] = json.loads(payload)
        return list(originals.values()), states
    finally:
        db.close()
