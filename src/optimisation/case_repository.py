"""Durable first-write-wins case registration for SQLite and PostgreSQL.

JSONL is a backwards-compatible mirror, not the idempotency authority.
Different registration keys may intentionally contain identical incidents.
"""
import json
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
        return json.loads(row[1]), created


def registered_records(target):
    with _connection(target) as cursor:
        cursor.execute("SELECT record_json FROM case_registrations")
        return [json.loads(row[0]) for row in cursor.fetchall()]
