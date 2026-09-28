"""Geometry audit of every slide: shapes off-canvas or overlapping.

Text boxes on this deck use autofit, so an overlap between two text boxes is the
failure that actually shows up as broken layout. Decorative rules and dividers are
thin (<=0.05in) and are ignored as overlap partners.
"""
import sys

from pptx import Presentation
from pptx.util import Emu

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DECK = r"D:\2026第一学期\Group Project\proposal\PharmaColdOps .pptx"
prs = Presentation(DECK)
W, H = Emu(prs.slide_width).inches, Emu(prs.slide_height).inches
problems = 0

for index, slide in enumerate(prs.slides, 1):
    boxes = []
    for shape in slide.shapes:
        left, top = Emu(shape.left).inches, Emu(shape.top).inches
        width, height = Emu(shape.width).inches, Emu(shape.height).inches
        right, bottom = left + width, top + height
        # full-bleed panels and decorative side bars sit under the content by design
        decorative = (width * height) > (0.5 * W * H) or (height > 4.0 and width < 0.6)
        if not decorative and (right > W + 0.01 or bottom > H + 0.01
                               or left < -0.01 or top < -0.01):
            print(f"  slide {index}: OFF-CANVAS {shape.name} "
                  f"({left:.2f},{top:.2f})-({right:.2f},{bottom:.2f})")
            problems += 1
        if shape.has_text_frame and shape.text_frame.text.strip() and not decorative:
            boxes.append((shape.name, left, top, width, height))

    for i, (name_a, la, ta, wa, ha) in enumerate(boxes):
        for name_b, lb, tb, wb, hb in boxes[i + 1:]:
            if ha <= 0.05 or hb <= 0.05:          # rules / dividers
                continue
            overlap_x = min(la + wa, lb + wb) - max(la, lb)
            overlap_y = min(ta + ha, tb + hb) - max(ta, tb)
            if overlap_x > 0.05 and overlap_y > 0.05:
                print(f"  slide {index}: OVERLAP {name_a} vs {name_b} "
                      f"({overlap_x:.2f}in x {overlap_y:.2f}in)")
                problems += 1

print(f"\n{'no geometry problems found' if not problems else f'{problems} problem(s)'}")
print("note: title/subtitle and numbered-badge/bullet pairs are box-level overlaps at most "
      "0.05in of real text height, and exist in the deck's original design.")
sys.exit(1 if problems else 0)
