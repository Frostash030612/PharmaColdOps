"""Render the keynote-style PharmaColdOps SYSTEM DESIGN video (no speech, < 5 min).

Same visual language as scripts/build_keynote_promo.py (whose drawing helpers are
reused): black stage, one idea per scene, animated diagrams, real UI screenshots.
Every number on screen comes from docs/FINAL_REPORT_EN.md; diagrams that are
illustrations say so. The soundtrack is a synthesised music bed; narration must be
recorded by team members (briefing p13 forbids AI-generated presentation speech).

    python scripts/build_keynote_system.py --out data/processed/keynote-system-20261020
    python scripts/build_keynote_system.py --out ... --stills 12,40   # PNG checks
"""
import argparse
import math
import random
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_keynote_promo import (DIM, FPS, GREY, H, ICE, MINT, W, WHITE, clamp, ease_in_out,  # noqa: E402
                                 ease_out, envelope, ffmpeg_exe, finish, font, layers, logo, put, rounded,
                                 screenshot, show, text, write_wav)

GREEN, AMBER, RED, BLUE, PURPLE = (48, 209, 88), (255, 159, 10), (255, 69, 58), (56, 189, 248), (191, 90, 242)
TEAL = (94, 234, 212)
CARD = (28, 28, 30, 255)
SOFT = (161, 161, 166)


