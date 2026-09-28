"""Apply this round's approved edits to the reference deck.

1. cover block: add the four NUS student IDs, presentation date -> 29 Sep 2026
2. slide 7 line 1: "13 of them dispatch operations" -> "15 of them dispatch operations"
3. slide 7 line 4: "305 test functions across 35 files" -> "... across 34 test files"
4. slide 8: the closed loop takes the hero position and the three evaluation
   results become equal-weight cards — the old layout made the 94.7% agreement
   with our own rubric the single headline of the whole results page.

Run:  .venv/Scripts/python.exe scripts/fix_deck_facts.py
A timestamped backup is written next to the deck before it is overwritten.
"""
from __future__ import annotations

import shutil
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Inches, Pt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "proposal" / "PharmaColdOps .pptx"

#: cover contact block, in order. The student IDs come from the proposal
#: (proposal/PharmaColdOps-Proposal-ZH.md, header) so both documents agree.
COVER_LINES = [
    "Project Group 41 · Xu Wenzhe · Zhu Jianyu · Wang Lepeng · Shen Ziyi",
    "A0328771W · A0353769L · A0357864L · A0350940J",
    "IRS Practice Module · Proposal Presentation · 29 Sep 2026",
]
COVER_SIZE = Pt(10)          # 12pt overflows the space between the blurb and the slide edge
#: the box was 0.37in tall, which is under the 0.42in three 10pt lines need, so
#: PowerPoint would shrink the text to fit. 0.60in keeps the real 10pt size and
#: still ends 0.24in above the slide edge.
COVER_HEIGHT = Inches(0.60)

#: (text-box line index, old text, new text) on slide 7
FACT_FIXES = [
    (0, "23 HTTP endpoints, 13 of them dispatch operations.",
        "23 HTTP endpoints, 15 of them dispatch operations."),
    (3, "305 test functions across 35 files.",
        "305 test functions across 34 test files."),
]

#: ---------------------------------------------------------------------------
#: slide 8 · results. Provenance for every number is pinned by
#: scripts/check_deck_facts.py; the loop facts come from the repo artifacts
#: named in proposal/README.md.
#: ---------------------------------------------------------------------------
SLIDE8_TITLE = "The Loop Runs — and Every Number Reproduces"
SLIDE8_SUBTITLE = "RESULTS AND PROGRESS · MEASURED FROM THE REPOSITORY, 2026-09-28"
SLIDE8_HERO_LABEL = "THE LOOP, END TO END"
SLIDE8_HERO_VALUE = "4"
#: the hero number needs an explicit reason next to it on the slide, not just a
#: noun label: "4" alone reads as decoration.
SLIDE8_HERO_UNIT = "dispositions the rule engine can assign:"
SLIDE8_HERO_LINE = ("release, quarantine, retest or scrap — reshipment is a separate "
                    "logistics action, never a fifth outcome.")
