"""Disposition rule engine for cold-chain temperature excursions.

The engine is deliberately deterministic and rule-based (not a classifier) so
that every decision carries an auditable rule path, per WHO TRS 961 Annex 9 and
EU GDP 2013/C 343/01. Thresholds live in :file:`rules_config.json` and are
placeholders to be replaced with product-specific stability data.

Rules are evaluated in priority order; the first match wins.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from .models import Decision, Disposition, ExcursionEvent, ProductSpec

CONFIG_PATH = Path(__file__).parent / "rules_config.json"

# Freeze damage is ice formation, which occurs at or below the freezing point of
# water. WHO TRS 961 Annex 9 §6.9 (Shipping container packing) requires that
# freeze-sensitive products be protected against temperatures below 0 °C; the
# *disposition* below (discard) is a project rule for irreversible freeze damage,
# not a WHO clause — Annex 9's disposal clauses (§8.6.x) are assessment-first.
# Per-field provenance: docs/阈值证据表_v1.md.
FREEZING_POINT_C = 0.0


def _load_specs() -> Dict[str, ProductSpec]:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {s["product_id"]: ProductSpec(**s) for s in raw["products"]}


class RuleEngine:
    def __init__(self, specs: Optional[Dict[str, ProductSpec]] = None):
        self.specs = specs or _load_specs()

    def evaluate(self, event: ExcursionEvent) -> Decision:
        spec = self.specs[event.product_id]

        # 1. Freeze damage: freeze-sensitive products lose potency once frozen.
        #    NOTE: cold-but-not-frozen (storage_min < temp <= 0 °C) is not covered
        #    here; it falls through to the duration/MKT rules below (a candidate
        #    for a lower-severity rule later).
        if spec.freeze_sensitive and event.excursion_temp_c <= FREEZING_POINT_C:
            return self._decide(
                Disposition.SCRAP,
                spec,
                event,
                "freeze damage; freeze-sensitive product exposed below freezing point",
                "WHO TRS 961 Annex 9 §6.9 — freeze-sensitive products must be protected "
                "against temperatures below 0 °C; discarding a frozen batch is the project "
                "rule for irreversible freeze damage",
                rule_no=1,
            )

        # 2. Compromised packaging during an excursion is unacceptable.
        if event.packaging == "compromised" and event.excursion_temp_c > spec.storage_max_c:
            return self._decide(
                Disposition.SCRAP,
                spec,
                event,
                "packaging compromised during excursion",
                "EU GDP 2013/C 343/01 — packaging integrity must be preserved during transport",
                rule_no=2,
            )

        # 3. Severe excursion (≫ allowable, or MKT well above threshold) → scrap.
        if event.duration_min >= 2 * spec.allowable_duration_min or event.mkt_c >= spec.mkt_threshold_c + 3.0:
            return self._decide(
                Disposition.SCRAP,
                spec,
                event,
                "excursion severity beyond any acceptable margin",
                "WHO TRS 961 Annex 9 — excursion beyond acceptable stability margin",
                rule_no=3,
            )

        # 4. Exceeds allowable duration or MKT threshold → scrap + reship.
        #    Policy: any overrun (strictly greater) is unacceptable, with no
        #    intermediate hold band. Confirmed independently by both annotators in
        #    the 2026-09-11 blind test and already reflected in the gold labels.
        #    rubric v1 stated `quarantine` here; rubric v1.1 changes this clause to
        #    `scrap` and this engine follows it — see
        #    docs/annotation_rubric_v1.1.md §0.1–§0.2 for the decision record.
        if event.duration_min > spec.allowable_duration_min or event.mkt_c > spec.mkt_threshold_c:
            return self._decide(
                Disposition.SCRAP,
                spec,
                event,
                "exceeded allowable excursion; any overrun is unacceptable (no hold band)",
                "WHO TRS 961 Annex 9 / EU GDP 2013/C 343/01 — excursion beyond the labelled "
                "range requires assessment; project policy (both annotators, 2026-09-11) "
                "treats any overrun as unacceptable",
                rule_no=4,
            )

        # 5. Within allowable but near the edge → retest to confirm.
        if spec.retestable and (
            event.duration_min >= 0.8 * spec.allowable_duration_min
            or event.mkt_c >= spec.mkt_threshold_c - 0.5
        ):
            return self._decide(
                Disposition.RETEST,
                spec,
                event,
                "within limits but near threshold; confirm by testing",
                "EU GDP 2013/C 343/01 — confirm within-threshold excursions by testing",
                rule_no=5,
            )

        # 6. Otherwise the excursion is negligible.
        return self._decide(
            Disposition.RELEASE,
            spec,
            event,
            "excursion within acceptable safety range",
            "WHO TRS 961 Annex 9 — within acceptable range",
            rule_no=6,
        )

    def _decide(
        self,
        disposition: Disposition,
        spec: ProductSpec,
        event: ExcursionEvent,
        reason: str,
        regulation: str,
        rule_no: int,
    ) -> Decision:
        rule_path = (
            f"{spec.product_id} ({spec.storage_min_c:g}–{spec.storage_max_c:g} °C) "
            f"at {event.excursion_temp_c:g} °C for {event.duration_min} min "
            f"(MKT {event.mkt_c:g} °C, allowable {spec.allowable_duration_min} min) "
            f"→ {disposition.value}: {reason}"
        )
        reshipment = disposition in (Disposition.SCRAP, Disposition.QUARANTINE)
        return Decision(
            disposition=disposition,
            reshipment_required=reshipment,
            rule_path=rule_path,
            rule_no=rule_no,
            reason=reason,
            regulation=regulation,
            evidence={
                "product_id": spec.product_id,
                "excursion_temp_c": event.excursion_temp_c,
                "duration_min": event.duration_min,
                "mkt_c": event.mkt_c,
                "packaging": event.packaging,
                "stage": event.stage,
                "freeze_sensitive": spec.freeze_sensitive,
                "regulation": regulation,
            },
        )
