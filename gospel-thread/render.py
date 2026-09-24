#!/usr/bin/env python3
"""The Scarlet Thread: the gospel from Genesis to Revelation (see STORYBOARD.md).

One continuous tracking shot across a single panoramic world, 1920x1080 at 24 fps.
A scarlet thread is sewn through every scene, from the first promise (Genesis 3:15)
to the throne of the Lamb (Revelation 21 - 22), and the film ends by pulling back to
show the whole story as one stitched line.

Shared drawing helpers (easing, figures, trees, text) come from ../bible-animation/render.py.

Usage:  python3 render.py [output.mp4] [--preview SECONDS ...]
"""

import math
import os
import random
import shutil
import subprocess
import sys
import wave
from multiprocessing import Pool

import cairo
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_shared():
    """Load ../bible-animation/render.py under its own module name (both scripts are render.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bible_render", os.path.join(HERE, "..", "bible-animation", "render.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bible_render"] = mod
    spec.loader.exec_module(mod)
    return mod


_shared = _load_shared()
from bible_render import (  # noqa: E402
    BODY_FONT, CREAM, DISPLAY_FONT, FFMPEG, FPS, GOLD, H, W, bird, circle, clamp, crown,
    ease_in, ease_in_out, ease_out, ease_out_back, ease_out_bounce, figure, glow, hexc, lerp,
    letters_c, mix, overlays, poly, prog, rays, set_font, src, text_c, tree,
)

SCARLET = hexc("#d0142c")
SCARLET_HI = hexc("#ff6a6a")

# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

N = 12                    # stations 0..11 (Creation .. New Creation)
SPACING = W               # world distance between stations
TRAVEL, HOLD = 1.0, 3.3
SEG = TRAVEL + HOLD
T_TITLE = 3.2
ARRIVE = [T_TITLE + TRAVEL + k * SEG for k in range(N)]
T_PULL = ARRIVE[-1] + HOLD          # 54.8
T_PULL_END = T_PULL + 2.3
TOTAL = 60.0
NFRAMES = int(round(TOTAL * FPS))

GY = 850                            # ground baseline; station centres sit at G0


def ground_y(x):
    return GY - 14 * math.cos(2 * math.pi * x / SPACING) + 6 * math.sin(2 * math.pi * x / 640)


G0 = ground_y(0)

# Focal point of each station (local x = 0): the thread passes through these.
FOCUS_Y = {1: 430, 2: G0 - 112, 3: G0 - 222, 4: G0 - 150, 5: 430, 6: 420, 7: G0 - 44,
           8: 400, 9: G0 - 160, 10: 440, 11: 430}

# Per-station palette: index 0 is the void before creation (x = -SPACING).
SKY_TOP = [hexc(h) for h in ("#04050c", "#5b9fe0", "#2e2340", "#0a1030", "#05070f", "#6aa6da", "#4f86cc",
                             "#2a2146", "#060a1e", "#14040a", "#6aa4e0", "#4d8ed8", "#8cc0f2")]
SKY_BOT = [hexc(h) for h in ("#0d0e22", "#ffe7b5", "#b8645a", "#3a3a6a", "#1c1a33", "#f6dca8", "#ffd697",
                             "#e0905a", "#262a58", "#5e1612", "#ffd9b8", "#fff0cc", "#fff8e2")]
GROUND = [hexc(h) for h in ("#07070f", "#3f8f4a", "#3b4a3a", "#1a1a2a", "#151220", "#c9a66b", "#7a8a4a",
                            "#5a3a2a", "#12142a", "#0e0608", "#4f8a44", "#5f9a4a", "#7cbf6a")]
FAR = [mix(mix(b, t, 0.45), (0, 0, 0), 0.25) for t, b in zip(SKY_TOP, SKY_BOT)]
MID = [mix(f, g, 0.55) for f, g in zip(FAR, GROUND)]
X_FIRST, X_LAST = -SPACING, (N - 1) * SPACING

CAPTIONS = [
    ("GENESIS 1 – 2", "Made to walk with God", "“God saw all that he had made, and it was very good.”"),
    ("GENESIS 3:15", "Sin — and a first promise", "“He will crush your head, and you will strike his heel.”"),
    ("GENESIS 22:8", "God will provide the lamb", "“God himself will provide the lamb.”"),
    ("EXODUS 12:13", "The Passover lamb", "“When I see the blood, I will pass over you.”"),
    ("LEVITICUS 17:11", "A covering for sin", "“It is the blood that makes atonement for one’s life.”"),
    ("2 SAMUEL 7:13", "A King forever", "“I will establish the throne of his kingdom forever.”"),
    ("ISAIAH 53:5", "The promised Servant", "“He was pierced for our transgressions.”"),
    ("JOHN 1:14", "God comes near", "“The Word became flesh and made his dwelling among us.”"),
    ("JOHN 19:30  ·  MATTHEW 27:51", "The Lamb of God", "“It is finished.”"),
    ("1 CORINTHIANS 15:55  ·  GENESIS 3:15 FULFILLED", "Death is defeated", "“Where, O death, is your victory?”"),
    ("GENESIS 12:3  ·  ACTS 2", "Good news for every nation", "“In you all the families of the earth shall be blessed.”"),
    ("REVELATION 21:3", "Home with God forever", "“God’s dwelling place is now among the people.”"),
]


def palette_at(pal, wx):
    u = clamp((wx - X_FIRST) / SPACING, 0, len(pal) - 1)
    i = min(int(u), len(pal) - 2)
    return mix(pal[i], pal[i + 1], ease_in_out(u - i))


def hgrad(pal):
    g = cairo.LinearGradient(X_FIRST, 0, X_LAST, 0)
    for i, c in enumerate(pal):
        g.add_color_stop_rgb(i / (len(pal) - 1), *c)
    return g


# ---------------------------------------------------------------------------
# Camera: eased dollies with a breathing zoom, then a logarithmic pull-back
# ---------------------------------------------------------------------------

Z_END = (W - 200) / (X_LAST - 0 + SPACING)


def camera_state(T):
    """Returns (camera centre x in world, zoom, shake_x, shake_y)."""
    if T < T_TITLE:
        cx, z = X_FIRST + T * 20, 1.0
    elif T < T_PULL:
        k = 0
        while k + 1 < N and T >= ARRIVE[k + 1] - TRAVEL:
            k += 1
        a = ARRIVE[k]
        x_from = (k - 1) * SPACING
        x_to = k * SPACING
        if T < a:
            u = (T - (a - TRAVEL)) / TRAVEL
            cx = lerp(x_from, x_to, ease_in_out(u))
            z = 1 - 0.07 * math.sin(math.pi * u)          # dolly back while moving
        else:
            cx = x_to + (T - a) * 12                      # gentle drift while holding
            z = 1.0
        # settle overshoot: tiny zoom-in "landing" after arrival
        z += 0.012 * math.sin(clamp((T - a) / 0.6) * math.pi) if T >= a else 0
    else:
        u = ease_in_out(prog(T, T_PULL, T_PULL_END))
        x0 = X_LAST + HOLD * 12
        cx = lerp(x0, (X_LAST - 0) / 2, u)
        z = math.exp(lerp(0.0, math.log(Z_END), u))       # log zoom feels uniform
    # earthquake at the cross
    sx = sy = 0.0
    lt = T - ARRIVE[8]
    if 0.85 < lt < 2.2:
        e = math.exp(-(lt - 0.85) * 2.6)
        sx = math.sin(lt * 71) * 12 * e
        sy = math.cos(lt * 53) * 8 * e
    return cx, z, sx, sy


def apply_camera(cr, cx, z, sx=0.0, sy=0.0):
    cr.translate(W / 2 + sx, H / 2 + sy)
    cr.scale(z, z)
    cr.translate(-cx, -H / 2)


# ---------------------------------------------------------------------------
# Motifs
# ---------------------------------------------------------------------------

def lamb(cr, x, y, s, c, horns=False, a=1.0, glow_c=None):
    cr.save()
    cr.translate(x, y)
    cr.scale(s, s)
    if glow_c:
        glow(cr, 0, -10, 120, glow_c, 0.7 * a)
    cr.set_line_width(5)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    src(cr, c, a)
    for lx in (-22, -10, 12, 24):
        cr.move_to(lx, 0)
        cr.line_to(lx, 26)
    cr.stroke()
    for dx, dy, r in ((-22, -8, 16), (-6, -14, 17), (12, -12, 16), (24, -4, 14), (0, 0, 18), (-18, 4, 13), (16, 4, 13)):
        circle(cr, dx, dy, r, c, a)
    circle(cr, 40, -20, 11, c, a)
    poly(cr, [(44, -24), (58, -16), (46, -12)], c, a)
    if horns:
        cr.set_line_width(5)
        cr.arc(34, -26, 9, math.pi * 0.9, math.pi * 2.2)
        cr.stroke()
    cr.restore()


def serpent(cr, pts, c, a=1.0, width=10, head_squash=0.0):
    cr.set_line_width(width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    src(cr, c, a)
    cr.stroke()
    hx, hy = pts[0]
    cr.save()
    cr.translate(hx, hy)
    cr.scale(1 + head_squash * 0.8, 1 - head_squash * 0.6)
    circle(cr, 0, 0, width * 1.05, c, a)
    cr.restore()


def mound(cr, cx, half_w, top, base, c):
    cr.move_to(cx - half_w, base + 40)
    cr.curve_to(cx - half_w * 0.5, base, cx - half_w * 0.35, top, cx, top)
    cr.curve_to(cx + half_w * 0.35, top, cx + half_w * 0.5, base, cx + half_w, base + 40)
    cr.close_path()
    src(cr, c)
    cr.fill()


def flame(cr, x, y, s, T, seed, c1=(1, 0.55, 0.15), c2=(1, 0.9, 0.5)):
    f = 1 + 0.15 * math.sin(T * 17 + seed) + 0.08 * math.sin(T * 29 + seed * 2)
    sway = math.sin(T * 9 + seed) * 4 * s
    for sc, c in ((1.0, c1), (0.55, c2)):
        h = 34 * s * f * sc
        w = 12 * s * sc
        cr.move_to(x - w, y)
        cr.curve_to(x - w, y - h * 0.5, x + sway * 0.5, y - h * 0.7, x + sway, y - h)
        cr.curve_to(x + sway * 0.3, y - h * 0.6, x + w, y - h * 0.5, x + w, y)
        cr.close_path()
        src(cr, c, 0.95)
        cr.fill()


def bloom_flowers(cr, lt, seed, x0, x1, t_start, colors, T):
    rnd = random.Random(seed)
    for i in range(14):
        x = rnd.uniform(x0, x1)
        y = ground_y(x) + rnd.uniform(18, 90)
        g = ease_out_back(prog(lt, t_start + i * 0.06, t_start + 0.5 + i * 0.06), 2.5)
        c = rnd.choice(colors)
        if g <= 0:
            continue
        cr.set_line_width(3)
        src(cr, hexc("#2f6b30"))
        cr.move_to(x, y)
        cr.line_to(x, y - 34 * g)
        cr.stroke()
        for k in range(5):
            ang = k * 2 * math.pi / 5 + T * 0.5
            circle(cr, x + math.cos(ang) * 8 * g, y - 34 * g + math.sin(ang) * 8 * g, 6 * g, c)
        circle(cr, x, y - 34 * g, 4.5 * g, hexc("#f5a623"))


# ---------------------------------------------------------------------------
# Stations. Local x = 0 is the station centre; lt = time since camera arrival.
# ---------------------------------------------------------------------------

def st_creation(cr, lt, T):
    glow(cr, -560, 250, 420, (1, 0.92, 0.65), 0.7)
    circle(cr, -560, 250, 62, (1, 0.97, 0.82))
    for x, s, lc in ((-820, 1.0, "#2c6b36"), (-680, 0.75, "#23572f"), (600, 0.85, "#23572f"), (760, 1.1, "#2c6b36")):
        tree(cr, x, ground_y(x) + 8, s, 1, hexc("#3b2a1e"), hexc(lc), T)
    # tree of life (returns in the New Jerusalem)
    tree(cr, 360, ground_y(360) + 8, 1.55, 1, hexc("#4a3222"), hexc("#2f7a3a"), T, fruit=hexc("#f5b43a"))
    # a pool fed by the river of Eden
    cr.save()
    cr.translate(-330, G0 + 70)
    cr.scale(1, 0.22)
    circle(cr, 0, 0, 170, hexc("#4f9fd0"))
    cr.restore()
    # God's presence walking in the garden
    px, py = 60, G0 - 150
    pul = 1 + 0.06 * math.sin(T * 3)
    rays(cr, px, py, 12, 260 * pul, T * 0.2, (1, 0.97, 0.8), 0.35)
    glow(cr, px, py, 170 * pul, (1, 0.96, 0.8), 0.9)
    walk = clamp(lt + 1.3) * 26
    for i, (x0, c) in enumerate(((-210, "#6a4a3a"), (-140, "#7a5a44"))):
        figure(cr, x0 + walk, ground_y(x0) + 4, 1.9, hexc(c), bob=abs(math.sin(T * 5 + i)) * 3,
               head_tilt=1.2, arm=0.35 if i == 1 else None, arm2=0.35 if i == 0 else None)
    bloom_flowers(cr, lt, 3, -700, 700, -0.6, [hexc(h) for h in ("#ffffff", "#f7d24a", "#f28ab0", "#b58cf0")], T)
    for i in range(5):
        bx = -700 + ((T * 90 + i * 120) % 1600)
        bird(cr, bx, 300 + (i % 3) * 36 + math.sin(T * 2 + i) * 10, 0.9, T * 12 + i, (0.16, 0.13, 0.22))


def st_fall(cr, lt, T):
    tx = -330
    poly(cr, [(tx - 22, G0 + 8), (tx - 12, G0 - 240), (tx + 12, G0 - 240), (tx + 22, G0 + 8)], hexc("#2a1f24"))
    for dx, dy, r in ((0, -330, 150), (-130, -270, 110), (130, -270, 110), (-60, -410, 100), (80, -400, 100)):
        circle(cr, tx + dx, G0 + dy, r, hexc("#2c3a34"))
    for dx, dy in ((-100, -260), (60, -360), (130, -240), (-40, -420)):
        circle(cr, tx + dx, G0 + dy, 12, hexc("#b0302c"))
    # the serpent recoils when the promise flares (follow-through with decay)
    flare_t = lt - 0.95
    recoil = 0.0 if flare_t < 0 else 40 * math.exp(-flare_t * 3) * math.sin(flare_t * 10 + 1.2) + 26 * ease_out(flare_t * 2)
    pts = []
    for i in range(46):
        u = i / 45
        ang = u * 5.2 * math.pi
        x = tx + 36 * math.sin(ang) * (1 - u * 0.3)
        y = G0 - 60 - u * 150 + 0 * ang
        if i < 10:
            y -= (10 - i) * 7
            x += (10 - i) * 12 - recoil * (1 - i / 10)
        pts.append((x, y))
    serpent(cr, pts, hexc("#16331f"))
    # thorns and thistles
    cr.set_line_width(3)
    src(cr, hexc("#1a1418"))
    for bx in (-640, 520, 700):
        for k in range(14):
            ang = -math.pi / 2 + (k - 6.5) * 0.22
            L = 50 + (k % 3) * 18
            cr.move_to(bx, ground_y(bx) + 6)
            cr.line_to(bx + math.cos(ang) * L, ground_y(bx) + 6 + math.sin(ang) * L)
        cr.stroke()
    # Adam and Eve leave the garden, heads bowed
    leave = ease_in(prog(lt, -0.6, 3.4)) * 380
    for i, x0 in enumerate((120, 190)):
        x = x0 + leave
        figure(cr, x, ground_y(x) + 4, 1.9, hexc("#241c28"), bob=abs(math.sin(T * 7 + i)) * 3, head_tilt=-2.5)
    # the promise: gather, pull in (anticipation), flare
    fy = FOCUS_Y[1]
    r = 10 * ease_out(prog(lt, 0.1, 0.75)) * (1 - 0.6 * ease_in(prog(lt, 0.75, 0.95)))
    b = prog(lt, 0.95, 1.8)
    if lt < 0.95:
        glow(cr, 0, fy, r * 10, (1, 0.85, 0.7), 0.8)
        circle(cr, 0, fy, r, (1, 1, 0.95))
    else:
        rays(cr, 0, fy, 16, 120 + 700 * ease_out(b), T * 0.3, (1, 0.8, 0.7), 0.5 * (1 - b) + 0.15)
        glow(cr, 0, fy, 90 + 300 * ease_out(b) * (1 - b) + 40, (1, 0.75, 0.65), 0.9)
        circle(cr, 0, fy, 9 + 3 * math.sin(T * 5), (1, 0.98, 0.95))


def st_abraham(cr, lt, T):
    rnd = random.Random(22)
    for i in range(70):   # "look up at the sky and count the stars"
        x, y = rnd.uniform(-900, 900), rnd.uniform(120, 520)
        p = ease_out_back(prog(lt, -0.4 + i * 0.02, -0.1 + i * 0.02), 3)
        if p > 0:
            tw = 0.6 + 0.4 * math.sin(T * 3 + i)
            circle(cr, x, y, rnd.uniform(1.5, 3.2) * p, (1, 0.97, 0.88), tw)
            glow(cr, x, y, 16 * p, (0.8, 0.85, 1), 0.3 * tw)
    top = G0 - 70
    mound(cr, 0, 720, top, G0, hexc("#141425"))
    # beam from heaven stops Abraham's hand
    bm = prog(lt, 0.1, 0.6) * (1 - 0.5 * prog(lt, 2.0, 3.0))
    if bm > 0:
        g = cairo.LinearGradient(0, 0, 0, top)
        g.add_color_stop_rgba(0, 1, 0.95, 0.8, 0)
        g.add_color_stop_rgba(1, 1, 0.95, 0.8, 0.45 * bm)
        poly(cr, [(-330, -50), (-250, -50), (-200, top), (-470, top)], (1, 1, 1), 0)
        cr.move_to(-320, -50)
        cr.line_to(-250, -50)
        cr.line_to(-180, top)
        cr.line_to(-470, top)
        cr.close_path()
        cr.set_source(g)
        cr.fill()
    # altar of stones with wood
    for row in range(3):
        for k in range(4 - row):
            x = -300 + k * 42 + row * 21
            y = top + 8 - row * 26
            poly(cr, [(x - 19, y), (x + 19, y), (x + 17, y - 24), (x - 17, y - 24)], hexc("#3a3a4a"))
    cr.set_line_width(7)
    src(cr, hexc("#5a3a22"))
    for k in range(4):
        cr.move_to(-310 + k * 8, top - 72 - k * 5)
        cr.line_to(-180 + k * 8, top - 80 - k * 5)
    cr.stroke()
    arm = lerp(2.9, 0.5, ease_out_back(prog(lt, 0.3, 1.0), 1.6))
    figure(cr, -420, top + 20, 2.0, hexc("#0a0a14"), arm=arm, arm2=0.3, head_tilt=-1.5 if lt > 0.2 else 0)
    figure(cr, -160, top + 8, 1.5, hexc("#0a0a14"), kneel=True, head_tilt=1)
    # the ram caught in the thicket (shaking settles with damped oscillation)
    sh = math.sin(lt * 26) * 6 * math.exp(-max(0.0, lt) * 1.6) if lt > 0 else 0
    fy = FOCUS_Y[2]
    for dx, dy, r in ((-60, 18, 46), (0, -6, 56), (60, 16, 48), (-30, -40, 40), (40, -38, 40)):
        circle(cr, dx + sh * 0.6, fy + dy + 20, r, hexc("#12301e"))
    lamb(cr, sh - 10, fy + 16, 1.3, hexc("#0a0a12"), horns=True)


def st_passover(cr, lt, T):
    # pyramids and moon
    glow(cr, 520, 200, 160, (0.9, 0.9, 1), 0.4)
    circle(cr, 520, 200, 38, (0.95, 0.95, 0.9))
    for px, pw in ((-700, 260), (-440, 180)):
        poly(cr, [(px - pw, G0 - 40), (px, G0 - 40 - pw * 0.9), (px + pw, G0 - 40)], hexc("#1c1830"))
    fy = FOCUS_Y[3]
    dtop = fy + 16
    poly(cr, [(-280, G0 + 8), (-280, fy - 120), (280, fy - 120), (280, G0 + 8)], hexc("#3b2c2a"))
    poly(cr, [(-300, fy - 120), (300, fy - 120), (300, fy - 140), (-300, fy - 140)], hexc("#2a1f1e"))
    poly(cr, [(-62, G0 + 8), (-62, dtop), (62, dtop), (62, G0 + 8)], hexc("#1a0f0c"))
    glow(cr, 0, G0 - 80, 140, (1, 0.7, 0.35), 0.55 + 0.1 * math.sin(T * 8))
    poly(cr, [(-56, G0 + 8), (-56, dtop + 8), (56, dtop + 8), (56, G0 + 8)], (1, 0.72, 0.38), 0.35)
    poly(cr, [(-170, fy - 60), (-120, fy - 60), (-120, fy - 10), (-170, fy - 10)], (1, 0.75, 0.4), 0.7)
    poly(cr, [(120, fy - 60), (170, fy - 60), (170, fy - 10), (120, fy - 10)], (1, 0.75, 0.4), 0.7)
    # blood painted on the lintel and both doorposts (brush wipe)
    blood = hexc("#b0121f")
    pl = ease_in_out(prog(lt, -0.3, 0.3))
    if pl > 0:
        poly(cr, [(-80, fy - 8), (-80 + 160 * pl, fy - 8), (-80 + 160 * pl, fy + 12), (-80, fy + 12)], blood)
    for side, t0 in ((-1, 0.3), (1, 0.6)):
        p = ease_in_out(prog(lt, t0, t0 + 0.5))
        if p > 0:
            x = side * 72
            poly(cr, [(x - 9, dtop), (x + 9, dtop), (x + 9, dtop + (G0 - dtop) * p), (x - 9, dtop + (G0 - dtop) * p)], blood)
    lamb(cr, 200, G0 - 20, 1.1, hexc("#e8e0d0"))
    # the destroyer: a dark wind that passes OVER the marked house
    p = prog(lt, 1.1, 2.8)
    if 0 < p < 1:
        rnd = random.Random(33)
        for i in range(40):
            x = lerp(1100, -1100, p) + rnd.uniform(-300, 300)
            base_y = rnd.uniform(G0 - 380, G0 - 60)
            lift = max(0.0, 1 - abs(x) / 340) * 260           # rises over the door
            y = base_y - lift - (G0 - 380 - fy + 160) * 0 + math.sin(T * 4 + i) * 12
            circle(cr, x, min(y, fy - 150 if abs(x) < 300 else y), rnd.uniform(30, 70), (0.02, 0.01, 0.04), 0.22 * math.sin(p * math.pi))


def st_tabernacle(cr, lt, T):
    # pillar of cloud over the tent
    for i in range(10):
        y = G0 - 260 - i * 55 - (T * 12) % 55
        circle(cr, math.sin(T + i) * 10, y, 55 + i * 3, (1, 1, 1), 0.55 - i * 0.04)
    fy = FOCUS_Y[4]
    # tent of meeting
    poly(cr, [(-190, G0), (-190, G0 - 230), (190, G0 - 230), (190, G0)], hexc("#6a3a2a"))
    poly(cr, [(-210, G0 - 230), (0, G0 - 290), (210, G0 - 230)], hexc("#4a2a22"))
    # entrance curtain: blue, purple and scarlet (Exodus 26:36)
    for k, c in enumerate(("#2c4f9a", "#6a3a8a", "#b0172a", "#2c4f9a")):
        poly(cr, [(-56 + k * 28, G0), (-56 + k * 28, fy - 50), (-28 + k * 28, fy - 50), (-28 + k * 28, G0)], hexc(c))
    gl = ease_out(prog(lt, 0.6, 1.8))
    glow(cr, 0, fy, 90 + 160 * gl, (1, 0.93, 0.7), 0.3 + 0.6 * gl)
    # courtyard linen fence
    poly(cr, [(-620, G0 + 20), (-620, G0 - 70), (-260, G0 - 70), (-260, G0 + 20)], hexc("#f2ece0"))
    poly(cr, [(260, G0 + 20), (260, G0 - 70), (620, G0 - 70), (620, G0 + 20)], hexc("#f2ece0"))
    cr.set_line_width(4)
    src(cr, hexc("#a08050"))
    for x in list(range(-620, -250, 60)) + list(range(260, 630, 60)):
        cr.move_to(x, G0 + 20)
        cr.line_to(x, G0 - 78)
    cr.stroke()
    # altar of burnt offering: fire and rising smoke
    ax = -420
    poly(cr, [(ax - 60, G0 + 10), (ax - 60, G0 - 70), (ax + 60, G0 - 70), (ax + 60, G0 + 10)], hexc("#8a5a2a"))
    for i in range(5):
        flame(cr, ax - 40 + i * 20, G0 - 68, 1.3, T, i)
    for i in range(8):
        u = ((T * 0.35 + i / 8) % 1)
        circle(cr, ax + math.sin(u * 6 + i) * 30 * u, G0 - 110 - u * 380, 20 + u * 50, (0.85, 0.82, 0.8), 0.35 * (1 - u))
    # the high priest carries the blood toward the Most Holy Place
    w = ease_in_out(prog(lt, -0.5, 2.2))
    px = lerp(-300, -110, w)
    figure(cr, px, G0 + 6, 2.0, hexc("#2d4a8a"), bob=abs(math.sin(T * 7)) * 3 * (1 if 0 < w < 1 else 0), arm=1.4)
    circle(cr, px + 36, G0 - 118, 9, hexc("#d4a73a"))


def st_david(cr, lt, T):
    rnd = random.Random(55)
    x = -900
    while x < 900:   # Jerusalem walls
        w = rnd.uniform(70, 140)
        h = rnd.uniform(110, 230)
        if abs(x + w / 2) > 180:
            poly(cr, [(x, G0 - 30), (x, G0 - 30 - h), (x + w, G0 - 30 - h), (x + w, G0 - 30)], hexc("#b99a6a"))
            for k in range(int(w // 22)):
                poly(cr, [(x + k * 22, G0 - 30 - h), (x + k * 22 + 12, G0 - 30 - h), (x + k * 22 + 12, G0 - 42 - h), (x + k * 22, G0 - 42 - h)], hexc("#b99a6a"))
        x += w + rnd.uniform(0, 30)
    fy = FOCUS_Y[5]
    rays(cr, 0, fy, 14, 700, T * 0.15, (1, 0.9, 0.6), 0.25)
    # throne
    poly(cr, [(-80, G0 + 6), (-80, G0 - 90), (80, G0 - 90), (80, G0 + 6)], hexc("#c8962e"))
    poly(cr, [(-70, G0 - 90), (-70, G0 - 250), (70, G0 - 250), (70, G0 - 90)], hexc("#e0b54a"))
    cr.arc(0, G0 - 250, 70, math.pi, 0)
    src(cr, hexc("#e0b54a"))
    cr.fill()
    poly(cr, [(-50, G0 - 110), (-50, G0 - 230), (50, G0 - 230), (50, G0 - 110)], hexc("#8a1f2a"))
    # the crown drops onto the thread: gravity, squash on impact, settle
    p = prog(lt, -0.1, 1.1)
    cy = lerp(-150, fy, ease_out_bounce(p))
    prox = max(0.0, 1 - abs(fy - cy) / 24) * (1 - p * 0.6)
    glow(cr, 0, cy, 240, (1, 0.9, 0.6), 0.5 * p)
    crown(cr, 0, cy + 10, 0.9, math.sin(T * 2) * 0.03 * (1 - p), 0.2 * prox)
    # David with his harp; sheep grazing
    dx = -330
    figure(cr, dx, ground_y(dx) + 4, 2.0, hexc("#4a2a5a"), arm=1.2, head_tilt=1)
    cr.set_line_width(4)
    src(cr, hexc("#c8962e"))
    cr.move_to(dx + 30, G0 - 120)
    cr.curve_to(dx + 70, G0 - 170, dx + 60, G0 - 60, dx + 30, G0 - 60)
    cr.close_path()
    cr.stroke()
    for i, sx in enumerate((300, 400, 520)):
        lamb(cr, sx, G0 + 10 + i * 8, 0.85, hexc("#f2ece0"))


def st_prophets(cr, lt, T):
    # a faint cross already stands on the horizon ahead
    ca = 0.2 * ease_out(prog(lt, 1.0, 2.2))
    if ca > 0:
        poly(cr, [(566, 180), (574, 180), (574, 330), (566, 330)], (1, 0.9, 0.8), ca)
        poly(cr, [(530, 220), (610, 220), (610, 228), (530, 228)], (1, 0.9, 0.8), ca)
    poly(cr, [(-620, G0 + 10), (-560, G0 - 110), (-420, G0 - 140), (-330, G0 - 90), (-280, G0 + 10)], hexc("#2a1a22"))
    figure(cr, -450, G0 - 136, 2.0, hexc("#1a1018"), arm=lerp(0.3, 2.5, ease_out_back(prog(lt, -0.2, 0.6), 2)), arm2=0.4)
    fy = FOCUS_Y[6]
    op = ease_in_out(prog(lt, -0.2, 1.0))
    half = lerp(24, 300, op)
    glow(cr, 0, fy, 420, (1, 0.85, 0.6), 0.35 * op)
    poly(cr, [(-half, fy - 140), (half, fy - 140), (half, fy + 140), (-half, fy + 140)], hexc("#efe1bf"))
    cr.set_line_width(3)
    src(cr, hexc("#5a3a2a"), 0.75)
    for i in range(9):   # lines write themselves in
        lp = prog(lt, 0.7 + i * 0.12, 1.1 + i * 0.12)
        if lp > 0 and half > 60:
            y = fy - 110 + i * 26
            if abs(y - fy) < 12:
                continue
            x0 = -half + 34
            x1 = lerp(x0, half - 34 - (i % 3) * 40, lp)
            cr.move_to(x0, y)
            cr.line_to(x1, y)
    cr.stroke()
    for side in (-1, 1):
        x = side * half
        poly(cr, [(x - 16, fy - 160), (x + 16, fy - 160), (x + 16, fy + 160), (x - 16, fy + 160)], hexc("#7a4a2a"))
        circle(cr, x, fy - 164, 12, hexc("#5a3420"))
        circle(cr, x, fy + 164, 12, hexc("#5a3420"))


def st_incarnation(cr, lt, T):
    sx, sy = 0, 190
    arr = ease_out(prog(lt, -0.3, 0.6))
    g = cairo.LinearGradient(0, sy, 0, G0)
    g.add_color_stop_rgba(0, 1, 0.95, 0.8, 0.35 * arr)
    g.add_color_stop_rgba(1, 1, 0.95, 0.8, 0.0)
    cr.move_to(sx - 6, sy)
    cr.line_to(sx + 6, sy)
    cr.line_to(220, G0)
    cr.line_to(-220, G0)
    cr.close_path()
    cr.set_source(g)
    cr.fill()
    pulse = 1 + 0.1 * math.sin(T * 5)
    rays(cr, sx, sy, 8, 190 * pulse, T * 0.2, (1, 0.95, 0.8), 0.6)
    glow(cr, sx, sy, 110 * pulse, (1, 0.95, 0.8), 0.8)
    circle(cr, sx, sy, 9, (1, 1, 0.95))
    rnd = random.Random(77)
    for side in (-1, 1):   # Bethlehem
        x = 320 * side
        for _ in range(4):
            w, h = rnd.uniform(90, 150), rnd.uniform(70, 150)
            x0 = x if side > 0 else x - w
            poly(cr, [(x0, G0), (x0, G0 - h), (x0 + w, G0 - h), (x0 + w, G0)], hexc("#0b0c20"))
            wx = x0 + w / 2 - 6
            poly(cr, [(wx, G0 - h + 30), (wx + 12, G0 - h + 30), (wx + 12, G0 - h + 46), (wx, G0 - h + 46)], (1, 0.75, 0.35),
                 0.6 + 0.3 * math.sin(T * 6 + x0))
            x += side * (w + 10)
    poly(cr, [(-220, G0 + 6), (-220, G0 - 170), (0, G0 - 250), (220, G0 - 170), (220, G0 + 6)], hexc("#2a1c22"))
    poly(cr, [(-180, G0 + 6), (-180, G0 - 150), (180, G0 - 150), (180, G0 + 6)], hexc("#140e16"))
    glow(cr, 0, G0 - 40, 200 * (1 + 0.05 * math.sin(T * 4)), (1, 0.8, 0.45), 0.8)
    poly(cr, [(-48, G0 + 6), (-38, G0 - 30), (38, G0 - 30), (48, G0 + 6)], hexc("#3a2418"))
    circle(cr, 0, FOCUS_Y[7], 15, (1, 0.94, 0.8))
    figure(cr, -105, G0 + 6, 1.7, hexc("#1b3a6a"), kneel=True, head_tilt=1.5, arm=1.2)
    figure(cr, 115, G0 + 6, 1.9, hexc("#3a2616"), head_tilt=-1.2, arm2=0.5)
    # shepherds arrive
    for i in range(2):
        w = ease_out(prog(lt, 0.2 + i * 0.3, 2.6 + i * 0.3))
        x = lerp(760 + i * 90, 300 + i * 80, w)
        figure(cr, x, ground_y(x) + 30, 1.7, hexc("#0d0d1a"), bob=abs(math.sin(T * 7 + i)) * 3 * (1 - w),
               arm=2.4, staff=True, head_tilt=-1)
    lamb(cr, 250, G0 + 40, 0.8, hexc("#d8d0c4"))


def st_cross(cr, lt, T):
    col = hexc("#0a0406")
    mound(cr, 0, 760, G0 - 120, G0, col)
    fy = FOCUS_Y[8]
    top = fy - 90
    base = G0 - 116
    poly(cr, [(-15, base), (-15, top), (15, top), (15, base)], col)
    poly(cr, [(-135, fy - 14), (135, fy - 14), (135, fy + 14), (-135, fy + 14)], col)
    fl = prog(lt, 0.0, 1.2)
    if fl > 0:
        rays(cr, 0, fy, 18, 1400 * ease_out(fl), T * 0.12, (1, 0.35, 0.3), 0.25)
        glow(cr, 0, fy, 120 + 380 * ease_out(fl), (1, 0.4, 0.35), 0.35 + 0.35 * (1 - fl))
    # temple veil torn in two from top to bottom
    vx0, vx1, vt, vb = 420, 700, 300, G0 - 40
    tear = ease_in(prog(lt, 0.9, 1.6))
    gap = ease_out(prog(lt, 1.4, 2.6)) * 60
    ty = lerp(vt, vb, tear)
    mid = (vx0 + vx1) / 2
    cloth = hexc("#7a1422")
    poly(cr, [(vx0 - 20, vt - 20), (vx1 + 20, vt - 20), (vx1 + 20, vt - 6), (vx0 - 20, vt - 6)], hexc("#c8962e"))
    for side in (-1, 1):
        pts = [(mid if side < 0 else mid, vt)]
        edge = []
        for i in range(13):
            y = lerp(vt, vb, i / 12)
            jag = (7 if i % 2 else -7) if y < ty else 0
            open_ = gap * (1 - (y - vt) / (vb - vt) * 0.3) if y < ty else gap * 0.0
            edge.append((mid + side * (open_ / 2 + 1) + jag, y))
        outer = vx0 if side < 0 else vx1
        pts = [(outer - side * gap * 0.15, vt)] + edge + [(outer, vb)]
        poly(cr, pts, cloth)
    if tear > 0:
        g = cairo.LinearGradient(0, vt, 0, ty)
        g.add_color_stop_rgba(0, 1, 0.95, 0.8, 0.9)
        g.add_color_stop_rgba(1, 1, 0.95, 0.8, 0.2)
        poly(cr, [(mid - gap / 2, vt), (mid + gap / 2, vt), (mid, ty)], (1, 1, 1), 0)
        cr.move_to(mid - gap / 2 - 2, vt)
        cr.line_to(mid + gap / 2 + 2, vt)
        cr.line_to(mid + 2, ty)
        cr.line_to(mid - 2, ty)
        cr.close_path()
        cr.set_source(g)
        cr.fill()
        glow(cr, mid, (vt + ty) / 2, 150 * tear, (1, 0.9, 0.7), 0.5 * tear)


def st_resurrection(cr, lt, T):
    sp = ease_out(prog(lt, -0.4, 3.0))
    glow(cr, -620, lerp(700, 320, sp), 420, (1, 0.85, 0.55), 0.8)
    circle(cr, -620, lerp(700, 320, sp), 60, (1, 0.95, 0.75))
    fy = FOCUS_Y[9]
    orr = 105
    cr.move_to(-330, G0 + 20)
    cr.curve_to(-300, G0 - 380, 330, G0 - 390, 360, G0 + 20)
    cr.close_path()
    src(cr, hexc("#b3a58f"))
    cr.fill()
    circle(cr, 0, fy, orr, hexc("#1a1612"))
    L = ease_out(prog(lt, 0.9, 1.8))
    if L > 0:
        cr.save()
        cr.arc(0, fy, orr, 0, 2 * math.pi)
        cr.clip()
        cr.rectangle(-200, fy - 200, 400, 400)
        src(cr, (1, 0.97, 0.85), L)
        cr.fill()
        cr.restore()
        rays(cr, 0, fy, 20, 1200 * L, T * 0.25, (1, 0.96, 0.8), 0.3 * L)
        glow(cr, 0, fy, 330 * L, (1, 0.97, 0.85), 0.8 * L)
    tremble = math.sin(T * 55) * 3.5 * prog(lt, -0.4, 0.2) * (1 - prog(lt, 0.25, 0.3))
    back = -30 * ease_in_out(prog(lt, 0.25, 0.6))
    roll = 330 * ease_in_out(prog(lt, 0.6, 1.7))
    sr = orr + 14
    cr.save()
    cr.translate(tremble + back + roll, fy)
    cr.rotate((back + roll) / sr)
    circle(cr, 0, 0, sr, hexc("#8c7f6c"))
    cr.set_line_width(5)
    src(cr, hexc("#6a604f"))
    cr.arc(0, 0, sr * 0.62, 0, 2 * math.pi)
    cr.stroke()
    cr.move_to(-sr * 0.6, 0)
    cr.line_to(sr * 0.6, 0)
    cr.stroke()
    cr.restore()
    # the serpent's head is crushed (Genesis 3:15 fulfilled)
    pts = [(-560 + i * 12, G0 + 40 + math.sin(i * 0.7) * 8) for i in range(24)]
    serpent(cr, pts, hexc("#1e2a1c"), head_squash=1.0)
    # broken chains fall away (gravity + bounce + spin)
    for i in range(6):
        p = prog(lt, 1.0 + i * 0.05, 1.9 + i * 0.05)
        x = 470 + i * 34 + p * (i - 2.5) * 30
        y = lerp(G0 - 160 + i * 6, G0 + 30 + (i % 2) * 10, ease_out_bounce(p))
        cr.save()
        cr.translate(x, y)
        cr.rotate(i * 0.6 + p * (i - 3) * 1.2)
        cr.set_line_width(7)
        src(cr, hexc("#5a5a66"))
        cr.save()
        cr.scale(1.6, 1)
        cr.arc(0, 0, 11, 0, 2 * math.pi)
        cr.restore()
        cr.stroke()
        cr.restore()
    bloom_flowers(cr, lt, 9, -700, 700, 1.4, [hexc(h) for h in ("#ffffff", "#f7d24a", "#f28ab0", "#b58cf0")], T)


def nation_people():
    rnd = random.Random(90)
    robes = ["#8a3b2e", "#3b5a8a", "#6a5a2e", "#5a3a6a", "#2e6a5a", "#a0663a", "#2e3a6a", "#7a2e5a"]
    ppl = []
    for i in range(22):
        ang = math.pi * (0.08 + 0.84 * i / 21)
        x = -math.cos(ang) * 720 + rnd.uniform(-20, 20)
        depth = math.sin(ang)
        y = G0 + 60 - depth * 70 + rnd.uniform(-8, 8)
        s = 1.9 - depth * 0.45
        ppl.append((x, y, s, hexc(rnd.choice(robes)), i))
    return sorted(ppl, key=lambda p: p[1])


PEOPLE = nation_people()


def st_nations(cr, lt, T):
    fy = FOCUS_Y[10]
    glow(cr, 0, fy, 300, (1, 0.9, 0.7), 0.6)
    # the thread divides into strands, one to each person
    for x, y, s, c, i in PEOPLE:
        p = ease_in_out(prog(lt, 0.2 + (i % 11) * 0.05, 1.3 + (i % 11) * 0.05))
        if p <= 0:
            continue
        hx, hy = x, y - 82 * s - 44
        qx, qy = x * 0.5, fy - 120
        cr.move_to(0, fy)
        for k in range(1, 25):
            u = p * k / 24
            bx = (1 - u) ** 2 * 0 + 2 * (1 - u) * u * qx + u * u * hx
            by = (1 - u) ** 2 * fy + 2 * (1 - u) * u * qy + u * u * hy
            cr.line_to(bx, by)
        cr.set_line_width(2.5)
        src(cr, SCARLET, 0.85)
        cr.stroke()
    for x, y, s, c, i in PEOPLE:
        fp = ease_out_back(prog(lt, 1.1 + (i % 11) * 0.05, 1.5 + (i % 11) * 0.05), 3)
        arm = lerp(0.3, 2.5, ease_out_back(prog(lt, 1.6 + (i % 7) * 0.08, 2.1 + (i % 7) * 0.08), 2)) if i % 3 == 0 else None
        figure(cr, x, y, s, c, arm=arm, head_tilt=(1 if x < 0 else -1) * 1.2)
        if fp > 0:
            flame(cr, x, y - 82 * s - 16, 0.8 * fp, T, i)


def st_new(cr, lt, T):
    rays(cr, 0, 430, 24, 1500, T * 0.1, (1, 1, 0.9), 0.35)
    glow(cr, 0, 430, 700, (1, 0.97, 0.85), 0.8)
    wall_y = G0 - 80
    rnd = random.Random(16)
    for i in range(15):
        x = -700 + i * 100
        if abs(x) < 120:
            continue
        h = 120 + rnd.uniform(0, 200)
        poly(cr, [(x - 38, wall_y), (x - 38, wall_y - h), (x + 38, wall_y - h), (x + 38, wall_y)], hexc("#fff3c8") if i % 2 else hexc("#f2cf72"))
        poly(cr, [(x - 44, wall_y - h), (x, wall_y - h - 46), (x + 44, wall_y - h)], hexc("#f2cf72"))
    poly(cr, [(-760, wall_y + 2), (-760, wall_y - 90), (760, wall_y - 90), (760, wall_y + 2)], hexc("#f2cf72"))
    for gx in (-520, -260, 260, 520):
        cr.arc(gx, wall_y - 34, 30, math.pi, 0)
        cr.line_to(gx + 30, wall_y + 2)
        cr.line_to(gx - 30, wall_y + 2)
        cr.close_path()
        src(cr, (1, 1, 0.95))
        cr.fill()
    fy = FOCUS_Y[11]
    # throne with an emerald rainbow drawn around it (Revelation 4:3)
    rp = ease_in_out(prog(lt, 0.3, 1.4))
    if rp > 0:
        cr.set_line_width(14)
        cr.arc(0, fy + 20, 190, -math.pi / 2, -math.pi / 2 + 2 * math.pi * rp)
        src(cr, hexc("#3fbf7a"), 0.7)
        cr.stroke()
    poly(cr, [(-90, wall_y + 2), (-90, fy + 100), (90, fy + 100), (90, wall_y + 2)], hexc("#fff8e0"))
    poly(cr, [(-120, fy + 100), (120, fy + 100), (120, fy + 80), (-120, fy + 80)], hexc("#f2cf72"))
    lamb(cr, -18, fy + 40, 1.4, (1, 1, 1), glow_c=(1, 0.97, 0.8))
    # river of life with flowing highlights
    poly(cr, [(-40, wall_y), (40, wall_y), (330, H + 300), (-330, H + 300)], hexc("#7fd0f0"))
    cr.set_line_width(3)
    for k in range(12):
        u = (T * 0.4 + k / 12) % 1
        y = lerp(wall_y, H + 150, u)
        hw = lerp(40, 280, u)
        off = math.sin(k * 2.3) * hw * 0.5
        cr.move_to(off - 20 - u * 30, y)
        cr.line_to(off + 20 + u * 30, y)
        src(cr, (1, 1, 1), 0.7)
        cr.stroke()
    for x, s in ((-470, 1.4), (470, 1.4)):   # the tree of life, on both banks
        tree(cr, x, ground_y(x) + 60, s, 1, hexc("#4a3222"), hexc("#2f8a3e"), T, fruit=hexc("#f5b43a"))
    # a great multitude with raised hands
    rnd = random.Random(8)
    robes = ["#f5f0e6", "#e8e0d0", "#fdf8ee"]
    for i in range(16):
        x = rnd.choice((-1, 1)) * rnd.uniform(560, 900)
        y = G0 + rnd.uniform(40, 120)
        wave = 2.3 + 0.25 * math.sin(T * 3 + i)
        figure(cr, x, y, 1.6, hexc(rnd.choice(robes)), arm=wave, arm2=wave if i % 2 else None, head_tilt=1 if x < 0 else -1)
    # the thread arrives: rings of light bloom from the throne
    for k in range(4):
        rp2 = ((lt - 0.2) * 0.45 + k / 4)
        if lt > 0.2:
            rp2 %= 1
            cr.set_line_width(4)
            cr.arc(0, fy, 40 + rp2 * 600, 0, 2 * math.pi)
            src(cr, mix(SCARLET, GOLD, rp2), 0.5 * (1 - rp2))
            cr.stroke()


STATIONS = [st_creation, st_fall, st_abraham, st_passover, st_tabernacle, st_david, st_prophets,
            st_incarnation, st_cross, st_resurrection, st_nations, st_new]


# ---------------------------------------------------------------------------
# Thread: Catmull-Rom spline through every focal point, arcing up between them
# ---------------------------------------------------------------------------

def build_thread():
    ctrl = []
    for k in range(1, N):
        ctrl.append((k * SPACING, FOCUS_Y[k]))
        if k + 1 < N:
            ctrl.append(((k + 0.5) * SPACING, max(210, min(FOCUS_Y[k], FOCUS_Y[k + 1]) - 190)))
    p = [ctrl[0]] + ctrl + [ctrl[-1]]
    pts = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = (np.array(v, float) for v in p[i - 1:i + 3])
        for s in np.linspace(0, 1, 60, endpoint=False):
            s2, s3 = s * s, s * s * s
            pts.append(0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s2 + (-p0 + 3 * p1 - 3 * p2 + p3) * s3))
    pts.append(np.array(ctrl[-1], float))
    return np.array(pts)


THREAD = build_thread()
THREAD_START = ARRIVE[1] + 0.95


def draw_thread(cr, T, cx, z):
    if T < THREAD_START:
        return
    tipx = clamp(cx if T < T_PULL else X_LAST, SPACING, X_LAST)
    # during the pull-back the whole thread is already drawn
    idx = int(np.searchsorted(THREAD[:, 0], tipx))
    pts = THREAD[:max(1, idx)]
    if idx < len(THREAD) and idx > 0:
        a, b = THREAD[idx - 1], THREAD[idx]
        u = (tipx - a[0]) / max(1e-6, b[0] - a[0])
        pts = np.vstack([pts, a + (b - a) * u])
    grow = ease_out(prog(T, THREAD_START, THREAD_START + 0.4))
    ws = 1 / z                               # keep a constant on-screen width
    if len(pts) > 1:
        for width, colr, alpha in ((22, SCARLET, 0.18), (10, SCARLET, 0.35), (5, SCARLET, 1.0)):
            cr.move_to(*pts[0])
            for p in pts[1:]:
                cr.line_to(*p)
            cr.set_line_width(width * ws * grow)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            src(cr, colr, alpha)
            cr.stroke()
        # a highlight flows along the thread
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.set_dash([40 * ws, 260 * ws], -T * 420 * ws)
        cr.set_line_width(2.2 * ws)
        src(cr, SCARLET_HI, 0.9)
        cr.stroke()
        cr.set_dash([])
    tx, ty = pts[-1]
    glow(cr, tx, ty, 40 * ws, (1, 0.45, 0.4), 0.9)
    circle(cr, tx, ty, 6 * ws, (1, 0.9, 0.88))
    # a ring "stitch" pulses outward each time the thread reaches a focal point
    for k in range(2, N):
        lt = T - ARRIVE[k]
        if 0 <= lt < 0.9:
            cr.set_line_width(4 * ws)
            cr.arc(k * SPACING, FOCUS_Y[k], (30 + 170 * ease_out(lt / 0.9)), 0, 2 * math.pi)
            src(cr, (1, 0.8, 0.75), 0.8 * (1 - lt / 0.9))
            cr.stroke()
    # during the pull-back every station becomes a bead on the thread
    if T > T_PULL:
        b = ease_out(prog(T, T_PULL + 0.6, T_PULL_END))
        for k in range(1, N):
            glow(cr, k * SPACING, FOCUS_Y[k], 26 * ws * b, (1, 0.8, 0.6), 0.9 * b)
            circle(cr, k * SPACING, FOCUS_Y[k], 5 * ws * b, (1, 0.97, 0.9), b)


# ---------------------------------------------------------------------------
# Frame composition
# ---------------------------------------------------------------------------

def parallax_layer(cr, cx, z, f, base, amp, pal, f1, f2):
    """A ridge that scrolls at factor f of the camera (depth cue)."""
    shift = cx * (1 - f)
    half = W / 2 / z + 200
    x0, x1 = cx - half, cx + half
    step = max(16.0, (x1 - x0) / 240)
    cr.move_to(x0, H + 600)
    x = x0
    while x <= x1 + step:
        lx = x - shift
        cr.line_to(x, base + amp * (0.6 * math.sin(lx * f1) + 0.4 * math.sin(lx * f2 + 1.3)))
        x += step
    cr.line_to(x1 + step, H + 600)
    cr.close_path()
    cr.set_source(hgrad(pal))
    cr.fill()


def draw_world(cr, T):
    cx, z, sx, sy = camera_state(T)
    cr.rectangle(0, 0, W, H)
    src(cr, hexc("#07060b"))
    cr.fill()
    half = W / 2 / z + 200
    # sky: horizontal palette for the top, blended to the horizon palette by a vertical mask
    cr.save()
    apply_camera(cr, cx, z, sx, sy)
    cr.rectangle(cx - half, -300, 2 * half, H + 900)
    cr.set_source(hgrad(SKY_TOP))
    cr.fill_preserve()
    cr.set_source(hgrad(SKY_BOT))
    cr.save()
    cr.clip()
    mask = cairo.LinearGradient(0, -100, 0, GY)
    mask.add_color_stop_rgba(0, 0, 0, 0, 0)
    mask.add_color_stop_rgba(1, 0, 0, 0, 1)
    cr.mask(mask)
    cr.restore()
    cr.new_path()
    cr.restore()
    # stars in screen space, visible only where the sky above is dark
    fade = clamp((z - 0.4) / 0.6)
    if fade > 0:
        rnd = random.Random(1)
        for i in range(260):
            px = (rnd.uniform(0, W * 3) - cx * 0.04) % (W + 40) - 20
            py = rnd.uniform(0, H * 0.62)
            wx = cx + (px - W / 2) / z
            top = palette_at(SKY_TOP, wx)
            dark = clamp(1 - (0.3 * top[0] + 0.5 * top[1] + 0.2 * top[2]) * 4.5)
            if dark <= 0.02:
                continue
            tw = 0.55 + 0.45 * math.sin(T * rnd.uniform(1.5, 4) + i)
            circle(cr, px, py, rnd.choice((0.8, 1.1, 1.4, 1.9)), (1, 0.97, 0.9), dark * tw * fade)
    cr.save()
    apply_camera(cr, cx, z, sx, sy)
    parallax_layer(cr, cx, z, 0.35, 640, 70, FAR, 0.0021, 0.0057)
    parallax_layer(cr, cx, z, 0.65, 745, 40, MID, 0.0032, 0.0081)
    # ground
    x0, x1 = cx - half, cx + half
    step = max(16.0, (x1 - x0) / 300)
    cr.move_to(x0, H + 600)
    x = x0
    while x <= x1 + step:
        cr.line_to(x, ground_y(x))
        x += step
    cr.line_to(x1 + step, H + 600)
    cr.close_path()
    cr.set_source(hgrad(GROUND))
    cr.fill()
    for k, fn in enumerate(STATIONS):
        X = k * SPACING
        if abs(X - cx) > half + SPACING * 0.5:
            continue
        cr.save()
        cr.translate(X, 0)
        fn(cr, T - ARRIVE[k], T)
        cr.restore()
    draw_thread(cr, T, cx, z)
    cr.restore()
    return cx, z


def caption(cr, T):
    for k, (ref, title, quote) in enumerate(CAPTIONS):
        lt = T - ARRIVE[k]
        a = ease_out(prog(lt, -0.25, 0.45)) * (1 - ease_in_out(prog(lt, HOLD - 0.35, HOLD + 0.1)))
        if a <= 0:
            continue
        g = cairo.LinearGradient(0, H - 360, 0, H)
        g.add_color_stop_rgba(0, 0, 0, 0, 0)
        g.add_color_stop_rgba(1, 0, 0, 0, 0.62 * a)
        cr.rectangle(0, H - 360, W, 360)
        cr.set_source(g)
        cr.fill()
        dy = (1 - ease_out(prog(lt, -0.25, 0.45))) * 30
        x = 120
        # eyebrow with a scarlet tick that draws in
        tick = ease_out(prog(lt, -0.1, 0.5))
        cr.set_line_width(4)
        src(cr, SCARLET, a)
        cr.move_to(x, H - 196 + dy)
        cr.line_to(x + 60 * tick, H - 196 + dy)
        cr.stroke()
        set_font(cr, DISPLAY_FONT, 22, bold=True)
        src(cr, GOLD, a)
        xx = x + 78
        for ch in ref:
            cr.move_to(xx, H - 188 + dy)
            cr.show_text(ch)
            xx += cr.text_extents(ch).x_advance + 2.5
        set_font(cr, DISPLAY_FONT, 62, bold=True)
        src(cr, CREAM, a)
        cr.move_to(x, H - 118 + dy * 1.2)
        cr.show_text(title)
        a2 = a * ease_out(prog(lt, 0.15, 0.8))
        set_font(cr, BODY_FONT, 38, italic=True)
        src(cr, CREAM, a2 * 0.92)
        cr.move_to(x, H - 62 + dy * 1.5)
        cr.show_text(quote)


def progress_bar(cr, T, cx):
    a = ease_out(prog(T, T_TITLE, T_TITLE + 0.8)) * (1 - ease_in_out(prog(T, T_PULL, T_PULL + 0.6)))
    if a <= 0:
        return
    x0, x1, y = 330, W - 330, 58
    g = cairo.LinearGradient(0, 0, 0, 130)
    g.add_color_stop_rgba(0, 0, 0, 0, 0.4 * a)
    g.add_color_stop_rgba(1, 0, 0, 0, 0)
    cr.rectangle(0, 0, W, 130)
    cr.set_source(g)
    cr.fill()
    set_font(cr, DISPLAY_FONT, 22, bold=True)
    src(cr, CREAM, 0.85 * a)
    w = cr.text_extents("GENESIS").x_advance
    cr.move_to(x0 - w - 28, y + 8)
    cr.show_text("GENESIS")
    cr.move_to(x1 + 28, y + 8)
    cr.show_text("REVELATION")
    cr.set_line_width(2)
    src(cr, CREAM, 0.3 * a)
    cr.move_to(x0, y)
    cr.line_to(x1, y)
    cr.stroke()
    p = clamp(cx / X_LAST)
    cr.set_line_width(4)
    src(cr, SCARLET, a)
    cr.move_to(x0, y)
    cr.line_to(lerp(x0, x1, p), y)
    cr.stroke()
    for k in range(N):
        bx = lerp(x0, x1, k / (N - 1))
        done = p >= k / (N - 1) - 1e-3
        circle(cr, bx, y, 5.5 if done else 4, SCARLET if done else CREAM, a * (1 if done else 0.5))
    mx = lerp(x0, x1, p)
    glow(cr, mx, y, 26, (1, 0.5, 0.45), a)
    circle(cr, mx, y, 6, (1, 0.95, 0.92), a)


def title_card(cr, T):
    a = 1 - ease_in_out(prog(T, T_TITLE - 0.3, T_TITLE + 0.5))
    if a <= 0:
        return
    glow(cr, W / 2, H / 2, 700, (0.9, 0.3, 0.3), 0.18 * ease_out(prog(T, 0, 1.5)) * a)
    letters_c(cr, "THE SCARLET THREAD", W / 2, H / 2 - 20, 112, CREAM, T, 0.25, 0.05, spacing=12, bold=True, alpha=a)
    p = ease_in_out(prog(T, 0.9, 2.2))
    if p > 0:
        cr.move_to(-20, H / 2 + 40)
        n = 120
        for i in range(1, int(n * p) + 1):
            x = -20 + (W + 40) * i / n
            cr.line_to(x, H / 2 + 40 + math.sin(i / n * math.pi * 6) * 14)
        cr.set_line_width(4)
        src(cr, SCARLET, a)
        cr.stroke()
    a2 = a * ease_out(prog(T, 1.5, 2.3))
    text_c(cr, "The gospel from Genesis to Revelation", W / 2, H / 2 + 120, 46, GOLD, a2, italic=True, spacing=1)


def end_card(cr, T):
    a = ease_out(prog(T, T_PULL + 1.4, T_PULL + 2.4))
    if a <= 0:
        return
    letters_c(cr, "ONE STORY. ONE SAVIOR.", W / 2, 300, 96, CREAM, T, T_PULL + 1.4, 0.04, spacing=10, bold=True)
    a2 = ease_out(prog(T, T_PULL + 2.4, T_PULL + 3.2))
    text_c(cr, "“Beginning with Moses and all the Prophets, he explained to them what was said", W / 2, 780, 38, CREAM, a2 * 0.92, italic=True)
    text_c(cr, "in all the Scriptures concerning himself.”", W / 2, 830, 38, CREAM, a2 * 0.92, italic=True)
    text_c(cr, "LUKE 24:27", W / 2, 892, 26, GOLD, a2, face=DISPLAY_FONT, bold=True, spacing=4)
    set_font(cr, DISPLAY_FONT, 22, bold=True)
    for lab, x in (("GENESIS", 150), ("REVELATION", W - 150)):
        w = cr.text_extents(lab).x_advance
        src(cr, GOLD, a2 * 0.9)
        cr.move_to(x - w / 2, 640)
        cr.show_text(lab)


def render_frame(f, surf):
    T = f / FPS
    cr = cairo.Context(surf)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cx, z = draw_world(cr, T)
    caption(cr, T)
    progress_bar(cr, T, cx)
    title_card(cr, T)
    end_card(cr, T)
    vig, grains = overlays()
    cr.set_source_surface(vig, 0, 0)
    cr.paint()
    cr.save()
    cr.scale(2, 2)
    cr.set_source_surface(grains[f % len(grains)], 0, 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint_with_alpha(0.022)
    cr.restore()
    fade = min(prog(T, 0, 0.4), 1 - prog(T, TOTAL - 0.7, TOTAL))
    if fade < 1:
        cr.rectangle(0, 0, W, H)
        src(cr, (0, 0, 0), 1 - ease_in_out(fade))
        cr.fill()
    surf.flush()


def render_chunk(args):
    f0, f1, path = args
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "21",
           "-pix_fmt", "yuv420p", "-r", str(FPS), path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(f0, f1):
        render_frame(f, surf)
        proc.stdin.write(bytes(surf.get_data()))
    proc.stdin.close()
    proc.wait()
    return path


# ---------------------------------------------------------------------------
# Score: an ambient pad that follows the story, with a bell on every "stitch"
# ---------------------------------------------------------------------------

CHORDS = [
    (0, T_TITLE, [38, 50, 57, 62, 69]),                                       # title: D (open)
] + [
    (ARRIVE[k] - TRAVEL, ARRIVE[k] + HOLD, c) for k, c in enumerate([
        [48, 55, 64, 67, 72, 76],    # creation: C
        [45, 52, 57, 60, 64],        # fall: Am
        [41, 53, 60, 65, 69],        # abraham: F
        [38, 50, 57, 62, 65],        # passover: Dm
        [43, 55, 62, 67, 71],        # tabernacle: G
        [48, 55, 64, 67, 72],        # david: C
        [40, 52, 59, 64, 67],        # prophets: Em
        [41, 53, 60, 65, 69, 72],    # incarnation: F
        [45, 52, 57, 60, 64],        # cross: Am
        [48, 55, 64, 67, 72, 79],    # resurrection: C
        [43, 55, 62, 67, 71, 74],    # nations: G
        [48, 55, 64, 67, 72, 76],    # new creation: C
    ])
] + [(T_PULL, TOTAL, [36, 48, 55, 64, 67, 72, 76, 79])]                  # finale: full C
BELLS = [(THREAD_START, 88)] + [(ARRIVE[k], m) for k, m in
                                 zip(range(2, N), (84, 86, 88, 91, 86, 88, 81, 91, 88, 96))] + [(T_PULL + 1.4, 84), (T_PULL + 1.5, 91)]


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def make_audio(path, sr=48000):
    n = int(TOTAL * sr)
    t = np.arange(n) / sr
    L = np.zeros(n)
    R = np.zeros(n)
    for s0, s1, notes in CHORDS:
        s0, s1 = s0 - 0.5, s1 + 0.5
        a, b = max(0, int(s0 * sr)), min(n, int(s1 * sr))
        tt = t[a:b]
        env = np.sin(np.clip((tt - s0) / 0.9, 0, 1) * np.clip((s1 - tt) / 0.9, 0, 1) * np.pi / 2) ** 2
        for j, m in enumerate(notes):
            f = midi_hz(m)
            amp = (0.07 if j == 0 else 0.045) * (0.75 if m > 76 else 1.0)
            trem = 1 + 0.15 * np.sin(2 * np.pi * (0.2 + j * 0.07) * tt + j)
            for det, ch in ((0.997, L), (1.003, R)):
                ph = 2 * np.pi * f * det * tt
                ch[a:b] += amp * env * trem * (np.sin(ph) + 0.22 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph))
    for t0, m in BELLS:
        a = int(t0 * sr)
        b = min(n, a + sr * 4)
        tt = t[a:b] - t0
        f = midi_hz(m)
        bell = sum(w * np.sin(2 * np.pi * f * k * tt) * np.exp(-tt * (1.2 + k * 0.9))
                   for k, w in ((1, 1.0), (2.01, 0.35), (2.76, 0.2), (5.4, 0.08)))
        bell *= np.clip(tt / 0.005, 0, 1) * 0.11
        L[a:b] += bell * 0.9
        R[a:b] += bell * 1.1
    for ch in (L, R):
        wet = np.zeros_like(ch)
        for dly, g in ((0.043, 0.35), (0.071, 0.3), (0.113, 0.25), (0.157, 0.2), (0.233, 0.15)):
            k = int(dly * sr * (1.03 if ch is R else 1.0))
            wet[k:] += ch[:-k] * g
        ch += wet
    fade = np.clip(t / 0.8, 0, 1) * np.clip((TOTAL - t) / 1.8, 0, 1)
    stereo = np.stack([L * fade, R * fade], axis=1)
    stereo = stereo / np.abs(stereo).max() * 0.8
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def main():
    args = sys.argv[1:]
    if "--preview" in args:
        k = args.index("--preview")
        os.makedirs("preview", exist_ok=True)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        for tm in (float(x) for x in args[k + 1:]):
            render_frame(int(round(tm * FPS)), surf)
            surf.write_to_png(f"preview/t{tm:05.2f}.png")
        return
    out = args[0] if args else os.path.join(HERE, "the_scarlet_thread.mp4")
    work = os.path.join(HERE, ".build")
    os.makedirs(work, exist_ok=True)
    print(f"{NFRAMES} frames, {TOTAL:.1f}s at {FPS} fps, {W}x{H}")
    nproc = max(1, os.cpu_count() or 1)
    per = math.ceil(NFRAMES / nproc)
    chunks = [(i, min(NFRAMES, i + per), os.path.join(work, f"part{j:02d}.mp4"))
              for j, i in enumerate(range(0, NFRAMES, per))]
    with Pool(len(chunks)) as pool:
        parts = pool.map(render_chunk, chunks)
    lst = os.path.join(work, "parts.txt")
    with open(lst, "w") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    wav = os.path.join(work, "score.wav")
    make_audio(wav)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", out], check=True)
    shutil.rmtree(work)
    print("wrote", out)


if __name__ == "__main__":
    main()