SLIDE8_LOOP_LABEL = "PROTOTYPE EVIDENCE, 2026-09-27"
SLIDE8_LOOP_LINES = [
    "· one closed case → reshipment order → route on a real 19-node Singapore OSM network; "
    "graph evidence = 9 nodes / 8 relationship types (2026-09-13)",
    "· live surface: 23 API paths / 24 operations, 15 dispatch paths; 25 archived cases and "
    "56 persisted dispatch operations",
    "· declared limits: simulated demand and time windows; no operational savings claimed",
]
#: the three equal-weight evaluation cards: (label, headline, description).
#: descriptions are written to fit two short lines at 12pt.
SLIDE8_CARDS = [
    ("DISPOSITION LAYER",
     "54/57 · κ = 0.6434",
     "54/57 = 94.7% agreement against our own rubric."),
    ("ROUTE LAYER",
     "142.63 → 133.81 km",
     "−6.19% vs greedy, 0 violations; Solomon optima in 10 s."),
    ("RISK LAYER",
     "F1 0.691 / ROC-AUC 0.925",
     "70/15/15 split; cause Top-1 0.143 vs majority baseline 0.161."),
]
#: the three cards are equal weight, so they sit on an even pitch that ends
#: 0.70in above the slide edge.
CARD_TOPS = [Inches(1.62), Inches(3.34), Inches(5.06)]
#: every box gets its size explicitly. Inherited run formatting is not safe here:
#: earlier revisions of the slide reused the same boxes at 22pt/17pt.
TITLE_SIZE = Pt(34)
SUBTITLE_SIZE = Pt(11)
HERO_LABEL_SIZE = Pt(11)
HERO_VALUE_SIZE = Pt(56)     # the numeral and its explanation sit side by side
HERO_UNIT_SIZE = Pt(17)
HERO_LINE_SIZE = Pt(17)
#: the numeral is 0.46in wide at 56pt; the explanation starts to its right and
#: stops 0.60in before the right column's card text
HERO_TEXT_LEFT = Inches(1.10)
HERO_TEXT_WIDTH = Inches(5.30)
LOOP_LABEL_SIZE = Pt(11)
LOOP_FACT_SIZE = Pt(11)
CARD_LABEL_SIZE = Pt(11)
CARD_VALUE_SIZE = Pt(22)
CARD_DESCRIPTION_SIZE = Pt(12)   # 12pt keeps every card description on one 4.70in line
#: The original slide numbers its nine text boxes in visual order but names the
#: remaining five out of order. Rather than guess a mapping, the rewrite uses the
#: first nine boxes (title, subtitle, hero x3, loop label, loop facts x3) and
#: rebuilds the five card boxes from a template.
LOOP_NAMES = ["Text 3", "Text 4", "Text 5", "Text 6", "Text 7", "Text 8", "Text 9"]
CARD_TEMPLATE = "Text 5"     # 17pt Funnel Sans, dark grey — the old description style
#: the right-column boxes the rebuild replaces, so a re-run cannot leave the
#: superseded copy sitting next to the new cards
STALE_CARD_BOXES = ["Text 10", "Text 11", "Text 12", "Text 13", "Text 14"]


def first_textbox(slide, needle: str):
    for shape in slide.shapes:
        if shape.has_text_frame and needle in shape.text_frame.text:
            return shape.text_frame
    raise AssertionError(f"no text box containing {needle!r} on this slide")


def set_run(paragraph, text: str, size=None) -> None:
    """Rewrite a paragraph to a single run, keeping the first run's formatting."""
    if not paragraph.runs:
        raise AssertionError("paragraph has no runs to copy formatting from")
    keep = paragraph.runs[0]
    for run in paragraph.runs[1:]:
        run._r.getparent().remove(run._r)
    keep.text = text
    if size is not None:
        keep.font.size = size


def _shape(slide, name: str):
    for shape in slide.shapes:
        if shape.name == name:
            return shape
    raise AssertionError(f"slide has no shape named {name!r}")


def _existing(slide, name: str):
    return next((shape for shape in slide.shapes if shape.name == name), None)


def _clone_shape(slide, template, name: str):
    """Copy a text box (element + run formatting) and give it a new shape name."""
    new_element = deepcopy(template._element)
    shape_id = max((int(el.get("id", 0)) for el in slide.shapes._spTree.iter()
                    if el.tag.endswith("}cNvPr")), default=1) + 1
    for cNvPr in new_element.iter():
        if cNvPr.tag.endswith("}cNvPr"):
            cNvPr.set("id", str(shape_id))
            cNvPr.set("name", name)
            break
    slide.shapes._spTree.append(new_element)
    return _shape(slide, name)


def _set_wrapped_text(shape, lines, size=None, height=None) -> None:
    """One paragraph per line, wrapping on, no autofit shrink.

    Straight-line text (word_wrap=False) is what let the old slide-8 copy run
    past the right edge of the slide.
    """
    frame = shape.text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    if height is not None:
        shape.height = height
    while len(frame.paragraphs) > len(lines) and len(frame.paragraphs) > 1:
        last = frame.paragraphs[-1]._p
        last.getparent().remove(last)
    for index, line in enumerate(lines):
        if index < len(frame.paragraphs):
            set_run(frame.paragraphs[index], line, size)
        else:
            new_p = deepcopy(frame.paragraphs[0]._p)
            frame._txBody.append(new_p)
            set_run(frame.paragraphs[-1], line, size)


