#!/usr/bin/env python3
"""Sentence/cell-level containment diff: submitted Word (docx) vs markdown source.

Normalises away the differences the docx builder introduces by construction
(link text gains " (url)", table cells become their own paragraphs, headings
become plain paragraphs), then reports only units that exist on exactly one
side. Those are the substantive differences.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ROOT = Path(__file__).resolve().parents[1]


def docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    out = []
    for p in root.iter(W + "p"):
        s = "".join(t.text or "" for t in p.iter(W + "t")).strip()
        if s:
            out.append(s)
    return out


def strip_urls(text: str) -> str:
    text = re.sub(r"\s*\((?:https?://|\.\./|IRS%20)[^)]*\)", "", text)
    text = re.sub(r"\s*\(#[^)]*\)", "", text)
    return text


def normalise(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = strip_urls(text)
    text = text.replace("**", " ").replace("`", " ")
    text = re.sub(r"^[-\u2022*]\s*", "", text.strip())
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;:")


def sentences(block: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？；;])\s+", block)
    return [p.strip() for p in parts if len(p.strip()) >= 30]


def md_units(path: Path) -> tuple[set[str], list[tuple[str, str]], set[str]]:
    """Return (all md unit set, ordered (section, unit) list, heading set)."""
    headings: set[str] = set()
    ordered: list[tuple[str, str]] = []
    section = "(no heading)"
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            section = normalise(s.lstrip("# "))
            headings.add(section)
            continue
        if s.startswith("```") or s.startswith("---") or s.startswith("!["):
            continue
        if s.startswith("|"):
            cells = [normalise(c) for c in s.strip("|").split("|")]
            for cell in cells:
                if len(cell) >= 30:
                    ordered.append((section, cell))
            continue
        for unit in sentences(normalise(s)):
            ordered.append((section, unit))
    return {u for _s, u in ordered}, ordered, headings


def main() -> int:
    src_md = ROOT / "proposal" / sys.argv[1]
    docx = ROOT / "proposal" / sys.argv[2]
    out_name = sys.argv[3]
    report = ROOT / "scripts" / out_name

    md_set, md_ordered, headings = md_units(src_md)

    docx_units: list[str] = []
    for para in docx_paragraphs(docx):
        for unit in sentences(normalise(para)):
            docx_units.append(unit)
    docx_set = set(docx_units)

    only_md = [(s, u) for s, u in md_ordered if u not in docx_set]
    only_docx = [u for u in docx_units if u not in md_set and u not in headings]

    lines = [f"# {src_md.name}  vs  {docx.name}",
             f"docx 单元: {len(docx_units)}   md 单元: {len(md_ordered)}",
             f"仅存在于 md（源稿已改/新增）: {len(only_md)}",
             f"仅存在于 docx（提交件有、源稿已删/改）: {len(only_docx)}", ""]
    lines.append("## A. 仅存在于源稿 md")
    cur = None
    for section, unit in only_md:
        if section != cur:
            lines.append("")
            lines.append(f"### {section}")
            cur = section
        lines.append(f"- {unit}")
    lines.append("")
    lines.append("## B. 仅存在于提交件 docx")
    for unit in only_docx:
        lines.append(f"- {unit}")

    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"{src_md.name}: md-only={len(only_md)}  docx-only={len(only_docx)} -> {out_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
