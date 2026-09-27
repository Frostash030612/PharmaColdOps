"""Estimate the page layout of the generated speech DOCX without opening Word.

Walks word/document.xml, splits at explicit page breaks, and estimates each
page's height from paragraph line counts, indents and spacings. It is an
estimate (no font metrics), but it catches the failure that matters here: a
speaker's part spilling onto an extra page, or a page overflowing its margins.
"""
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "proposal" / "演讲稿-4人版.docx"

# A4 with 2 cm margins: text area 17.4 cm wide, ~25.6 cm tall.
PAGE_H_TWIPS = 16838 - 1134 - 1134      # 14570 twips of text height
TEXT_W_TWIPS = 11906 - 1134 - 1134      # 9638 twips of text width
TWIPS_PER_CM = 567.0

doc = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
body = doc.find(f"{W}body")


def para_lines(p, size_pt: float) -> int:
    """Rough line count: characters / chars-per-line, plus spacing in lines."""
    text = "".join(t.text or "" for t in p.iter(f"{W}t"))
    ppr = p.find(f"{W}pPr")
    left = 0
    if ppr is not None:
        ind = ppr.find(f"{W}ind")
        if ind is not None:
            left = int(ind.get(f"{W}left") or 0)
    width_twips = max(TEXT_W_TWIPS - left, 2000)
    # Average glyph advance ≈ 0.5 em for Latin, 1.0 for CJK.
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    latin = len(text) - cjk
    chars_per_line = width_twips / (size_pt * 20 * 0.5) / max(1.0, (latin + 2 * cjk) / max(latin + cjk, 1))
    return max(1, int((latin + 2 * cjk) / max(chars_per_line, 4)) + 1), size_pt


def para_height_twips(p) -> float:
    text = "".join(t.text or "" for t in p.iter(f"{W}t"))
    size_pt = 21 / 2.0
    for sz in p.iter(f"{W}sz"):
        size_pt = int(sz.get(f"{W}val")) / 2.0
        break
    ppr = p.find(f"{W}pPr")
    spacing = ppr.find(f"{W}spacing") if ppr is not None else None
    before = int(spacing.get(f"{W}before") or 0) if spacing is not None else 0
    after = int(spacing.get(f"{W}after") or 0) if spacing is not None else 0
    line = int(spacing.get(f"{W}line") or 276) if spacing is not None else 276

    if re.search(f"{W}br", ET.tostring(p, encoding="unicode")):
        return float("inf")                       # page break marker
    lines, _ = para_lines(p, size_pt)
    # line="276" with lineRule=auto means 1.15× the single line height.
    single = size_pt * 20 * 1.2
    return before + after + lines * single * (line / 240.0)


def has_page_break(p) -> bool:
    """The generator emits a page break as an empty paragraph holding <w:br
    w:type="page"/>, so this has to look inside the paragraph, not at body tops."""
    for br in p.iter(f"{W}br"):
        if br.get(f"{W}type") == "page":
            return True
    return False


pages: list[list] = [[]]
for node in body:
    if node.tag == f"{W}p":
        if has_page_break(node):
            pages.append([])
            continue
        text = "".join(t.text or "" for t in node.iter(f"{W}t")).strip()
        pages[-1].append((para_height_twips(node), text))
    elif node.tag == f"{W}tbl":
        rows = len(node.findall(f"{W}tr"))
        pages[-1].append((rows * 260.0, f"[table: {rows} rows]"))

print(f"explicit page breaks: {sum(1 for p in body if p.tag == f'{W}p' and has_page_break(p))}")
print(f"estimated pages: {len(pages)}")
for index, page in enumerate(pages, 1):
    total = sum(h for h, _ in page)
    used_pct = total / PAGE_H_TWIPS * 100
    first = next((t for _, t in page if t), "")
    last = next((t for _, t in reversed(page) if t), "")
    flag = "  <-- 超出一页" if used_pct > 100 else ""
    print(f"\n  第 {index} 页: 约 {used_pct:5.1f}% 版心高{flag}")
    print(f"    起: {first[:64]}")
    print(f"    止: {last[:64]}")
print(f"\n(版心 {TEXT_W_TWIPS}×{PAGE_H_TWIPS} twips ≈ "
      f"{TEXT_W_TWIPS/TWIPS_PER_CM:.1f}×{PAGE_H_TWIPS/TWIPS_PER_CM:.1f} cm)")
