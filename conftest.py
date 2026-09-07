"""Pytest configuration: make the `src/` packages importable in tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
