"""Rule engine vs. gold-standard scenario bank (proposal §8.3, steps 1 & 4).

`scenarios.csv` 的 `gold_label` 列自 2026-09-12 起是**独立人工标注的终版 gold**
（B、C 双人盲标 → 仲裁），不再是引擎自身的输出。

因此本文件**不再断言「引擎 == gold」**：那等于让引擎给自己判卷，正是提案 §8.3
要打破的反循环。现在断言的是「引擎与 gold 的已知偏离被完整冻结」——
任何**新增**偏离都会失败并指名道姓，迫使人二选一：修引擎，或把该条登记进
`KNOWN_GOLD_DEVIATIONS` 并写明依据。

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

#: 引擎（忠实实现 rubric v1）与终版 gold 的**全部** 18 条偏离。
#: 元组 = (引擎应判, gold 实际判, 分歧类别)。
#:
#: 这 18 条**不是引擎 bug**：两人独立标注都越过了 rubric 字面，责任在说明书不在引擎。
#: 真正要修的是规则文本（rubric v1.1），修完重测后本表应随之收缩。
KNOWN_GOLD_DEVIATIONS = {
    # ── 阈值政策分歧（5 条）────────────────────────────────────────────
    # 政策：时长或 MKT 任一越限即 scrap。rubric v1 第 4 条字面给的是 quarantine。
    "S017": ("quarantine", "scrap", "阈值政策分歧"),
    "S018": ("quarantine", "scrap", "阈值政策分歧"),
    "S038": ("quarantine", "scrap", "阈值政策分歧"),
    "S039": ("quarantine", "scrap", "阈值政策分歧"),
    "S040": ("quarantine", "scrap", "阈值政策分歧"),
    # ── 规范缺口（13 条）──────────────────────────────────────────────
    # 两人答案**完全相同**，且**都与 rubric 不符**——责任在说明书，不在标注者。
    "S019": ("quarantine", "scrap", "规范缺口"),
    "S020": ("quarantine", "scrap", "规范缺口"),
    "S021": ("quarantine", "scrap", "规范缺口"),
    "S022": ("quarantine", "scrap", "规范缺口"),
    "S023": ("quarantine", "scrap", "规范缺口"),
    "S024": ("quarantine", "scrap", "规范缺口"),
    "S034": ("release", "quarantine", "规范缺口"),
    "S035": ("release", "quarantine", "规范缺口"),
    "S041": ("quarantine", "scrap", "规范缺口"),
    "S042": ("quarantine", "scrap", "规范缺口"),
    "S052": ("retest", "quarantine", "规范缺口"),
    "S053": ("quarantine", "scrap", "规范缺口"),
    "S056": ("quarantine", "scrap", "规范缺口"),
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
    """除冻结的 18 条外，引擎必须与 gold 一致。"""
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
    """冻结的 18 条：引擎侧与 gold 侧都必须与登记值一致（任一侧漂移都要失败）。"""
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
    """把结论数字本身钉住：引擎 vs 终版 gold = 39/57 = 68.4%。

    这个数字低不是失败——它是提案 §8.3 反循环设计**要测出来的东西**。
    分母的变化必须是有意识的（改 rubric 后重测），不能是悄悄漂移。
    """
    engine = RuleEngine()
    rows = _load_scenarios()
    agree = sum(
        1 for r in rows
        if engine.evaluate(_event(r)).disposition.value == r["gold_label"]
    )
    assert (agree, len(rows)) == (39, 57), (
        f"引擎 vs gold 一致率变成 {agree}/{len(rows)}"
        f"（登记值为 39/57）。见 docs/annotation_findings_v1.md。"
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
    insulin = engine.evaluate(ExcursionEvent("N1", "insulin_2_8", 11.0, 35, 10.8, "intact", "transit"))
    assert insulin.disposition.value == "quarantine"
    mrna = engine.evaluate(ExcursionEvent("N2", "mrna_ultracold", -30.0, 150, -35.0, "intact", "warehouse"))
    assert mrna.disposition.value == "scrap"


def test_decision_carries_regulation():
    engine = RuleEngine()
    event = ExcursionEvent("R1", "vaccine_2_8", 12.0, 35, 11.2, "intact", "airport_dwell")
    decision = engine.evaluate(event)
    assert decision.regulation
    assert ("WHO" in decision.regulation) or ("GDP" in decision.regulation)
    assert decision.evidence["regulation"] == decision.regulation
