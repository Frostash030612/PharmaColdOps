"""Rule engine vs. gold-standard scenario bank (proposal §8.3, steps 1 & 4).

`scenarios.csv` 的 `gold_label` 列自 2026-09-12 起是**独立人工标注的终版 gold**
（B、C 双人盲标 → 仲裁），不再是引擎自身的输出。

因此本文件**不再断言「引擎 == gold」**：那等于让引擎给自己判卷，正是提案 §8.3
要打破的反循环。现在断言的是「引擎与 gold 的已知偏离被完整冻结」——
任何**新增**偏离都会失败并指名道姓，迫使人二选一：修引擎，或把该条登记进
`KNOWN_GOLD_DEVIATIONS` 并写明依据。

**2026-09-14 · rubric v1.1 落地后本表由 18 条收缩为 3 条**：v1.1 把第 4 条的处置由
`quarantine` 改为 `scrap`（政策：时长或 MKT 任一越限即报废，不设缓冲档），
该档位在全库命中 15 条、其 gold 全部是 `scrap`，故这 15 条一次性从偏离表消失。
引擎 vs gold 一致率随之由 39/57 升为 54/57。决策记录见
`docs/annotation_rubric_v1.1.md` §0.1–§0.2。

剩余 3 条**不指向引擎，而指向 gold 自身**（S034/S035 为场景次序产物，
S052 为 0.1 的边界），按「gold 侧待复核」登记，本轮不改 gold。

偏离的逐条依据见 `docs/annotation_findings_v1.md`；分歧类别与来源见
`data/scenarios/gold_labels.csv` 的 `decision_source` / `disagreement_type` 列。
"""
import csv
from pathlib import Path

from rule_engine.engine import RuleEngine
from rule_engine.models import ExcursionEvent

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data" / "scenarios" / "scenarios.csv"
GOLD_LABELS = ROOT / "data" / "scenarios" / "gold_labels.csv"

#: 引擎（忠实实现 rubric v1.1）与终版 gold 的**全部** 3 条偏离。
#: 元组 = (引擎应判, gold 实际判, 分歧类别)。
#:
#: 这 3 条**不是引擎 bug，也不是 rubric 缺陷**——v1.1 之后它们指向 gold 自身：
#:   S034/S035  findings §6.1 已证明该批 frozen_m20 暖端异常由场景排列次序造成
#:              （打乱次序并摆出规则后两人全判 release）；
#:   S052       第 5 条复检线为 9.5，该条 mkt = 9.6，只差 0.1（findings §5.3）。
#: 本轮决定**不改 gold**（改金标准会移动 9/19 引擎评估基线），故按待复核登记。
KNOWN_GOLD_DEVIATIONS = {
    # ── gold 侧待复核（3 条）──────────────────────────────────────────
    "S034": ("release", "quarantine", "规范缺口"),
    "S035": ("release", "quarantine", "规范缺口"),
    "S052": ("retest", "quarantine", "规范缺口"),
}


def _load_scenarios():
    with SCENARIOS.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _event(row):
    return ExcursionEvent(
        scenario_id=row["scenario_id"],
        product_id=row["product_id"],
        excursion_temp_c=float(row["excursion_temp_c"]),
        duration_min=int(row["duration_min"]),
        mkt_c=float(row["mkt_c"]),
        packaging=row["packaging"],
        stage=row["stage"],
    )


def test_engine_matches_gold_outside_known_deviations():
    """除冻结的 3 条外，引擎必须与 gold 一致。"""
    engine = RuleEngine()
    unexplained = []
    for row in _load_scenarios():
        if row["scenario_id"] in KNOWN_GOLD_DEVIATIONS:
            continue
        got = engine.evaluate(_event(row)).disposition.value
        if got != row["gold_label"]:
            unexplained.append(
                f"{row['scenario_id']}: gold={row['gold_label']} 引擎={got} "
                f"— {engine.evaluate(_event(row)).rule_path}"
            )
    assert not unexplained, (
        "出现未登记的引擎-gold 偏离。修引擎，或登记进 KNOWN_GOLD_DEVIATIONS 并写明依据：\n  "
        + "\n  ".join(unexplained)
    )


def test_known_deviations_are_frozen():
    """冻结的 3 条：引擎侧与 gold 侧都必须与登记值一致（任一侧漂移都要失败）。"""
    engine = RuleEngine()
    for row in _load_scenarios():
        sid = row["scenario_id"]
        if sid not in KNOWN_GOLD_DEVIATIONS:
            continue
        eng_expected, gold_expected, kind = KNOWN_GOLD_DEVIATIONS[sid]
        got = engine.evaluate(_event(row)).disposition.value
        assert got == eng_expected, (
            f"{sid}: 引擎行为变了 {eng_expected} -> {got}（{kind}）。"
            "若 rubric v1.1 已修好这条，把它从 KNOWN_GOLD_DEVIATIONS 移除。"
        )
        assert row["gold_label"] == gold_expected, (
            f"{sid}: gold 变了 {gold_expected} -> {row['gold_label']}（{kind}）"
        )


