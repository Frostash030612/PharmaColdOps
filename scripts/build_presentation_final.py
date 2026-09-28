"""Build PharmaColdOps-Proposal-Presentation-Final.pptx from PharmaColdOps_tune.pptx.

Why: the tune deck's facts were written before the 9/12-9/14 implementation and were
never re-synced with the proposal. This script (a) fills the real team identity,
(b) removes every claim the proposal itself contradicts, and (c) appends the
sections the IRS presentation guidelines ask for but the deck lacked
(market context, implementation screenshots, quantitative results, challenges,
conclusion).

Run:  .venv/Scripts/python.exe scripts/build_presentation_final.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deck_theme import (  # noqa: E402  (path set above)
    CREAM, DARK_PANEL, DEEP_BLUE, FONT_BODY, FONT_BODY_BOLD, FONT_TITLE, GOLD,
    INK, MUTED, PAPER, SAND, SIZE_BODY, SIZE_CAPTION, SIZE_CARD_HEAD, SIZE_H1,
    SIZE_SMALL, SIZE_TITLE, WHITE,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "proposal" / "PharmaColdOps_tune.pptx"
DST = ROOT / "proposal" / "PharmaColdOps-Proposal-Presentation-Final.pptx"

# Colours, fonts and sizes come from deck_theme (measured off the hand-designed
# pages) — do not reintroduce local literal colours here, or the added slides
# drift away from the rest of the deck again.
ACCENT = GOLD


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def para(shape, index: int) -> object:
    return shape.text_frame.paragraphs[index]


def set_para(shape, index: int, text: str, *, keep_run0: bool = True,
             color: RGBColor | None = None, size: Pt | None = None) -> None:
    """Replace a paragraph's text while keeping the first run's formatting."""
    p = para(shape, index)
    runs = p.runs
    if not runs:
        raise AssertionError(f"paragraph {index} of {shape.name} has no run")
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)
    if color is not None:
        runs[0].font.color.rgb = color
    if size is not None:
        runs[0].font.size = size


def set_runs(shape, p_index: int, texts: list[str]) -> None:
    """Replace a paragraph's per-run text, one string per existing run."""
    runs = para(shape, p_index).runs
    if len(runs) != len(texts):
        raise AssertionError(
            f"{shape.name} p{p_index}: {len(runs)} runs vs {len(texts)} texts")
    for r, t in zip(runs, texts):
        r.text = t


def replace_in_run(shape, p_index: int, run_index: int, text: str) -> None:
    para(shape, p_index).runs[run_index].text = text


def find(slide, name: str):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
    raise KeyError(f"{name} not on slide")


def add_slide(prs):
    """A blank slide on the deck's own master at the deck's own size."""
    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)
    xml = slide._element
    for child in list(xml):
        if child.tag.endswith("}sp"):
            xml.remove(child)
    return slide


# --------------------------------------------------------------------------
# deleting slides (python-pptx has no API for this)
# --------------------------------------------------------------------------
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_RT_SLIDE = ("http://schemas.openxmlformats.org/officeDocument/2006/"
             "relationships/slide")


def slide_text(slide) -> str:
    """All text on the slide, for identity checks.

    Using the first shape alone is not enough: some slides start with a small
    kicker label ("GAP ANALYSIS") rather than the real title."""
    return "\n".join(sh.text_frame.text for sh in slide.shapes
                     if sh.has_text_frame and sh.text_frame.text.strip())


def slide_title(slide) -> str:
    for sh in slide.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip():
            return sh.text_frame.text.strip().splitlines()[0]
    return ""


def slide_by_title(prs: Presentation, needle: str):
    """The one slide whose text contains `needle` (a title or a stable phrase)."""
    hits = [s for s in prs.slides if needle in slide_text(s)]
    if len(hits) != 1:
        raise KeyError(f"{needle!r} matched {len(hits)} slides")
    return hits[0]


def delete_slides(prs, titles) -> list[str]:
    """Drop the slides whose title matches, by dropping their sldId entries.

    A slide part that is no longer referenced by the presentation is simply not
    part of the deck any more; leaving the orphaned part in the package is
    harmless (and keeps this from having to rewrite content-type overrides)."""
    ids = prs.slides._sldIdLst
    dropped = []
    for entry in list(ids):
        slide = None
        for candidate in prs.slides:
            if candidate._element is entry and slide is None:
                slide = candidate
        if slide is None:
            continue
        title = slide_title(slide)
        if title in titles:
            prs.part.drop_rel(entry.get(_R_ID))
            ids.remove(entry)
            dropped.append(title)
    return dropped


