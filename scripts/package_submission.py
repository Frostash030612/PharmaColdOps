"""Audit/assemble the course hand-in from a committed repository and human videos.

Only tracked source enters the nested repository ZIP. Env files, runtime data,
model binaries and local generated evaluation outputs must not enter that archive.
This checks packaging inputs, not human authorship or scientific validity.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def safe_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,150}", name):
        raise ValueError("submission name must be a simple ASCII filename stem")
    return name


def audit(report, promotion, system):
    files = {"member-github": ROOT / "member-github.txt", "report": report,
             "promotion": promotion, "system": system}
    missing = [name for name, path in files.items() if path is None or not path.is_file() or path.stat().st_size == 0]
    if report and report.suffix.lower() not in {".pdf", ".doc", ".docx"}:
        raise ValueError("course report must be PDF or Word")
    for path in (promotion, system):
        if path and path.suffix.lower() not in {".mp4", ".wmv", ".mov", ".avi", ".webm"}:
            raise ValueError("unsupported video extension")
    return files, missing


def validate_source(names):
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("unsafe repository archive path")
        parts = path.parts
        if ".git" in parts or any(p in {".venv", "node_modules", "__pycache__"} for p in parts):
            raise ValueError("local tooling accidentally tracked")
        if any((p == ".env" or p.startswith(".env.")) and not p.endswith(".example") for p in parts):
            raise ValueError("private environment file accidentally tracked")
        if "deploy" in parts and ("runtime" in parts or path.suffix == ".env"):
            raise ValueError("private deployment data accidentally tracked")
        if "data/audit/" in name or ("data/processed/" in name and path.name not in {"PROVENANCE.md", "agreement_stats.md"}):
            raise ValueError("generated runtime/evaluation data accidentally tracked")
        if path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".joblib", ".pkl", ".jsonl"}:
            raise ValueError("runtime/model artifact accidentally tracked")


def assemble(name, output, files):
    safe_name(name)
    if output.exists():
        raise FileExistsError("fresh output required")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True)
    if dirty.strip():
        raise ValueError("commit completed work before packaging a source release")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    names = subprocess.check_output(["git", "ls-tree", "-rz", "--name-only", "HEAD"], cwd=ROOT).decode("utf-8").rstrip("\0").split("\0")
    validate_source(names)
    source = subprocess.check_output(["git", "archive", "--format=zip", "--prefix=PharmaColdOps/", "HEAD"], cwd=ROOT)
    with ZipFile(io.BytesIO(source)) as archive:
        for entry in archive.infolist():
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("repository symlinks require explicit delivery review")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "pharmacoldops-course-submission-v1", "source_commit": commit,
                "scope": "file assembly only; verify human speech, 5-minute durations, M6 evidence and Canvas naming separately",
                "sha256": {}}
    with tempfile.TemporaryDirectory(prefix="pharma-submission-", dir=output.parent) as temp:
        staging = Path(temp) / "submission.zip"
        with ZipFile(staging, "w", ZIP_DEFLATED) as archive:
            source_name = name + "-source.zip"
            archive.writestr(source_name, source)
            manifest["sha256"][source_name] = hashlib.sha256(source).hexdigest()
            payloads = {"member-github.txt": files["member-github"]}
            for key, suffix in [("report", "Group-Report"), ("promotion", "promotion"), ("system", "system")]:
                path = files[key]
                payloads[name + "-" + suffix + path.suffix.lower()] = path
            for target, path in payloads.items():
                digest = hashlib.sha256()
                with path.open("rb") as incoming, archive.open(target, "w", force_zip64=True) as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        digest.update(chunk)
                        outgoing.write(chunk)
                manifest["sha256"][target] = digest.hexdigest()
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with output.open("xb") as stream, staging.open("rb") as incoming:
            shutil.copyfileobj(incoming, stream)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "docs/PharmaColdOps-Group-Report.pdf")
    parser.add_argument("--promotion", type=Path)
    parser.add_argument("--system", type=Path)
    parser.add_argument("--check", action="store_true", help="read-only input inventory; does not create an archive")
    parser.add_argument("--name", help="confirm date, class and group naming against the actual Canvas instructions")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        files, missing = audit(args.report, args.promotion, args.system)
        if args.check:
            print(json.dumps({"status": "missing_inputs" if missing else "inputs_present", "missing": missing,
                              "files": {key: str(value) if value else None for key, value in files.items()},
                              "scope": "availability only; not project completion, media validation or M6 scoring"}))
            return 1 if missing else 0
        if missing:
            parser.error("missing required inputs: " + ", ".join(missing))
        if not args.name or not args.output:
            parser.error("--name and --output are required for assembly")
        manifest = assemble(args.name, args.output, files)
        print(json.dumps({"status": "assembled", "output": str(args.output), "source_commit": manifest["source_commit"]}))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