def test_deviation_freeze_matches_provenance():
    """冻结清单必须与 `gold_labels.csv` 的分歧类别逐条对齐，防止两边各自漂移。"""
    with GOLD_LABELS.open(newline="", encoding="utf-8-sig") as f:
        prov = {r["scenario_id"]: r for r in csv.DictReader(f)}
    missing = sorted(set(KNOWN_GOLD_DEVIATIONS) - set(prov))
    assert not missing, f"冻结清单里的场景不在 gold_labels.csv 中：{missing}"
    for sid, (_, _, kind) in KNOWN_GOLD_DEVIATIONS.items():
        assert prov[sid]["decision_source"] == "arbitration", (
            f"{sid}: 冻结表列为偏离，凭证却记 decision_source="
            f"{prov[sid]['decision_source']!r}（应为 arbitration）"
        )
        assert prov[sid]["disagreement_type"] == kind, (
            f"{sid}: 冻结表记 {kind!r}，凭证记 {prov[sid]['disagreement_type']!r}"
        )


def test_gold_agreement_rate():
    """把结论数字本身钉住：引擎 vs 终版 gold = 54/57 = 94.7%。

    分母的变化必须是**有意识的**（改 rubric 后同步更新），不能是悄悄漂移。
    沿革：rubric v1 下为 39/57（68.4%）——那 18 条不是引擎的错，其中 15 条是
    v1 第 4 条漏掉了「越限即报废」这条已确认政策。v1.1 补上后升至 54/57，
    残留 3 条指向 gold 自身（见 KNOWN_GOLD_DEVIATIONS 的说明）。
    """
    engine = RuleEngine()
    rows = _load_scenarios()
    agree = sum(
        1 for r in rows
        if engine.evaluate(_event(r)).disposition.value == r["gold_label"]
    )
    assert (agree, len(rows)) == (54, 57), (
        f"引擎 vs gold 一致率变成 {agree}/{len(rows)}"
        f"（登记值为 54/57）。见 docs/annotation_rubric_v1.1.md §0.1。"
    )


def test_scrap_triggers_reshipment():
    engine = RuleEngine()
    event = ExcursionEvent("T1", "vaccine_2_8", 20.0, 90, 19.0, "intact", "transit")
    decision = engine.evaluate(event)
    assert decision.disposition.value == "scrap"
    assert decision.reshipment_required is True


def test_release_does_not_trigger_reshipment():
    engine = RuleEngine()
    event = ExcursionEvent("T2", "vaccine_2_8", 6.0, 10, 5.0, "intact", "transit")
    decision = engine.evaluate(event)
    assert decision.disposition.value == "release"
    assert decision.reshipment_required is False


def test_freeze_damage_triggers_scrap():
    engine = RuleEngine()
    event = ExcursionEvent("F1", "vaccine_2_8", -5.0, 5, 4.0, "intact", "transit")
    decision = engine.evaluate(event)
    assert decision.disposition.value == "scrap"
    assert decision.reshipment_required is True
    assert "freeze" in decision.rule_path.lower()


def test_frozen_product_not_freeze_sensitive():
    engine = RuleEngine()
    event = ExcursionEvent("F2", "frozen_m20", -30.0, 5, -28.0, "intact", "transit")
    decision = engine.evaluate(event)
    assert decision.disposition.value == "release"


def test_new_products_load_and_evaluate():
    engine = RuleEngine()
    assert "insulin_2_8" in engine.specs
    assert "mrna_ultracold" in engine.specs
    # rubric v1.1 第 4 条：时长 35 > 允许 30（严格大于）→ scrap（v1 为 quarantine）。
    # 这里同时锁住档位与命中条款号，使「越限即报废、不设缓冲档」这条政策
    # 一旦被改回就立刻失败，而不是等到 gold 一致率变化才被发现。
    insulin = engine.evaluate(ExcursionEvent("N1", "insulin_2_8", 11.0, 35, 10.8, "intact", "transit"))
    assert insulin.disposition.value == "scrap"
    assert insulin.rule_no == 4
    assert insulin.reshipment_required is True
    mrna = engine.evaluate(ExcursionEvent("N2", "mrna_ultracold", -30.0, 150, -35.0, "intact", "warehouse"))
    assert mrna.disposition.value == "scrap"


def test_decision_carries_regulation():
    engine = RuleEngine()
    event = ExcursionEvent("R1", "vaccine_2_8", 12.0, 35, 11.2, "intact", "airport_dwell")
    decision = engine.evaluate(event)
    assert decision.regulation
    assert ("WHO" in decision.regulation) or ("GDP" in decision.regulation)
    assert decision.evidence["regulation"] == decision.regulation
