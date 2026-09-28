"""Put the uncropped front-end screenshot back into the teammate's deck.

The revised deck shows the screenshot at 7.78 x 7.50 in (1.04:1) while the real
capture is 2498x1829 (1.37:1), so roughly the right quarter — the excursion rail
and the QA panel — had been cut away to fit that frame.

Fixing it without distorting the picture means letting the height follow the
source aspect ratio (7.78 in wide -> 5.70 in tall) and centring it in the left
column; the right-hand text column stays exactly where the teammate put it.

The picture is addressed by slide number and shape name, never by "the biggest
picture": on slide 1 that heuristic selects the full-bleed background.

    python scripts/restore_screenshot.py [deck.pptx] [source.png] [slide] [shape]
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

ROOT = Path(__file__).resolve().parents[1]
DECK = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "proposal" / "PharmaColdOps .pptx"
SOURCE = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "proposal" / "figures" / "frontend_demo.png"
SLIDE_NO = int(sys.argv[3]) if len(sys.argv) > 3 else 7
SHAPE_NAME = sys.argv[4] if len(sys.argv) > 4 else "Image 0"
EMU_IN = 914400
FRAME = RGBColor.from_string("DDD3BA")     # the deck's sand tone


def main() -> None:
    for path, what in ((DECK, "deck"), (SOURCE, "source image")):
        if not path.exists():
            raise SystemExit(f"{what} not found: {path}")

    backup = DECK.with_name(DECK.stem + ".before-screenshot-fix" + DECK.suffix)
    if not backup.exists():
        shutil.copy2(DECK, backup)
        print(f"备份原文件: {backup.name}")

    src_w, src_h = Image.open(SOURCE).size
    aspect = src_w / src_h

    prs = Presentation(str(DECK))
    slide = prs.slides[SLIDE_NO - 1]
    picture = next((sh for sh in slide.shapes if sh.name == SHAPE_NAME), None)
    if picture is None or picture.shape_type != 13:
        names = [sh.name for sh in slide.shapes if sh.shape_type == 13]
        raise SystemExit(f"第 {SLIDE_NO} 页没有名为 {SHAPE_NAME!r} 的图片；该页图片: {names}")

    before = (picture.width / EMU_IN, picture.height / EMU_IN)
    print(f"目标: 第 {SLIDE_NO} 页 / {picture.name}")
    print(f"  改前: {before[0]:.2f} x {before[1]:.2f} in ({picture.width / picture.height:.2f}:1)"
          f"  —— 源图 {src_w}x{src_h} ({aspect:.2f}:1)")

    left, top = picture.left, picture.top
    width = picture.width
    height = Emu(int(width / aspect))
    new_top = Emu(int(top + (picture.height - height) / 2))

    frame = picture.line
    frame.color.rgb = FRAME
    frame.width = Pt(1)

    picture.left = left
    picture.width = width
    picture.height = height
    picture.top = new_top
    # Register the untouched capture as an image part of this slide and point the
    # picture's blip at it (get_or_add_image_part returns (part, rId)).
    _, r_id = picture.part.get_or_add_image_part(str(SOURCE))
    picture._element.blipFill.blip.rEmbed = r_id

    print(f"  改后: {picture.width / EMU_IN:.2f} x {picture.height / EMU_IN:.2f} in "
          f"(比例 {aspect:.2f}:1，与源图一致，未裁剪未拉伸)")
    print(f"  位置: L{picture.left / EMU_IN:.2f} T{picture.top / EMU_IN:.2f} "
          f"R{(picture.left + picture.width) / EMU_IN:.2f} B{(picture.top + picture.height) / EMU_IN:.2f} in")

    prs.save(str(DECK))
    print(f"\n已写回: {DECK.name}  ({DECK.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
