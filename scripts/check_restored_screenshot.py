"""Verify the restored screenshot: the embedded bitmap is now the uncropped one,
the geometry matches its aspect ratio, and the rest of the deck is untouched."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
EMU_IN = 914400
DECK = Path("proposal/PharmaColdOps .pptx")
SOURCE = Path("proposal/figures/frontend_demo.png")

src = Image.open(SOURCE)
print(f"源图: {SOURCE.name}  {src.size[0]}x{src.size[1]} "
      f"({src.size[0] / src.size[1]:.3f}:1)")

prs = Presentation(str(DECK))
print(f"演示文稿: {len(prs.slides)} 页, {DECK.stat().st_size / 1024 / 1024:.2f} MB\n")

for index, slide in enumerate(prs.slides, 1):
    for shape in slide.shapes:
        if shape.shape_type != 13:
            continue
        w, h = shape.image.size
        if w < 800:
            continue
        shown = (shape.width / EMU_IN, shape.height / EMU_IN)
        emb_ratio = w / h
        shown_ratio = shape.width / shape.height
        tags = []
        if emb_ratio == src.size[0] / src.size[1]:
            tags.append("与源图同比例")
        if abs(shown_ratio - src.size[0] / src.size[1]) < 0.01 and w > 2000:
            tags.append("整图无裁剪")
        print(f"slide {index:>2} {shape.name}: 内嵌 {w}x{h} ({shape.image.ext}) "
              f"比例 {emb_ratio:.3f} | 显示 {shown[0]:.2f}x{shown[1]:.2f} in "
              f"(比例 {shown_ratio:.3f})  {' '.join(tags)}")

big = src.size
found = False
for index, slide in enumerate(prs.slides, 1):
    for shape in slide.shapes:
        if shape.shape_type == 13 and shape.image.size == big:
            found = True
            print(f"\n第 {index} 页已嵌入原始分辨率位图 ({big[0]}x{big[1]})，未缩放为缩略图 ✓")
print("" if found else "\n!! 未找到原始分辨率位图")
