"""Render the keynote-style PharmaColdOps promotion segments (no speech).

Two motion-graphics segments wrap the team's own live demo recording:

    part A (opening, 80 s)  ->  [live demo, 2-3 min]  ->  part B (closing, 70 s)

Everything is drawn frame by frame with Pillow and piped to FFmpeg. The only
pixels not drawn here are real UI screenshots already committed under
proposal/figures/. The soundtrack is a procedurally synthesised music bed; no
voice is generated (briefing p13 forbids AI-generated presentation speech).

    python scripts/build_keynote_promo.py --out data/processed/keynote-promo
    python scripts/build_keynote_promo.py --out ... --demo path/to/demo.mp4
    python scripts/build_keynote_promo.py --out ... --stills 3,9,20   # PNG checks
"""
import argparse
import math
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "proposal/figures"
W, H, FPS, SR = 1920, 1080, 30, 48000
FONTS = Path("C:/Windows/Fonts")
FACE = {"light": "segoeuil.ttf", "semilight": "segoeuisl.ttf", "semibold": "seguisb.ttf",
        "bold": "segoeuib.ttf", "black": "seguibl.ttf", "symbol": "seguisym.ttf"}

WHITE, GREY, DIM = (245, 245, 247), (134, 134, 139), (110, 110, 115)
ICE = ((155, 231, 255), (58, 123, 255))
HEAT = ((255, 179, 71), (255, 59, 48))
MINT = ((94, 234, 212), (14, 165, 233))
OUTCOME = {"Release": (48, 209, 88), "Retest": (255, 214, 10),
           "Quarantine": (255, 159, 10), "Scrap": (255, 69, 58)}


# ---------------------------------------------------------------- primitives
def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def ease_out(x):
    return 1 - (1 - clamp(x)) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def envelope(t, t_in, t_out, d_in=0.9, d_out=0.6):
    """Opacity and remaining rise (0..1) for an element shown in [t_in, t_out]."""
    grow = ease_out((t - t_in) / d_in)
    return grow * (1 - ease_in_out((t - t_out) / d_out)), 1 - grow


@lru_cache(maxsize=None)
def font(face, size):
    return ImageFont.truetype(str(FONTS / FACE[face]), size)


def gradient(size, colours, vertical=False):
    w, h = size
    ramp = np.linspace(0, 1, h if vertical else w)[:, None] if vertical else np.linspace(0, 1, w)[None, :]
    a, b = (np.array(c, float) for c in colours)
    rgb = a + (b - a) * ramp[..., None]
    return Image.fromarray(np.broadcast_to(rgb, (h, w, 3)).astype(np.uint8), "RGB")


@lru_cache(maxsize=None)
def text(s, face, size, fill=WHITE, grad=None, glow=0):
    f = font(face, size)
    left, top, right, bottom = f.getbbox(s)
    pad = 4 + glow * 3
    w, h = right - left + 2 * pad, bottom - top + 2 * pad
    if w > W - 60:
        raise ValueError(f"text too wide for frame ({w}px): {s!r}")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((pad - left, pad - top), s, font=f, fill=255)
    base = gradient((w, h), grad) if grad else Image.new("RGB", (w, h), fill)
    sprite = base.convert("RGBA")
    sprite.putalpha(mask)
    if glow:
        halo = sprite.copy()
        halo.putalpha(mask.filter(ImageFilter.GaussianBlur(glow)).point(lambda v: int(v * 0.55)))
        sprite = Image.alpha_composite(halo, sprite)
    return sprite


def faded(sprite, alpha):
    if alpha >= 0.999:
        return sprite
    out = sprite.copy()
    out.putalpha(sprite.getchannel("A").point(lambda v: int(v * alpha)))
    return out


def put(canvas, sprite, cx, cy, alpha=1.0, scale=1.0, anchor="c"):
    if alpha <= 0.004:
        return
    if abs(scale - 1) > 1e-3:
        sprite = sprite.resize((max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))),
                               Image.BILINEAR)
    sprite = faded(sprite, alpha)
    x = round(cx - sprite.width / 2) if anchor == "c" else round(cx)
    y = round(cy - sprite.height / 2)
    box = (max(0, -x), max(0, -y), min(sprite.width, W - x), min(sprite.height, H - y))
    if box[2] > box[0] and box[3] > box[1]:
        canvas.alpha_composite(sprite.crop(box), dest=(x + box[0], y + box[1]))


