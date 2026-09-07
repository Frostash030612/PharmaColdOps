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


def _load_specs() -> Dict[str, ProductSpec]:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {s["product_id"]: ProductSpec(**s) for s in raw["products"]}


class RuleEngine:
    def __init__(self, specs: Optional[Dict[str, ProductSpec]] = None):
        self.specs = specs or _load_specs()

    def evaluate(self, event: ExcursionEvent) -> Decision:
        spec = self.specs[event.product_id]

        # 1. Compromised packaging during an excursion is unacceptable.
        if event.packaging == "compromised" and event.excursion_temp_c > spec.storage_max_c:
            return self._decide(
                Disposition.SCRAP, spec, event, "packaging compromised during excursion"
            )

        # 2. Severe excursion (≫ allowable, or MKT well above threshold) → scrap.
        if event.duration_min >= 2 * spec.allowable_duration_min or event.mkt_c >= spec.mkt_threshold_c + 3.0:
            return self._decide(
                Disposition.SCRAP, spec, event, "excursion severity beyond any acceptable margin"
            )

        # 3. Exceeds allowable duration or MKT threshold → quarantine + assess.
        if event.duration_min > spec.allowable_duration_min or event.mkt_c > spec.mkt_threshold_c:
            return self._decide(
                Disposition.QUARANTINE, spec, event, "exceeded allowable excursion; hold for quality assessment"
            )

        # 4. Within allowable but near the edge → retest to confirm.
        if spec.retestable and (
            event.duration_min >= 0.8 * spec.allowable_duration_min
            or event.mkt_c >= spec.mkt_threshold_c - 0.5
        ):
            return self._decide(
                Disposition.RETEST, spec, event, "within limits but near threshold; confirm by testing"
            )

        # 5. Otherwise the excursion is negligible.
        return self._decide(
            Disposition.RELEASE, spec, event, "excursion within acceptable safety range"
        )

    def _decide(
        self, disposition: Disposition, spec: ProductSpec, event: ExcursionEvent, reason: str
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
            evidence={
                "product_id": spec.product_id,
                "excursion_temp_c": event.excursion_temp_c,
                "duration_min": event.duration_min,
                "mkt_c": event.mkt_c,
                "packaging": event.packaging,
                "stage": event.stage,
            },
        )
