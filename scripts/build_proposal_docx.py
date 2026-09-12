#!/usr/bin/env python3
"""Build the Chinese proposal DOCX from the revised Markdown source.

This intentionally avoids third-party packages so the proposal can be rebuilt
in the course workspace even when python-docx/pandoc are unavailable.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def attr_escape(text: str) -> str:
    return html.escape(text, quote=True)


def clean_inline(text: str) -> str:
    text = text.replace("`", "")
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = text.replace("\\|", "|")
    return text.strip()


def split_bold_runs(text: str) -> list[tuple[str, bool]]:
    parts: list[tuple[str, bool]] = []
    pos = 0
    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        if match.start() > pos:
            parts.append((clean_inline(text[pos : match.start()]), False))
        parts.append((clean_inline(match.group(1)), True))
        pos = match.end()
    if pos < len(text):
        parts.append((clean_inline(text[pos:]), False))
    return [(value, bold) for value, bold in parts if value]


def run_xml(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    size: int = 22,
    color: str = "000000",
    font: str = "Aptos",
    east_asia_font: str = "Microsoft YaHei",
) -> str:
    space = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    props = [
        f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:eastAsia="{east_asia_font}"/>',
        f'<w:sz w:val="{size}"/>',
        f'<w:szCs w:val="{size}"/>',
        f'<w:color w:val="{color}"/>',
    ]
    if bold:
        props.append("<w:b/>")
        props.append("<w:bCs/>")
    if italic:
        props.append("<w:i/>")
        props.append("<w:iCs/>")
    return f"<w:r><w:rPr>{''.join(props)}</w:rPr><w:t{space}>{esc(text)}</w:t></w:r>"


def paragraph_xml(
    runs: list[tuple[str, bool]] | str,
    *,
    style: str | None = None,
    size: int = 22,
    bold: bool = False,
    italic: bool = False,
    before: int = 0,
    after: int = 120,
    line: int = 276,
    indent_left: int = 0,
    hanging: int = 0,
    align: str | None = None,
    keep_next: bool = False,
) -> str:
    ppr: list[str] = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        ppr.append("<w:keepNext/>")
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    ppr.append(f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="auto"/>')
    if indent_left or hanging:
        ppr.append(f'<w:ind w:left="{indent_left}" w:hanging="{hanging}"/>')
    if isinstance(runs, str):
        body = run_xml(clean_inline(runs), bold=bold, italic=italic, size=size)
    else:
        body = "".join(run_xml(text, bold=(is_bold or bold), italic=italic, size=size) for text, is_bold in runs)
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{body}</w:p>"


def heading_xml(text: str, level: int) -> str:
    if level == 1:
        return paragraph_xml(text, size=40, bold=True, before=0, after=80, line=320, keep_next=True)
    if level == 2:
        return paragraph_xml(text, size=28, bold=True, before=260, after=100, line=300, keep_next=True)
    return paragraph_xml(text, size=24, bold=True, before=180, after=80, line=286, keep_next=True)


def table_xml(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    cols = max(len(r) for r in rows)
    widths = [int(9360 / cols)] * cols
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    table_props = (
        '<w:tblPr><w:tblW w:w="9360" w:type="dxa"/>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="D9D9D9"/>'
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="D9D9D9"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="D9D9D9"/>'
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="D9D9D9"/>'
        '<w:insideH w:val="single" w:sz="6" w:space="0" w:color="D9D9D9"/>'
        '<w:insideV w:val="single" w:sz="6" w:space="0" w:color="D9D9D9"/>'
        '</w:tblBorders><w:tblLook w:firstRow="1" w:lastRow="0" w:firstColumn="0" '
        'w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
    )
    out = [f"<w:tbl>{table_props}<w:tblGrid>{grid}</w:tblGrid>"]
    for row_idx, row in enumerate(rows):
        out.append("<w:tr>")
        for col_idx in range(cols):
            text = clean_inline(row[col_idx]) if col_idx < len(row) else ""
            shading = '<w:shd w:fill="1F4E79"/>' if row_idx == 0 else ('<w:shd w:fill="F6F8FA"/>' if row_idx % 2 == 0 else "")
            color = "FFFFFF" if row_idx == 0 else "000000"
            cell_props = (
                f'<w:tcPr><w:tcW w:w="{widths[col_idx]}" w:type="dxa"/>{shading}'
                '<w:tcMar><w:top w:w="90" w:type="dxa"/><w:left w:w="90" w:type="dxa"/>'
                '<w:bottom w:w="90" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tcMar>'
                '<w:vAlign w:val="center"/></w:tcPr>'
            )
            para = (
                '<w:p><w:pPr><w:spacing w:before="0" w:after="60" w:line="250" w:lineRule="auto"/></w:pPr>'
                + run_xml(text, bold=(row_idx == 0), size=19, color=color)
                + "</w:p>"
            )
            out.append(f"<w:tc>{cell_props}{para}</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def parse_markdown(md: str) -> list[str]:
    blocks: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("|") and "|" in line[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                current = lines[i].strip()
                if not re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", current):
                    cells = [c.strip() for c in current.strip("|").split("|")]
                    table_lines.append(cells)
                i += 1
            blocks.append(table_xml(table_lines))
            continue
        match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if match:
            blocks.append(heading_xml(clean_inline(match.group(2)), len(match.group(1))))
            i += 1
            continue
        if line.startswith("!["):
            alt = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", line)
            blocks.append(paragraph_xml(f"图示：{alt}", italic=True, size=20, after=70))
            i += 1
            continue
        if line.startswith("- "):
            blocks.append(paragraph_xml("• " + clean_inline(line[2:]), size=21, after=65, indent_left=420, hanging=220))
            i += 1
            continue
        ordered = re.match(r"^(\d+)\.\s+(.+)$", line)
        if ordered:
            blocks.append(paragraph_xml(f"{ordered.group(1)}. {clean_inline(ordered.group(2))}", size=21, after=65, indent_left=420, hanging=260))
            i += 1
            continue
        if line.startswith("**") and line.endswith("**") and line.count("**") == 2:
            blocks.append(paragraph_xml(line.strip("*"), bold=True, size=23, after=80))
            i += 1
            continue

        para_parts = [line.strip()]
        i += 1
        while i < len(lines):
            nxt = lines[i].rstrip()
            if not nxt.strip() or nxt.startswith("#") or nxt.startswith("|") or nxt.startswith("- ") or re.match(r"^\d+\.\s+", nxt) or nxt.startswith("!["):
                break
            para_parts.append(nxt.strip())
            i += 1
        paragraph = " ".join(para_parts)
        blocks.append(paragraph_xml(split_bold_runs(paragraph), size=21, after=95))
    return blocks


def document_xml(body_blocks: list[str]) -> str:
    sect = (
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" '
        'w:header="720" w:footer="720" w:gutter="0"/>'
        '<w:cols w:space="720"/><w:docGrid w:linePitch="360"/></w:sectPr>'
    )
    body = "".join(body_blocks) + sect
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}" xmlns:xml="{XML_NS}">'
        f"<w:body>{body}</w:body></w:document>"
    )


def core_xml() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>PharmaColdOps 项目提案</dc:title>'
        '<dc:subject>冷链药品温度偏移处置与配送改派决策支持原型</dc:subject>'
        '<dc:creator>PharmaColdOps Team</dc:creator>'
        '<cp:lastModifiedBy>Codex</cp:lastModifiedBy>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        '</cp:coreProperties>'
    )


def build_docx(source_md: Path, template_docx: Path, output_docx: Path) -> None:
    blocks = parse_markdown(source_md.read_text(encoding="utf-8"))
    doc_xml = document_xml(blocks)
    with ZipFile(template_docx, "r") as zin:
        entries = {info.filename: zin.read(info.filename) for info in zin.infolist()}
    entries["word/document.xml"] = doc_xml.encode("utf-8")
    entries["docProps/core.xml"] = core_xml().encode("utf-8")
    tmp = output_docx.with_suffix(".docx.tmp")
    with ZipFile(tmp, "w", ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            zout.writestr(name, data)
    tmp.replace(output_docx)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: build_proposal_docx.py SOURCE_MD TEMPLATE_DOCX OUTPUT_DOCX", file=sys.stderr)
        return 2
    build_docx(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
