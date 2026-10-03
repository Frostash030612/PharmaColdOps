"""Serialize review / workflow / case-reship mutations across API workers.

One database-wide guard is adequate for this local demo. It does not lock every
ordinary vehicle tick, and it is not a distributed logistics transaction.
"""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import threading

from .dispatch_repository import _is_postgres, _postgres_connect

_lock = threading.RLock()


@contextmanager
def case_action_guard(target):
    with _lock:
        if _is_postgres(target):
            key = int.from_bytes(hashlib.sha256(b"pharmacoldops-case-actions").digest()[:8], "big", signed=True)
            db = _postgres_connect(target)
            try:
                db.execute("SELECT pg_advisory_lock(%s)", (key,))
                db.commit()
                yield
            finally:
                db.close()  # releases the session advisory lock, including errors
        else:
            value = str(target)
            if value.startswith("sqlite:///"):
                value = "/" + value[len("sqlite:///"):].lstrip("/")
            path = Path(value).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            with Path(str(path) + ".case-actions.lock").open("a+b") as handle:
                # Native host is macOS/Linux; fail closed on unsupported hosts.
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
