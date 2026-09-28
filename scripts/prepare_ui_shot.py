"""Prepare a fresh UI screenshot for the deck.

Checks the capture, trims a uniform border (browser chrome / desktop), and saves
it as proposal/figures/demo-ui.png, which build_presentation_final.py picks up
automatically (it prefers demo-ui.png over the stale 2026-09-12 figure).

Usage:
  python prepare_ui_shot.py <source.png> [--keep]      # --keep = do not trim
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "proposal" / "figures" / "demo-ui.png"


def trim_uniform_border(im: Image.Image, tol: int = 6) -> Image.Image:
    """Crop away rows/columns that are a single near-uniform colour."""
    px = im.convert("RGB")
    w, h = px.size
    corners = [px.getpixel((0, 0)), px.getpixel((w - 1, 0)),
               px.getpixel((0, h - 1)), px.getpixel((w - 1, h - 1))]
    bg = max(set(corners), key=corners.count)

    def row_uniform(y: int) -> bool:
        return all(
            abs(px.getpixel((x, y))[i] - bg[i]) <= tol
            for x in range(0, w, max(1, w // 120))
            for i in range(3)
        )

    def col_uniform(x: int) -> bool:
        return all(
            abs(px.getpixel((x, y))[i] - bg[i]) <= tol
            for y in range(0, h, max(1, h // 120))
            for i in range(3)
        )

    top = 0
    while top < h - 1 and row_uniform(top):
        top += 1
    bottom = h - 1
    while bottom > top and row_uniform(bottom):
        bottom -= 1
    left = 0
    while left < w - 1 and col_uniform(left):
        left += 1
    right = w - 1
    while right > left and col_uniform(right):
        right -= 1
    if (top, left, bottom, right) == (0, 0, h - 1, w - 1):
        return im
    return im.crop((left, top, right + 1, bottom + 1))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        print(f"missing source: {src}")
        return 2

    im = Image.open(src)
    orig = im.size
    if "--keep" not in sys.argv:
        im = trim_uniform_border(im)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT)
    print(f"{src.name}: {orig[0]}x{orig[1]} -> {im.size[0]}x{im.size[1]}  => {OUT.relative_to(ROOT)}")
    if im.size[0] < 1400:
        print("WARNING: output narrower than 1400 px; on a 13.3in slide it may look soft at full width.")
    if im.size[1] / im.size[0] > 0.95:
        print("NOTE: the shot is much taller than wide; the slide reserves 7.4in x ~5.1in, "
              "so it will be scaled down. Consider cropping to the map + dispatch panel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
