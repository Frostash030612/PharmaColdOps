"""Shared OOXML building blocks for the printable documents in this repo.

The course workspace may not have python-docx or pandoc, so these helpers write
a complete OOXML package from scratch. They were factored out of
`build_speech_docx.py` unchanged, so both documents keep the same look and there
is only one copy of the styling rules.

Consumers:
    scripts/build_speech_docx.py  — the four-speaker presentation script
    scripts/build_qa_docx.py      — the printed Q&A preparation sheet
"""
from __future__ import annotations

import html
import re
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


def page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def read_rows(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    """Collect a Markdown table starting at `start`; returns (rows, next index)."""
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            rows.append(cells)
        i += 1
    return rows, i


def equal_widths(rows: list[list[str]]) -> list[int]:
    n = max(len(r) for r in rows)
    widths = [int(100 / n)] * n
    widths[-1] = 100 - sum(widths[:-1])
    return widths


# --------------------------------------------------------------------------
# package
# --------------------------------------------------------------------------
def document_xml(blocks: list[str], *, margin=1134, footer: str = "") -> str:
    """A4, single column. `margin` is in twips (1134 = 2 cm)."""
    sect = ('<w:sectPr>'
            '<w:pgSz w:w="11906" w:h="16838"/>'                     # A4
            f'<w:pgMar w:top="{margin}" w:right="{margin}" w:bottom="{margin}" '
            f'w:left="{margin}" w:header="709" w:footer="709" w:gutter="0"/>'
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


def build(blocks: list[str], out: Path, *, margin: int = 1134) -> None:
    with ZipFile(out, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", document_xml(blocks, margin=margin))
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", STYLES)
