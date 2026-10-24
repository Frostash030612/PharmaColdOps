"""Build the final report DOCX; optionally append the submitted proposal to a rendered PDF.

The report source is `docs/FINAL_REPORT_EN.md`. Styling lives only here so the Word
deliverable and the rendered PDF stay reproducible. Documentation-only extras:
python-docx, pypdf and the bundled LibreOffice converter. Runtime dependencies are
unchanged.

Two-pass build:
  1. build the DOCX with unresolved contents page numbers, render the body PDF;
  2. resolve headings against that PDF, rebuild the DOCX, render the final body PDF;
  3. append the unchanged submitted proposal to the final PDF.

Render and visually review the DOCX with the documented document renderer before PDF
assembly.
"""
import argparse
from pathlib import Path
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/FINAL_REPORT_EN.md"
MEMBERS = ROOT / "member-github.txt"

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
CONTENT_WIDTH = 6.7          # inches, Letter with 0.9 in side margins
INK = "1F2A30"
NAVY = "16384A"
TEAL = "0E7C86"
MUTED = "5B6B75"
LIGHT = "8A98A0"
RULE = "D6DFE4"
BAND = "EDF3F4"
ZEBRA = "F7FAFA"
CODE_BG = "F4F7F8"
LINK = "0B6570"

BODY_FONT = "Georgia"
HEAD_FONT = "Arial"
MONO_FONT = "Consolas"
EA_FONT = "Microsoft YaHei"


def plain(text):
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    return text.replace("**", "").replace("`", "")


def contents_entries():
    """All numbered headings; the contents page lists H1 and H2 entries."""
    entries = []
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            entries.append({"text": plain(line[3:]), "level": 1, "page": ""})
        elif line.startswith("### "):
            entries.append({"text": plain(line[4:]), "level": 2, "page": ""})
    return entries


def contents_from_pdf(path):
    """Resolve every contents entry against a freshly rendered body PDF.

    Contents pages use dot leaders, so they are excluded before the sequential
    heading search; this keeps duplicate words in front matter from matching a
    body heading.
    """
    from pypdf import PdfReader

    norm = lambda value: re.sub(r"\s+", " ", value).strip()
    pages = [norm(page.extract_text()) for page in PdfReader(path).pages]
    toc_pages = [i for i, text in enumerate(pages[:8]) if len(re.findall(r"\.{3,}", text)) >= 3]
    start = max(toc_pages) + 1 if toc_pages else 2
    entries = contents_entries()
    last = start
    for entry in entries:
        target = norm(entry["text"])
        found = next((j for j in range(last, len(pages)) if target in pages[j]), None)
        if found is None:
            matches = [j for j in range(start, len(pages)) if target in pages[j]]
            if len(matches) != 1:
                raise ValueError(f"Cannot resolve unique heading {entry['text']!r}: {matches}")
            found = matches[0]
        entry["page"] = found + 1
        last = found
    return entries


def _members():
    members = []
    for line in MEMBERS.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"(.+?)\s+-\s+(A\d+[A-Z]?)", line.strip())
        if match:
            members.append((match.group(1), match.group(2)))
    if len(members) != 4:
        raise ValueError("member-github.txt must list four members and student IDs")
    return members


