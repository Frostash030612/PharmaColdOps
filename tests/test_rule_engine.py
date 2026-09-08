"""Rule engine vs. gold-standard scenario bank (proposal §8.3, steps 1 & 4)."""
import csv
from pathlib import Path

from rule_engine.engine import RuleEngine
from rule_engine.models import ExcursionEvent

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data" / "scenarios" / "scenarios.csv"


def _load_scenarios():
    with SCENARIOS.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_engine_matches_gold_labels():
    engine = RuleEngine()
    for row in _load_scenarios():
        event = ExcursionEvent(
            scenario_id=row["scenario_id"],
            product_id=row["product_id"],
            excursion_temp_c=float(row["excursion_temp_c"]),
            duration_min=int(row["duration_min"]),
            mkt_c=float(row["mkt_c"]),
            packaging=row["packaging"],
            stage=row["stage"],
        )
        decision = engine.evaluate(event)
        assert decision.disposition.value == row["gold_label"], (
            f"{row['scenario_id']}: expected {row['gold_label']}, "
            f"got {decision.disposition.value} — {decision.rule_path}"
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