def show(canvas, t, sprite, cx, cy, t_in, t_out, rise=40, d_in=0.9, d_out=0.6, scale=1.0):
    alpha, left = envelope(t, t_in, t_out, d_in, d_out)
    put(canvas, sprite, cx, cy + rise * left, alpha, scale)


def rounded(size, radius, fill):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=fill)
    return img


@lru_cache(maxsize=None)
def logo(size):
    pad = size // 3
    tile = gradient((size, size), MINT).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), size // 4.5, fill=255)
    tile.putalpha(mask)
    flake = text("\u2744", "symbol", int(size * 0.58))
    tile.alpha_composite(flake, ((size - flake.width) // 2, (size - flake.height) // 2))
    out = Image.new("RGBA", (size + 2 * pad, size + 2 * pad), (0, 0, 0, 0))
    halo = Image.new("RGBA", out.size, (45, 212, 191, 0))
    halo.putalpha(Image.new("L", out.size, 0))
    ImageDraw.Draw(halo).rounded_rectangle((pad, pad, pad + size, pad + size), size // 4.5,
                                           fill=(45, 212, 191, 120))
    out = Image.alpha_composite(out, halo.filter(ImageFilter.GaussianBlur(pad / 2.5)))
    out.alpha_composite(tile, (pad, pad))
    return out


@lru_cache(maxsize=None)
def screenshot(name, crop, height):
    src = Image.open(FIG / name).convert("RGB").crop(crop)
    width = round(height * src.width / src.height)
    shot = src.resize((width, height), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), 22, fill=255)
    shot.putalpha(mask)
    ImageDraw.Draw(shot).rounded_rectangle((0, 0, width - 1, height - 1), 22,
                                           outline=(255, 255, 255, 60), width=2)
    pad = 90
    out = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    glow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((pad, pad + 20, pad + width, pad + height), 30,
                                           fill=(56, 189, 248, 70))
    out = Image.alpha_composite(out, glow.filter(ImageFilter.GaussianBlur(45)))
    out.alpha_composite(shot, (pad, pad))
    return out


@lru_cache(maxsize=None)
def backdrop_map():
    src = Image.open(FIG / "promo/main-page.png").convert("RGB").crop((450, 359, 1651, 981))
    img = src.resize((W, round(W * src.height / src.width)), Image.LANCZOS).convert("L")
    img = Image.merge("RGB", (img.point(lambda v: v // 3), img.point(lambda v: v // 2), img.point(lambda v: v // 2)))
    out = img.filter(ImageFilter.GaussianBlur(3)).convert("RGBA")
    fall = np.linspace(1, 0, out.height) ** 0.8
    out.putalpha(Image.fromarray((np.outer(fall, np.ones(out.width)) * 255).astype(np.uint8), "L"))
    return out


@lru_cache(maxsize=None)
def scaled(name, width):
    src = Image.open(FIG / name).convert("RGB")
    return src.resize((width, round(src.height * width / src.width)), Image.LANCZOS)


@lru_cache(maxsize=None)
def panel_chrome(width, height):
    pad = 70
    back = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(back).rounded_rectangle((pad, pad + 16, pad + width, pad + height), 26, fill=(56, 189, 248, 65))
    back = back.filter(ImageFilter.GaussianBlur(36))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), 22, fill=255)
    edge = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle((0, 0, width - 1, height - 1), 22, outline=(255, 255, 255, 60), width=2)
    return back, mask, edge, pad


def scroll_panel(name, width, height, offset):
    """A tall screenshot shown through a rounded window, scrolled down by `offset` pixels."""
    page = scaled(name, width)
    offset = round(clamp(offset, 0, page.height - height))
    back, mask, edge, pad = panel_chrome(width, height)
    view = page.crop((0, offset, width, offset + height)).convert("RGBA")
    view.putalpha(mask)
    view.alpha_composite(edge)
    out = back.copy()
    out.alpha_composite(view, (pad, pad))
    return out


# ------------------------------------------------------------------- part A
def a_open(c, t):
    show(c, t, text("Every day, across Singapore,", "semilight", 62, GREY), W / 2, 470, 0.6, 6.2)
    show(c, t, text("medicines travel cold.", "semibold", 104), W / 2, 575, 2.0, 6.2)


def a_window(c, t):
    alpha, left = envelope(t, 0.3, 7.2, 1.4, 0.8)
    put(c, text("2\u20138 \u00b0C", "black", 300, grad=ICE, glow=26), W / 2, 470 + 30 * left,
        alpha, 1.06 - 0.06 * ease_out(t / 8))
    show(c, t, text("The narrow window that keeps a vaccine a vaccine.", "semilight", 50, GREY),
         W / 2, 790, 2.2, 7.2)


def temperature(u):
    rise = ease_in_out((u - 0.30) / 0.10)
    fall = ease_in_out((u - 0.80) / 0.10)
    wobble = 0.25 * math.sin(u * 61) + 0.15 * math.sin(u * 23 + 1)
    return 5 + 8 * rise * (1 - fall) + wobble


def heat_colour(temp):
    k = clamp((temp - 8) / 4)
    return tuple(round(a + (b - a) * k) for a, b in zip((100, 210, 255), (255, 69, 58)))


def a_excursion(c, t):
    alpha = envelope(t, 0.2, 11.2, 0.8, 0.8)[0]
    x0, x1, y_top, y_bot = 230, 1690, 300, 860
    to_y = lambda temp: y_bot - (temp / 16) * (y_bot - y_top)
    s = 2
    layer = Image.new("RGBA", ((x1 - x0 + 120) * s, (y_bot - y_top + 120) * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ox, oy = x0 - 60, y_top - 60
    p = lambda x, y: ((x - ox) * s, (y - oy) * s)
    d.rectangle((*p(x0, to_y(8)), *p(x1, to_y(2))), fill=(45, 212, 191, 34))
    for edge in (2, 8):
        for xs in range(x0, x1, 28):
            d.line((*p(xs, to_y(edge)), *p(min(xs + 14, x1), to_y(edge))), fill=(45, 212, 191, 110), width=2 * s)
    head = clamp((t - 0.8) / 7.4)
    n = max(2, int(500 * head))
    pts = [(x0 + (x1 - x0) * i / 499, temperature(i / 499)) for i in range(n)]
    for (xa, ta), (xb, tb) in zip(pts, pts[1:]):
        d.line((*p(xa, to_y(ta)), *p(xb, to_y(tb))), fill=heat_colour(max(ta, tb)) + (255,), width=6 * s)
    layer = layer.resize((layer.width // s, layer.height // s), Image.LANCZOS)
    glow = layer.filter(ImageFilter.GaussianBlur(10))
    put(c, faded(Image.alpha_composite(glow, layer), alpha), ox, oy + layer.height / 2, anchor="l")
    for edge in (8, 2):
        put(c, text(f"{edge} \u00b0C", "semilight", 30, (94, 234, 212)), x0 - 70, to_y(edge), alpha)
    hx, ht = pts[-1]
    colour = heat_colour(ht)
    ring = (t * 1.2) % 1
    dot = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dot)
    r = 12 + 34 * ring
    dd.ellipse((60 - r, 60 - r, 60 + r, 60 + r), outline=colour + (int(200 * (1 - ring)),), width=3)
    dd.ellipse((48, 48, 72, 72), fill=colour + (255,))
    put(c, dot, hx, to_y(ht), alpha)
    if ht > 8.4:
        put(c, text(f"{round(ht)} \u00b0C", "bold", 54, colour), hx, to_y(ht) - 70, alpha)
    show(c, t, text("Then, something goes wrong.", "semibold", 76), W / 2, 170, 3.6, 11.2)
    show(c, t, text("Illustrative excursion: 13 \u00b0C for about five hours.", "semilight", 30, DIM),
         W / 2, 950, 6.0, 11.2)


def a_questions(c, t):
    lines = ["Is it still safe?", "Who signs off?", "Can we prove it to an auditor?"]
    for i, line in enumerate(lines):
        t_in = 0.5 + 1.6 * i
        alpha, left = envelope(t, t_in, 7.0, 0.8, 0.6)
        lit = 1 if i == len(lines) - 1 or t < t_in + 1.6 else 0.45
        put(c, text(line, "semibold", 88), W / 2, 380 + 150 * i + 30 * left, alpha * lit)
    show(c, t, text("Today, the answers live in", "semilight", 60, GREY), W / 2, 470, 7.8, 12.2)
    show(c, t, text("binders, spreadsheets and memory.", "semibold", 88), W / 2, 580, 8.4, 12.2)


def a_reveal(c, t):
    alpha, left = envelope(t, 0.2, 8.2, 1.6, 0.8)
    put(c, logo(200), W / 2, 330, alpha, 0.7 + 0.3 * ease_out((t - 0.2) / 1.8))
    show(c, t, text("PharmaColdOps", "semibold", 132, glow=0), W / 2, 590, 1.6, 8.2, d_in=1.2)
    show(c, t, text("Explainable decisions for the pharmaceutical cold chain.", "semilight", 46, GREY),
         W / 2, 720, 3.0, 8.2)


def a_outcomes(c, t):
    show(c, t, text("Four outcomes. One clear path.", "semibold", 80), W / 2, 250, 0.3, 11.2)
    words = [text(name, "black", 96, rgb, glow=18) for name, rgb in OUTCOME.items()]
    gap = 90
    x = W / 2 - (sum(w.width for w in words) - 2 * 4 * 18 * 3 + gap * 3) / 2
    for i, word in enumerate(words):
        inner = word.width - 2 * (4 + 18 * 3)
        show(c, t, word, x + inner / 2, 540, 1.3 + 0.35 * i, 11.2, rise=30)
        x += inner + gap
    show(c, t, text("Every recommendation shows its rule, its clause and its evidence.", "semilight", 44, GREY),
         W / 2, 800, 5.4, 11.2)


def a_product(c, t):
    wide = screenshot("promo/main-page.png", (0, 0, 2529, 1406), 860)
    swap = ease_in_out((t - 6.2) / 0.9)
    out = envelope(t, 0.2, 12.2, 1.2, 0.8)[0]
    put(c, wide, W / 2, 620, out * (1 - swap), 0.94 + 0.05 * ease_out(t / 6.5))
    if swap > 0:
        scroll = ease_in_out((t - 7.0) / 5.0)
        rise = 50 * (1 - ease_out((t - 6.2) / 1.2))
        put(c, scroll_panel("promo/accident-rules.png", 560, 800, 1000 * scroll), W / 2 - 330, 600 + rise, out * swap)
        put(c, scroll_panel("promo/accident-review.png", 560, 800, 330 * scroll), W / 2 + 330, 600 + rise,
            out * ease_in_out((t - 6.6) / 0.9))
    show(c, t, text("See every excursion in context.", "semibold", 72), W / 2, 105, 0.4, 6.0, d_out=0.5)
    show(c, t, text("The rule engine explains. A human decides.", "semibold", 66),
         W / 2, 105, 6.6, 12.2, rise=20)


def a_cue(c, t):
    show(c, t, text("Let\u2019s see it in action.", "semibold", 96), W / 2, H / 2, 0.5, 4.6, d_out=0.9)


# ------------------------------------------------------------------- part B
def count_line(c, t, big, small, cy, alpha, left):
    gap = 30
    width = big.width + small.width + gap - 2 * 8 - 2 * 4
    x = W / 2 - width / 2
    put(c, big, x + big.width / 2 - 8, cy + 40 * left, alpha)
    base = cy + big.height / 2 - 40
    put(c, small, x + big.width - 8 - 4 + gap + small.width / 2 - 4, base - small.height / 2 + 40 * left, alpha)


def b_agreement(c, t):
    alpha, left = envelope(t, 0.3, 9.2, 0.9, 0.8)
    n = round(54 * ease_out((t - 0.4) / 2.4))
    count_line(c, t, text(str(n), "black", 280, grad=ICE, glow=8), text("/ 57", "semibold", 140, GREY),
               430, alpha, left)
    show(c, t, text("historical scenarios where the rule engine", "semilight", 48, GREY), W / 2, 700, 1.8, 9.2)
    show(c, t, text("matched the human gold standard.", "semilight", 48, GREY), W / 2, 765, 1.8, 9.2)
    show(c, t, text("Synthetic scenarios. The three misses were all quarantine cases, and we report them.",
                    "semilight", 30, DIM), W / 2, 930, 4.2, 9.2)


def b_routes(c, t):
    alpha, left = envelope(t, 0.2, 9.2, 1.4, 0.8)
    put(c, backdrop_map(), W / 2, H - backdrop_map().height / 2 + 60, alpha * 0.55)
    value = 16.59 * ease_out((t - 0.4) / 2.4)
    show(c, t, text(f"{value:.1f}%", "black", 280, grad=MINT, glow=8), W / 2, 420, 0.3, 9.2)
    show(c, t, text("shorter delivery distance on our Singapore network,", "semilight", 48, GREY),
         W / 2, 690, 1.8, 9.2)
    show(c, t, text("compared with a greedy baseline.", "semilight", 48, GREY), W / 2, 755, 1.8, 9.2)
    show(c, t, text("OR-Tools 137.85 km vs greedy 165.26 km on one frozen static instance. "
                    "Not an operational savings claim.", "semilight", 30, DIM), W / 2, 930, 4.2, 9.2)


TILES = [("01", "Rule engine", ["Six priority rules, four outcomes,", "every step auditable."], (48, 209, 88)),
         ("02", "Machine learning", ["Risk and root-cause models", "trained on simulated events."], (255, 159, 10)),
         ("03", "Route optimisation", ["OR-Tools VRPTW re-plans", "replacement deliveries."], (56, 189, 248)),
         ("04", "Knowledge graph", ["Ask in plain English. Answers", "cite the case and the clause."], (191, 90, 242))]


@lru_cache(maxsize=None)
def tile(index):
    num, title, lines, accent = TILES[index]
    card = rounded((780, 290), 34, (28, 28, 30, 255))
    for sprite, x, y in [(text(num, "black", 56, accent), 42, 34), (text(title, "semibold", 52), 42, 104)]:
        card.alpha_composite(sprite, (x - 4, y - 4))
    for i, line in enumerate(lines):
        card.alpha_composite(text(line, "semilight", 32, (161, 161, 166)), (38, 182 + 44 * i))
    return card


def b_bento(c, t):
    show(c, t, text("Four techniques. One workflow.", "semibold", 76), W / 2, 160, 0.3, 13.2)
    for i in range(4):
        cx = W / 2 + (-410 if i % 2 == 0 else 410)
        cy = 455 + (i // 2) * 330
        show(c, t, tile(i), cx, cy, 1.0 + 0.45 * i, 13.2, rise=60, d_in=1.0)


def b_human(c, t):
    show(c, t, text("Nothing moves", "semibold", 96), W / 2, 180, 0.4, 7.2)
    show(c, t, text("until a human says yes.", "semibold", 96, grad=ICE), W / 2, 300, 1.2, 7.2)
    show(c, t, screenshot("promo/button-page.png", (0, 445, 1243, 1005), 470), W / 2, 680, 2.2, 7.2, rise=60)
    show(c, t, text("The system recommends. Reviewers decide. Every decision is logged.",
                    "semilight", 36, GREY), W / 2, 1000, 3.0, 7.2)


def b_one_more(c, t):
    show(c, t, text("One more thing.", "semibold", 76, GREY), W / 2, H / 2, 0.4, 2.8, d_in=1.0, d_out=0.7)
    show(c, t, text("It knows what it doesn\u2019t know.", "semibold", 104), W / 2, 480, 3.6, 9.2)
    show(c, t, text("When the evidence isn\u2019t there, PharmaColdOps says so.", "semilight", 48, GREY),
         W / 2, 640, 5.2, 9.2)


def b_belief(c, t):
    show(c, t, text("Cold-chain decisions shouldn\u2019t depend", "semibold", 84), W / 2, 470, 0.4, 7.2)
    show(c, t, text("on who happens to be on shift.", "semibold", 84, grad=ICE), W / 2, 590, 1.3, 7.2)


def b_end(c, t):
    alpha = 1 - ease_in_out((t - 10.0) / 1.0)
    for sprite, y, t_in in [(logo(140), 300, 0.3), (text("PharmaColdOps", "semibold", 116), 520, 0.9),
                            (text("Explainable. Auditable. Human in the loop.", "semilight", 46, GREY), 640, 1.8),
                            (text("Project Group 41  \u00b7  NUS-ISS  \u00b7  2026", "semilight", 34, GREY), 880, 2.6),
                            (text("Research prototype  \u00b7  simulated data  \u00b7  not a production or "
                                  "compliance system", "semilight", 26, DIM), 940, 2.6)]:
        a, left = envelope(t, t_in, 99)
        put(c, sprite, W / 2, y + 40 * left, a * alpha)


PARTS = {
    "a": [(7, a_open), (8, a_window), (12, a_excursion), (13, a_questions), (9, a_reveal),
          (12, a_outcomes), (13, a_product), (6, a_cue)],
    "b": [(10, b_agreement), (10, b_routes), (14, b_bento), (8, b_human), (10, b_one_more),
          (8, b_belief), (11, b_end)],
}


def frame(part, t):
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    start = 0
    for seconds, scene in PARTS[part]:
        if start <= t < start + seconds:
            scene(canvas, t - start)
            break
        start += seconds
    return canvas.convert("RGB")


def duration(part):
    return sum(seconds for seconds, _ in PARTS[part])


# -------------------------------------------------------------------- music
NOTE = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}


def hz(name):
    return 440 * 2 ** ((NOTE[name[0]] + 12 * (int(name[1:]) - 4)) / 12)


CHORDS = [("A1", ["A3", "C4", "E4", "B4"]), ("F1", ["F3", "A3", "C4", "E4"]),
          ("C2", ["G3", "C4", "E4", "D5"]), ("G1", ["G3", "B3", "D4", "A4"])]


def tone(freq, seconds, partials=(1, 0.35, 0.12)):
    t = np.arange(int(seconds * SR)) / SR
    return sum(a * np.sin(2 * np.pi * freq * k * t + k) for k, a in enumerate(partials, 1))


def layers(total):
    n = int(total * SR)
    pad, bass, arp = np.zeros(n), np.zeros(n), np.zeros(n)
    bar = 6.0
    for i in range(int(total / bar) + 1):
        root, notes = CHORDS[i % len(CHORDS)]
        start = int(i * bar * SR)
        length = int((bar + 2.5) * SR)
        env = np.minimum(1, np.minimum(np.arange(length) / (1.8 * SR), (length - np.arange(length)) / (2.5 * SR)))
        voice = sum(tone(hz(m) * (1 + d), bar + 2.5) for m in notes for d in (-0.0015, 0.0015)) / 8
        end = min(n, start + length)
        pad[start:end] += (voice * env)[:end - start]
        bass[start:end] += (tone(hz(root), bar + 2.5, (1, 0.2)) * env)[:end - start]
        step = 60 / 96 / 2
        for j in range(int(bar / step)):
            s = start + int(j * step * SR)
            pluck = tone(hz(notes[j % len(notes)]) * 2, 0.9, (1, 0.25)) * np.exp(-np.arange(int(0.9 * SR)) / (0.18 * SR))
            e = min(n, s + len(pluck))
            if s < n:
                arp[s:e] += pluck[:e - s]
    return pad, bass, arp


def finish(mix, total, peak_db):
    """Add a short noise-reverb tail, fade the edges and normalise to a peak level."""
    n = len(mix)
    t = np.arange(n) / SR
    rng = np.random.default_rng(41)
    tail = rng.standard_normal(int(2.4 * SR)) * np.exp(-np.arange(int(2.4 * SR)) / (0.7 * SR))
    size = 1 << (n + len(tail)).bit_length()
    wet = np.fft.irfft(np.fft.rfft(mix, size) * np.fft.rfft(tail, size), size)[:n]
    mix = 0.75 * mix + 0.25 * wet / (np.abs(wet).max() + 1e-9) * np.abs(mix).max()
    mix *= np.minimum(1, np.minimum(t / 0.5, (total - t) / 1.0))
    mix = mix / (np.abs(mix).max() + 1e-9) * 10 ** (peak_db / 20)
    stereo = np.stack([mix, np.roll(mix, int(0.012 * SR))], 1)
    return (stereo * 32767).astype(np.int16)


def music(part):
    total = duration(part)
    pad, bass, arp = layers(total)
    n = len(pad)
    t = np.arange(n) / SR
    marks = np.cumsum([0] + [s for s, _ in PARTS[part]])
    if part == "a":
        pad_gain = np.interp(t, [0, 14, 15, 27, 40, 41, 74, 80], [0.5, 0.6, 0.25, 0.3, 0.45, 0.9, 0.9, 0.0])
        arp_gain = np.interp(t, [0, 40, 41.5, 74, 79], [0, 0, 0.5, 0.5, 0])
        hit = marks[4]
    else:
        quiet = marks[4]
        pad_gain = np.interp(t, [0, 1, quiet - 0.5, quiet, quiet + 2.6, quiet + 3.6, total - 2, total],
                             [0.0, 0.85, 0.85, 0.1, 0.1, 0.9, 0.9, 0.0])
        arp_gain = np.interp(t, [0, 1, quiet - 0.5, quiet, quiet + 3.6, quiet + 5, total - 3, total],
                             [0.3, 0.45, 0.45, 0, 0, 0.45, 0.3, 0])
        hit = quiet + 3.6
    mix = pad * pad_gain + 0.35 * bass * pad_gain + 0.12 * arp * arp_gain
    boom_t = np.arange(int(3 * SR)) / SR
    boom = np.sin(2 * np.pi * 48 * boom_t) * np.exp(-boom_t / 0.9) * 0.9
    s = int(hit * SR)
    mix[s:s + len(boom)] += boom[:max(0, n - s)]
    return finish(mix, total, -6)


def bed(total):
    """Quiet pad-only bed under the live demo, leaving room for human narration."""
    pad, bass, arp = layers(total)
    return finish(pad + 0.35 * bass + 0.05 * arp, total, -18)


def write_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(samples.tobytes())


# ------------------------------------------------------------------ output
def ffmpeg_exe(explicit):
    if explicit:
        return explicit
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def render(part, out, ffmpeg):
    wav = out / f"promo-part-{part}-music.wav"
    write_wav(wav, music(part))
    mp4 = out / f"promo-part-{part}.mp4"
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "17",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frames = round(duration(part) * FPS)
    for i in range(frames):
        proc.stdin.write(frame(part, i / FPS).tobytes())
        if i % (FPS * 10) == 0:
            print(f"part {part}: {i / FPS:5.1f}s / {duration(part)}s", flush=True)
    proc.stdin.close()
    if proc.wait():
        raise SystemExit("ffmpeg failed while encoding " + str(mp4))
    return mp4


def probe(ffmpeg, path):
    """Return (seconds, has_audio) from ffmpeg's banner for a media file."""
    info = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    if "Duration: " not in info or "Video:" not in info:
        raise SystemExit("not a readable video: " + str(path))
    h, m, s = info.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s), "Audio:" in info


def splice(ffmpeg, part_a, demo, part_b, target):
    """Concatenate A + demo + B, letterboxing the demo to 1920x1080 at 30 fps."""
    seconds, demo_has_audio = probe(ffmpeg, demo)
    video = f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2," \
            "setsar=1,format=yuv420p"
    audio = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    inputs = ["-i", str(part_a), "-i", str(demo), "-i", str(part_b)]
    demo_audio = "1:a"
    if not demo_has_audio:
        inputs += ["-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        demo_audio = "3:a"
    graph = ";".join([f"[{i}:v]{video}[v{i}];[{a}]{audio}[a{i}]" for i, a in ((0, "0:a"), (1, demo_audio), (2, "2:a"))]
                     + ["[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]"])
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[v]",
                    "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac",
                    "-b:a", "192k", "-movflags", "+faststart", str(target)], check=True)
    return target


# ------------------------------------------------------- live demo cut
# Source: the team's 5:00 English promotion VISUAL DRAFT (25 fps, no audio), see
# docs/英文画面视频与真人配音交接.md. Cut points are tied to this exact file.
DRAFT_SHA256 = "1ba495f414b38b45038cecfce76b160d31fc8088ae8b72919384cdc1ce6685d5"
# The draft burns a "VISUAL DRAFT" banner into y 0-59 and note captions into y 980-1079;
# the UI recording sits in between with white page margins left and right.
DRAFT_CROP = (144, 60, 1632, 920)  # x, y, w, h
STAGE_Y = 48
# (source in, source out, [(seconds into the cut, caption)]); chapters per docs/video-storyboard-en.json
DRAFT_CUTS = [
    (20.6, 28.5, [(0, "A local prototype on Singapore\u2019s road network. Orders and readings are simulated.")]),
    (44.5, 58.5, [(0, "Generate today\u2019s simulated delivery batch and check every order.")]),
    (76.5, 88.5, [(0, "Confirm the plan. The fleet departs on a simulated clock.")]),
    (116.5, 140.0, [(0, "An excursion is linked to its delivery order and where it happened."),
                    (17.0, "The rule engine recommends. Handling waits for human review.")]),
    (147.5, 176.0, [(0, "A scripted demo review is saved apart from the original rule snapshot."),
                    (12.0, "Compare replacement options. Nothing changes until one is adopted.")]),
    (189.0, 208.0, [(0, "The replacement is tracked to delivery on a 300\u00d7 simulated clock.")]),
    (221.0, 237.0, [(0, "Ask about this case. Answers come with the recorded evidence."),
                    (8.0, "Off-topic questions are refused, not guessed.")]),
    (243.0, 259.0, [(0, "Close the case and export the complete audit trail.")]),
]
DEMO_FADE = 0.35


def demo_seconds():
    return sum(b - a for a, b, _ in DRAFT_CUTS)


@lru_cache(maxsize=None)
def stage():
    x, y, w, h = DRAFT_CROP
    back = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    left = (W - w) // 2
    ImageDraw.Draw(glow).rounded_rectangle((left, STAGE_Y + 20, left + w, STAGE_Y + h), 24, fill=(56, 189, 248, 55))
    back = Image.alpha_composite(back, glow.filter(ImageFilter.GaussianBlur(40)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 18, fill=255)
    return back, mask, left


def demo_frame(shot, cut, t):
    back, mask, left = stage()
    seconds = cut[1] - cut[0]
    canvas = back.copy()
    canvas.paste(shot, (left, STAGE_Y), mask)
    captions = cut[2]
    for i, (start, line) in enumerate(captions):
        end = captions[i + 1][0] if i + 1 < len(captions) else seconds
        alpha = ease_out((t - start - 0.2) / 0.6) * (1 - ease_in_out((t - end + 0.5) / 0.4))
        put(canvas, text(line, "semilight", 38, WHITE), W / 2, STAGE_Y + DRAFT_CROP[3] + 58, alpha)
    fade = min(1, ease_in_out(t / DEMO_FADE), ease_in_out((seconds - t) / DEMO_FADE))
    rgb = canvas.convert("RGB")
    return rgb if fade >= 0.999 else Image.eval(rgb, lambda v: int(v * fade))


def render_demo(draft, out, ffmpeg):
    import hashlib
    digest = hashlib.sha256(Path(draft).read_bytes()).hexdigest()
    if digest != DRAFT_SHA256:
        raise SystemExit("draft video differs from the one the cut points were chosen for: " + digest)
    total = demo_seconds()
    wav = out / "promo-demo-cut-bed.wav"
    write_wav(wav, bed(total))
    mp4 = out / "promo-demo-cut.mp4"
    enc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264",
                            "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                            "-shortest", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    x, y, w, h = DRAFT_CROP
    for cut in DRAFT_CUTS:
        start, end, _ = cut
        frames = round((end - start) * FPS)
        dec = subprocess.run([ffmpeg, "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(draft),
                              "-t", f"{end - start:.3f}", "-vf", f"crop={w}:{h}:{x}:{y},fps={FPS}",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        size = w * h * 3
        got = len(dec) // size
        if got < frames - 1:
            raise SystemExit(f"cut {start}-{end}: decoded {got} frames, expected {frames}")
        for i in range(frames):
            k = min(i, got - 1)
            shot = Image.frombuffer("RGB", (w, h), dec[k * size:(k + 1) * size])
            enc.stdin.write(demo_frame(shot, cut, i / FPS).tobytes())
        print(f"demo cut {start:6.1f}-{end:6.1f}s done", flush=True)
    enc.stdin.close()
    if enc.wait():
        raise SystemExit("ffmpeg failed while encoding " + str(mp4))
    return mp4


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="new output directory (git-ignored data/processed/...)")
    parser.add_argument("--parts", default="ab", help="which segments to render: a, b or ab")
    parser.add_argument("--demo", type=Path, help="live demo recording to splice between part A and part B")
    parser.add_argument("--draft", type=Path, help="5:00 promotion visual draft: cut it down and use it as --demo")
    parser.add_argument("--stills", help="comma-separated times; writes PNGs like a-12.0.png instead of video")
    parser.add_argument("--ffmpeg", help="ffmpeg executable (default: imageio-ffmpeg bundle)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_exe(args.ffmpeg)
    if args.stills:
        for part in args.parts:
            for stamp in args.stills.split(","):
                frame(part, float(stamp)).save(args.out / f"{part}-{float(stamp):05.1f}.png")
        return
    rendered = {part: render(part, args.out, ffmpeg) for part in args.parts}
    if args.draft:
        args.demo = render_demo(args.draft, args.out, ffmpeg)
    if args.demo:
        if set(rendered) != {"a", "b"}:
            raise SystemExit("--demo needs both parts rendered in the same run (--parts ab)")
        target = splice(ffmpeg, rendered["a"], args.demo, rendered["b"], args.out / "PharmaColdOps-promotion.mp4")
        print("spliced:", target)


if __name__ == "__main__":
    main()