def build(output, toc=None, report_date="23 October 2026"):
    from docx import Document
    from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.shared import Inches, Pt, RGBColor

    rgb = lambda value: RGBColor.from_string(value)
    doc = Document()
    doc.core_properties.title = "PharmaColdOps Project Report"
    doc.core_properties.author = "Project Group 41"
    doc.core_properties.subject = "IRS practice module: implemented system and evaluation"
    doc.core_properties.keywords = "cold chain; pharmaceutical; decision support; MKT; VRPTW; knowledge graph"
    doc.core_properties.comments = "Group 41 final report. Simulated data; not a clinical validation."
    doc.core_properties.category = "Course project report"

    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = Inches(0.9)
    section.bottom_margin = Inches(0.85)
    section.left_margin = section.right_margin = Inches(0.9)
    section.header_distance = Inches(0.45)
    section.footer_distance = Inches(0.4)
    section.different_first_page_header_footer = True

    if toc is None:
        toc = contents_entries()

    # ---------------------------------------------------------------- styles
    def set_font(style, font, size, color=INK, bold=False, italic=False):
        style.font.name = font
        style.font.size = Pt(size)
        style.font.color.rgb = rgb(color)
        style.font.bold = bold
        style.font.italic = italic
        rpr = style.element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.insert(0, fonts)
        for key, value in (("w:ascii", font), ("w:hAnsi", font), ("w:eastAsia", EA_FONT), ("w:cs", font)):
            fonts.set(qn(key), value)
        for tag in ("w:lang",):
            node = rpr.find(qn(tag))
            if node is None:
                node = OxmlElement(tag)
                rpr.append(node)
            node.set(qn("w:val"), "en-GB")

    normal = doc.styles["Normal"]
    set_font(normal, BODY_FONT, 10.5)
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(5.5)
    pf.line_spacing = 1.3
    pf.widow_control = True

    set_font(doc.styles["Heading 1"], HEAD_FONT, 15, NAVY, bold=True)
    set_font(doc.styles["Heading 2"], HEAD_FONT, 11.5, TEAL, bold=True)
    set_font(doc.styles["Heading 3"], HEAD_FONT, 10.5, NAVY, bold=True)
    for name, before, after in (("Heading 1", 0, 10), ("Heading 2", 12, 3), ("Heading 3", 9, 2)):
        style = doc.styles[name]
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.line_spacing = 1.0
    # Drop inherited template rules; direct heading rules are added below.
    for node in doc.styles.element.xpath(".//w:pBdr"):
        node.getparent().remove(node)

    # ------------------------------------------------------- header/footer
    def add_field(paragraph, instruction, size=7.5, color=MUTED):
        run = paragraph.add_run()
        run.font.name = HEAD_FONT
        run.font.size = Pt(size)
        run.font.color.rgb = rgb(color)
        rpr = run._r.get_or_add_rPr()
        fonts = OxmlElement("w:rFonts")
        fonts.set(qn("w:ascii"), HEAD_FONT)
        fonts.set(qn("w:hAnsi"), HEAD_FONT)
        fonts.set(qn("w:eastAsia"), EA_FONT)
        rpr.insert(0, fonts)
        begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = f" {instruction} "
        separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
        value = OxmlElement("w:t"); value.text = "1"
        end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
        run._r.extend([begin, instr, separate, value, end])

    def add_bottom_rule(paragraph, color, size=6, space=4):
        ppr = paragraph._p.get_or_add_pPr()
        pbdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), str(size))
        bottom.set(qn("w:space"), str(space))
        bottom.set(qn("w:color"), color)
        pbdr.append(bottom)
        ppr.append(pbdr)

    header = section.header.paragraphs[0]
    header.paragraph_format.space_after = Pt(2)
    header.paragraph_format.tab_stops.add_tab_stop(Inches(CONTENT_WIDTH), WD_TAB_ALIGNMENT.RIGHT)
    run = header.add_run("PharmaColdOps Project Report")
    run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(7.5), rgb(MUTED)
    header.add_run("\t")
    run = header.add_run("IRS Practice Module  ·  Project Group 41")
    run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(7.5), rgb(MUTED)
    add_bottom_rule(header, RULE, size=6, space=3)

    footer = section.footer.paragraphs[0]
    footer.paragraph_format.space_before = Pt(2)
    footer.paragraph_format.tab_stops.add_tab_stop(Inches(CONTENT_WIDTH), WD_TAB_ALIGNMENT.RIGHT)
    run = footer.add_run("Project Group 41  ·  " + report_date)
    run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(7.5), rgb(MUTED)
    footer.add_run("\t")
    run = footer.add_run("Page ")
    run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(7.5), rgb(MUTED)
    add_field(footer, "PAGE")
    run = footer.add_run(" of ")
    run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(7.5), rgb(MUTED)
    add_field(footer, "NUMPAGES")

    first_footer = section.first_page_footer.paragraphs[0]
    first_footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    first_footer.paragraph_format.space_before = Pt(4)
    add_bottom_rule(first_footer, TEAL, size=6, space=6)  # top edge in the footer area
    run = first_footer.add_run("Editable Word report  ·  the companion PDF appends the submitted proposal as Appendix C")
    run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(7.5), rgb(MUTED)

    # -------------------------------------------------------------- helpers
    def spacer(points):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(points)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        return p

    def add_runs(paragraph, text, size=10.5, color=INK, bold=False, font=BODY_FONT):
        """Append text with inline **bold** and [label](target) markdown."""
        pattern = re.compile(r"(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)")
        position = 0

        def add_plain(value, is_bold=False):
            if not value:
                return
            run = paragraph.add_run(value)
            run.font.name = font
            run.font.size = Pt(size)
            run.font.color.rgb = rgb(color)
            run.font.bold = bold or is_bold
            rpr = run._r.get_or_add_rPr()
            fonts = rpr.find(qn("w:rFonts"))
            if fonts is None:
                fonts = OxmlElement("w:rFonts")
                rpr.insert(0, fonts)
            for key, font_value in (("w:ascii", font), ("w:hAnsi", font),
                                    ("w:eastAsia", EA_FONT), ("w:cs", font)):
                fonts.set(qn(key), font_value)

        for match in pattern.finditer(text):
            add_plain(text[position:match.start()])
            token = match.group(0)
            if token.startswith("**"):
                add_plain(token[2:-2], is_bold=True)
            else:
                label = token[1:token.index("]")]
                target = token[token.index("(") + 1:-1]
                if not re.match(r"[a-z]+://", target):
                    relative = (SOURCE.parent / target).resolve().relative_to(ROOT).as_posix()
                    target = "https://github.com/Frostash030612/PharmaColdOps/blob/main/" + quote(relative, safe="/")
                relationship = paragraph.part.relate_to(
                    target, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
                link = OxmlElement("w:hyperlink")
                link.set(qn("r:id"), relationship)
                run = OxmlElement("w:r")
                properties = OxmlElement("w:rPr")
                for tag, attrs in (
                    ("w:rFonts", {"w:ascii": font, "w:hAnsi": font, "w:eastAsia": EA_FONT}),
                    ("w:color", {"w:val": LINK}),
                    ("w:u", {"w:val": "none"}),
                    ("w:sz", {"w:val": str(int(size * 2))}),
                ):
                    node = OxmlElement(tag)
                    for key, value in attrs.items():
                        node.set(qn(key), value)
                    properties.append(node)
                run.append(properties)
                value = OxmlElement("w:t")
                value.text = label
                run.append(value)
                link.append(run)
                paragraph._p.append(link)
            position = match.end()
        add_plain(text[position:])

    def caption(prefix, rest, kind):
        paragraph = doc.add_paragraph()
        fmt = paragraph.paragraph_format
        if kind == "table":
            fmt.space_before = Pt(9)
            fmt.space_after = Pt(3)
            fmt.keep_with_next = True
        else:
            fmt.space_before = Pt(4)
            fmt.space_after = Pt(10)
            fmt.left_indent = Inches(0.55)
            fmt.right_indent = Inches(0.55)
        first = paragraph.add_run(prefix + " ")
        first.font.name = HEAD_FONT
        first.font.size = Pt(8.3)
        first.font.bold = True
        first.font.color.rgb = rgb(TEAL)
        second = paragraph.add_run(rest)
        second.font.name = HEAD_FONT
        second.font.size = Pt(8.3)
        second.font.color.rgb = rgb(MUTED)
        return paragraph

    def add_picture_border(inline_shape):
        try:
            from docx.oxml import parse_xml
            from docx.oxml.ns import nsdecls
            sp_pr = inline_shape._inline.graphic.graphicData.pic.spPr
            sp_pr.append(parse_xml(
                f'<a:ln {nsdecls("a")} w="6350"><a:solidFill><a:srgbClr val="{RULE}"/>'
                '</a:solidFill><a:prstDash val="solid"/></a:ln>'))
        except Exception:
            pass

    # ---------------------------------------------------------------- cover
    members = _members()
    band = doc.add_table(rows=1, cols=1)
    band.alignment = WD_TABLE_ALIGNMENT.CENTER
    band.autofit = False
    band.columns[0].width = Inches(CONTENT_WIDTH)
    band.rows[0].height = Inches(0.16)
    band.rows[0].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    band_cell = band.rows[0].cells[0]
    band_cell.width = Inches(CONTENT_WIDTH)
    band_cell._tc.get_or_add_tcPr().append(OxmlElement("w:shd"))
    band_cell._tc.get_or_add_tcPr()[-1].set(qn("w:fill"), NAVY)
    band_cell._tc.get_or_add_tcPr().append(OxmlElement("w:tcMar"))
    band_cell.paragraphs[0].paragraph_format.space_after = Pt(0)
    band_cell.paragraphs[0].add_run("")

    spacer(18)
    kicker = doc.add_paragraph()
    kicker.paragraph_format.space_after = Pt(6)
    run = kicker.add_run("IRS PRACTICE MODULE   ·   FINAL PROJECT REPORT")
    run.font.name, run.font.size, run.font.bold, run.font.color.rgb = HEAD_FONT, Pt(8.5), True, rgb(TEAL)
    run._r.get_or_add_rPr().append(OxmlElement("w:spacing"))
    run._r.get_or_add_rPr()[-1].set(qn("w:val"), "34")

    title = doc.add_paragraph()
    title.paragraph_format.space_after = Pt(0)
    title.paragraph_format.line_spacing = 0.98
    run = title.add_run("PharmaColdOps")
    run.font.name, run.font.size, run.font.bold, run.font.color.rgb = BODY_FONT, Pt(34), True, rgb(NAVY)

    subtitle = doc.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(10)
    run = subtitle.add_run("Project Report")
    run.font.name, run.font.size, run.font.color.rgb = BODY_FONT, Pt(19), rgb(MUTED)

    rule = doc.add_paragraph()
    rule.paragraph_format.space_after = Pt(0)
    rule.paragraph_format.line_spacing = Pt(1)
    add_bottom_rule(rule, TEAL, size=12, space=2)

    spacer(14)
    tagline = doc.add_paragraph()
    tagline.paragraph_format.space_after = Pt(0)
    tagline.paragraph_format.line_spacing = 1.25
    run = tagline.add_run("An explainable decision-support prototype for pharmaceutical "
                          "cold-chain temperature excursions: assessment, human review, "
                          "replacement delivery and case evidence.")
    run.font.name, run.font.size, run.font.italic = BODY_FONT, Pt(12.5), True
    run.font.color.rgb = rgb(MUTED)

    spacer(144)
    group = doc.add_paragraph()
    group.paragraph_format.space_after = Pt(5)
    run = group.add_run("PROJECT GROUP 41")
    run.font.name, run.font.size, run.font.bold, run.font.color.rgb = HEAD_FONT, Pt(9), True, rgb(TEAL)
    run._r.get_or_add_rPr().append(OxmlElement("w:spacing"))
    run._r.get_or_add_rPr()[-1].set(qn("w:val"), "30")

    authors = doc.add_table(rows=2, cols=2)
    authors.alignment = WD_TABLE_ALIGNMENT.LEFT
    authors.autofit = False
    for column in authors.columns:
        column.width = Inches(CONTENT_WIDTH / 2)
    for index, (name, student_id) in enumerate(members):
        row, column = divmod(index, 2)
        cell = authors.rows[row].cells[column]
        cell.width = Inches(CONTENT_WIDTH / 2)
        cell.paragraphs[0].paragraph_format.space_after = Pt(4)
        run = cell.paragraphs[0].add_run(name)
        run.font.name, run.font.size, run.font.bold, run.font.color.rgb = BODY_FONT, Pt(10.5), True, rgb(NAVY)
        run = cell.paragraphs[0].add_run("   " + student_id)
        run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(9), rgb(MUTED)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    # remove the decorative table borders
    tbl_pr = authors._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement("w:" + edge)
        node.set(qn("w:val"), "none")
        borders.append(node)
    tbl_pr.append(borders)

    date_paragraph = doc.add_paragraph()
    date_paragraph.paragraph_format.space_before = Pt(8)
    date_paragraph.paragraph_format.space_after = Pt(0)
    run = date_paragraph.add_run(report_date)
    run.font.name, run.font.size, run.font.color.rgb = HEAD_FONT, Pt(9.5), rgb(MUTED)

    # ---------------------------------------------------------------- contents
    if toc:
        doc.add_page_break()
        heading = doc.add_paragraph()
        heading.paragraph_format.space_after = Pt(14)
        run = heading.add_run("Contents")
        run.font.name, run.font.size, run.font.bold, run.font.color.rgb = HEAD_FONT, Pt(20), True, rgb(NAVY)
        add_bottom_rule(heading, TEAL, size=10, space=6)
        for entry in toc:
            item = doc.add_paragraph()
            fmt = item.paragraph_format
            fmt.tab_stops.add_tab_stop(Inches(CONTENT_WIDTH), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            fmt.line_spacing = 1.0
            if entry.get("level", 1) == 1:
                fmt.space_before = Pt(4.5)
                fmt.space_after = Pt(0)
                run = item.add_run(entry["text"])
                run.font.name, run.font.size, run.font.bold, run.font.color.rgb = HEAD_FONT, Pt(9.5), True, rgb(NAVY)
            else:
                fmt.left_indent = Inches(0.28)
                fmt.space_before = Pt(0)
                fmt.space_after = Pt(0)
                run = item.add_run(entry["text"])
                run.font.name, run.font.size, run.font.color.rgb = BODY_FONT, Pt(9.0), rgb(INK)
            item.add_run("\t")
            page_run = item.add_run(str(entry.get("page", "")))
            page_run.font.name, page_run.font.size, page_run.font.color.rgb = HEAD_FONT, Pt(9), rgb(MUTED)

    # ------------------------------------------------------------------ body
    def add_heading(text, level):
        paragraph = doc.add_paragraph(plain(text), style=f"Heading {level}")
        if level == 1:
            # The contents page ends before the summary; the body flows from there.
            starts_new_page = text == "Executive summary"
            paragraph.paragraph_format.page_break_before = starts_new_page
            paragraph.paragraph_format.space_before = Pt(0 if starts_new_page else 20)
            add_bottom_rule(paragraph, TEAL, size=8, space=4)
        return paragraph

    def add_table(matrix, caption_text=None):
        number, _, rest = caption_text.partition(". ")
        caption(number + ".", rest, "table")
        headers = [plain(cell) for cell in matrix[0]]
        widths_map = {
            ("Priority",): [0.72, 4.65, 1.33],
            ("Method",): [1.1, 3.9, 1.7],
            ("Module",): [0.7, 3.8, 2.2],
            ("Candidate",): [1.55, 1.0, 1.35, 1.15, 1.65],
            ("Historical class",): [2.6, 1.35, 1.35, 1.4],
            ("Risk metric",): [3.9, 2.8],
            ("Split",): [1.95, 1.2, 1.35, 1.1, 1.1],
            ("Held-out role", "Frozen v1"): [2.0, 1.05, 1.3, 1.35, 1.0],
            ("Held-out role", "Supported / tested"): [1.9, 1.45, 1.6, 1.75],
            ("Instance",): [1.9, 1.6, 1.6, 1.6],
            ("Instance and method",): [2.9, 1.25, 1.25, 1.3],
            ("Review dimension",): [2.45, 0.7, 0.85, 0.85, 0.85, 1.0],
            ("Frozen example",): [1.65, 2.5, 2.55],
            ("Area",): [2.1, 2.15, 2.45],
            ("Course area",): [1.75, 3.05, 1.9],
        }
        widths = next((value for key, value in widths_map.items() if headers[:len(key)] == list(key)), None)
        if widths is None or len(widths) != len(headers):
            widths = [CONTENT_WIDTH / len(headers)] * len(headers)
        table = doc.add_table(rows=0, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        for column, width in zip(table.columns, widths):
            column.width = Inches(width)
        table_xml = table._tbl
        tbl_pr = table_xml.tblPr
        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        tbl_pr.append(layout)
        borders = OxmlElement("w:tblBorders")
        for edge, size, color in (("top", "8", NAVY), ("bottom", "8", NAVY),
                                  ("insideH", "4", RULE), ("left", "0", RULE),
                                  ("right", "0", RULE), ("insideV", "0", RULE)):
            node = OxmlElement("w:" + edge)
            node.set(qn("w:val"), "single" if int(size) else "none")
            node.set(qn("w:sz"), size)
            node.set(qn("w:space"), "0")
            node.set(qn("w:color"), color)
            borders.append(node)
        tbl_pr.append(borders)

        numeric = []
        for column in range(len(headers)):
            values = [row[column] for row in matrix[1:] if column < len(row)]
            numeric.append(bool(values) and sum(
                bool(re.fullmatch(r"[0-9 .%/+−±()–-]+", value)) for value in values) > len(values) / 2)

        for row_index, values in enumerate(matrix):
            cells = table.add_row().cells
            row = table.rows[row_index]
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            tr_pr = row._tr.get_or_add_trPr()
            tr_pr.append(OxmlElement("w:cantSplit"))
            if len(matrix) <= 9:
                for cell in cells:
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.keep_with_next = row_index < len(matrix) - 1
            for column, (cell, value) in enumerate(zip(cells, values)):
                cell.width = Inches(widths[column])
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                tc_pr = cell._tc.get_or_add_tcPr()
                margins = OxmlElement("w:tcMar")
                for edge, size in (("top", "70"), ("left", "90"), ("bottom", "70"), ("right", "90")):
                    node = OxmlElement("w:" + edge)
                    node.set(qn("w:w"), size)
                    node.set(qn("w:type"), "dxa")
                    margins.append(node)
                tc_pr.append(margins)
                if row_index == 0:
                    shade = OxmlElement("w:shd")
                    shade.set(qn("w:fill"), BAND)
                    tc_pr.append(shade)
                elif row_index % 2 == 0:
                    shade = OxmlElement("w:shd")
                    shade.set(qn("w:fill"), ZEBRA)
                    tc_pr.append(shade)
                paragraph = cell.paragraphs[0]
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.05
                if row_index > 0 and numeric[column]:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run(plain(value))
                run.font.name = HEAD_FONT
                run.font.size = Pt(8.7 if row_index else 8.6)
                run.font.bold = row_index == 0
                run.font.color.rgb = rgb(NAVY if row_index == 0 else INK)
                if row_index == 0:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if column else WD_ALIGN_PARAGRAPH.LEFT
        if table.rows:
            repeat = OxmlElement("w:tblHeader")
            table.rows[0]._tr.get_or_add_trPr().append(repeat)
        spacer(6)

    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    in_references = False
    pending_caption = None
    expected_table = 1
    expected_figure = 1
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        if line.startswith("!["):
            match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line)
            if not match:
                raise ValueError("unsupported figure syntax")
            caption_text = match.group(1)
            width = None
            if "|" in caption_text:
                caption_text, _, spec = caption_text.rpartition("|")
                if re.fullmatch(r"\d+(?:\.\d+)?(?:in)?", spec.strip()):
                    width = float(spec.strip().rstrip("in"))
            prefix, _, rest = caption_text.partition(". ")
            if not prefix.startswith("Figure "):
                raise ValueError("figure captions must start with Figure N.")
            number = int(prefix.split()[1])
            if number != expected_figure:
                raise ValueError(f"unexpected figure number {number}, expected {expected_figure}")
            expected_figure += 1
            paragraph = doc.add_paragraph()
            paragraph.alignment = 1
            paragraph.paragraph_format.space_before = Pt(8)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.keep_with_next = True
            run = paragraph.add_run()
            picture = run.add_picture(str(SOURCE.parent / match.group(2)),
                                      width=Inches(min(width or 6.5, 6.5)))
            add_picture_border(picture)
            caption(prefix + ".", rest, "figure")
            i += 1
            continue
        if line.startswith("# "):
            i += 1
            continue
        if line.startswith("## "):
            text = line[3:]
            in_references = text.startswith("References")
            add_heading(text, 1)
            i += 1
            continue
        if line.startswith("### "):
            add_heading(line[4:], 2)
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            paragraph = doc.add_paragraph()
            fmt = paragraph.paragraph_format
            fmt.space_before = Pt(6)
            fmt.space_after = Pt(8)
            fmt.left_indent = Inches(0.12)
            fmt.right_indent = Inches(0.05)
            fmt.line_spacing = 1.1
            fmt.keep_together = True
            ppr = paragraph._p.get_or_add_pPr()
            shade = OxmlElement("w:shd")
            shade.set(qn("w:val"), "clear")
            shade.set(qn("w:color"), "auto")
            shade.set(qn("w:fill"), CODE_BG)
            ppr.append(shade)
            border = OxmlElement("w:pBdr")
            left = OxmlElement("w:left")
            left.set(qn("w:val"), "single")
            left.set(qn("w:sz"), "12")
            left.set(qn("w:space"), "6")
            left.set(qn("w:color"), TEAL)
            border.append(left)
            ppr.append(border)
            for number, code_line in enumerate(block):
                run = paragraph.add_run(code_line)
                run.font.name = MONO_FONT
                run.font.size = Pt(8.2)
                run.font.color.rgb = rgb("24323A")
                rpr = run._r.get_or_add_rPr()
                fonts = OxmlElement("w:rFonts")
                for key, value in (("w:ascii", MONO_FONT), ("w:hAnsi", MONO_FONT),
                                   ("w:eastAsia", EA_FONT), ("w:cs", MONO_FONT)):
                    fonts.set(qn(key), value)
                rpr.insert(0, fonts)
                if number < len(block) - 1:
                    run.add_break()
            continue
        caption_match = re.fullmatch(r"Table (\d+)\. (.+)", line)
        if caption_match:
            number = int(caption_match.group(1))
            if number != expected_table:
                raise ValueError(f"unexpected table caption {number}, expected {expected_table}")
            pending_caption = f"Table {number}. {caption_match.group(2)}"
            i += 1
            continue
        if line.startswith("|"):
            matrix = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                values = [plain(x.strip()) for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", x) for x in values):
                    matrix.append(values)
                i += 1
            if not matrix:
                continue
            if pending_caption is None:
                raise ValueError("table without a numbered caption")
            add_table(matrix, pending_caption)
            pending_caption = None
            expected_table += 1
            continue
        if in_references:
            reference = re.fullmatch(r"(\d+)\. (.+)", line)
            if reference:
                paragraph = doc.add_paragraph()
                fmt = paragraph.paragraph_format
                fmt.left_indent = Inches(0.34)
                fmt.first_line_indent = Inches(-0.34)
                fmt.space_after = Pt(3)
                fmt.line_spacing = 1.08
                fmt.tab_stops.add_tab_stop(Inches(0.34))
                run = paragraph.add_run(reference.group(1) + ".")
                run.font.name, run.font.size, run.font.bold, run.font.color.rgb = HEAD_FONT, Pt(9), True, rgb(NAVY)
                paragraph.add_run("\t")
                add_runs(paragraph, reference.group(2), size=9)
                i += 1
                continue
        # ordinary paragraph: merge consecutive source lines
        parts = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "```", "![", "<!--")) \
                and not re.match(r"^Table \d+\. ", lines[i].strip()):
            parts.append(lines[i].strip())
            i += 1
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.keep_together = False
        add_runs(paragraph, " ".join(parts))

    if pending_caption is not None:
        raise ValueError("a table caption has no following table")
    if expected_table - 1 != 15:
        raise ValueError(f"expected 15 table captions, found {expected_table - 1}")
    if expected_figure - 1 != 5:
        raise ValueError(f"expected 5 figures, found {expected_figure - 1}")

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def merge(main_pdf, output):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(main_pdf), outline_item="Project report")
    writer.append(PdfReader(ROOT / "proposal/PharmaColdOps-Proposal-Group 41.pdf"),
                  outline_item="Appendix C Submitted proposal (full PDF)")
    writer.add_metadata({"/Title": "PharmaColdOps Project Report", "/Author": "Project Group 41"})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        writer.write(stream)
    print(f"PDF assembled: {len(writer.pages)} pages")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--merge-pdf", type=Path)
    contents = parser.add_mutually_exclusive_group()
    contents.add_argument("--toc", type=Path, help="JSON list of {level, text, page}")
    contents.add_argument("--toc-from-pdf", type=Path, help="Resolve headings from a freshly rendered first-pass body PDF")
    parser.add_argument("--report-date", default="23 October 2026", help="Cover date; fixed for reproducible report builds")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("fresh output required; preserve previous report versions")
    if args.merge_pdf:
        if args.output.suffix.lower() != ".pdf":
            parser.error("PDF output required for assembly")
        merge(args.merge_pdf, args.output)
    else:
        if args.output.suffix.lower() != ".docx":
            parser.error("DOCX output required")
        toc = None
        if args.toc:
            import json
            toc = json.loads(args.toc.read_text(encoding="utf-8"))
        elif args.toc_from_pdf:
            toc = contents_from_pdf(args.toc_from_pdf)
        build(args.output, toc, report_date=args.report_date)


if __name__ == "__main__":
    main()
