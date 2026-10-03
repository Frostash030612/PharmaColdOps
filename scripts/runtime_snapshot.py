"""Offline SQLite/JSONL snapshot and fresh-target restore; never overwrite data.

Stop the API first and explicitly pass --quiesced. Neo4j is a derived mirror:
restore into a NEW deployment and let bootstrap replay non-conflicting cases.
This helper does not rotate credentials, authenticate files or migrate models.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

FILES = {"dispatch.sqlite3", "runs.jsonl"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_database(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular SQLite database required")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("database integrity check failed")
        db.execute("SELECT count(*) FROM dispatch_runs").fetchone()


def backup(source, output, *, quiesced):
    if not quiesced:
        raise ValueError("stop API writes and explicitly confirm --quiesced")
    if source.is_symlink() or output.exists():
        raise ValueError("regular source and fresh snapshot directory required")
    checked_database(source / "dispatch.sqlite3")
    archive = source / "runs.jsonl"
    if archive.is_symlink():
        raise ValueError("symlink archive refused")
    if archive.exists():
        for line in archive.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict) or not value.get("run_id"):
                    raise ValueError("malformed case archive")
    output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect((source / "dispatch.sqlite3").resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(output / "dispatch.sqlite3") as dst:
            src.backup(dst)
    if archive.exists():
        shutil.copyfile(archive, output / archive.name)
    for name in FILES:
        if (output / name).exists():
            (output / name).chmod(0o600)
    hashes = {name: digest(output / name) for name in sorted(FILES) if (output / name).exists()}
    manifest = {"schema": "demo-runtime-snapshot-v1", "files": hashes, "api_quiescence_user_confirmed": True,
                "scope": "authoritative SQLite and optional JSONL; graph rebuilt, serving model/image pinned separately"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def restore(snapshot, target):
    if snapshot.is_symlink() or (snapshot / "manifest.json").is_symlink():
        raise ValueError("symlink snapshot refused")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    names = set(manifest.get("files", {}))
    if manifest.get("schema") != "demo-runtime-snapshot-v1" or not names <= FILES or "dispatch.sqlite3" not in names:
        raise ValueError("unsupported snapshot manifest")
    for name in names:
        path = snapshot / name
        if path.is_symlink() or digest(path) != manifest["files"][name]:
            raise ValueError("snapshot integrity mismatch")
    checked_database(snapshot / "dispatch.sqlite3")
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ValueError("restore target must be NEW or empty; existing data never overwritten")
    target.mkdir(parents=True, exist_ok=True)
    owner = target.stat()
    for name in sorted(names):
        # Exclusive create also protects against a concurrent target writer.
        with (snapshot / name).open("rb") as src, (target / name).open("xb") as dst:
            shutil.copyfileobj(src, dst)
        (target / name).chmod(0o600)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            # Offline container restore runs as root, but serving is non-root.
            os.chown(target / name, owner.st_uid, owner.st_gid)
    return {"status": "restored", "files": sorted(names), "graph_replay_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("backup")
    a.add_argument("--source", type=Path, required=True)
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--quiesced", action="store_true")
    b = sub.add_parser("restore")
    b.add_argument("--snapshot", type=Path, required=True)
    b.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = backup(args.source, args.output, quiesced=args.quiesced) if args.mode == "backup" else restore(args.snapshot, args.target)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Snapshot refused ({type(exc).__name__}); existing data preserved", file=sys.stderr)
        return 1
    print(json.dumps(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