def style_run(r, *, font: str, size: float, color: str, bold: bool = False,
              italic: bool = False) -> None:
    """Everything the added slides write goes through here.

    The hand-designed pages use Libre Baskerville for headings and DM Sans for
    body text, on cream with a gold accent; runs built with plain python-pptx
    inherit Calibri and looked like a different presentation. Both the latin and
    the east-asian font name are set so Chinese text follows the same families."""
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.name = font
    r.font.color.rgb = RGBColor.from_string(color)
    rPr = r._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.makeelement(qn(tag), {"typeface": font})
        rPr.append(el)


def textbox(slide, left, top, width, height):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    return box, tf


def add_title(slide, text: str, kicker: str | None = None) -> None:
    box, tf = textbox(slide, 0.62, 0.40, 12.1, 0.95)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text
    style_run(r, font=FONT_TITLE, size=SIZE_TITLE, color=INK)
    if kicker:
        box2, tf2 = textbox(slide, 0.66, 1.28, 12.1, 0.4)
        r2 = tf2.paragraphs[0].add_run()
        r2.text = kicker
        style_run(r2, font=FONT_BODY, size=SIZE_SMALL, color=MUTED)
    # A hairline under the title, the way the designed pages separate the head
    # from the body.
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.62), Inches(1.20),
                                  Inches(2.2), Pt(1.6))
    rule.fill.solid()
    rule.fill.fore_color.rgb = RGBColor.from_string(GOLD)
    rule.line.fill.background()
    rule.shadow.inherit = False


def add_bullets(slide, items, *, left=0.62, top=1.75, width=12.1, height=5.0,
                size=17, space=10, color=INK, marker="●", name: str | None = None):
    box, tf = textbox(slide, left, top, width, height)
    if name:
        # Give the block the slide-local name the design uses ("TextBox 3"), so
        # the short build can find it by name instead of guessing: python-pptx
        # auto-names new text boxes sequentially, which drifts when a slide is
        # rebuilt with a different number of shapes.
        box._element.nvSpPr.cNvPr.set("name", name)
    for i, item in enumerate(items):
        sub = isinstance(item, tuple)
        text = item[1] if sub else item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = 1 if sub else 0
        p.space_after = Pt(space)
        r = p.add_run()
        r.text = ("– " if sub else f"{marker} ") + text
        style_run(r, font=FONT_BODY, size=(size - 2 if sub else size),
                  color=(MUTED if sub else color))
    return box


def add_footer(slide, text: str, *, name: str | None = None) -> None:
    box, tf = textbox(slide, 0.62, 6.85, 12.1, 0.4)
    if name:
        box._element.nvSpPr.cNvPr.set("name", name)
    r = tf.paragraphs[0].add_run()
    r.text = text
    style_run(r, font=FONT_BODY, size=SIZE_CAPTION, color=MUTED, italic=True)


