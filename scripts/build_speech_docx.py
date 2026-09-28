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

import html
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_TYPE = ("http://schemas.openxmlformats.org/officeDocument/2006/"
                "relationships/officeDocument")
STYLE_REL_TYPE = ("http://schemas.openxmlformats.org/officeDocument/2006/"
                  "relationships/styles")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "proposal" / "演讲稿-4人版.md"
DST = ROOT / "proposal" / "演讲稿-4人版.docx"

ACCENT = "0D9488"          # the deck's teal, for cue lines
INK = "1A2B3C"
MUTED = "5A6B7B"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


# --------------------------------------------------------------------------
# runs and paragraphs
# --------------------------------------------------------------------------
def run(text: str, *, bold=False, italic=False, size=21, color=INK,
        font="Arial", ea="Microsoft YaHei") -> str:
    if any("\u3400" <= ch <= "\u9fff" for ch in text):
        font = ea = "Microsoft YaHei"
    space = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    props = [f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:eastAsia="{ea}"/>',
             f'<w:sz w:val="{size}"/>', f'<w:szCs w:val="{size}"/>',
             f'<w:color w:val="{color}"/>']
    if bold:
        props += ["<w:b/>", "<w:bCs/>"]
    if italic:
        props += ["<w:i/>", "<w:iCs/>"]
    return f"<w:r><w:rPr>{''.join(props)}</w:rPr><w:t{space}>{esc(text)}</w:t></w:r>"


def inline_runs(text: str, *, size=21, color=INK, italic_all=False) -> str:
    """**bold**, *italic*, `code` → runs. Code is rendered in a monospace font."""
    out = []
    pattern = re.compile(r"(\*\*.+?\*\*|\*[^*]+?\*|`[^`]+?`)", re.S)
    for chunk in pattern.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**"):
            out.append(run(chunk[2:-2], bold=True, size=size, color=color,
                           italic=italic_all))
        elif chunk.startswith("`") and chunk.endswith("`"):
            out.append(run(chunk[1:-1], size=size - 2, color="334155",
                           font="Consolas", ea="Consolas", italic=italic_all))
        elif chunk.startswith("*") and chunk.endswith("*") and len(chunk) > 2:
            out.append(run(chunk[1:-1], italic=True, size=size, color=color))
        else:
            out.append(run(chunk, size=size, color=color, italic=italic_all))
    return "".join(out) or run("", size=size)


def para(runs_xml: str, *, before=0, after=100, line=288, left=0, hanging=0,
         right=0, align=None, keep_next=False, shade=None, border_left=None,
         border_bottom=None) -> str:
    ppr = []
    if keep_next:
        ppr.append("<w:keepNext/>")
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    ppr.append(f'<w:spacing w:before="{before}" w:after="{after}" '
               f'w:line="{line}" w:lineRule="auto"/>')
    if left or hanging or right:
        ppr.append(f'<w:ind w:left="{left}" w:right="{right}" w:hanging="{hanging}"/>')
    if shade:
        ppr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
    if border_left:
        ppr.append('<w:pBdr>'
                   f'<w:left w:val="single" w:sz="18" w:space="8" w:color="{border_left}"/>'
                   '</w:pBdr>')
    if border_bottom:
        ppr.append('<w:pBdr>'
                   f'<w:bottom w:val="single" w:sz="6" w:space="2" w:color="{border_bottom}"/>'
                   '</w:pBdr>')
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs_xml}</w:p>"


def cell(text: str, *, bold=False, width_pct: int = 0) -> str:
    props = []
    if width_pct:
        props.append(f'<w:tcW w:w="{width_pct * 50}" w:type="pct"/>')
    return ("<w:tc><w:tcPr>" + "".join(props) + "</w:tcPr>"
            + para(inline_runs(text, size=19, color=INK if bold else MUTED,
                               italic_all=False) if not bold
                   else run(text, bold=True, size=19),
                   before=20, after=20, line=252)
            + "</w:tc>")


def table(rows: list[list[str]], widths: list[int]) -> str:
    borders = ('<w:tblBorders>'
               + "".join(f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="D8E0E8"/>'
                         for edge in ("top", "left", "bottom", "right", "insideH", "insideV"))
               + "</w:tblBorders>")
    xml = ['<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/>' + borders + '</w:tblPr>']
    for r_index, row in enumerate(rows):
        header = r_index == 0
        xml.append("<w:tr>")
        if header:
            xml.append('<w:trPr><w:tblHeader/></w:trPr>')
        for c_index, text in enumerate(row):
            width = widths[c_index] if c_index < len(widths) else 0
            props = []
            if width:
                props.append(f'<w:tcW w:w="{width * 50}" w:type="pct"/>')
            if header:
                props.append('<w:shd w:val="clear" w:color="auto" w:fill="F1F5F9"/>')
            body = (run(text, bold=True, size=19) if header
                    else inline_runs(text, size=19))
            xml.append("<w:tc><w:tcPr>" + "".join(props) + "</w:tcPr>"
                       + para(body, before=20, after=20, line=252) + "</w:tc>")
        xml.append("</w:tr>")
    xml.append("</w:tbl>" + para("", after=0, line=120))
    return "".join(xml)


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


# --------------------------------------------------------------------------
# package
# --------------------------------------------------------------------------
def document_xml(blocks: list[str]) -> str:
    sect = ('<w:sectPr>'
            '<w:pgSz w:w="11906" w:h="16838"/>'                     # A4
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
            'w:header="709" w:footer="709" w:gutter="0"/>'
            '<w:cols w:space="708"/><w:docGrid w:linePitch="360"/></w:sectPr>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}">'
            f'<w:body>{"".join(blocks)}{sect}</w:body></w:document>')


CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 f'<Types xmlns="{CT_NS}">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                 '</Types>')

ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<Relationships xmlns="{PKG_REL_NS}">'
             f'<Relationship Id="rId1" Type="{DOC_REL_TYPE}" Target="word/document.xml"/>'
             '</Relationships>')

DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">'
            f'<Relationship Id="rId1" Type="{STYLE_REL_TYPE}" Target="styles.xml"/>'
            '</Relationships>')

# Minimal but non-empty styles part: Word wants the built-in "Normal" style and
# the default font declared here, not only on each run.
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          f'<w:styles xmlns:w="{W_NS}">'
          '<w:docDefaults><w:rPrDefault><w:rPr>'
          '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/>'
          '<w:sz w:val="21"/><w:szCs w:val="21"/>'
          '</w:rPr></w:rPrDefault>'
          '<w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="288" w:lineRule="auto"/>'
          '</w:pPr></w:pPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
          '<w:name w:val="Normal"/><w:qFormat/></w:style>'
          '</w:styles>')


def build(md: str, out: Path) -> None:
    blocks = parse(md)
    with ZipFile(out, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", document_xml(blocks))
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", STYLES)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DST
    if not src.exists():
        raise SystemExit(f"source not found: {src}")
    md = src.read_text(encoding="utf-8")
    build(md, dst)
    # A page count of page breaks is a cheap sanity signal that the four parts
    # were split rather than run together.
    breaks = md.count("\n---\n---\n")
    print(f"wrote {dst.relative_to(ROOT)}  ({dst.stat().st_size / 1024:.0f} KB, "
          f"{len(md)} chars in, {breaks} part break(s))")


if __name__ == "__main__":
    main()
