"""Frontend threshold constants must stay in lockstep with the engine's
``rules_config.json`` (DAILY_PLAN D 9/12 ③: one source, no drifting copies).

A's 9/11 rules_config v1.0 hand-updated the JS literals in both frontends;
this test pins that parity so a future threshold change that forgets the
frontends fails here instead of showing stale numbers in the demo.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "src" / "rule_engine" / "rules_config.json"
FRONTENDS = [
    REPO / "frontend" / "index.html",
    REPO / "frontend" / "index-zh.html",
    REPO / "frontend-vue" / "src" / "data" / "products.js",
]


def _num(x: float) -> str:
    """Accept either JS formatting of the same value (``2`` or ``2.0``)."""
    return rf"(?:{x:g}|{x:.1f})"


def test_frontend_thresholds_match_rules_config():
    products = json.loads(CONFIG.read_text(encoding="utf-8"))["products"]
    for p in products:
        # mirrors the JS literal shape:
        #   pid: { id: "pid", ..., min: X, max: Y, allowable: N,
        #          mktThreshold: T, retestable: b, freezeSensitive: b }
        needle = re.compile(
            re.escape(p['product_id']) + r":\s*\{[^}}]*?"
            rf"min:\s*{_num(p['storage_min_c'])},\s*max:\s*{_num(p['storage_max_c'])},"
            rf"[^}}]*?allowable:\s*{_num(p['allowable_duration_min'])},"
            rf"[^}}]*?mktThreshold:\s*{_num(p['mkt_threshold_c'])}"
            rf"[^}}]*?retestable:\s*{str(p['retestable']).lower()}"
            rf"[^}}]*?freezeSensitive:\s*{str(p['freeze_sensitive']).lower()}"
        )
        for f in FRONTENDS:
            assert needle.search(f.read_text(encoding="utf-8")), (
                f"{p['product_id']} thresholds out of sync in {f.name}"
            )
