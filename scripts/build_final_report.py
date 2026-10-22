"""Build the final report DOCX; optionally append the submitted proposal to a rendered PDF.

Documentation-only extras: python-docx and pypdf. Runtime dependencies are unchanged.
Render and visually review the DOCX with the documented document renderer before PDF assembly.
"""
import argparse
from pathlib import Path
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/FINAL_REPORT_EN.md"


def plain(text):
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    return text.replace("**", "").replace("`", "")


def contents_entries():
    return [{"text": plain(line.lstrip("# ")), "level": 1 if line.startswith("## ") else 2, "page": ""}
            for line in SOURCE.read_text(encoding="utf-8").splitlines()
            if line.startswith("## ") or re.match(r"^### (2\.[123]|4\.4|6\.[1-5]|8\.[89]) ", line)]


def contents_from_pdf(path):
    """Resolve the contents against a freshly rendered body, never stale guesses."""
    from pypdf import PdfReader

    norm = lambda value: re.sub(r"\s+", " ", value).strip()
    pages = [norm(page.extract_text()) for page in PdfReader(path).pages]
    entries = contents_entries()
    for entry in entries:
        # Cover and contents are the first two pages in this report template.
        matches = [i + 1 for i, text in enumerate(pages) if i >= 2 and norm(entry["text"]) in text]
        if len(matches) != 1:
            raise ValueError(f"Cannot resolve unique heading {entry['text']!r}: {matches}")
        entry["page"] = matches[0]
    return entries


