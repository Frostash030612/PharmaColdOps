"""Single-source guard: the front-ends' default product specs must not drift.

Product thresholds are authoritative in ``src/rule_engine/rules_config.json``
(Python). In offline mode the vanilla and Vue front-ends evaluate with their
*own* embedded default spec (``PRODUCTS`` / ``PRODUCT_NUM``), which is a
second copy that can silently drift when the config is edited (A re-verifies
thresholds against WHO/GDP sources around 9/11 — any change there must land in
all three JS copies too, or offline mode stops matching the backend).

These tests assert each JS default equals the config for every product, so a
config edit that forgets the JS copies fails loudly instead of diverging at
demo time.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "src" / "rule_engine" / "rules_config.json"
# (label, file with the per-product default spec literal)
SPEC_SOURCES = (
    ("vanilla EN", ROOT / "frontend" / "index.html"),
    ("vanilla ZH", ROOT / "frontend" / "index-zh.html"),
    ("vue", ROOT / "frontend-vue" / "src" / "data" / "products.js"),
)
# JS field → rules_config.json key
_JS_FIELDS = {
    "min": "storage_min_c",
    "max": "storage_max_c",
    "allowable": "allowable_duration_min",
    "mktThreshold": "mkt_threshold_c",
    "retestable": "retestable",
    "freezeSensitive": "freeze_sensitive",
}
_NUMERIC = {"min", "max", "allowable", "mktThreshold"}


def _config_specs() -> dict:
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    return {p["product_id"]: p for p in raw["products"]}


def _parse_product_line(text: str, pid: str) -> dict:
    """Extract the six spec fields from one ``<pid>: { ... }`` literal."""
    m = re.search(rf"^\s*{re.escape(pid)}:\s*\{{(.*?)\}}", text, re.M | re.S)
    if not m:
        raise AssertionError(f"no spec literal found for {pid!r}")
    body = m.group(1)
    out = {}
    for js_key in _JS_FIELDS:
        fm = re.search(rf"\b{js_key}:\s*(-?[\d.]+|true|false)\b", body)
        assert fm, f"{pid}: missing field {js_key} in {body!r}"
        out[js_key] = fm.group(1)
    return out


def _js_bool(s: str) -> bool:
    assert s in ("true", "false"), f"expected JS boolean, got {s!r}"
    return s == "true"


@pytest.mark.parametrize("label,path", SPEC_SOURCES)
@pytest.mark.parametrize(
    "pid",
    ["vaccine_2_8", "frozen_m20", "insulin_2_8", "mrna_ultracold"],
)
def test_offline_default_spec_matches_rules_config(label, path, pid):
    if not path.exists():
        pytest.fail(f"{label}: file missing — {path}")
    text = path.read_text(encoding="utf-8")
    js = _parse_product_line(text, pid)
    cfg = _config_specs()[pid]

    for js_key, cfg_key in _JS_FIELDS.items():
        if js_key in _NUMERIC:
            got, want = float(js[js_key]), float(cfg[cfg_key])
        else:
            got, want = _js_bool(js[js_key]), bool(cfg[cfg_key])
        assert got == want, (
            f"{label} {pid}: {js_key} ({got}) != rules_config {cfg_key} ({want})\n"
            f"  Edit rules_config.json together with all three JS copies "
            f"({[p for _, p in SPEC_SOURCES]})."
        )


@pytest.mark.parametrize("label,path", SPEC_SOURCES)
def test_all_four_products_present(label, path):
    text = path.read_text(encoding="utf-8")
    for pid in ("vaccine_2_8", "frozen_m20", "insulin_2_8", "mrna_ultracold"):
        assert re.search(rf"^\s*{pid}:\s*\{{", text, re.M), f"{label}: missing {pid}"