# --------------------------------------------------------------------------
# 1. corrections to the existing 12 slides
# --------------------------------------------------------------------------
def fix_existing(prs: Presentation) -> None:
    # --- Slide 1: real identity, real presentation date -------------------
    s1 = prs.slides[0]
    t2 = find(s1, "Text 2")
    # The title block is 6.89in wide at 14.5pt, so a paragraph must stay within
    # about 126 characters or it wraps and pushes the date line out of the box.
    # The NUS student IDs therefore live in the appendix, not here.
    set_para(t2, 1, "Project Group 41 · Xu Wenzhe · Zhu Jianyu · Wang Lepeng · Shen Ziyi")
    set_para(t2, 2, "IRS Practice Module · Proposal Presentation · 22 Sep 2026")

    # --- Slide 2: drop the blanket "everything is manual" claim ----------
    s2 = prs.slides[1]
    set_para(find(s2, "Text 9"), 0, "Mixed Handling, Weak Traceability")
    set_para(find(s2, "Text 10"), 0,
             "Practices vary by site and shift; the reasoning behind a disposition "
             "is rarely reconstructable.")

    # --- Slide 3: soften the patient/supply claim ------------------------
    s3 = prs.slides[2]
    set_para(find(s3, "Text 8"), 0,
             "Depend on correct outcomes — fewer improper releases, fewer avoidable shortages.")

    # --- Slide 4: the proposal forbids the "alert-only vendors" claim ----
    # Every replacement below is kept within the character budget of the string it
    # replaces: the deck's placeholders come from a design tool and rely on
    # shrink-to-fit, so text longer than the original made the three columns
    # collide. scripts/check_ppt_text_budget.py checks this per box.
    s4 = prs.slides[3]
    set_para(find(s4, "Text 3"), 0, "Fragmented, Not Absent")
    set_para(find(s4, "Text 4"), 0,
             "Monitoring exists; the gap is an inspectable rule path linking "
             "disposition to order, route and evidence.")
    set_para(find(s4, "Text 7"), 0, "Black-Box AI")
    set_para(find(s4, "Text 8"), 0,
             "A recommendation that cannot show its rule, evidence and limits "
             "will not be signed off in an audit.")

    # --- Slide 5: reshipment is a separate action, not a disposition -----
    s5 = prs.slides[4]
    set_para(find(s5, "Text 6"), 0,
             "Four outcomes with a traceable rule path; reshipment is a separate "
             "logistics action, not a fifth disposition.")
    set_para(find(s5, "Text 10"), 0,
             "Reuses a running vehicle's spare capacity, or sends another one.")
    set_para(find(s5, "Text 14"), 0,
             "Every decision cites its rule, regulation or SOP and evidence limits.")

    # --- Slide 6: root cause is an offline experiment --------------------
    s6 = prs.slides[5]
    set_para(find(s6, "Text 8"), 0, "Candidate causes (offline experiment)")

    # --- Slide 7: name the actual solver and the actual QA technique -----
    s7 = prs.slides[6]
    set_para(find(s7, "Text 9"), 0,
             "Failure classification, candidate causes, SHAP — offline, synthetic data")
    set_para(find(s7, "Text 12"), 0,
             "Neo4j, parameterised Cypher, restricted question routing — not a chatbot")

    # --- Slide 8: no multi-temperature zones / stockout priority yet -----
    s8 = prs.slides[7]
    set_para(find(s8, "Text 4"), 0,
             "LightGBM / XGBoost with SHAP; association, not causal proof.")
    set_para(find(s8, "Text 6"), 0,
             "VRPTW with capacity and time windows (OR-Tools, guided local search); "
             "multi-temperature stays an extension.")

    # --- Slide 9: honest data provenance (the proposal's own wording) ----
    s9 = prs.slides[8]
    set_para(find(s9, "Text 0"), 0, "Data Sources: Verifiable, Disclosed Provenance")
    set_para(find(s9, "Text 8"), 0,
             "Six Solomon instances (c101 … rc201) with published reference solutions.")
    set_para(find(s9, "Text 10"), 0,
             "WHO TRS 961 Annex 9 · EU GDP 2013/C 343/01 · ICH Quality · CDC guidance.")

    # --- Slide 10: evaluation metrics as actually planned ----------------
    s10 = prs.slides[9]
    set_para(find(s10, "Text 9"), 0,
             "Top-1/Top-3 and macro-F1 vs the majority baseline.")
    set_para(find(s10, "Text 12"), 0,
             "Distance, vehicles, on-time rate, violations, unserved orders.")
    set_para(find(s10, "Text 15"), 0,
             "End-to-end latency, identifier linkage, failure states, clean reproduction.")

    # --- Slide 11: scope wording + the plan we are actually on -----------
    s11 = prs.slides[10]
    set_para(find(s11, "Text 0"), 0, "Scoped MVP & Seven-Week Plan")
    set_para(find(s11, "Text 38"), 0,
             "MVP: single-city (Singapore) network · 4 prototype product classes · rule engine "
             "first, then greedy → OR-Tools (GLS). Excluded: ERP/WMS, real IoT, patient data.")

    # --- Slide 12: real risks, real names, real next steps ---------------
    s12 = prs.slides[11]
    set_runs(find(s12, "Text 3"), 0, [
        "Annotator agreement",
        " κ = 0.6434 vs our 0.80 target → report it",
    ])
    set_runs(find(s12, "Text 4"), 0, [
        "Quarantine recall 0/3",
        " 3 gold cases → report support counts",
    ])
    set_runs(find(s12, "Text 5"), 0, [
        "Synthetic data",
        " suspected-synthetic → disclose the limit",
    ])
    set_runs(find(s12, "Text 10"), 0,
             ["Project Lead / Rules", " · Xu Wenzhe: rules, evidence, evaluation, report"])
    set_runs(find(s12, "Text 11"), 0,
             ["Data & ML", " · Zhu Jianyu: data, risk, causes, SHAP, experiments"])
    set_runs(find(s12, "Text 12"), 0,
             ["Optimisation", " · Wang Lepeng: VRPTW, routes, comparison"])
    set_runs(find(s12, "Text 13"), 0,
             ["KG + QA + Frontend", " · Shen Ziyi: KG, QA, API, videos"])
    t9 = find(s12, "Text 9")
    set_runs(t9, 0, ["W1: threshold review; multi-fold risk experiments"])
    set_runs(t9, 1, ["W3: integrated acceptance and failure states"])
    set_para(t9, 2, "W5: reproduce cleanly; videos by 25 Oct")


# --------------------------------------------------------------------------
# 1b. make text fitting deterministic
# --------------------------------------------------------------------------
def normalize_text_fit(prs: Presentation) -> None:
    """Give every text frame the same fitting behaviour.

    The deck's placeholders came from a design tool: some had word wrap off (so a
    long string ran past the shape instead of wrapping) and most had
    ``TEXT_TO_FIT_SHAPE``, which lets PowerPoint shrink the text silently while
    python-pptx or LibreOffice may render it unshrunk — the same slide could look
    right in one renderer and overlap in another. Turning wrapping on everywhere
    and switching autofit to "shrink text on overflow" makes the behaviour
    explicit and identical in PowerPoint, LibreOffice and the export paths.
    """
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            tf = shape.text_frame
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE


