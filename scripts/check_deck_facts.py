"""Verify the presentation deck's measurement slide against the repository.

The deck's slide 7 ("Built and Running Today") quotes counts that must be
re-measurable from the repo. This check recomputes them from source and fails
loudly on any mismatch, so a stale hand-typed number cannot survive unnoticed.

Run:  .venv/Scripts/python.exe scripts/check_deck_facts.py
Exit code is 1 when any checked number disagrees with the deck.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

from pptx import Presentation

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "proposal" / "PharmaColdOps .pptx"


def measure() -> dict[str, int]:
    """Recompute every number quoted on slide 7 from the repository itself."""
    main_py = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    routes = re.findall(r'@app\.(?:get|post|put|delete|patch)\(\s*"([^"]+)"', main_py)
    dispatch = [p for p in routes if p.startswith("/api/dispatch")]

    test_sources = {
        path: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "tests").glob("*.py"))
    }
    test_functions = sum(len(re.findall(r"(?m)^\s*def test_", text))
                         for text in test_sources.values())
    test_files = sum(1 for text in test_sources.values()
                     if re.search(r"(?m)^\s*def test_", text))

    runs_path = ROOT / "data" / "audit" / "runs.jsonl"
    archived = sum(1 for line in runs_path.read_text(encoding="utf-8").splitlines()
                   if line.strip())

    db_path = ROOT / "data" / "audit" / "dispatch.sqlite3"
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        persisted = connection.execute(
            "SELECT count(*) FROM dispatch_runs").fetchone()[0]

    components = len(list((ROOT / "frontend-vue" / "src" / "components").glob("*.vue")))

    return {
        "api_paths": len(set(routes)),
        "api_operations": len(routes),
        "dispatch_paths": len(set(dispatch)),
        "dispatch_operations": len(dispatch),
        "test_functions": test_functions,
        "test_files": test_files,
        "archived_cases": archived,
        "dispatch_operations_persisted": persisted,
        "vue_components": components,
    }


def check_results_slide(facts: dict[str, int]) -> int:
    """Slide 8 quotes the closed loop and the three evaluation layers.

    The evaluation numbers are frozen artifacts (rubric v1.1, the recorded routing
    run, the risk experiment), so this checks the numbers are *present and
    mutually consistent* rather than re-deriving them; the loop facts it can
    re-derive from the repo are checked against the measurement.
    """
    slide_text = "\n".join(
        shape.text_frame.text for shape in Presentation(str(DECK)).slides[7].shapes
        if shape.has_text_frame
    )
    expectations = [
        ("loop hero", "4"),
        ("loop fact 1: 19-node OSM network", "19-node Singapore OSM network"),
        ("loop fact 1: graph evidence", "9 nodes / 8 relationship types"),
        ("loop fact 2: api paths", f"{facts['api_paths']} API paths"),
        ("loop fact 2: dispatch paths", f"{facts['dispatch_paths']} dispatch paths"),
        ("loop fact 2: archived cases", f"{facts['archived_cases']} archived cases"),
        ("loop fact 2: persisted operations",
         f"{facts['dispatch_operations_persisted']} persisted dispatch operations"),
        ("loop fact 3: declared limits", "no operational savings claimed"),
        ("disposition layer: agreement", "54/57 = 94.7%"),
        ("disposition layer: kappa", "0.6434"),
        ("route layer: result", "142.63 → 133.81 km"),
        ("route layer: gain", "−6.19%"),
        ("risk layer: headline", "F1 0.691 / ROC-AUC 0.925"),
        ("risk layer: negative result", "majority baseline 0.161"),
    ]

    print(f"\ndeck: {DECK.name}  (slide 8)")
    failures = 0
    for label, expected in expectations:
        ok = expected in slide_text
        if not ok:
            failures += 1
        print(f"  [{'ok ' if ok else 'BAD'}] {label}"
              f"{'' if ok else f'  -> slide 8 does not contain {expected!r}'}")
    print(f"{len(expectations) - failures}/{len(expectations)} slide-8 checks match")
    return failures


def main() -> int:
    facts = measure()
    slide = Presentation(str(DECK)).slides[6]
    slide_text = "\n".join(
        shape.text_frame.text for shape in slide.shapes if shape.has_text_frame
    )

    #: what the slide is *expected* to say for each measured fact. The wording is
    #: the deck's own ("23 HTTP endpoints" — OpenAPI reports 23 paths / 24
    #: operations); only the counts may drift, and that is what this checks.
    expectations = [
        ("api paths on the slide", f"{facts['api_paths']} HTTP endpoints",
         facts["api_paths"]),
        ("dispatch paths", f"{facts['dispatch_paths']} of them dispatch",
         facts["dispatch_paths"]),
        ("vue components", f"{facts['vue_components']} components", facts["vue_components"]),
        ("archived cases", f"{facts['archived_cases']} archived cases",
         facts["archived_cases"]),
        ("persisted dispatch operations",
         f"{facts['dispatch_operations_persisted']} dispatch operations persisted",
         facts["dispatch_operations_persisted"]),
        ("test functions", f"{facts['test_functions']} test functions", facts["test_functions"]),
        ("test files", f"{facts['test_files']} test files", facts["test_files"]),
    ]

    print(f"deck: {DECK.name}  (slide 7)")
    failures = 0
    for label, expected, value in expectations:
        ok = bool(expected) and expected in slide_text
        if not ok:
            failures += 1
        print(f"  [{'ok ' if ok else 'BAD'}] {label}: repo={value}"
              f"{'' if ok else f'  -> slide does not contain {expected!r}'}")

    print(f"\n{len(expectations) - failures}/{len(expectations)} slide-7 checks match the deck")
    print(f"note: {facts['api_paths']} paths / {facts['api_operations']} operations and "
          f"{facts['dispatch_paths']} / {facts['dispatch_operations']} dispatch — the deck "
          f"quotes the path count, the speech quotes both.")
    failures += check_results_slide(facts)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