def edit_slide8(slide) -> None:
    """Give the closed loop the hero position and equal weight to the three
    evaluation results.

    Sizes and colours are inherited from the boxes already on the slide, so the
    page keeps the deck's own type scale instead of introducing new styling.
    """
    # --- headline --------------------------------------------------------
    _set_wrapped_text(_shape(slide, "Text 1"), [SLIDE8_TITLE],
                      size=TITLE_SIZE, height=Inches(0.95))
    subtitle = _shape(slide, "Text 2")
    subtitle.width = Inches(12.33)          # 12.83in ran to a 13.33in slide edge
    subtitle.top = Inches(1.24)
    _set_wrapped_text(subtitle, [SLIDE8_SUBTITLE],
                      size=SUBTITLE_SIZE, height=Inches(0.30))

    # --- left column: the loop, then the prototype evidence --------------
    #: Text 7/8/9 and the old card1_label are emptied first; the loop content then
    #: goes into its own dedicated boxes, so the same text can never appear twice
    #: and nothing depends on which named boxes survived an earlier revision.
    for name in ("Text 5", "Text 6", "Text 7", "Text 8", "Text 9", "card1_label"):
        shape = _existing(slide, name)
        if shape is not None:
            _set_wrapped_text(shape, [""], height=Inches(0.10))
            shape.left, shape.top, shape.width = Inches(0.05), Inches(7.30), Inches(0.10)
    loop_slots = []
    for index in range(4):
        name = f"loop_{index}"
        shape = _existing(slide, name) or _clone_shape(slide, _shape(slide, "Text 3"), name)
        loop_slots.append(name)
    for index, lines in enumerate([SLIDE8_LOOP_LABEL] + SLIDE8_LOOP_LINES):
        name = loop_slots[index]
        shape = _shape(slide, name)
        _set_wrapped_text(shape, [lines], size=LOOP_LABEL_SIZE if index == 0 else LOOP_FACT_SIZE,
                          height=Inches(0.24 if index == 0 else 0.38))
        shape.left = Inches(0.50)
        shape.width = Inches(7.14)
        shape.top = Inches((5.42, 5.82, 6.22, 6.62)[index])

    for name, lines, size, height, top, width in (
            ("Text 3", [SLIDE8_HERO_LABEL], HERO_LABEL_SIZE, 0.24, 2.18, 7.14),
            #: 1.00in, not 0.76in: a 56pt line is 0.91in tall and the box autofits,
            #: so a smaller box would silently shrink the hero number. The box is
            #: only as wide as the numeral, because the explanation sits beside it.
            ("Text 4", [SLIDE8_HERO_VALUE], HERO_VALUE_SIZE, 1.00, 2.46, 0.50)):
        shape = _shape(slide, name)
        _set_wrapped_text(shape, lines, size=size, height=Inches(height))
        shape.left, shape.top, shape.width = Inches(0.50), Inches(top), Inches(width)

    #: the explanation sits to the RIGHT of the numeral, not below it, so the
    #: number is explained at the point where the eye lands
    hero_lead = _existing(slide, "hero_lead") or _clone_shape(slide, _shape(slide, "Text 3"),
                                                              "hero_lead")
    _set_wrapped_text(hero_lead, [SLIDE8_HERO_UNIT], size=HERO_UNIT_SIZE, height=Inches(0.30))
    hero_lead.left, hero_lead.top, hero_lead.width = HERO_TEXT_LEFT, Inches(2.86), HERO_TEXT_WIDTH
    hero_why = _existing(slide, "hero_why") or _clone_shape(slide, _shape(slide, "Text 3"),
                                                            "hero_why")
    _set_wrapped_text(hero_why, [SLIDE8_HERO_LINE], size=HERO_LINE_SIZE, height=Inches(0.80))
    hero_why.left, hero_why.top, hero_why.width = HERO_TEXT_LEFT, Inches(3.18), HERO_TEXT_WIDTH

    rule_above = _shape(slide, "Shape 16")              # gold rule under the hero
    rule_above.left, rule_above.width, rule_above.height = (
        Inches(0.50), Inches(5.51), Inches(0.02))
    rule_above.top = Inches(4.96)
    rule_below = _shape(slide, "Shape 17")              # magenta rule above the evidence
    rule_below.left, rule_below.width = Inches(0.50), Inches(7.14)
    rule_below.top = Inches(5.30)

    # --- right column: three equal-weight evaluation cards ---------------
    #: the two surviving card boxes are templates; every card slot is rebuilt from
    #: whichever template box still exists on the slide
    divider = _shape(slide, "Shape 18")
    divider.left, divider.top = Inches(7.84), Inches(1.05)
    divider.width, divider.height = Inches(0.04), Inches(5.75)
    template = next((_existing(slide, n) for n in
                     ("card2_value", "card2_desc", "card3_value", CARD_TEMPLATE)
                     if _existing(slide, n) is not None), None)
    if template is None:
        raise AssertionError("slide 8 has no text box left to use as a template")
    for index, ((label, value, description), top) in enumerate(zip(SLIDE8_CARDS, CARD_TOPS)):
        for kind, text, size, offset, height in (
                ("label", label, CARD_LABEL_SIZE, 0.00, 0.24),
                ("value", value, CARD_VALUE_SIZE, 0.32, 0.48),
                ("desc", description, CARD_DESCRIPTION_SIZE, 0.88, 0.46)):
            name = f"card{index + 1}_{kind}"
            shape = _existing(slide, name)
            if shape is None:
                shape = _clone_shape(slide, template, name)
            _set_wrapped_text(shape, [text], size=size, height=Inches(height))
            shape.left, shape.width = Inches(8.00), Inches(4.35)
            shape.top = top + Inches(offset)

    # the superseded boxes are emptied, not deleted; the rebuild works on elements
    # whose shape ids python-pptx has already handed out
    for name in ("Text 11", "Text 12", "Text 13", "Text 14",
                 "Text 15", "Text 16", "Text 17", "Text 18"):
        shape = _existing(slide, name)
        if shape is not None and shape.has_text_frame:
            _set_wrapped_text(shape, [""], height=Inches(0.10))
            shape.left, shape.top, shape.width = Inches(0.05), Inches(7.30), Inches(0.10)