# --------------------------------------------------------------------------
# 1c. report any box where the replacement is longer than the text it replaced
# --------------------------------------------------------------------------
def text_budget_report(prs: Presentation) -> list[str]:
    """Flag text boxes whose replacement is longer than the original string.

    This is the only dependable fit signal available offline: the original deck
    was laid out by hand, so its own string length is the design's budget for
    that box. Rendering the deck would be better, but PowerPoint automation does
    not work on this machine (COM refuses to open even the untouched original),
    and a character-width model cannot be calibrated without a render — an
    absolute "lines needed" threshold flagged the designer's own text as
    overflowing.
    """
    original = Presentation(str(SRC))
    # Match slides by title, not by index: the short build deletes and reorders
    # slides, so the same page number no longer means the same slide — comparing
    # by index made this report cry wolf (+300%) on pages nothing had touched.
    budgets = {}
    for slide in original.slides:
        title = slide_title(slide)
        if title:
            budgets[title] = slide_text(slide)

    warnings = []
    for idx, slide in enumerate(prs.slides, 1):
        now = slide_text(slide)
        if not now.strip():
            continue
        was = next((text for title, text in budgets.items() if title in now), None)
        if was is None:
            continue                     # a slide this script added
        if len(now) > len(was) * 1.12 + 8:
            warnings.append(
                f"slide {idx:>2}: {len(was)} -> {len(now)} chars "
                f"({len(now) / max(len(was), 1) - 1:+.0%}) — {now[:52]!r}")
    return warnings


# --------------------------------------------------------------------------
# 2. the slides the guidelines ask for and the deck did not have
# --------------------------------------------------------------------------
def add_scale_slide(prs):
    """What actually exists now, as opposed to what the proposal promised.

    The deck was built from the frozen 2026-09-13 submission, so every slide
    described W0 intentions. This one states the implemented surface instead,
    with numbers that can be re-measured in the repo."""
    s = add_slide(prs)
    add_title(s, "What Is Already Built", "Measured from the repository, 2026-09-27")
    add_bullets(s, [
        "Backend: 23 API paths / 24 operations — disposition, QA, routing and 15 "
        "dispatch paths / 16 operations (plan, confirm, depart, simulated clock, "
        "emergency insert, replay, overnight parking).",
        "Frontend: one Vue 3 client, 23 components and 5 stores (≈5,900 lines); "
        "EN/ZH switch, offline JS engine, ?api= backend mode, Leaflet workspace.",
        "Working data on disk: 25 archived cases (keyword: one per closed inbound "
        "case) and 56 recorded dispatch operations with state persisted in SQLite.",
        "Rules and data: 6 priority rules over 4 prototype product classes, 57 "
        "human-labelled scenarios, 19-node Singapore road network (19×19 matrix).",
        "Tests: 305 test functions across 34 test files (≈5,000 lines) — engine, API "
        "contract, dispatch state machine, provenance and frontend/rule parity.",
        "Still missing and stated as such: Dockerfile/cloud deploy, duplicate-closure "
        "de-duplication, destination-pool expansion, occurrence-facility field.",
    ], size=15, space=10, name="TextBox 3")
    add_footer(s, "Every figure here is re-measurable: /openapi.json, data/audit/runs.jsonl, "
                  "data/audit/dispatch.sqlite3, pytest --collect-only -q.", name="TextBox 4")
    return s


def add_market_slide(prs):
    s = add_slide(prs)
    add_title(s, "Where PharmaColdOps Sits", "Project background · market context and related work")
    add_bullets(s, [
        "Commercial platforms already monitor temperature, give shipment visibility and "
        "automate parts of the quality process — Controlant's Product Stability Automation "
        "determines release status from stability profiles. We do not claim to be first.",
        "Academic foundations we build on: Solomon's VRPTW benchmark (1987), OR-Tools Routing "
        "Solver, gradient-boosted tree models (XGBoost, LightGBM) and SHAP attribution.",
        "The gap we address is not monitoring and not a new algorithm; it is the unbroken, "
        "inspectable chain from temperature event to disposition to replacement order to route "
        "to cited evidence, in one evaluable prototype.",
        "Honest positioning: unverified competitor capabilities are recorded as unknown — "
        "missing public documentation is not evidence of absence.",
    ], size=17, space=14, name="TextBox 3")
    add_footer(s, "Proposal §3.2–3.3 · Figure 1. Market value still requires user interviews and operational data.", name="TextBox 4")
    return s


