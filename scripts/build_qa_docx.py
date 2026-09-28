#!/usr/bin/env python3
"""Build a printable DOCX from the Q&A preparation sheet.

Same zero-dependency OOXML pipeline as the speech script (`scripts/docx_kit.py`),
but the sheet is reference material rather than something read aloud, so:

  * tighter margins (1.5 cm) and 10.5pt body text — this is a desk copy;
  * every question is a small numbered heading with `keepNext`, so Word cannot
    leave a question at the bottom of a page with its answer overleaf;
  * the first answer line of each entry (the sentence to say out loud) is set as
    a teal cue line with a left rule, exactly like the speech script's cues;
  * `> note` lines render as indented grey hints, `（…）` metadata stays small.

Usage:
    python scripts/build_qa_docx.py [source.md] [output.docx]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# scripts/ is not a package; add it to the path so `docx_kit` resolves whether the
# script is run directly or via `python -m`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx_kit import (ACCENT, INK, MUTED, build, esc, equal_widths,  # noqa: E402
                      inline_runs, page_break, para, read_rows, run, table)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "proposal" / "QA准备-演讲稿配套.md"
DST = ROOT / "proposal" / "QA准备-演讲稿配套.docx"

BODY = 21          # 10.5pt — dense but readable on paper
SMALL = 19         # 9.5pt
MARGIN = 851       # 1.5 cm

Q_RE = re.compile(r"^\*\*(Q\d+)\.\s*(.*?)\*\*\s*$")
A_RE = re.compile(r"^\*\*([A-F]\d+)\.\s*(.*?)\*\*\s*$")


def looks_like_answer(text: str) -> bool:
    """The spoken sentence: the line that is entirely bold."""
    stripped = text.strip()
    return (stripped.startswith("**") and stripped.endswith("**")
            and stripped.count("**") == 2 and len(stripped) > 8)


def parse(md: str) -> list[str]:
    lines = md.split("\n")
    blocks: list[str] = []
    i = 0
    in_qa_entry = False

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # ---- horizontal rule: a thin separator, never a page break ---------
        if re.fullmatch(r"-{3,}", stripped):
            blocks.append(para("", after=80, border_bottom="D8E0E8"))
            i += 1
            continue

        # ---- headings ------------------------------------------------------
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            if level == 1:
                in_qa_entry = False
                blocks.append(para(run(text, bold=True, size=30, color=INK),
                                   before=0, after=120, keep_next=True))
            elif level == 2:
                in_qa_entry = False
                # a top-level section starts on its own page, except the first
                if not text.startswith("0."):
                    blocks.append(page_break())
                blocks.append(para(run(text, bold=True, size=26, color=ACCENT),
                                   before=120, after=120, keep_next=True,
                                   border_bottom="D8E0E8"))
            else:
                # ### Q1. … is the question; ### A. … is a themed block
                qm = Q_RE.match(text)
                am = A_RE.match(text)
                if qm:
                    in_qa_entry = True
                    blocks.append(para(
                        run(f"{qm.group(1)}. ", bold=True, size=23, color=ACCENT)
                        + inline_runs(qm.group(2), size=23, color=INK),
                        before=180, after=60, keep_next=True, line=276))
                elif am:
                    in_qa_entry = True
                    blocks.append(para(inline_runs(am.group(2), size=23, color=INK),
                                       before=180, after=60, keep_next=True))
                else:
                    in_qa_entry = True
                    blocks.append(para(run(text, bold=True, size=23, color=ACCENT),
                                       before=160, after=60, keep_next=True))
            i += 1
            continue

        # ---- table ---------------------------------------------------------
        if stripped.startswith("|"):
            rows, i = read_rows(lines, i)
            if rows:
                blocks.append(table(rows, equal_widths(rows)))
            continue

        # ---- blockquote: a hint about what not to say ----------------------
        if stripped.startswith(">"):
            body = stripped.lstrip(">").strip()
            if body:
                blocks.append(para(inline_runs(body, size=SMALL, color=MUTED),
                                   before=20, after=60, left=300,
                                   border_left="CBD5E1"))
            i += 1
            continue

        # ---- bullet list ---------------------------------------------------
        if re.match(r"^[-*]\s+", stripped):
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                item = re.sub(r"^[-*]\s+", "", lines[i].strip())
                blocks.append(para(inline_runs(item, size=BODY), left=430, hanging=200,
                                   after=40, line=276))
                i += 1
            continue

        # ---- numbered list -------------------------------------------------
        if re.match(r"^\d+\.\s+", stripped):
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                item = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                blocks.append(para(inline_runs(item, size=BODY), left=430, hanging=200,
                                   after=40, line=276))
                i += 1
            continue

        # ---- question heading written as a bold line (**Q1「…」**（A / D）) ----
        qm = Q_RE.match(stripped)
        if qm:
            in_qa_entry = True
            blocks.append(para(
                run(f"{qm.group(1)}. ", bold=True, size=23, color=ACCENT)
                + inline_runs(qm.group(2), size=23, color=INK),
                before=180, after=60, keep_next=True, line=276))
            i += 1
            continue

        # ---- inside a Q&A entry: cue line, metadata or body ----------------
        if in_qa_entry and looks_like_answer(stripped):
            blocks.append(para(inline_runs(stripped[2:-2], size=BODY, color=INK),
                               before=40, after=60, left=200, line=288,
                               border_left=ACCENT, shade="F0FDFA"))
        elif stripped.startswith("**") and stripped.endswith("**") and i + 1 < len(lines):
            # **A2. "…"** style lines that were not caught above
            blocks.append(para(inline_runs(stripped, size=23), before=160, after=40,
                               keep_next=True))
        elif stripped.startswith("（") or stripped.startswith("**出处") or "：为什么" in stripped:
            blocks.append(para(inline_runs(stripped, size=SMALL, color=MUTED),
                               before=0, after=50, left=200, line=264))
        else:
            blocks.append(para(inline_runs(stripped, size=BODY),
                               before=0, after=60, left=200, line=276))
        i += 1

    return blocks


def build_package(md: str, out: Path) -> None:
    build(parse(md), out, margin=MARGIN)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DST
    if not src.exists():
        raise SystemExit(f"source not found: {src}")
    md = src.read_text(encoding="utf-8")
    build_package(md, dst)
    questions = len(re.findall(r"^### [QA]\d+\.|^\*\*Q\d+", md, re.M))
    print(f"wrote {dst.relative_to(ROOT)}  ({dst.stat().st_size / 1024:.0f} KB, "
          f"{len(md)} chars in, {questions} questions)")


if __name__ == "__main__":
    main()
