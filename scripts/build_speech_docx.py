#!/usr/bin/env python3
"""Build a printable DOCX from the four-speaker presentation script.

Zero third-party dependencies (the course workspace may not have python-docx or
pandoc), and it writes a complete OOXML package from scratch rather than editing
a template, so it cannot inherit a stale style from another document.

What it maps, from the script's own Markdown:
  # / ##            -> title / section headings
  > **P1 封面**（20 秒） -> a highlighted cue line (the slide + its time budget)
  > English…        -> a spoken-paragraph block, indented with a left rule
  **项目**：…        -> a bold-label line
  | tables |        -> real Word tables
  ---               -> page break between speakers (the script separates the four
                       parts with '---' so each speaker gets their own page)
  - items           -> bullets

Usage:
    python scripts/build_speech_docx.py [source.md] [output.docx]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx_kit import (ACCENT, INK, MUTED, build, cell, equal_widths, esc,  # noqa: F401
                      inline_runs, page_break, para, read_rows, run, table)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "proposal" / "演讲稿-4人版.md"
DST = ROOT / "proposal" / "演讲稿-4人版.docx"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


# --------------------------------------------------------------------------
# markdown → blocks
# --------------------------------------------------------------------------
def parse(md: str) -> list[str]:
    lines = md.split("\n")
    blocks: list[str] = []
    i = 0
    quote_buf: list[str] = []

    def flush_quote() -> None:
        """A blockquote is either a cue line (**P1 封面**（20 秒）) or spoken text."""
        nonlocal quote_buf
        if not quote_buf:
            return
        for entry in quote_buf:
            is_cue = bool(re.match(r"^\*\*[^*]+\*\*[（(]\s*\d+\s*秒\s*[）)]\s*$", entry.strip()))
            if is_cue:
                label = re.sub(r"\*\*", "", entry.strip())
                blocks.append(para(run(label, bold=True, size=22, color=ACCENT),
                                   before=200, after=60, keep_next=True,
                                   border_left=ACCENT, left=140, shade="F0FDFA"))
            else:
                blocks.append(para(inline_runs(entry, size=22),
                                   before=0, after=120, left=140, line=300))
        quote_buf = []

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith(">"):
            body = stripped.lstrip(">").strip()
            if body:
                quote_buf.append(body)
            i += 1
            continue
        flush_quote()

        if not stripped:
            i += 1
            continue

        # horizontal rule: a run of --- separates the four speakers
        if re.fullmatch(r"-{3,}", stripped):
            j = i
            while j < len(lines) and re.fullmatch(r"-{3,}", lines[j].strip()):
                j += 1
            # The '---\n---' before the appendix already starts its page; emitting
            # another break here produced a blank page (the appendix adds its own
            # break too, so exactly one of the three must fire).
            next_line = next((l.strip() for l in lines[j:] if l.strip()), "")
            starts_appendix = next_line.startswith("# 附")
            if j - i >= 2 and not starts_appendix:
                blocks.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            elif j - i < 2:
                blocks.append(para("", after=60, border_bottom="D8E0E8"))
            i = j
            continue

        # headings
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            # The appendix (Q&A cards, cut-list, stage notes) starts on its own
            # page: it is not spoken, and leaving it to flow on made the last
            # speaker's page run over.
            if level == 1 and text.startswith("附"):
                blocks.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            if level == 1:
                blocks.append(para(inline_runs(text, size=32, color=INK),
                                   before=120, after=160, keep_next=True))
            elif level == 2:
                blocks.append(para(run(text, bold=True, size=25, color=ACCENT),
                                   before=180, after=100, keep_next=True))
            else:
                blocks.append(para(run(text, bold=True, size=22, color=INK),
                                   before=140, after=80, keep_next=True))
            i += 1
            continue

        # table
        if stripped.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                n = max(len(r) for r in rows)
                widths = [int(100 / n)] * n
                widths[-1] = 100 - sum(widths[:-1])
                blocks.append(table(rows, widths))
            continue

        # bullet list
        if re.match(r"^[-*]\s+", stripped):
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                item = re.sub(r"^[-*]\s+", "", lines[i].strip())
                blocks.append(para(inline_runs(item, size=21), left=340, hanging=180,
                                   after=60, line=276))
                i += 1
            continue

        # numbered list (the cut-list uses "1." …)
        if re.match(r"^\d+\.\s+", stripped):
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                item = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                blocks.append(para(inline_runs(item, size=21), left=340, hanging=180,
                                   after=60, line=276))
                i += 1
            continue

        # metadata line: **项目**：… (bold label + text) — keep them tight together.
        # The appendix flows at the same 21pt as the spoken text: it is reference
        # material, and reading it comfortably matters more than fitting one page
        # (it takes two, which is fine — nobody reads it aloud).
        blocks.append(para(inline_runs(stripped, size=21), after=40, line=276))
        i += 1

    flush_quote()
    return blocks


def build_package(md: str, out: Path) -> None:
    """Parse the Markdown and write the OOXML package (helpers live in docx_kit)."""
    build(parse(md), out)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DST
    if not src.exists():
        raise SystemExit(f"source not found: {src}")
    md = src.read_text(encoding="utf-8")
    build_package(md, dst)
    # A page count of page breaks is a cheap sanity signal that the four parts
    # were split rather than run together.
    breaks = md.count("\n---\n---\n")
    print(f"wrote {dst.relative_to(ROOT)}  ({dst.stat().st_size / 1024:.0f} KB, "
          f"{len(md)} chars in, {breaks} part break(s))")


if __name__ == "__main__":
    main()