def add_progress_slide(prs):
    s = add_slide(prs)
    add_title(s, "Implementation: The Loop Is Already Closed", "Implementation progress, 2026-09-18")
    left = 0.62
    # Prefer a current UI capture; fall back to the 2026-09-12 proposal figure
    # (whose layout predates the map-first / transport-view frontend).
    CANDIDATES = [
        (ROOT / "proposal" / "figures" / "frontend_demo.png", 7.4,
         "Screenshot: Vue client in API mode ({date}; route and evidence computed live by the "
         "backend, not mocked)."),
        (ROOT / "proposal" / "figures" / "demo-route-qa-en.png", 7.4,
         "Screenshot: Vue client in API mode, 2026-09-12 (route and evidence computed live by the "
         "backend). Layout predates the current map-first workspace."),
    ]
    img = next(((p, w, cap) for p, w, cap in CANDIDATES if p.exists()), None)
    if img:
        path, width, caption = img
        import datetime
        date = datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
        s.shapes.add_picture(str(path), Inches(left), Inches(1.75), width=Inches(width))
        caption = caption.format(date=date)
    else:
        caption = "Screenshot omitted: no UI capture available in proposal/figures/."
    add_bullets(s, [
        "Rule engine: 6 priority rules, 4 dispositions, run_id-scoped input snapshot and rule path.",
        "Closed-case loop: POST /api/case_close → POST /api/route (case-specific reshipment route) "
        "→ POST /api/qa (cited evidence) → POST /api/dispatch/reshipments (reserves stock, assigns "
        "a vehicle, departs, simulated clock, per-order delivery).",
        "Knowledge graph: Neo4j via docker compose, case-level CITES edges, machine-readable QA "
        "status (ok / no case / insufficient evidence / unsupported); database path verified "
        "end-to-end on 2026-09-13.",
        "Frontend: one Vue 3 + Vite client, EN/ZH switch, offline JS engine, ?api= backend mode, "
        "Leaflet map, dispatch console.",
        "Still missing and stated as such: occurrence-facility field in the close form, "
        "duplicate-closure de-duplication, destination-pool expansion, Dockerfile/cloud deploy.",
    ], left=8.25, top=1.75, width=4.5, size=13.5, space=9, name="TextBox 4")
    add_footer(s, caption)
    return s


def add_results_slide(prs):
    s = add_slide(prs)
    add_title(s, "Preliminary Results", "Results and progress · every number here is reproducible in the repo")
    add_bullets(s, [
        "Disposition engine vs human gold: 54/57 = 94.7% (rubric v1.1, 2026-09-14; 39/57 = 68.4% under rubric v1). "
        "Two team members labelled all 57 scenarios independently, then a third arbitrated.",
        "Annotator agreement: B↔C raw agreement 44/57, Cohen's κ = 0.6434 — below our own 0.80 target and reported as it is.",
        "High-consequence recall: scrap 33/33 (100%); quarantine 0/3 on only three gold cases.",
        "Risk classification (suspected-synthetic 8,000 shipments, seed 42): LightGBM F1 0.691 / ROC-AUC 0.925 / "
        "PR-AUC 0.754; LR 0.626 / 0.891 / 0.651; XGBoost 0.685 / 0.922 / 0.731.",
        "Candidate causes: LightGBM Top-1 0.143, Top-3 0.421 — below the majority baseline Top-1 0.161; "
        "reported as a negative result with the baseline kept visible.",
        "Routing: greedy 142.63 km → OR-Tools Routing 133.81 km (6.19% shorter, no violations, "
        "no unserved orders); on the published Solomon c101/c201 instances the same solver reaches "
        "the best known solution within 10 s — a genetic algorithm we also implemented ties it, "
        "never beats it.",
        # A bullet about the dispatch options' measured trade-off used to sit here.
        # The committee cut it when they laid the results slide out as one big
        # number plus three metric cards, so it is gone from both the short deck
        # and here: the two decks must not disagree about what the results are.
    ], size=15, space=9, name="TextBox 3")
    add_footer(s, "Boundaries: suspected-synthetic data, single random split, time-bounded solver — these do not "
                  "establish real-world or operational savings.", name="TextBox 4")
    return s


def add_challenges_slide(prs):
    s = add_slide(prs)
    add_title(s, "Challenges We Are Working Through", "Challenges and roadblocks · stated before we are asked")
    add_bullets(s, [
        "Annotator agreement is below target (κ 0.6434 vs 0.80). Mitigation: report the confusion matrix and "
        "support counts, keep the disagreements frozen in tests, and do not tune the rubric to raise κ.",
        "Three gold cases remain contested (gold quarantine; engine released two and retested one) and only three "
        "quarantine cases exist in gold. Mitigation: retain them, report support beside every metric, seek domain evidence.",
        "Cause classification does not beat the majority baseline. Mitigation: keep the baseline, analyse candidate "
        "ranking and feature availability at diagnosis time, avoid using outcome columns as inputs.",
        "Dataset authenticity: most inputs are suspected-synthetic or simulated. Mitigation: define one task per dataset, "
        "disclose provenance and licences, and claim no clinical, operational or regulatory validity.",
        "Threshold provenance: allowable durations, MKT ceilings and multipliers are engineering assumptions, not "
        "regulation. Mitigation: a per-product threshold evidence table with sources, plus a documented low-temperature gap.",
        "Integration and disclosure: some links are simulated rather than executed. Mitigation: integrated acceptance "
        "across reshipment / no-reshipment / infeasible / no-evidence / repeated-closure cases, and clean-environment reproduction.",
    ], size=15, space=10)
    return s