def build(output, toc=None, report_date="23 October 2026"):
    from docx import Document
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    doc.core_properties.title = "PharmaColdOps Project Report"
    doc.core_properties.author = "Project Group 41"
    doc.core_properties.subject = "IRS system implementation and evaluation"
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.7)
    section.left_margin = section.right_margin = Inches(0.75)
    for name in ["Normal", "Title", "Heading 1", "Heading 2", "Heading 3"]:
        style = doc.styles[name]
        style.font.name = "Arial"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Arial Unicode MS")
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.size = Pt({"Title": 23, "Heading 1": 15, "Heading 2": 12, "Heading 3": 11}.get(name, 11))
        style.paragraph_format.space_after = Pt(7)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.08
    for name in ["Heading 1", "Heading 2", "Heading 3"]:
        doc.styles[name].paragraph_format.space_before = Pt(12)
        doc.styles[name].paragraph_format.keep_with_next = True
    footer = section.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run("Group 41  |  ").font.size = Pt(9)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)

    def add_text(paragraph, text, size=11):
        position = 0
        for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
            paragraph.add_run(plain(text[position:match.start()])).font.size = Pt(size)
            target = match[2]
            if not re.match(r"[a-z]+://", target):
                relative = (SOURCE.parent / target).resolve().relative_to(ROOT).as_posix()
                target = "https://github.com/Frostash030612/PharmaColdOps/blob/main/" + quote(relative, safe="/")
            relationship = paragraph.part.relate_to(target, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
            link = OxmlElement("w:hyperlink")
            link.set(qn("r:id"), relationship)
            run = OxmlElement("w:r")
            properties = OxmlElement("w:rPr")
            color = OxmlElement("w:color")
            color.set(qn("w:val"), "000000")
            properties.append(color)
            font_size = OxmlElement("w:sz")
            font_size.set(qn("w:val"), str(int(size * 2)))
            properties.append(font_size)
            run.append(properties)
            value = OxmlElement("w:t")
            value.text = match[1]
            run.append(value)
            link.append(run)
            paragraph._p.append(link)
            position = match.end()
        paragraph.add_run(plain(text[position:])).font.size = Pt(size)

    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    if toc is None:
        # First-pass page placeholders are resolved against the rendered PDF.
        toc = contents_entries()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line == "<!-- PAGEBREAK -->":
            doc.add_page_break()
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
            caption = match[1]
            width = None
            if "|" in caption:
                caption, _, spec = caption.rpartition("|")
                if re.fullmatch(r"\d+(?:\.\d+)?(?:in)?", spec.strip()):
                    width = float(spec.strip().rstrip("in"))
            paragraph = doc.add_paragraph()
            paragraph.alignment = 1
            run = paragraph.add_run()
            # Supplying only width makes python-docx preserve the aspect ratio.
            # Mutating picture.width afterwards left height unchanged and stretched
            # the architecture figure in the previous report.
            picture = run.add_picture(str(SOURCE.parent / match[2]), width=Inches(min(width or 6.7, 6.8)))
            caption_paragraph = doc.add_paragraph(caption)
            caption_paragraph.alignment = 1
            caption_paragraph.runs[0].font.size = Pt(9)
            paragraph.paragraph_format.keep_with_next = True
            i += 1
            continue
        if line.startswith("# "):
            doc.add_paragraph(plain(line[2:]), "Title")
            doc.add_paragraph(f"IRS Practice Module  |  Project Group 41  |  {report_date}")
            doc.add_paragraph("Xu Wenzhe, Zhu Jianyu, Wang Lepeng and Shen Ziyi")
            doc.add_paragraph("Implementation, evaluation and findings")
            if toc:
                doc.add_page_break()
                contents = doc.add_paragraph()
                contents.add_run("Contents").font.size = Pt(15)
                contents.runs[0].font.bold = True
                for entry in toc:
                    item = doc.add_paragraph()
                    item.paragraph_format.tab_stops.add_tab_stop(
                        Inches(7.0), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
                    if entry.get("level", 1) >= 2:
                        item.paragraph_format.left_indent = Inches(0.25)
                        item.paragraph_format.space_after = Pt(2)
                    item.add_run(entry["text"]).font.size = Pt(10.5)
                    item.add_run("\t")
                    item.add_run(str(entry["page"])).font.size = Pt(10.5)
                doc.add_page_break()
            i += 1
            continue
        if line.startswith("##"):
            level = len(line.split(" ", 1)[0]) - 1
            doc.add_heading(plain(line.split(" ", 1)[1]), level=min(level, 3))
            i += 1
            continue
        if line.startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                paragraph = doc.add_paragraph()
                run = paragraph.add_run(lines[i])
                run.font.name, run.font.size = "Courier New", Pt(9)
                paragraph.paragraph_format.space_after = Pt(3)
                i += 1
            i += 1
            continue
        if line.startswith("|"):
            matrix = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                values = [plain(x.strip()) for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", x) for x in values):
                    matrix.append(values)
                i += 1
            table = doc.add_table(rows=0, cols=len(matrix[0]))
            table.autofit = False
            count = len(matrix[0])
            first = matrix[0][0]
            if first == "Module":
                widths = [0.65, 3.8, 2.55]
            elif first == "Priority":
                widths = [0.65, 5.1, 1.25]
            elif first == "Method":
                widths = [1.1, 3.65, 2.25]
            elif first == "Frozen example":
                widths = [1.5, 2.6, 2.9]
            elif first in {"Area", "Course area"}:
                widths = [1.55, 2.6, 2.85]
            elif count == 5:
                widths = [2.2, 1.2, 1.2, 1.2, 1.2]
            elif count == 4:
                widths = [2.2, 1.6, 1.6, 1.6]
            elif count == 3:
                widths = [2.1, 2.45, 2.45]
            else:
                widths = [7 / count] * count
            for col, width in zip(table.columns, widths):
                col.width = Inches(width)
            for ri, values in enumerate(matrix):
                cells = table.add_row().cells
                no_split = OxmlElement("w:cantSplit")
                table.rows[ri]._tr.get_or_add_trPr().append(no_split)
                if len(values) != len(cells):
                    raise ValueError("inconsistent report table")
                for ci, (cell, value) in enumerate(zip(cells, values)):
                    cell.width = Inches(widths[ci])
                    cell.text = value
                    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    tc_pr = cell._tc.get_or_add_tcPr()
                    borders = OxmlElement("w:tcBorders")
                    for edge in ["top", "left", "bottom", "right"]:
                        e = OxmlElement("w:" + edge)
                        for k, v in {"val": "single", "sz": "4", "color": "D9D9D9"}.items():
                            e.set(qn("w:" + k), v)
                        borders.append(e)
                    tc_pr.append(borders)
                    shade = OxmlElement("w:shd")
                    shade.set(qn("w:fill"), "24445C" if ri == 0 else ("F3F6F8" if ri % 2 else "FFFFFF"))
                    tc_pr.append(shade)
                    margins = OxmlElement("w:tcMar")
                    for edge in ["top", "left", "bottom", "right"]:
                        e = OxmlElement("w:" + edge)
                        e.set(qn("w:w"), "90")
                        e.set(qn("w:type"), "dxa")
                        margins.append(e)
                    tc_pr.append(margins)
                    for p in cell.paragraphs:
                        p.paragraph_format.space_after = Pt(3)
                        # All report tables are compact enough to keep together.
                        # The final row breaks the chain so the next paragraph can flow.
                        p.paragraph_format.keep_with_next = ri < len(matrix) - 1
                        if ri > 0 and re.fullmatch(r"[0-9 .%/+−±()-]+", value):
                            p.alignment = 1
                        for run in p.runs:
                            run.font.size = Pt(10)
                            run.font.bold = ri == 0
                            run.font.color.rgb = RGBColor(255, 255, 255) if ri == 0 else RGBColor(0, 0, 0)
                if ri == 0:
                    repeat = OxmlElement("w:tblHeader")
                    table.rows[ri]._tr.get_or_add_trPr().append(repeat)
            doc.add_paragraph().paragraph_format.space_after = Pt(0)
            continue
        if re.match(r"^\d+\. ", line):
            paragraph = doc.add_paragraph()
            add_text(paragraph, line, size=10)
            i += 1
            continue
        parts = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "```", "![", "<!--")) and not re.match(r"^\d+\. ", lines[i]):
            parts.append(lines[i].strip())
            i += 1
        add_text(doc.add_paragraph(), " ".join(parts))
    # Remove inherited template borders as well as direct paragraph rules.
    for node in doc.styles.element.xpath(".//w:pBdr") + doc.element.xpath(".//w:pBdr"):
        node.getparent().remove(node)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def merge(main_pdf, output):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(main_pdf), outline_item="Project report")
    writer.append(PdfReader(ROOT / "proposal/PharmaColdOps-Proposal-Group 41.pdf"), outline_item="Appendix C Submitted proposal")
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