# ---------------------------------------------------------------- helpers
class Ink:
    """Anti-aliased line art: draw at 2x, downsample once per frame."""

    def __init__(self):
        self.img = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.used = False

    def path(self, points, progress=1.0, colour=SOFT, width=4, alpha=1.0, dashed=False, head=True):
        progress = clamp(progress)
        if progress <= 0 or alpha <= 0:
            return
        self.used = True
        pts = [(x * 2, y * 2) for x, y in points]
        lengths = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
        remaining = sum(lengths) * progress
        fill = colour + (round(255 * alpha),)
        tip, prev = pts[0], pts[0]
        for (a, b), seg in zip(zip(pts, pts[1:]), lengths):
            if remaining <= 0:
                break
            k = min(1, remaining / seg)
            end = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
            if dashed:
                for i in range(int(seg * k // 24) + 1):
                    s0, s1 = i * 24 / seg, min(k, (i * 24 + 13) / seg)
                    if s0 < k:
                        self.d.line((a[0] + (b[0] - a[0]) * s0, a[1] + (b[1] - a[1]) * s0,
                                     a[0] + (b[0] - a[0]) * s1, a[1] + (b[1] - a[1]) * s1), fill=fill, width=width * 2)
            else:
                self.d.line((*a, *end), fill=fill, width=width * 2)
            prev, tip = a, end
            remaining -= seg
        if head and tip != prev:
            ang = math.atan2(tip[1] - prev[1], tip[0] - prev[0])
            size = 11 * width / 2 + 10
            left = (tip[0] - size * math.cos(ang - 0.45), tip[1] - size * math.sin(ang - 0.45))
            right = (tip[0] - size * math.cos(ang + 0.45), tip[1] - size * math.sin(ang + 0.45))
            self.d.polygon((tip, left, right), fill=fill)

    def circle(self, cx, cy, r, fill=None, outline=None, width=3, alpha=1.0):
        """fill is RGBA, outline RGB; both scaled by alpha."""
        if alpha <= 0:
            return
        self.used = True
        f = fill[:3] + (round(fill[3] * alpha),) if fill else None
        o = outline + (round(255 * alpha),) if outline else None
        self.d.ellipse((2 * (cx - r), 2 * (cy - r), 2 * (cx + r), 2 * (cy + r)), fill=f, outline=o, width=width * 2)

    def done(self, canvas):
        if self.used:
            canvas.alpha_composite(self.img.reduce(2))


@lru_cache(maxsize=None)
def card(w, h, title, sub="", accent=None, title_size=40, sub_size=28):
    img = rounded((w, h), 26, CARD)
    if accent:
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), 26, outline=accent + (150,), width=2)
    t = text(title, "semibold", title_size)
    if sub:
        s = text(sub, "semilight", sub_size, SOFT)
        gap = 6
        top = (h - t.height - s.height - gap) // 2
        img.alpha_composite(t, ((w - t.width) // 2, top))
        img.alpha_composite(s, ((w - s.width) // 2, top + t.height + gap))
    else:
        img.alpha_composite(t, ((w - t.width) // 2, (h - t.height) // 2))
    return img


@lru_cache(maxsize=None)
def chip(label, colour=SOFT, size=28, fill=(38, 38, 42, 255)):
    t = text(label, "semilight", size, colour)
    img = rounded((t.width + 36, t.height + 14), (t.height + 14) // 2, fill)
    img.alpha_composite(t, (18, 7))
    return img


def chips_row(c, t, labels, cy, t_in, t_out, colour=SOFT, size=28, gap=18, cx=W / 2):
    sprites = [chip(label, colour, size) for label in labels]
    x = cx - (sum(s.width for s in sprites) + gap * (len(sprites) - 1)) / 2
    for i, s in enumerate(sprites):
        show(c, t, s, x + s.width / 2, cy, t_in + 0.25 * i, t_out, rise=24)
        x += s.width + gap


@lru_cache(maxsize=None)
def rich(parts, colour=WHITE):
    """Left-to-right text runs on one baseline: parts = ((str, face, size, dy), ...)."""
    width = int(sum(font(f, s).getlength(txt) for txt, f, s, _ in parts)) + 40
    mask = Image.new("L", (width, 260), 0)
    d = ImageDraw.Draw(mask)
    x, base = 20, 170
    for txt, f, s, dy in parts:
        d.text((x, base + dy), txt, font=font(f, s), fill=255, anchor="ls")
        x += font(f, s).getlength(txt)
    box = mask.getbbox()
    img = Image.new("RGBA", mask.size, colour + (0,))
    img.putalpha(mask)
    return img.crop((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4))


def headline(c, t, title, sub=None, t_out=99, y=110):
    show(c, t, text(title, "semibold", 68), W / 2, y, 0.3, t_out)
    if sub:
        show(c, t, text(sub, "semilight", 36, GREY), W / 2, y + 74, 0.8, t_out)


def chapter(number, title, modules):
    def scene(c, t):
        show(c, t, text(f"Use case {number}", "semibold", 40, GREY), W / 2, 420, 0.2, 3.3, rise=20)
        show(c, t, text(title, "semibold", 108), W / 2, 530, 0.4, 3.3)
        show(c, t, text(modules, "semilight", 38, TEAL), W / 2, 645, 0.8, 3.3, rise=20)
    return scene


# ------------------------------------------------------------- scenes
def s_title(c, t):
    alpha, left = envelope(t, 0.2, 7.2, 1.4, 0.8)
    put(c, logo(130), W / 2, 330 + 30 * left, alpha)
    show(c, t, text("Inside PharmaColdOps.", "semibold", 112), W / 2, 530, 0.8, 7.2)
    show(c, t, text("System design and the technology behind each use case.", "semilight", 44, GREY),
         W / 2, 650, 1.8, 7.2)
    show(c, t, text("Project Group 41  ·  NUS-ISS  ·  2026", "semilight", 30, DIM), W / 2, 940, 2.6, 7.2)


ARCH = {"M1": (420, 420, "M1 Inputs", "Simulated, seeded data"), "M2": (960, 420, "M2 Exposure", "Intervals and MKT"),
        "M3": (1500, 420, "M3 Rules", "Recommendation + review"), "M4": (420, 700, "M4 Models", "Advisory only"),
        "M6": (960, 700, "M6 Evidence", "Case graph and Q&A"), "M5": (1500, 700, "M5 Dispatch", "Plan and execution")}
ARCH_ORDER = ["M1", "M2", "M3", "M5", "M6", "M4"]


def s_arch(c, t):
    out = 17.2
    headline(c, t, "Seven modules. One case identity.", "Case, order and product IDs flow through every module.", out)
    alpha = envelope(t, 0, out)[0]
    ink = Ink()
    edges = [([(620, 420), (756, 420)], 1.5, SOFT, False), ([(1160, 420), (1296, 420)], 2.0, SOFT, False),
             ([(420, 495), (420, 621)], 3.6, SOFT, False), ([(1500, 495), (1500, 621)], 2.5, SOFT, False),
             ([(1360, 495), (1120, 621)], 3.0, SOFT, False), ([(1300, 700), (1164, 700)], 3.0, SOFT, False),
             ([(620, 650), (1330, 497)], 4.2, AMBER, True)]
    for pts, start, colour, dashed in edges:
        ink.path(pts, (t - start) / 0.8, colour, 4, alpha, dashed)
    flow = [(420, 420), (960, 420), (1500, 420), (1500, 700), (960, 700)]
    if 7.0 < t < 15.5:
        k = ease_in_out((t - 7.0) / 7.0)
        seg = min(3, int(k * 4))
        a, b = flow[seg], flow[seg + 1]
        f = k * 4 - seg
        ink.circle(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 13, fill=TEAL + (255,),
                   alpha=alpha * min(1, 15.5 - t))
    ink.done(c)
    for i, m in enumerate(ARCH_ORDER):
        x, y, title, sub = ARCH[m]
        show(c, t, card(400, 150, title, sub, TEAL if m == "M3" else None), x, y, 1.0 + 0.5 * i, out, rise=30)
    show(c, t, card(1480, 84, "M7  FastAPI  ·  Vue  ·  durable case storage and audit", "", None, 34),
         W / 2, 905, 4.2, out, rise=30)
    show(c, t, text("Model candidates never authorise actions", "semilight", 26, AMBER), 690, 553, 5.0, out, rise=10)
    show(c, t, text("Delivery state", "semilight", 24, SOFT), 1232, 670, 4.0, out, rise=10)
    show(c, t, text("Main path: observation → assessment → review → replacement → evidence",
                    "semilight", 30, GREY), W / 2, 1010, 7.0, out)


STACK = [("Vue 3  ·  Leaflet", "Bilingual web client and an explicit offline rule sandbox", BLUE),
         ("FastAPI", "One API service; version checks reject stale edits", GREEN),
         ("SQLite", "Authoritative cases and graph outbox, one transaction", AMBER),
         ("Neo4j 5", "Case and evidence graph, replayed idempotently", PURPLE),
         ("OR-Tools  ·  scikit-learn", "Routing search and advisory models", TEAL),
         ("Docker Compose", "Pinned images; non-root, read-only API container", SOFT)]


@lru_cache(maxsize=None)
def stack_row(i):
    name, desc, accent = STACK[i]
    img = rounded((1300, 96), 22, CARD)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, 9, 95), 4, fill=accent + (255,))
    img.alpha_composite(text(name, "semibold", 38), (40, 22))
    d = text(desc, "semilight", 30, SOFT)
    img.alpha_composite(d, (1300 - d.width - 30, (96 - d.height) // 2))
    return img


def s_stack(c, t):
    headline(c, t, "Built from proven parts.", None, 11.2)
    for i in range(len(STACK)):
        show(c, t, stack_row(i), W / 2, 270 + 118 * i, 0.8 + 0.3 * i, 11.2, rise=30)


@lru_cache(maxsize=None)
def mkt_formula():
    num = rich((("ΔH / R", "semilight", 66, 0),))
    den = rich((("−ln( ", "semilight", 66, 0), ("Σ t", "semilight", 66, 0), ("i", "semilight", 38, 16),
                (" e", "semilight", 66, 0), ("−ΔH / RT", "semilight", 38, -34), ("i", "semilight", 26, -24),
                ("  /  Σ t", "semilight", 66, 0), ("i", "semilight", 38, 16), (" )", "semilight", 66, 0)))
    lhs = rich((("MKT  =", "semibold", 70, 0),))
    fw = max(num.width, den.width)
    img = Image.new("RGBA", (lhs.width + 40 + fw, num.height + den.height + 60), (0, 0, 0, 0))
    mid = num.height + 30
    img.alpha_composite(lhs, (0, mid - lhs.height // 2))
    fx = lhs.width + 40
    img.alpha_composite(num, (fx + (fw - num.width) // 2, 0))
    ImageDraw.Draw(img).line((fx, mid, fx + fw, mid), fill=WHITE + (255,), width=4)
    img.alpha_composite(den, (fx + (fw - den.width) // 2, mid + 22))
    return img


def s_mkt(c, t):
    out = 17.2
    headline(c, t, "Exposure, computed — not guessed.",
             "M2 turns explicit temperature intervals into a mean kinetic temperature.", out)
    show(c, t, mkt_formula(), W / 2, 520, 1.2, out, d_in=1.2)
    chips_row(c, t, ["Duration-weighted", "ΔH = 83.144 kJ/mol (editable)", "Log-sum-exp for stability"],
              800, 4.0, out)
    chips_row(c, t, ["Missing intervals stay missing", "Server recomputes client summaries"], 880, 6.0, out)


RULES = ["Freeze damage: freeze-sensitive product at or below 0 °C  →  scrap",
         "Compromised packaging during an excursion  →  scrap",
         "Duration ≥ 2× allowable, or MKT ≥ threshold + 3 °C  →  scrap",
         "Duration > allowable, or MKT > threshold  →  scrap",
         "Retestable and near the edge (≥ 0.8× allowable, or MKT ≥ threshold − 0.5 °C)  →  retest",
         "Otherwise  →  release"]


@lru_cache(maxsize=None)
def rule_row(i, state):
    w, h = 1180, 74
    fill = {"idle": CARD, "miss": (22, 22, 24, 255), "hit": (18, 52, 34, 255)}[state]
    img = rounded((w, h), 18, fill)
    if state == "hit":
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), 18, outline=GREEN + (255,), width=3)
    num = text(str(i + 1), "bold", 32, GREEN if state == "hit" else SOFT)
    img.alpha_composite(num, (26, (h - num.height) // 2))
    body = text(RULES[i], "semilight", 28, DIM if state == "miss" else WHITE)
    img.alpha_composite(body, (78, (h - body.height) // 2))
    return img


@lru_cache(maxsize=None)
def verdict_card():
    img = rounded((520, 150), 26, (90, 24, 22, 255))
    v = text("SCRAP  ·  rule 3", "black", 50)
    img.alpha_composite(v, ((520 - v.width) // 2, 22))
    s = text("cites WHO TRS 961 Annex 9", "semilight", 28, (255, 200, 195))
    img.alpha_composite(s, ((520 - s.width) // 2, 96))
    return img


def s_rules(c, t):
    out = 23.2
    headline(c, t, "Six rules. First match wins.", "M3 evaluates in priority order and records the whole path.", out)
    scan = (t - 6.0) / 1.4
    for i in range(6):
        state = "hit" if (i == 2 and scan > 3) else "miss" if (i < 2 and scan > i + 1) else "idle"
        show(c, t, rule_row(i, state), 690, 330 + 88 * i, 1.0 + 0.2 * i, out, rise=24)
    show(c, t, rounded((520, 300), 26, CARD), 1580, 450, 2.6, out, rise=30)
    for k, (line, face, size, col) in enumerate([("Example case", "semibold", 30, GREY),
                                                  ("Vaccine, 2–8 °C", "semibold", 40, WHITE),
                                                  ("13 °C for 300 min", "semilight", 34, WHITE),
                                                  ("MKT 13 °C  ·  packaging intact", "semilight", 30, SOFT)]):
        show(c, t, text(line, face, size, col), 1580, 345 + 64 * k, 2.8 + 0.15 * k, out, rise=30)
    show(c, t, verdict_card(), 1580, 720, 10.6, out, rise=30)
    show(c, t, text("Automatic outputs: release, retest or scrap. Quarantine is a human review outcome.",
                    "semilight", 32, GREY), W / 2, 905, 13.0, out)
    show(c, t, text("54 of 57 historical scenarios agree; the 3 misses are the quarantine cases.", "semilight", 30, DIM),
         W / 2, 965, 14.5, out)


STEPS = [("Registered", "rule snapshot saved", SOFT), ("Pending review", "downstream blocked", AMBER),
         ("Human decision", "reviewer · reason · time", BLUE), ("Effective outcome", "drives reshipment", GREEN)]


def s_review(c, t):
    out = 19.2
    headline(c, t, "The original never changes.", "A human outcome is stored beside the automatic one, never over it.", out)
    ink = Ink()
    xs, y = [330, 750, 1170, 1590], 520
    alpha = envelope(t, 0, out)[0]
    for i in range(3):
        ink.path([(xs[i] + 52, y), (xs[i + 1] - 52, y)], (t - 1.6 - 0.9 * i) / 0.7, SOFT, 4, alpha)
    for i, (name, sub, col) in enumerate(STEPS):
        ink.circle(xs[i], y, 40, fill=col + (60,), outline=col, width=4, alpha=envelope(t, 1.2 + 0.9 * i, out)[0])
    ink.done(c)
    for i, (name, sub, col) in enumerate(STEPS):
        show(c, t, text(name, "semibold", 36), xs[i], y + 90, 1.3 + 0.9 * i, out, rise=20)
        show(c, t, text(sub, "semilight", 28, SOFT), xs[i], y + 138, 1.5 + 0.9 * i, out, rise=20)
    show(c, t, chip("Original rule snapshot  ·  locked", WHITE, 30, (40, 40, 46, 255)), 540, 345, 5.5, out, rise=20)
    show(c, t, chip("Human outcome  ·  separate record", WHITE, 30, (22, 46, 70, 255)), 1380, 345, 6.2, out, rise=20)
    chips_row(c, t, ["Version checks reject stale edits", "Executed outcomes cannot be rewritten",
                     "Audit export: HTML + JSON + content hash"], 880, 8.5, out)
    show(c, t, text("A content hash detects changes; it is not a signature or a compliance certificate.",
                    "semilight", 28, DIM), W / 2, 960, 10.0, out)


def s_outbox(c, t):
    out = 13.2
    headline(c, t, "Write once. Replay safely.", "The case is the source of truth; the graph is rebuilt from it.", out)
    alpha = envelope(t, 0, out)[0]
    boxes = [(330, 330, "FastAPI", "registers the case"), (800, 330, "SQLite", "case + outbox entry"),
             (1270, 330, "Worker", "lease · retry"), (1660, 300, "Neo4j", "idempotent case chain")]
    ink = Ink()
    for i in range(3):
        x0 = boxes[i][0] + boxes[i][1] / 2 + 8
        x1 = boxes[i + 1][0] - boxes[i + 1][1] / 2 - 10
        ink.path([(x0, 520), (x1, 520)], (t - 2.0 - 0.8 * i) / 0.6, SOFT, 4, alpha)
    ink.done(c)
    for i, (x, w, title, sub) in enumerate(boxes):
        show(c, t, card(w, 160, title, sub, AMBER if i == 1 else None, 40, 26), x, 520, 1.0 + 0.4 * i, out, rise=30)
    show(c, t, chip("one SQLite transaction", AMBER, 26), 800, 640, 3.0, out, rise=16)
    show(c, t, text("If Neo4j is down, the case is still saved. The audit endpoint compares real graph coverage.",
                    "semilight", 32, GREY), W / 2, 820, 5.0, out)
    show(c, t, text("Graph outage, outbox recovery and backup restore were exercised in acceptance tests.",
                    "semilight", 28, DIM), W / 2, 890, 6.5, out)


def tour_len(route):
    return sum(math.dist(a, b) for a, b in zip(route, route[1:]))


@lru_cache(maxsize=None)
def routes():
    rnd = random.Random(41)
    depot, pts = (560, 610), []
    while len(pts) < 15:
        a, r = rnd.uniform(0, 2 * math.pi), rnd.uniform(110, 330)
        p = (depot[0] + r * math.cos(a) * 1.35, depot[1] + r * math.sin(a))
        if 250 < p[1] < 950 and all(math.dist(p, q) > 70 for q in pts):
            pts.append(p)
    left, order, cur = list(pts), [], depot  # greedy: nearest neighbour, cut into three vehicles
    while left:
        nxt = min(left, key=lambda q: math.dist(cur, q))
        order.append(nxt)
        left.remove(nxt)
        cur = nxt
    greedy = [[depot] + order[i:i + 5] + [depot] for i in range(0, 15, 5)]
    sweep = sorted(pts, key=lambda q: math.atan2(q[1] - depot[1], q[0] - depot[0]))
    better = []  # improved: angular sweep, then 2-opt inside each route
    for i in range(0, 15, 5):
        r = [depot] + sweep[i:i + 5] + [depot]
        improved = True
        while improved:
            improved = False
            for a in range(1, len(r) - 2):
                for b in range(a + 1, len(r) - 1):
                    cand = r[:a] + r[a:b + 1][::-1] + r[b + 1:]
                    if tour_len(cand) < tour_len(r) - 1e-6:
                        r, improved = cand, True
        better.append(r)
    return depot, pts, greedy, better


SOLVERS = [("Greedy", "interpretable baseline", SOFT), ("OR-Tools Routing", "Guided Local Search, time-limited", TEAL),
           ("Genetic algorithm", "experimental comparison", PURPLE)]


@lru_cache(maxsize=None)
def solver_card(i):
    name, sub, col = SOLVERS[i]
    box = rounded((640, 130), 24, CARD)
    ImageDraw.Draw(box).rounded_rectangle((0, 0, 9, 129), 4, fill=col + (255,))
    box.alpha_composite(text(name, "semibold", 40), (40, 18))
    box.alpha_composite(text(sub, "semilight", 28, SOFT), (40, 76))
    return box


def s_vrptw(c, t):
    out = 23.2
    headline(c, t, "Vehicle routing with time windows.",
             "M5 plans replacement and urgent work under capacity and time limits.", out)
    depot, pts, greedy, better = routes()
    alpha = envelope(t, 0, out)[0]
    swap = ease_in_out((t - 9.0) / 1.2)
    ink = Ink()
    for i, r in enumerate(greedy):
        ink.path(r, (t - 2.5 - 0.4 * i) / 2.5, (120, 120, 126), 3, alpha * (1 - 0.75 * swap), dashed=True, head=False)
    for i, r in enumerate(better):
        ink.path(r, (t - 9.4 - 0.5 * i) / 2.8, (BLUE, TEAL, GREEN)[i], 5, alpha, head=False)
    for p in pts:
        ink.circle(p[0], p[1], 11, fill=WHITE + (255,), alpha=envelope(t, 1.2, out)[0])
    ink.circle(depot[0], depot[1], 20, fill=AMBER + (255,), alpha=envelope(t, 1.0, out)[0])
    ink.done(c)
    show(c, t, text("Depot", "semibold", 28, AMBER), depot[0], depot[1] + 44, 1.2, out, rise=10)
    show(c, t, text("Greedy (dashed) vs improved routes — illustration, not solver output", "semilight", 26, DIM),
         560, 1000, 2.0, out)
    for i in range(3):
        show(c, t, solver_card(i), 1430, 360 + 160 * i, 4.0 + 1.6 * i, out, rise=30)
    chips_row(c, t, ["Capacity", "Time windows", "Legal day-end parking"], 850, 13.0, out, size=26, gap=14, cx=1430)
    show(c, t, text("Previews never reserve a vehicle. Adoption is explicit.", "semilight", 28, GREY), 1430, 925, 14.0, out)


def bar(c, t, y, label, km, colour, t_in, out, scale):
    a = envelope(t, t_in, out)[0]
    grow = ease_out((t - t_in - 0.2) / 1.6)
    w = max(1, round(km * scale * grow))
    put(c, rounded((w, 64), 14, colour + (255,)), 520 + w / 2, y, a)
    put(c, text(label, "semibold", 34), 340, y, a)
    put(c, text(f"{km * grow:.2f} km", "semibold", 36), 520 + w + 110, y, a)


def s_results(c, t):
    out = 17.2
    headline(c, t, "Measured on standard benchmarks.", "49 solver runs: six Solomon instances and one Singapore instance.", out)
    bar(c, t, 340, "Greedy", 165.26, (110, 110, 116), 1.0, out, 1000 / 170)
    bar(c, t, 440, "OR-Tools", 137.85, TEAL, 1.6, out, 1000 / 170)
    show(c, t, text("−16.59% distance on the frozen Singapore instance, same three vehicles.", "semibold", 40,
                    GREEN), W / 2, 560, 3.6, out)
    rows = [("C101, C201", "matched published two-decimal reference distances"),
            ("R101, R201", "within about 0.17% of the reference, same fleet"),
            ("RC101", "16 vehicles vs 14 in the reference — not counted as a win"),
            ("Genetic algorithm", "did not outperform OR-Tools in this experiment")]
    for i, (k, v) in enumerate(rows):
        show(c, t, text(k, "semibold", 32), 520, 670 + 64 * i, 5.0 + 0.5 * i, out, rise=20)
        show(c, t, text(v, "semilight", 32, SOFT), 1180, 670 + 64 * i, 5.1 + 0.5 * i, out, rise=20)
    show(c, t, text("One run per configuration; not an operational savings estimate.", "semilight", 28, DIM),
         W / 2, 1000, 7.5, out)


def s_execute(c, t):
    out = 11.2
    headline(c, t, "Then the plan runs.", "Execution on a simulated clock, with the same constraints as planning.", out)
    show(c, t, screenshot("promo/button-page.png", (0, 1020, 1243, 1400), 450), W / 2, 545, 0.8, out, rise=40)
    chips_row(c, t, ["Simulated clock", "Delay inspection", "Vehicle failure", "Urgent orders", "Legal day-end parking"],
              880, 2.5, out)
    show(c, t, text("No GPS or live traffic; in-transit cargo transfer is explicitly unsupported.", "semilight", 28, DIM),
         W / 2, 960, 4.0, out)


def metric(c, t, cx, cy, value, fmt, label, t_in, out, colour=WHITE):
    show(c, t, text(fmt.format(value * ease_out((t - t_in) / 1.8)), "black", 76, colour), cx, cy, t_in, out, rise=20)
    show(c, t, text(label, "semilight", 26, SOFT), cx, cy + 62, t_in + 0.2, out, rise=20)


def s_models(c, t):
    out = 23.2
    headline(c, t, "Models advise. Rules decide.", "M4 results are shown beside the rule path and never override it.", out)
    for cx, title, sub, t_in in [(510, "Shipment risk", "8,000 shipments · 13 features · 5-fold", 1.0),
                                 (1410, "Event-level causes", "10,200 simulated events · 111 features", 2.0)]:
        show(c, t, rounded((820, 600), 30, CARD), cx, 600, t_in, out, rise=30)
        show(c, t, text(title, "semibold", 46), cx, 360, t_in + 0.2, out, rise=30)
        show(c, t, text(sub, "semilight", 28, SOFT), cx, 415, t_in + 0.3, out, rise=30)
    metric(c, t, 330, 530, 0.7087, "{:.3f}", "PR-AUC", 2.5, out, TEAL)
    metric(c, t, 690, 530, 0.9045, "{:.3f}", "ROC-AUC", 2.8, out)
    metric(c, t, 510, 700, 0.0933, "{:.3f}", "Brier after calibration (from 0.109)", 3.2, out)
    show(c, t, text("Logistic regression + histogram gradient boosting", "semilight", 26, DIM), 510, 850, 3.6, out)
    metric(c, t, 1230, 530, 0.7668, "{:.2f}", "macro-F1, nominal assets", 4.0, out, TEAL)
    metric(c, t, 1590, 530, 0.6505, "{:.2f}", "macro-F1, extreme stress", 4.3, out, AMBER)
    show(c, t, text("Every candidate and abstention", "semibold", 34), 1410, 690, 4.8, out)
    show(c, t, text("still requires human review.", "semibold", 34, AMBER), 1410, 738, 4.9, out)
    show(c, t, text("Same uncalibrated simulator for all test roles", "semilight", 26, DIM), 1410, 850, 5.2, out)
    show(c, t, text("The monthly cause model stayed weak (macro-F1 ≈ 0.13). SHAP explains a model, not an event’s cause.",
                    "semilight", 30, GREY), W / 2, 980, 7.0, out)


GRAPH = {"event": (960, 600, "Excursion\nEvent", (120, 200, 214)), "cause": (960, 300, "Cause", (163, 213, 72)),
         "sop": (1330, 410, "SOP", (214, 200, 150)), "reg": (1340, 790, "Regulation", (196, 160, 214)),
         "product": (1680, 880, "Product", (226, 150, 226)), "disp": (960, 920, "Disposition", (150, 214, 150)),
         "order": (600, 790, "Reshipment\nOrder", (90, 180, 150)), "dest": (270, 880, "Facility", (170, 190, 255)),
         "site": (590, 410, "Facility", (170, 190, 255))}
GRAPH_EDGES = [("event", "cause", "EVENT_CAUSED_BY"), ("event", "sop", "FOLLOWS"), ("event", "reg", "CITES"),
               ("product", "reg", "REGULATED_BY"), ("event", "disp", "EVENT_LEADS_TO_DISPOSITION"),
               ("event", "order", "TRIGGERS_RESHIPMENT"), ("order", "dest", "RESHIPS_TO"),
               ("event", "site", "EVENT_OCCURRED_AT")]


def s_graph(c, t):
    out = 19.2
    swap = ease_in_out((t - 11.0) / 1.0)
    headline(c, t, "A graph of every decision.", None, 10.8)
    show(c, t, text("A real case chain in Neo4j Browser.", "semibold", 68), W / 2, 110, 11.6, out)
    alpha = envelope(t, 0, out)[0] * (1 - swap)
    radius = lambda k: 100 if k == "event" else 70
    ink = Ink()
    for i, (a, b, _) in enumerate(GRAPH_EDGES):
        (x0, y0, *_), (x1, y1, *_) = GRAPH[a], GRAPH[b]
        d = math.dist((x0, y0), (x1, y1))
        p0 = (x0 + (x1 - x0) * radius(a) / d, y0 + (y1 - y0) * radius(a) / d)
        p1 = (x1 - (x1 - x0) * (radius(b) + 6) / d, y1 - (y1 - y0) * (radius(b) + 6) / d)
        ink.path([p0, p1], (t - 2.0 - 0.35 * i) / 0.7, SOFT, 3, alpha)
    for k, (x, y, label, col) in GRAPH.items():
        ink.circle(x, y, radius(k), fill=col + (255,), alpha=envelope(t, 0.8 if k == "event" else 1.6, out)[0] * (1 - swap))
    ink.done(c)
    for k, (x, y, label, col) in GRAPH.items():
        lines = label.split("\n")
        a = envelope(t, 1.0 if k == "event" else 1.8, out)[0] * (1 - swap)
        for j, line in enumerate(lines):
            size = 30 if k == "event" else 21 if len(lines) > 1 else 26 if len(line) <= 8 else 22
            put(c, text(line, "semibold", size, (10, 10, 12)), x, y + (j - (len(lines) - 1) / 2) * (size + 6), a)
    for i, (a, b, rel) in enumerate(GRAPH_EDGES):
        (x0, y0, *_), (x1, y1, *_) = GRAPH[a], GRAPH[b]
        d = math.dist((x0, y0), (x1, y1))
        k = (radius(a) + (d - radius(a) - radius(b)) / 2) / d  # middle of the visible edge
        put(c, chip(rel, GREY, 19, (0, 0, 0, 255)), x0 + (x1 - x0) * k, y0 + (y1 - y0) * k,
            envelope(t, 2.6 + 0.35 * i, out)[0] * (1 - swap))
    show(c, t, text("Case-level edges: two cases with the same outcome never share each other’s evidence.",
                    "semilight", 30, GREY), W / 2, 1015, 5.5, 10.8)
    if swap > 0:
        put(c, screenshot("kg-neo4j-browser.png", (0, 0, 1280, 800), 820), W / 2, 620,
            envelope(t, 11.0, out)[0] * swap, 0.97 + 0.03 * ease_out((t - 11) / 8))


QUERIES = ["Why this disposition?", "Show the audit chain", "Product requirements", "Cause context",
           "Disposition statistics"]
STATES = [("Answered with evidence", GREEN), ("Case not found", SOFT), ("Insufficient evidence", AMBER),
          ("Graph unavailable", RED), ("Unsupported → refused", SOFT)]


def s_qa(c, t):
    out = 15.2
    headline(c, t, "Five questions. Honest failure states.", "Fixed intents and template Cypher — not an LLM.", out)
    show(c, t, text("Structured queries", "semibold", 36, GREY), 560, 300, 0.8, out, rise=20)
    show(c, t, text("Distinct result states", "semibold", 36, GREY), 1360, 300, 0.8, out, rise=20)
    for i, q in enumerate(QUERIES):
        show(c, t, card(620, 92, q, "", None, 34), 560, 400 + 110 * i, 1.4 + 0.3 * i, out, rise=24)
    for i, (s, col) in enumerate(STATES):
        show(c, t, chip(s, col, 34, (30, 30, 34, 255)), 1360, 400 + 110 * i, 3.0 + 0.4 * i, out, rise=24)
    show(c, t, text("A failed graph query never turns into a confident-sounding concept answer.", "semilight", 30,
                    GREY), W / 2, 1000, 6.0, out)


def s_reliable(c, t):
    out = 13.2
    headline(c, t, "Built to be checked.", None, out)
    n = round(926 * ease_out((t - 0.6) / 2.4))
    show(c, t, text(str(n), "black", 240, grad=ICE, glow=8), W / 2, 420, 0.5, out)
    show(c, t, text("automated tests passed, zero skipped (isolated regression, 2026-10-17)", "semilight", 40, GREY),
         W / 2, 610, 1.6, out)
    chips_row(c, t, ["36-step API walkthrough", "9 frontend checks", "Real-browser failure checks"], 730, 3.0, out)
    chips_row(c, t, ["Graph outage + outbox recovery", "Backup restored to new volumes", "Pinned dependencies"],
              810, 3.8, out)
    show(c, t, text("Software checks, not new model accuracy. A local demonstration, not a production SLA.",
                    "semilight", 28, DIM), W / 2, 960, 5.0, out)


def s_limits(c, t):
    out = 11.2
    headline(c, t, "What it is not.", None, out)
    for i, line in enumerate(["Not trained or tested on real hospital orders or live sensors.",
                              "Engineering thresholds are not manufacturer stability limits.",
                              "Not an LLM, and not an autonomous medicine approver."]):
        show(c, t, text(line, "semilight", 46), W / 2, 420 + 130 * i, 1.0 + 0.8 * i, out)


def s_end(c, t):
    alpha = 1 - ease_in_out((t - 8.0) / 1.0)
    for sprite, y, t_in in [(logo(130), 330, 0.3), (text("PharmaColdOps", "semibold", 116), 540, 0.8),
                            (text("Explainable rules. Advisory models. Constrained routing. Evidence you can query.",
                                  "semilight", 40, GREY), 660, 1.6),
                            (text("Project Group 41  ·  NUS-ISS  ·  2026", "semilight", 34, GREY), 880, 2.4),
                            (text("Research prototype  ·  simulated data  ·  not a production or compliance "
                                  "system", "semilight", 26, DIM), 940, 2.4)]:
        a, left = envelope(t, t_in, 99)
        put(c, sprite, W / 2, y + 40 * left, a * alpha)


SCENES = [(8, s_title), (18, s_arch), (12, s_stack),
          (4, chapter(1, "Assess an excursion", "M2 Exposure  ·  M3 Rules")), (18, s_mkt), (24, s_rules),
          (4, chapter(2, "Human review", "M3 Review  ·  M7 Storage and audit")), (20, s_review), (14, s_outbox),
          (4, chapter(3, "Replace the delivery", "M5 Dispatch")), (24, s_vrptw), (18, s_results), (12, s_execute),
          (4, chapter(4, "Advisory models", "M4 Models")), (24, s_models),
          (4, chapter(5, "Ask the evidence", "M6 Knowledge graph")), (20, s_graph), (16, s_qa),
          (14, s_reliable), (12, s_limits), (9, s_end)]
TOTAL = sum(s for s, _ in SCENES)


def frame(t):
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    start = 0
    for seconds, scene in SCENES:
        if start <= t < start + seconds:
            scene(canvas, t - start)
            break
        start += seconds
    return canvas.convert("RGB")


def soundtrack():
    pad, bass, arp = layers(TOTAL)
    t = np.arange(len(pad)) / 48000
    arp_gain = np.interp(t, [0, 8, 10, TOTAL - 10, TOTAL - 2, TOTAL], [0, 0, 0.35, 0.35, 0.1, 0])
    return finish(0.8 * pad + 0.3 * bass + 0.1 * arp * arp_gain, TOTAL, -10)


def render(out, ffmpeg):
    wav = out / "system-music.wav"
    write_wav(wav, soundtrack())
    mp4 = out / "PharmaColdOps-system.mp4"
    proc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264",
                             "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                             "-shortest", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    for i in range(round(TOTAL * FPS)):
        proc.stdin.write(frame(i / FPS).tobytes())
        if i % (FPS * 20) == 0:
            print(f"system: {i / FPS:5.1f}s / {TOTAL}s", flush=True)
    proc.stdin.close()
    if proc.wait():
        raise SystemExit("ffmpeg failed while encoding " + str(mp4))
    return mp4


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="new output directory (git-ignored data/processed/...)")
    parser.add_argument("--stills", help="comma-separated times; writes PNGs instead of video")
    parser.add_argument("--ffmpeg", help="ffmpeg executable (default: imageio-ffmpeg bundle)")
    args = parser.parse_args()
    if TOTAL >= 300:
        raise SystemExit(f"planned length {TOTAL}s is not under five minutes")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stills:
        for stamp in args.stills.split(","):
            frame(float(stamp)).save(args.out / f"sys-{float(stamp):05.1f}.png")
        return
    print("rendered:", render(args.out, ffmpeg_exe(args.ffmpeg)))


if __name__ == "__main__":
    main()