def main() -> None:
    prs = Presentation(str(DECK))

    # --- 1. cover: member IDs + presentation date -------------------------
    cover_shape = next(
        shape for shape in prs.slides[0].shapes
        if shape.has_text_frame and "Project Group 41" in shape.text_frame.text)
    cover_shape.height = COVER_HEIGHT
    cover = cover_shape.text_frame
    while len(cover.paragraphs) > len(COVER_LINES) and len(cover.paragraphs) > 1:
        last = cover.paragraphs[-1]._p
        last.getparent().remove(last)
    for index, line in enumerate(COVER_LINES):
        if index < len(cover.paragraphs):
            set_run(cover.paragraphs[index], line, COVER_SIZE)
        else:
            from copy import deepcopy

            new_p = deepcopy(cover.paragraphs[0]._p)
            cover._txBody.append(new_p)
            set_run(cover.paragraphs[-1], line, COVER_SIZE)

    # --- 2/3. slide 7 measurements ---------------------------------------
    facts = first_textbox(prs.slides[6], "HTTP endpoints")
    for index, old, new in FACT_FIXES:
        paragraph = facts.paragraphs[index]
        current = "".join(run.text for run in paragraph.runs)
        if current == new:
            continue                       # already applied: re-running is harmless
        if old not in current:
            raise AssertionError(
                f"slide 7 line {index} is neither the old nor the new text: {current!r}")
        set_run(paragraph, new)

    # --- 4. slide 8: loop hero + equal-weight evaluation cards ------------
    edit_slide8(prs.slides[7])

    backup = DECK.with_name(
        f"{DECK.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{DECK.suffix}")
    shutil.copy2(DECK, backup)
    prs.save(str(DECK))
    print(f"backup: {backup.name}")
    print(f"wrote : {DECK.name}")
    print("\ncover block now:")
    for line in first_textbox(Presentation(str(DECK)).slides[0], "Project Group 41").text.splitlines():
        print(f"   {line}")
    print("\nslide 7 now:")
    for line in first_textbox(Presentation(str(DECK)).slides[6], "HTTP endpoints").text.splitlines():
        print(f"   {line}")
    print("\nslide 8 now:")
    for shape in Presentation(str(DECK)).slides[7].shapes:
        if shape.has_text_frame and shape.text_frame.text.strip():
            print(f"   [{shape.name}] {shape.text_frame.text}")


if __name__ == "__main__":
    main()