def add_conclusion_slide(prs):
    s = add_slide(prs)
    add_title(s, "Conclusion and Next Steps", "Conclusion · what we are committing to")
    add_bullets(s, [
        "PharmaColdOps already has the core reasoning path: deterministic disposition rules with a rule path, "
        "an independently annotated 57-case gold set, offline risk and cause experiments, a real-road routing "
        "result, and a graph QA path verified against a live Neo4j.",
        "It also already carries its own critique: rule-versus-judgement disagreement, a weak cause classifier, "
        "suspected-synthetic data and prototype thresholds. Those limits are part of the contribution, not hidden.",
        "The project covers all four IRS technique groups — decision automation, resource optimisation, knowledge "
        "discovery and data mining, and cognitive systems — against a requirement of three.",
        "By 25 Oct 2026 we deliver: the integrated minimal loop with failure states, a clean-environment reproduction, "
        "the thresholds and provenance appendix, and two five-minute videos.",
        "What this prototype will not do: replace the quality lead's approval, or authorise real product release, "
        "destruction or transport.",
    ], size=16, space=13, name="TextBox 3")
    add_footer(s, "Thank you — we are happy to take questions.", name="TextBox 4")
    return s


#: The 10-minute, four-speaker cut. Everything not listed is dropped: the pitch
#: is 10 minutes long, so a slide has to earn its ~60 seconds. The list is in
#: speaking order; titles must match the deck exactly.
SHORT_DECK_KEEP = [
    "An Intelligent System for Temperature-Excursion",     # 1 cover
    "Cold-Chain Excursions Threaten Drug Safety",         # 2 the problem
    "Where Existing Tools Fall Short",                    # 3 market gap
    "Our Solution: PharmaColdOps",                        # 4 what we build
    "Where PharmaColdOps Sits",                           # 5 positioning
    "Data Sources: Verifiable, Disclosed Provenance",     # 6 data
    "Implementation: The Loop Is Already Closed",         # 7 what runs today
    "Preliminary Results",                                # 8 numbers
    "Risks, Team & Next Steps",                           # 9 limits + team
    "Conclusion and Next Steps",                          # 10 close
]


def apply_short_deck(prs: Presentation) -> list[str]:
    """Cut the deck down to SHORT_DECK_KEEP and order it as listed.

    Slides are addressed by their relationship id, not by element identity:
    python-pptx hands out a fresh lxml proxy on every attribute access, so
    comparing `slide._element is entry` silently matches nothing. Slides are
    identified by their full text, since some open with a kicker label rather
    than the title."""
    ids = prs.slides._sldIdLst

    kept = []                                   # [(keep-list title, rId)]
    doomed = []                                 # rIds to drop
    for entry in list(ids):
        r_id = entry.get(_R_ID)
        part = prs.part.related_part(r_id)
        title = next((sh.text_frame.text.strip() for sh in part.slide.shapes
                      if sh.has_text_frame and sh.text_frame.text.strip()), "")
        text = "\n".join(sh.text_frame.text for sh in part.slide.shapes
                         if sh.has_text_frame and sh.text_frame.text.strip())
        wanted = next((t for t in SHORT_DECK_KEEP if t in text), None)
        (kept if wanted else doomed).append((wanted, r_id) if wanted else r_id)

    if not kept:
        raise AssertionError(
            f"keep-list matched no slides; first slide title seen: {title!r}")

    for r_id in doomed:
        prs.part.drop_rel(r_id)
    for entry in list(ids):
        ids.remove(entry)

    order = {t: i for i, t in enumerate(SHORT_DECK_KEEP)}
    kept.sort(key=lambda pair: order[pair[0]])
    for _, r_id in kept:
        ids.add_sldId(r_id)
    return [t for t, _ in kept]


