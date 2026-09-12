"""Initialize the dispatch schema in the configured cloud PostgreSQL."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from optimisation.dispatch_repository import ensure_schema


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is missing; copy .env.example to .env and set it")
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("DATABASE_URL must be a PostgreSQL connection URL")
    ensure_schema(database_url)
    print("dispatch_runs table is ready")


if __name__ == "__main__":
    main()
