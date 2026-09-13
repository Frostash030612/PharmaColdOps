#!/usr/bin/env python3
"""Build the Chinese proposal DOCX from the revised Markdown source.

This intentionally avoids third-party packages so the proposal can be rebuilt
in the course workspace even when python-docx/pandoc are unavailable.
"""
from __future__ import annotations

import html
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EMU_PER_INCH = 914400
MAX_IMAGE_CX = int(6.2 * EMU_PER_INCH)
# Letter page (11 in) less 0.75 in margins on each side leaves 9.5 in of text
# height; leave room for the caption. An inline image taller than the text area
# is pushed off the page by Word and reads as a blank block, so the long edge is
# capped as well as the width.
MAX_IMAGE_CY = int(8.5 * EMU_PER_INCH)


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def attr_escape(text: str) -> str:
    return html.escape(text, quote=True)


def clean_inline(text: str, *, strip: bool = True) -> str:
    text = text.replace("`", "")
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = text.replace("\\|", "|")
    # Only the outer edges of a paragraph may be stripped. Stripping every
    # inline segment would eat the space that separates a bold run from the
    # text after it ("**Demo, 2026-09-13:** Precomputed…" -> "…13:Precomputed").
    return text.strip() if strip else text


def split_bold_runs(text: str) -> list[tuple[str, bool]]:
    text = text.strip()  # strip the paragraph's outer edges once, not per segment
    parts: list[tuple[str, bool]] = []
    pos = 0
    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        if match.start() > pos:
            parts.append((clean_inline(text[pos : match.start()], strip=False), False))
        parts.append((clean_inline(match.group(1)), True))
        pos = match.end()
    if pos < len(text):
        parts.append((clean_inline(text[pos:], strip=False), False))
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


def svg_dimensions(path: Path) -> tuple[float, float]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    view_box = re.search(r'viewBox="([^"]+)"', text)
    if view_box:
        parts = [float(p) for p in re.split(r"[\s,]+", view_box.group(1).strip()) if p]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return parts[2], parts[3]
    width = re.search(r'width="([0-9.]+)', text)
    height = re.search(r'height="([0-9.]+)', text)
    if width and height:
        return float(width.group(1)), float(height.group(1))
    return 960.0, 540.0


def png_dimensions(path: Path) -> tuple[float, float]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return 960.0, 540.0
    width, height = struct.unpack(">II", data[16:24])
    return float(width), float(height)


def image_dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.lower() == ".svg":
        width, height = svg_dimensions(path)
    elif path.suffix.lower() == ".png":
        width, height = png_dimensions(path)
    else:
        width, height = 960.0, 540.0
    aspect = height / width if width else 0.5625
    cx = MAX_IMAGE_CX
    cy = int(cx * aspect)
    if cy > MAX_IMAGE_CY:
        scale = MAX_IMAGE_CY / cy
        cx = int(cx * scale)
        cy = MAX_IMAGE_CY
    return cx, cy


def image_xml(alt: str, rid: str, docpr_id: int, cx: int, cy: int) -> str:
    name = attr_escape(alt or f"Figure {docpr_id}")
    return (
        '<w:p><w:pPr><w:spacing w:before="120" w:after="90" w:line="276" w:lineRule="auto"/>'
        '<w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{docpr_id}" name="{name}" descr="{name}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr>'
        f'<pic:cNvPr id="{docpr_id}" name="{name}"/>'
        '<pic:cNvPicPr><a:picLocks noChangeAspect="1" noChangeArrowheads="1"/></pic:cNvPicPr>'
        '</pic:nvPicPr><pic:blipFill>'
        f'<a:blip r:embed="{rid}"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr bwMode="auto">'
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        '</pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic>'
        '</wp:inline></w:drawing></w:r></w:p>'
    )


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


def parse_markdown(md: str, source_dir: Path) -> tuple[list[str], list[tuple[str, Path, str]]]:
    blocks: list[str] = []
    media: list[tuple[str, Path, str]] = []
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
            image_match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line)
            if image_match:
                alt = clean_inline(image_match.group(1))
                rel_path = image_match.group(2)
                image_path = (source_dir / rel_path).resolve()
                rid = f"rIdImg{len(media) + 1}"
                cx, cy = image_dimensions(image_path)
                media.append((rid, image_path, rel_path))
                blocks.append(image_xml(alt, rid, len(media), cx, cy))
            else:
                blocks.append(paragraph_xml(clean_inline(line), italic=True, size=20, after=70))
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
    return blocks, media


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
        f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}" xmlns:xml="{XML_NS}" '
        f'xmlns:wp="{WP_NS}" xmlns:a="{A_NS}" xmlns:pic="{PIC_NS}">'
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


def add_relationships(rels_xml: bytes, media: list[tuple[str, Path, str]]) -> bytes:
    text = rels_xml.decode("utf-8")
    text = re.sub(
        r'<Relationship Id="rIdImg\d+" Type="http://schemas\.openxmlformats\.org/officeDocument/2006/relationships/image" Target="media/image\d+\.[^"]+"\s*/>',
        "",
        text,
    )
    insert = "".join(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/image{idx}{path.suffix.lower()}"/>'
        for idx, (rid, path, _rel_path) in enumerate(media, start=1)
    )
    text = text.replace("</Relationships>", insert + "</Relationships>")
    return text.encode("utf-8")


def ensure_content_types(content_xml: bytes, media: list[tuple[str, Path, str]]) -> bytes:
    text = content_xml.decode("utf-8")
    defaults = {
        ".png": '<Default Extension="png" ContentType="image/png"/>',
        ".svg": '<Default Extension="svg" ContentType="image/svg+xml"/>',
    }
    needed = []
    for _rid, path, _rel_path in media:
        suffix = path.suffix.lower()
        if suffix in defaults and f'Extension="{suffix[1:]}"' not in text:
            needed.append(defaults[suffix])
    if needed:
        text = re.sub(r"(<Types\b[^>]*>)", r"\1" + "".join(dict.fromkeys(needed)), text, count=1)
    return text.encode("utf-8")


def build_docx(source_md: Path, template_docx: Path, output_docx: Path) -> None:
    blocks, media = parse_markdown(source_md.read_text(encoding="utf-8"), source_md.parent)
    doc_xml = document_xml(blocks)
    with ZipFile(template_docx, "r") as zin:
        entries = {info.filename: zin.read(info.filename) for info in zin.infolist()}
    entries = {
        name: data
        for name, data in entries.items()
        if not re.fullmatch(r"word/media/image\d+\.(svg|png)", name)
    }
    entries["word/document.xml"] = doc_xml.encode("utf-8")
    entries["docProps/core.xml"] = core_xml().encode("utf-8")
    entries["word/_rels/document.xml.rels"] = add_relationships(
        entries["word/_rels/document.xml.rels"], media
    )
    entries["[Content_Types].xml"] = ensure_content_types(entries["[Content_Types].xml"], media)
    for idx, (_rid, image_path, _rel_path) in enumerate(media, start=1):
        entries[f"word/media/image{idx}{image_path.suffix.lower()}"] = image_path.read_bytes()
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