# --------------------------------------------------------------------------
# the 10-minute cut: rewrite the four longest blocks to ~300 characters
# --------------------------------------------------------------------------
def shorten_for_short_deck(prs: Presentation) -> None:
    """Trim the wordiest slides so the 10-slide pitch fits 10 minutes.

    The full deck's added pages run 900-1500 characters — two to three times the
    original design's own slides (~480). At four speakers and 10 minutes there is
    roughly one minute per slide, which is ~300 characters of spoken text, so the
    long blocks are rewritten to that size instead of being read aloud.
    """
    def by_title(needle: str):
        return slide_by_title(prs, needle)

    # --- 1 cover: same facts, two lines (cover = the slide that IS the title
    #     slide, not the many slides that merely mention the project name) ---
    cover = prs.slides[0]
    set_para(find(cover, "Text 2"), 1,
             "Project Group 41 · Xu Wenzhe · Zhu Jianyu · Wang Lepeng · Shen Ziyi")

    # --- 2 problem -------------------------------------------------------
    s2 = by_title("Cold-Chain Excursions Threaten Drug Safety")
    set_para(find(s2, "Text 4"), 0,
             "Vaccines and biologics can lose efficacy after even a brief "
             "deviation in transport or storage.")
    set_para(find(s2, "Text 7"), 0,
             "Common tools only raise an alarm: they record the deviation but do "
             "not decide what to do with the batch.")
    set_para(find(s2, "Text 10"), 0,
             "Practices vary by site and shift; the reasoning behind a disposition "
             "is rarely reconstructable.")

    # --- 3 gap (drops the third column's long body to one line) ----------
    s4 = by_title("Where Existing Tools Fall Short")
    set_para(find(s4, "Text 4"), 0,
             "Monitoring exists; what is missing is a rule path linking the "
             "disposition to the order, route and evidence.")
    set_para(find(s4, "Text 8"), 0,
             "A recommendation that cannot show its rule, evidence and limits "
             "will not be signed off in an audit.")

    # --- 4 solution ------------------------------------------------------
    s5 = by_title("Our Solution: PharmaColdOps")
    set_para(find(s5, "Text 6"), 0,
             "Four outcomes with a traceable rule path; reshipment is a separate "
             "logistics action.")
    set_para(find(s5, "Text 10"), 0,
             "A reshipment order solved as a capacity- and time-window routing problem.")
    set_para(find(s5, "Text 14"), 0,
             "Every decision cites its rule, regulation or SOP and evidence limits.")

    # --- 5 positioning: three bullets, no examples (say them instead) ----
    s13 = by_title("Where PharmaColdOps Sits")
    set_para(find(s13, "TextBox 1"), 0, "Where PharmaColdOps Sits")
    set_para(find(s13, "TextBox 2"), 0, "Positioning · market context and related work")
    body = find(s13, "TextBox 3")          # the bullet block add_market_slide created
    bullets = [
        "● Commercial platforms already monitor temperature and automate parts "
        "of the quality process — we do not claim to be first.",
        "● We build on existing foundations: Solomon's VRPTW benchmark, "
        "OR-Tools, gradient-boosted trees, SHAP.",
        "● The gap we address is the unbroken, inspectable chain from event to "
        "disposition to order to route to cited evidence.",
    ]
    for index, text in enumerate(bullets):
        set_para(body, index, text)
    # Drop the original 4th bullet: it restates a point the limits slide already
    # makes, and 10 minutes cannot carry two versions of it.
    for extra in list(body.text_frame.paragraphs)[len(bullets):]:
        extra._p.getparent().remove(extra._p)

    # --- 6 data: keep the provenance point, drop the long list -----------
    s9 = by_title("Data Sources: Verifiable, Disclosed Provenance")
    set_para(find(s9, "Text 0"), 0, "Data: Verifiable, Disclosed Provenance")
    set_para(find(s9, "Text 2"), 0, "≈8,000 rows — failure classification.")
    set_para(find(s9, "Text 4"), 0, "≈26,700 rows — sequence and MKT work.")
    set_para(find(s9, "Text 6"), 0, "Simulated facility-monthly records.")
    set_para(find(s9, "Text 8"), 0, "Six Solomon instances + OSM road network.")
    set_para(find(s9, "Text 10"), 0, "WHO / EU GDP / ICH · CDC. Thresholds are prototype assumptions.")

    # --- 7 what runs today: replace the added bullet block, don't stack on it
    #     (adding a second list left two overlapping texts on one slide) -----
    s14 = by_title("Implementation: The Loop Is Already Closed")
    set_para(find(s14, "TextBox 1"), 0, "Built and Running Today")
    set_para(find(s14, "TextBox 2"), 0, "Measured from the repository, 2026-09-27")
    old = find(s14, "TextBox 4")             # the long 5-bullet block from the full deck
    old._element.getparent().remove(old._element)
    # The screenshot caption: in the full deck it is TextBox 5; in the short build
    # the slide is created without it, so create it when missing.
    try:
        caption = find(s14, "TextBox 5")
        set_para(caption, 0, "Screenshot: the Vue client in API mode, 2026-09-27.")
    except KeyError:
        add_footer(s14, "Screenshot: the Vue client in API mode, 2026-09-27.",
                   name="TextBox 5")
    add_bullets(s14, [
        "23 API paths / 24 operations, 15 of them dispatch paths.",
        "One Vue 3 client, 23 components; EN/ZH and offline mode.",
        "25 archived cases; 56 dispatch operations persisted.",
        "305 test functions across 34 test files.",
        "Still missing: cloud deploy, de-duplication, destination pool.",
    ], left=8.25, top=1.75, width=4.5, size=13, space=9, name="TextBox 4")

    # --- 8 results: five bullets, numbers kept, prose removed ------------
    s15 = by_title("Preliminary Results")
    set_para(find(s15, "TextBox 1"), 0, "Results So Far")
    set_para(find(s15, "TextBox 2"), 0, "Every number reproducible in the repo")
    box = find(s15, "TextBox 3")
    box._element.getparent().remove(box._element)
    add_bullets(s15, [
        "Engine vs human gold: 54/57 = 94.7%; scrap recall 33/33.",
        "Annotator agreement κ = 0.6434 — below our 0.80 target.",
        "Routing: 142.63 → 133.81 km (−6.19%, 0 violations); Solomon optima "
        "reached in 10 s.",
        "Risk model: F1 0.691 / ROC-AUC 0.925; cause Top-1 0.143 is below the "
        "majority baseline and reported as such.",
    ], left=0.62, top=2.00, width=12.1, height=4.4, size=17, space=16)

    # --- 9 limits + team: four limits over the four names ---------------
    s12 = by_title("Risks, Team & Next Steps")
    set_runs(find(s12, "Text 3"), 0, [
        "Annotator agreement",
        " κ = 0.6434 vs our 0.80 target → report it",
    ])
    set_runs(find(s12, "Text 4"), 0, [
        "Quarantine recall 0/3",
        " 3 gold cases → report support counts",
    ])
    set_runs(find(s12, "Text 5"), 0, [
        "Synthetic data",
        " suspected-synthetic → disclose the limit",
    ])
    t9 = find(s12, "Text 9")
    set_runs(t9, 0, ["W1: threshold review; multi-fold risk experiments"])
    set_runs(t9, 1, ["W3: integrated acceptance and failure states"])
    set_para(t9, 2, "W5: reproduce cleanly; videos by 25 Oct")
    set_runs(find(s12, "Text 10"), 0,
             ["Project Lead / Rules", " · Xu Wenzhe: rules, evidence, evaluation"])
    set_runs(find(s12, "Text 11"), 0,
             ["Data & ML", " · Zhu Jianyu: data, risk, causes, SHAP"])
    set_runs(find(s12, "Text 12"), 0,
             ["Optimisation", " · Wang Lepeng: VRPTW, routes, dispatch"])
    set_runs(find(s12, "Text 13"), 0,
             ["KG + QA + Frontend", " · Shen Ziyi: KG, QA, API, frontend"])

    # --- 10 conclusion: five bullets to four, shorter ------------------
    s17 = by_title("Conclusion and Next Steps")
    set_para(find(s17, "TextBox 1"), 0, "Conclusion and Next Steps")
    set_para(find(s17, "TextBox 2"), 0, "What we commit to")
    box = find(s17, "TextBox 3")
    box._element.getparent().remove(box._element)
    add_bullets(s17, [
        "The reasoning path exists and carries its own critique: rule-versus-"
        "judgement disagreement, a weak cause classifier, prototype thresholds.",
        "All four IRS technique groups are covered, against a requirement of three.",
        "By 25 Oct: integrated acceptance with failure states, clean-environment "
        "reproduction, the two videos.",
        "It does not replace the quality lead's approval, and does not authorise "
        "real product release, destruction or transport.",
    ], left=0.62, top=2.00, width=12.1, height=4.4, size=17, space=16, name="TextBox 3")
    add_footer(s17, "Thank you — we are happy to take questions.", name="TextBox 4")


def main() -> None:
    short = "--short" in sys.argv or "--10min" in sys.argv

    prs = Presentation(str(SRC))
    fix_existing(prs)
    # The short cut reuses the same added pages (positioning, progress, results,
    # conclusion) and then deletes everything off the keep list, so both builds
    # share one source of truth for content.
    add_market_slide(prs)
    add_progress_slide(prs)
    add_results_slide(prs)
    add_conclusion_slide(prs)
    if not short:
        add_scale_slide(prs)
        add_challenges_slide(prs)
    else:
        # Delete first (while the slides still carry their original titles), then
        # rewrite the kept ones — renaming before deleting made the keep-list
        # match on titles that no longer existed.
        dropped = apply_short_deck(prs)
        print(f"short deck: kept {dropped} slides")
        shorten_for_short_deck(prs)

    normalize_text_fit(prs)
    prs.save(str(DST))
    print(f"wrote {DST}  slides={len(prs.slides)}")

    warnings = text_budget_report(prs)
    if warnings:
        print(f"\n{len(warnings)} box(es) longer than the string they replaced "
              f"(the original layout is the budget):")
        for line in warnings:
            print("  " + line)
    else:
        print("\ntext budget: every replacement fits the original's own length")


if __name__ == "__main__":
    main()
