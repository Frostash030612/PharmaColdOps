#!/usr/bin/env python
"""Syntax-check the inline <script> blocks of the demo HTML files.

The demo ships as self-contained HTML with one inline script per file (plus the
external real_data.js). A quick esprima parse catches syntax errors introduced
by edits without needing a DOM or node.

Usage:  python scripts/check_demo_js.py [frontend/index.html ...]
"""
import re
import sys
from pathlib import Path

import esprima

ROOT = Path(__file__).resolve().parents[1]


def script_blocks(html: str):
    return [m.group(1) for m in
            re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", html)]


def main(argv) -> int:
    files = [Path(a) for a in argv] or [ROOT / "frontend" / "index.html", ROOT / "frontend" / "index-zh.html"]
    ok = True
    for f in files:
        if not f.exists():
            print(f"[missing] {f}")
            ok = False
            continue
        blocks = script_blocks(f.read_text(encoding="utf-8"))
        for i, src in enumerate(blocks):
            try:
                esprima.parseScript(src)
                print(f"[ok] {f} script#{i + 1} ({len(src.splitlines())} lines)")
            except esprima.Error as exc:
                ok = False
                print(f"[FAIL] {f} script#{i + 1}: {exc}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
