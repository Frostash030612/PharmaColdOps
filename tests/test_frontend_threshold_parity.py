"""Frontend threshold constants must stay in lockstep with the engine's
``rules_config.json`` (DAILY_PLAN D 9/12 ③: one source, no drifting copies).

A's 9/11 rules_config v1.0 hand-updated the JS literals in both frontends;
this test pins that parity so a future threshold change that forgets the
frontends fails here instead of showing stale numbers in the demo.

2026-09-14 追加：**阈值有 parity，处置档原先没有**。rubric v1.1 把第 4 条由
`quarantine` 改为 `scrap` 时，三份 JS 副本（两个静态页 + Vue 的 `lib/engine.js`）
就静默地与 Python 引擎分了叉——离线模式（`?api=` 为空）说 quarantine、
API 模式说 scrap，**演示里能同时看到两个答案，而没有任何测试会红**。
``test_clause4_disposition_matches_engine_in_all_js_copies`` 补上这个缺口：
期望值直接向引擎索取，故以后改政策只需改一处，三份副本漏改会立刻失败。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from rule_engine.engine import RuleEngine
from rule_engine.models import ExcursionEvent

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "src" / "rule_engine" / "rules_config.json"
FRONTENDS = [
    REPO / "frontend" / "index.html",
    REPO / "frontend" / "index-zh.html",
    REPO / "frontend-vue" / "src" / "data" / "products.js",
]

#: 三份 JS 副本里「第 4 条」返回处置档的写法（静态页用 decide()，Vue 用元组）。
CLAUSE4_SITES = [
    (REPO / "frontend" / "index.html", r'return\s+decide\("(\w+)",\s*4\)'),
    (REPO / "frontend" / "index-zh.html", r'return\s+decide\("(\w+)",\s*4\)'),
    (REPO / "frontend-vue" / "src" / "lib" / "engine.js",
     r'return\s+\["(\w+)",\s*4\]'),
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


def test_clause4_disposition_matches_engine_in_all_js_copies():
    """第 4 条（时长或 MKT 任一越限）的处置档，三份 JS 副本必须与引擎一致。

    期望值**不写死**：直接向 Python 引擎索取，故以后改政策只需改引擎一处，
    漏改任何一份 JS 副本都会在这里失败。夹具先自证命中第 4 条，
    否则断言会因为规则顺序变化而变成空转。
    """
    engine = RuleEngine()
    # insulin_2_8：时长 35 > 允许 30，MKT 10.8 > 阈值 10 → 恰命中第 4 条
    decision = engine.evaluate(
        ExcursionEvent("PARITY4", "insulin_2_8", 11.0, 35, 10.8, "intact", "transit")
    )
    assert decision.rule_no == 4, (
        f"夹具没命中第 4 条（实际第 {decision.rule_no} 条），本测试失去意义"
    )
    expected = decision.disposition.value

    for path, pattern in CLAUSE4_SITES:
        m = re.search(pattern, path.read_text(encoding="utf-8"))
        assert m, (
            f"{path.name}: 找不到第 4 条的返回语句——写法变了？"
            f"（模式 {pattern}）"
        )
        assert m.group(1) == expected, (
            f"{path.name}: 第 4 条处置为 {m.group(1)!r}，引擎为 {expected!r}。"
            "离线模式与 API 模式会给出不同答案（见本文件 docstring）。"
        )
