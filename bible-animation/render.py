#!/usr/bin/env python3
"""The Story of the Bible: a 1080p / 24 fps procedural animation.

Every frame is drawn from code with Cairo (vector shapes, gradients, text),
so there are no external image assets. The animation uses classic principles:

  * easing (slow-in / slow-out) on all motion, with overshoot for "pop"
  * anticipation (the light pulls in before it bursts, the stone rocks back
    before it rolls, Moses dips his staff before raising it)
  * squash & stretch (the falling fruit, the dropping crown)
  * follow-through & overlapping action (staggered letters, trees, crowds)
  * secondary motion (swaying trees, rain, birds, shimmer, drifting motes)
  * physically driven motion (the ark rides the slope of the waves, the tomb
    stone rotates by distance / radius as it rolls)
  * staging with a slow camera (push-ins, pull-backs, tilts) and
    cross-dissolves between scenes, plus film grain and a vignette

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

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:  # fall back to a system ffmpeg
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

W, H, FPS = 1920, 1080, 24
XF = 0.5  # cross-dissolve length (seconds)
HERE = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# Fonts: use the bundled OFL fonts if fontconfig can see them.
# --------------------------------------------------------------------------

def install_fonts():
    dst = os.path.expanduser("~/.fonts")
    src = os.path.join(HERE, "fonts")
    if not os.path.isdir(src):
        return
    os.makedirs(dst, exist_ok=True)
    changed = False
    for f in os.listdir(src):
        if f.endswith(".ttf") and not os.path.exists(os.path.join(dst, f)):
            shutil.copy(os.path.join(src, f), dst)
            changed = True
    if changed and shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f"], check=False)


def font_available(name):
    if not shutil.which("fc-list"):
        return False
    out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
    return name.lower() in out.lower()


install_fonts()
DISPLAY_FONT = "Cinzel" if font_available("Cinzel") else "FreeSerif"
BODY_FONT = "EB Garamond" if font_available("EB Garamond") else "FreeSerif"


# --------------------------------------------------------------------------
# Math / easing
# --------------------------------------------------------------------------

def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def prog(t, a, b):
    """Normalised progress of t through [a, b], clamped to 0..1."""
    if b <= a:
        return 1.0 if t >= a else 0.0
    return clamp((t - a) / (b - a))


def ease_in_out(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in(t):
    t = clamp(t)
    return t ** 3


def ease_out_back(t, s=1.70158):
    t = clamp(t) - 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def ease_out_bounce(t):
    t = clamp(t)
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def mix(c1, c2, t):
    return tuple(lerp(a, b, t) for a, b in zip(c1, c2))


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


GOLD = hexc("#f3c86b")
CREAM = hexc("#fbf3e2")
INK = hexc("#120d14")


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------

def src(cr, c, a=1.0):
    cr.set_source_rgba(c[0], c[1], c[2], a)


def sky(cr, stops):
    g = cairo.LinearGradient(0, -200, 0, H + 200)
    for o, c in stops:
        g.add_color_stop_rgb(o, *c)
    cr.rectangle(-400, -400, W + 800, H + 800)
    cr.set_source(g)
    cr.fill()


def fill_all(cr, c, a=1.0):
    cr.rectangle(-400, -400, W + 800, H + 800)
    src(cr, c, a)
    cr.fill()


def circle(cr, x, y, r, c, a=1.0):
    if r <= 0 or a <= 0:
        return
    cr.arc(x, y, r, 0, 2 * math.pi)
    src(cr, c, a)
    cr.fill()


def glow(cr, x, y, r, c, a=1.0):
    if r <= 0 or a <= 0:
        return
    g = cairo.RadialGradient(x, y, 0, x, y, r)
    g.add_color_stop_rgba(0, c[0], c[1], c[2], a)
    g.add_color_stop_rgba(0.35, c[0], c[1], c[2], a * 0.45)
    g.add_color_stop_rgba(1, c[0], c[1], c[2], 0)
    cr.arc(x, y, r, 0, 2 * math.pi)
    cr.set_source(g)
    cr.fill()


def rays(cr, x, y, n, r1, angle, c, a, width=0.5):
    """Soft god-rays: n wedges fading out from (x, y)."""
    if a <= 0:
        return
    g = cairo.RadialGradient(x, y, 0, x, y, r1)
    g.add_color_stop_rgba(0, c[0], c[1], c[2], a)
    g.add_color_stop_rgba(1, c[0], c[1], c[2], 0)
    step = 2 * math.pi / n
    for i in range(n):
        a0 = angle + i * step
        cr.move_to(x, y)
        cr.arc(x, y, r1, a0, a0 + step * width)
        cr.close_path()
    cr.set_source(g)
    cr.fill()


def poly(cr, pts, c, a=1.0):
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    cr.close_path()
    src(cr, c, a)
    cr.fill()


def ridge_y(x, base, amp, ph, f1=0.0035, f2=0.009):
    return base + amp * (0.65 * math.sin(x * f1 + ph) + 0.35 * math.sin(x * f2 + ph * 1.7))


def hill(cr, base, amp, ph, c, a=1.0, f1=0.0035, f2=0.009):
    cr.move_to(-400, H + 400)
    for x in range(-400, W + 401, 16):
        cr.line_to(x, ridge_y(x, base, amp, ph, f1, f2))
    cr.line_to(W + 400, H + 400)
    cr.close_path()
    src(cr, c, a)
    cr.fill()


def stars(cr, n, seed, t, alpha, y_max=H * 0.7, size=1.0, appear=None):
    rnd = random.Random(seed)
    for i in range(n):
        x = rnd.uniform(-100, W + 100)
        y = rnd.uniform(-150, y_max)
        r = rnd.choice([0.8, 1.0, 1.2, 1.5, 2.0, 2.6]) * size
        ph = rnd.uniform(0, 6.28)
        sp = rnd.uniform(1.5, 4.0)
        s = 1.0
        if appear is not None:
            t0 = appear[0] + rnd.random() * appear[1]
            s = ease_out_back(prog(t, t0, t0 + 0.35), 3)
            if s <= 0:
                continue
        tw = 0.55 + 0.45 * math.sin(t * sp + ph)
        circle(cr, x, y, r * s, (1, 0.97, 0.9), alpha * tw)
        if r > 2.2:
            glow(cr, x, y, r * 7 * s, (0.8, 0.85, 1.0), alpha * tw * 0.35)


def figure(cr, x, y, s, c, arm=None, arm2=None, bob=0.0, head_tilt=0.0, kneel=False, staff=False):
    """Stylised robed figure (silhouette). (x, y) is the feet position.

    arm / arm2: angles in radians (0 = pointing down, pi = straight up) for the
    right / left arm; None hides the arm under the robe.
    """
    cr.save()
    cr.translate(x, y - bob * s)
    cr.scale(s, s)
    h = 0.62 if kneel else 1.0
    # robe
    cr.move_to(-19, 0)
    cr.curve_to(-17, -30 * h, -13, -52 * h, -9, -62 * h)
    cr.curve_to(-4, -66 * h, 4, -66 * h, 9, -62 * h)
    cr.curve_to(13, -52 * h, 17, -30 * h, 19, 0)
    cr.close_path()
    src(cr, c)
    cr.fill()
    # head
    hx, hy = 1.5 * head_tilt, -73 * h + abs(head_tilt) * 1.5
    circle(cr, hx, hy, 9.5, c)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_width(6)
    src(cr, c)
    for ang, side in ((arm, 1), (arm2, -1)):
        if ang is None:
            continue
        sx, sy = 7 * side, -58 * h
        ex = sx + side * math.sin(ang) * 30
        ey = sy + math.cos(ang) * 30
        cr.move_to(sx, sy)
        cr.line_to(ex, ey)
        cr.stroke()
        if staff and side == 1:
            cr.set_line_width(3)
            cr.move_to(ex - side * math.sin(ang) * 30, ey - math.cos(ang) * 30 + 40)
            cr.line_to(ex + side * math.sin(ang) * 40, ey + math.cos(ang) * 40)
            cr.stroke()
            cr.set_line_width(6)
    cr.restore()


def tree(cr, x, y, s, grow, trunk, leaf, t=0.0, fruit=None, sway=0.02):
    if grow <= 0:
        return
    cr.save()
    cr.translate(x, y)
    cr.scale(s * grow, s * grow)
    poly(cr, [(-9, 0), (-5, -95), (5, -95), (9, 0)], trunk)
    cr.rotate(math.sin(t * 1.3 + x) * sway)
    for dx, dy, r in ((0, -150, 62), (-48, -118, 46), (48, -118, 46), (-26, -178, 42), (28, -176, 44)):
        circle(cr, dx, dy, r, leaf)
    if fruit:
        for dx, dy in ((-40, -120), (30, -160), (50, -110), (-10, -190), (-60, -150)):
            circle(cr, dx, dy, 7, fruit)
    cr.restore()


def bird(cr, x, y, s, flap, c, a=1.0):
    w = math.sin(flap) * 10
    cr.save()
    cr.translate(x, y)
    cr.scale(s, s)
    cr.move_to(-22, -w)
    cr.curve_to(-12, -w * 0.4 - 4, -5, -3, 0, 2)
    cr.curve_to(5, -3, 12, -w * 0.4 - 4, 22, -w)
    cr.set_line_width(3.2)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    src(cr, c, a)
    cr.stroke()
    cr.restore()


def cloud(cr, x, y, s, c, a=1.0):
    for dx, dy, r in ((0, 0, 60), (60, 10, 50), (-60, 12, 48), (30, -35, 50), (-25, -30, 44), (100, 22, 34), (-100, 24, 32)):
        circle(cr, x + dx * s, y + dy * s, r * s, c, a)


def set_font(cr, face, size, italic=False, bold=False):
    cr.select_font_face(face,
                        cairo.FONT_SLANT_ITALIC if italic else cairo.FONT_SLANT_NORMAL,
                        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)


def text_c(cr, s, x, y, size, c, a, face=None, italic=False, bold=False, spacing=0.0):
    if a <= 0:
        return
    set_font(cr, face or BODY_FONT, size, italic, bold)
    widths = [cr.text_extents(ch).x_advance + spacing for ch in s]
    x0 = x - (sum(widths) - spacing) / 2
    src(cr, c, a)
    for ch, w in zip(s, widths):
        cr.move_to(x0, y)
        cr.show_text(ch)
        x0 += w


def letters_c(cr, s, x, y, size, c, t, start, stagger, face=None, spacing=0.0, bold=False, alpha=1.0):
    """Per-letter staggered reveal (overlapping action) with overshoot."""
    set_font(cr, face or DISPLAY_FONT, size, bold=bold)
    widths = [cr.text_extents(ch).x_advance + spacing for ch in s]
    x0 = x - (sum(widths) - spacing) / 2
    for i, (ch, w) in enumerate(zip(s, widths)):
        t0 = start + i * stagger
        p = prog(t, t0, t0 + 0.55)
        if p > 0:
            k = ease_out_back(p, 2.2)
            cr.save()
            cr.translate(x0 + w / 2, y + (1 - k) * 46)
            sc = lerp(0.6, 1.0, k)
            cr.scale(sc, sc)
            cr.move_to(-(w - spacing) / 2, 0)
            src(cr, c, alpha * ease_out(p * 1.4))
            cr.show_text(ch)
            cr.restore()
        x0 += w


def caption(cr, t, d, title, ref, t_in=0.35, t_out=None):
    """Lower-third caption: slides up and fades in, fades out before the cut."""
    t_out = d - 0.55 if t_out is None else t_out
    ai = ease_out(prog(t, t_in, t_in + 0.7))
    a = ai * (1 - prog(t, t_out - 0.45, t_out))
    if a <= 0:
        return
    g = cairo.LinearGradient(0, H - 330, 0, H)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0, 0, 0, 0.6 * a)
    cr.rectangle(-10, H - 330, W + 20, 340)
    cr.set_source(g)
    cr.fill()
    dy = (1 - ai) * 36
    text_c(cr, title, W / 2, H - 118 + dy, 66, CREAM, a, face=DISPLAY_FONT, bold=True, spacing=2)
    a2 = a * ease_out(prog(t, t_in + 0.2, t_in + 0.9))
    text_c(cr, ref, W / 2, H - 66 + dy * 1.4, 34, GOLD, a2, italic=True, spacing=1)


def camera(cr, zoom=1.0, dx=0.0, dy=0.0, cx=W / 2, cy=H / 2):
    cr.translate(cx + dx, cy + dy)
    cr.scale(zoom, zoom)
    cr.translate(-cx, -cy)


# --------------------------------------------------------------------------
# Scenes. Each takes (cr, t, d): local time and scene duration.
# --------------------------------------------------------------------------

def s_title(cr, t, d):
    fill_all(cr, (0.02, 0.018, 0.035))
    g = ease_out(prog(t, 0, 2.2))
    rays(cr, W / 2, H / 2, 18, 1300 * g, t * 0.08, (1, 0.85, 0.55), 0.10 * g)
    glow(cr, W / 2, H / 2, lerp(120, 950, g), (1, 0.78, 0.45), 0.30 * g)
    rnd = random.Random(7)
    for _ in range(110):
        x = rnd.uniform(0, W)
        sp = rnd.uniform(18, 70)
        y = (rnd.uniform(0, H + 40) - t * sp) % (H + 40)
        x += math.sin(t * rnd.uniform(0.5, 1.5) + y * 0.01) * 12
        circle(cr, x, y, rnd.uniform(1, 3.2), (1, 0.86, 0.55), 0.55 * g * rnd.uniform(0.25, 1))
    letters_c(cr, "THE STORY OF THE BIBLE", W / 2, H / 2 - 4, 104, CREAM, t, 0.25, 0.045, spacing=10, bold=True)
    p = ease_in_out(prog(t, 1.35, 2.25))
    cr.set_line_width(2.5)
    src(cr, GOLD, 0.9)
    cr.move_to(W / 2 - 430 * p, H / 2 + 44)
    cr.line_to(W / 2 + 430 * p, H / 2 + 44)
    cr.stroke()
    circle(cr, W / 2, H / 2 + 44, 6 * ease_out_back(prog(t, 1.2, 1.6), 3), GOLD)
    a = ease_out(prog(t, 1.9, 2.7))
    text_c(cr, "From Creation to New Creation, in one minute", W / 2, H / 2 + 112 + (1 - a) * 20, 44, GOLD, a, italic=True, spacing=1)


def s_creation(cr, t, d):
    L = ease_in_out(prog(t, 1.3, 3.2))
    dark = (0.01, 0.012, 0.03)
    sky(cr, [(0, mix(dark, hexc("#2d5fa8"), L)), (0.62, mix(dark, hexc("#f5b77a"), L)), (1, mix(dark, hexc("#ffe2a8"), L))])
    cr.save()
    camera(cr, lerp(1.08, 1.0, ease_out(t / d)))
    # the deep: dark waters moving before the light
    wa = 0.22 * (1 - L)
    if wa > 0.01:
        cr.set_line_width(2)
        for k in range(9):
            cr.move_to(-400, 0)
            for x in range(-400, W + 401, 24):
                cr.line_to(x, H * 0.46 + k * 60 + math.sin(x * 0.006 + t * 1.6 + k) * 16)
            src(cr, (0.45, 0.55, 0.8), wa * (1 - k / 11))
            cr.stroke()
    stars(cr, 160, 11, t, 0.8 * (1 - L * 0.85) * ease_out(prog(t, 1.4, 2.4)), appear=(1.3, 1.1))
    # "Let there be light": anticipation (pull in), then burst.
    cx, cy = W / 2, H * 0.42
    if t < 1.25:
        grow = ease_out(prog(t, 0.2, 0.95)) * 16
        pull = ease_in(prog(t, 0.95, 1.2))
        r = grow * (1 - 0.8 * pull)
        glow(cr, cx, cy, r * 9, (1, 0.9, 0.7), 0.8)
        circle(cr, cx, cy, r, (1, 1, 0.95))
    b = prog(t, 1.2, 2.4)
    if 0 < b < 1:
        e = ease_out(b)
        rays(cr, cx, cy, 24, 200 + 1900 * e, t * 0.4, (1, 0.95, 0.8), 0.7 * (1 - b))
        glow(cr, cx, cy, 80 + 1600 * e, (1, 0.97, 0.88), 0.95 * (1 - b) ** 1.5)
    # sun rises with overshoot
    sp = ease_out_back(prog(t, 2.0, 3.5), 1.2)
    sx, sy = W * 0.72, lerp(H * 0.9, H * 0.3, sp)
    if sp > 0:
        glow(cr, sx, sy, 420, (1, 0.85, 0.5), 0.6)
        circle(cr, sx, sy, 70, (1, 0.93, 0.7))
    # land rises from the waters
    far = lerp(H + 300, H * 0.64, ease_out(prog(t, 2.2, 3.3)))
    near = lerp(H + 400, H * 0.78, ease_out(prog(t, 2.5, 3.7)))
    hill(cr, far, 40, 0.4, mix(hexc("#34507a"), hexc("#5d8a5a"), L))
    hill(cr, near, 34, 2.1, mix(hexc("#1c2a3a"), hexc("#2f6b3e"), L), f1=0.0025)
    for i, xf in enumerate((0.1, 0.24, 0.4, 0.61, 0.83, 0.94)):
        x = W * xf
        gr = ease_out_back(prog(t, 3.4 + i * 0.13, 3.95 + i * 0.13), 2.0)
        tree(cr, x, ridge_y(x, near, 34, 2.1, 0.0025) + 6, 0.8 + (i % 3) * 0.18, gr,
             hexc("#3b2a1e"), hexc("#23572f") if i % 2 else hexc("#2c6b36"), t)
    # birds cross the sky (secondary life)
    for i in range(6):
        bx = lerp(-150, W + 250, prog(t, 3.7 + i * 0.08, 6.2)) - (i % 3) * 60
        by = H * 0.22 + (i % 3) * 38 + math.sin(t * 2 + i) * 10
        if 3.7 < t:
            bird(cr, bx, by, 1.0 - i * 0.06, t * 13 + i * 1.3, (0.15, 0.12, 0.2))
    cr.restore()
    caption(cr, t, d, "In the beginning, God created", "Genesis 1 – 2", t_in=2.4)


def s_fall(cr, t, d):
    D = ease_in_out(prog(t, 2.4, 4.0))
    sky(cr, [(0, mix(hexc("#6fb2e6"), hexc("#2b2140"), D)), (1, mix(hexc("#fff3c9"), hexc("#b0605a"), D))])
    cr.save()
    camera(cr, lerp(1.0, 1.07, ease_in_out(t / d)))
    glow(cr, W * 0.5, H * 0.35, 700, mix((1, 0.95, 0.75), (0.8, 0.4, 0.4), D), 0.5 * (1 - D * 0.6))
    hill(cr, H * 0.66, 30, 1.0, mix(hexc("#7dbb6a"), hexc("#5a5a60"), D))
    ground = H * 0.8
    hill(cr, ground, 12, 3.0, mix(hexc("#3d8a45"), hexc("#3a3a45"), D), f1=0.002)
    # tree of knowledge
    tx, ty = W * 0.5, ground + 4
    trunk, leaf = mix(hexc("#4a3222"), hexc("#2a1f24"), D), mix(hexc("#2f7a3a"), hexc("#3b3a48"), D)
    poly(cr, [(tx - 26, ty), (tx - 14, ty - 250), (tx + 14, ty - 250), (tx + 26, ty)], trunk)
    cr.set_line_width(14)
    src(cr, trunk)
    cr.move_to(tx - 8, ty - 230)
    cr.curve_to(tx - 80, ty - 280, tx - 170, ty - 300, tx - 270, ty - 300)
    cr.stroke()
    cr.save()
    cr.translate(tx, ty - 250)
    cr.rotate(math.sin(t * 1.1) * 0.012)
    for dx, dy, r in ((0, -120, 170), (-150, -60, 120), (150, -60, 125), (-80, -200, 115), (95, -195, 120), (-230, -50, 70)):
        circle(cr, dx, dy, r, leaf)
    for dx, dy in ((-120, -40), (60, -150), (140, -20), (-40, -220), (-200, -90), (180, -110)):
        circle(cr, dx, dy, 13, mix(hexc("#d8342c"), hexc("#6a2e33"), D))
    cr.restore()
    # serpent: a travelling sine wave along the branch (secondary motion)
    sa = 1 - prog(t, 3.2, 4.0)
    if sa > 0:
        cr.set_line_width(11)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        pts = []
        for i in range(40):
            u = i / 39
            x = lerp(tx - 290, tx - 120, u)
            y = ty - 296 - u * 10 + math.sin(u * 12 - t * 5) * 11 * (0.3 + u) + 16
            pts.append((x, y))
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        src(cr, hexc("#15331f"), sa)
        cr.stroke()
        circle(cr, pts[0][0] - 4, pts[0][1], 10, hexc("#15331f"), sa)
    # the fruit: anticipation wobble -> gravity fall -> squash & bounce
    fx, fy0 = tx + 60, ty - 250 - 110
    fg = ground - 14
    if t < 1.5:
        wob = math.sin(t * 28) * 0.25 * prog(t, 0.7, 1.5)
        fx_, fy, sx, sy = fx + wob * 8, fy0, 1, 1
    else:
        p = prog(t, 1.5, 2.6)
        fy = lerp(fy0, fg, ease_out_bounce(p))
        fx_ = fx + p * 90
        prox = max(0.0, 1 - abs(fg - fy) / 18)
        stretch = 0.0 if prox > 0 else min(0.25, abs(fy - fy0) / 900) * (1 - p)
        sx, sy = 1 + 0.35 * prox - stretch, 1 - 0.3 * prox + stretch
    cr.save()
    cr.translate(fx_, fy + 14 * (1 - sy))
    cr.scale(sx, sy)
    circle(cr, 0, 0, 14, mix(hexc("#e2382e"), hexc("#7a2a2f"), D))
    circle(cr, -4, -5, 4, (1, 1, 1), 0.5 * (1 - D))
    cr.restore()
    # Adam & Eve: stand, then walk out of the garden with heads bowed
    wk = ease_in(prog(t, 2.9, 5.2))
    for i, (x0, c) in enumerate(((W * 0.36, hexc("#2a2230")), (W * 0.62, hexc("#2a2230")))):
        ph = (t - 2.9) * 9 + i
        moving = t > 2.9
        x = x0 - wk * (900 + i * 120)
        bob = abs(math.sin(ph)) * 4 if moving else 0
        figure(cr, x, ground + 2, 1.9, mix(hexc("#3a2e3a"), INK, D), bob=bob,
               head_tilt=-2 * D, arm=0.25 if i == 0 else None, arm2=None if i == 0 else 0.25)
    # leaves drift down as the world darkens
    rnd = random.Random(5)
    for i in range(18):
        lt = t - 2.6 - rnd.random() * 1.5
        if lt > 0:
            x = rnd.uniform(tx - 350, tx + 350) + math.sin(lt * 3 + i) * 40
            y = ty - 380 + lt * rnd.uniform(90, 160)
            cr.save()
            cr.translate(x, y)
            cr.rotate(lt * 3 + i)
            cr.scale(1, 0.45)
            circle(cr, 0, 0, 9, mix(hexc("#9a7a3a"), hexc("#5a4a50"), D), 0.9)
            cr.restore()
    cr.restore()
    caption(cr, t, d, "Sin breaks the world", "Genesis 3", t_in=1.9)


def wave_y(x, base, amp, t, k):
    return base + amp * (math.sin(x * 0.006 + t * 1.8 + k) * 0.6 + math.sin(x * 0.013 - t * 2.4 + k * 2) * 0.4)


def s_flood(cr, t, d):
    C = ease_in_out(prog(t, 2.5, 3.9))
    sky(cr, [(0, mix(hexc("#12171f"), hexc("#5b8fcc"), C)), (1, mix(hexc("#3b4652"), hexc("#ffd9a0"), C))])
    # lightning (instant attack, exponential decay)
    flash = sum(math.exp(-(t - lt) * 9) for lt in (0.55, 1.45) if t > lt) * (1 - C)
    cr.save()
    camera(cr, 1.04, dx=math.sin(t * 0.7) * 10)
    # rainbow: God's promise, drawn band by band
    cols = [hexc(h) for h in ("#e8433b", "#f39a35", "#f5d547", "#5dbb5a", "#3f86d6", "#7a55c2")]
    cr.set_line_width(26)
    for i, c in enumerate(cols):
        p = ease_in_out(prog(t, 3.1 + i * 0.06, 4.3 + i * 0.06))
        if p > 0:
            r = 700 - i * 26
            cr.arc(W / 2, H * 0.92, r, math.pi, math.pi + math.pi * p)
            src(cr, c, 0.55)
            cr.stroke()
    # storm clouds part and drift away
    for i in range(7):
        x = W * (i / 6) + (i - 3) * C * 220 + t * 12
        y = H * 0.12 + (i % 2) * 60 - C * 260
        cloud(cr, x, y, 1.8, mix(hexc("#232a33"), hexc("#fff7ea"), C), 0.95 - C * 0.6)
    # dove flies in after the storm
    if t > 3.3:
        p = prog(t, 3.3, d)
        bird(cr, lerp(W * 0.1, W * 0.55, ease_out(p)), H * 0.3 - math.sin(p * 3) * 40, 1.3, t * 12, (1, 1, 1), 0.95)
    amp = lerp(46, 12, C)
    wc = [mix(hexc(a), hexc(b), C) for a, b in (("#1c2d3f", "#3c6e9c"), ("#16263a", "#2d5a86"), ("#0e1b2a", "#224a70"))]
    for k, base in enumerate((H * 0.66,)):
        cr.move_to(-400, H + 400)
        for x in range(-400, W + 401, 16):
            cr.line_to(x, wave_y(x, base, amp * 0.8, t, 0.3))
        cr.line_to(W + 400, H + 400)
        src(cr, wc[0])
        cr.fill()
    # ark rides the wave: height AND rotation from the wave's slope
    ax = W * 0.5 + math.sin(t * 0.4) * 30
    base2 = H * 0.74
    y1 = wave_y(ax - 60, base2, amp, t - 0.12, 1.1)
    y2 = wave_y(ax + 60, base2, amp, t - 0.12, 1.1)
    cr.save()
    cr.translate(ax, (y1 + y2) / 2 - 18)
    cr.rotate(math.atan2(y2 - y1, 120) * 0.8)
    hull = hexc("#5a3a22")
    cr.move_to(-250, -60)
    cr.line_to(250, -60)
    cr.curve_to(230, 10, 170, 40, 120, 40)
    cr.line_to(-120, 40)
    cr.curve_to(-170, 40, -230, 10, -250, -60)
    src(cr, hull)
    cr.fill()
    cr.set_line_width(3)
    src(cr, hexc("#3a2414"))
    for yy in (-35, -10, 15):
        cr.move_to(-225, yy)
        cr.line_to(225, yy)
        cr.stroke()
    poly(cr, [(-140, -60), (-140, -125), (140, -125), (140, -60)], hexc("#6e4a2c"))
    poly(cr, [(-165, -125), (0, -175), (165, -125)], hexc("#4a2e1a"))
    for wx in (-90, -30, 30, 90):
        circle(cr, wx, -95, 9, hexc("#ffd58a"), 0.35 + 0.65 * C)
    cr.restore()
    for k, (base, a) in enumerate(((H * 0.8, 0.95), (H * 0.9, 1.0))):
        cr.move_to(-400, H + 400)
        for x in range(-400, W + 401, 16):
            cr.line_to(x, wave_y(x, base, amp * (1 + k * 0.3), t, 2 + k * 1.7))
        cr.line_to(W + 400, H + 400)
        src(cr, wc[k + 1], a)
        cr.fill()
    # rain (secondary motion, stops with the storm)
    ra = 0.45 * (1 - C)
    if ra > 0.01:
        rnd = random.Random(3)
        cr.set_line_width(2)
        src(cr, (0.75, 0.82, 0.9), ra)
        for _ in range(280):
            x0 = rnd.uniform(-200, W + 200)
            sp = rnd.uniform(1400, 2000)
            y = (rnd.uniform(0, H + 200) + t * sp) % (H + 200) - 100
            x = x0 - (y * 0.25)
            cr.move_to(x, y)
            cr.line_to(x - 12, y + 46)
        cr.stroke()
    cr.restore()
    if flash > 0.01:
        fill_all(cr, (0.9, 0.93, 1), min(0.75, flash * 0.7))
    caption(cr, t, d, "The Flood and a promise", "Genesis 6 – 9", t_in=0.6)


def s_abraham(cr, t, d):
    cr.save()
    camera(cr, 1.06, dy=lerp(-60, 70, ease_in_out(t / d)))
    sky(cr, [(0, hexc("#03050f")), (0.7, hexc("#141c44")), (1, hexc("#2d2a55"))])
    # milky way band
    cr.save()
    cr.translate(W / 2, H * 0.25)
    cr.rotate(-0.35)
    cr.scale(3.2, 0.5)
    glow(cr, 0, 0, 420, (0.6, 0.6, 0.95), 0.18)
    cr.restore()
    # "Look toward heaven, and number the stars": they pop in by the hundreds
    stars(cr, 520, 21, t, 1.0, y_max=H * 0.75, appear=(0.4, 2.6))
    hill(cr, H * 0.8, 50, 0.8, hexc("#0d0f22"))
    gy = ridge_y(W * 0.62, H * 0.8, 50, 0.8)
    # tent
    poly(cr, [(W * 0.25, H * 0.86), (W * 0.31, H * 0.76), (W * 0.37, H * 0.86)], hexc("#080914"))
    glow(cr, W * 0.31, H * 0.85, 60, (1, 0.7, 0.3), 0.5 + 0.1 * math.sin(t * 9))
    # Abraham raises his hand to the sky (overshoot) with a staff
    raise_ = ease_out_back(prog(t, 0.5, 1.4), 2.0)
    figure(cr, W * 0.62, gy + 4, 2.1, hexc("#07070f"), arm=lerp(0.2, 2.6, raise_), arm2=0.25,
           head_tilt=-1 if raise_ > 0.5 else 0)
    cr.restore()
    caption(cr, t, d, "A promise to Abraham", "Genesis 12 – 22", t_in=0.9)


def s_exodus(cr, t, d):
    cr.save()
    camera(cr, lerp(1.0, 1.06, t / d))
    sky(cr, [(0, hexc("#2a1740")), (0.55, hexc("#c4543c")), (1, hexc("#ffb35c"))])
    y0 = H * 0.5
    # pillar of fire at the far shore
    glow(cr, W / 2, y0 - 40, 260, (1, 0.6, 0.25), 0.7 + 0.1 * math.sin(t * 7))
    cr.set_line_width(1)
    # far shore
    hill(cr, y0 - 4, 10, 0.2, hexc("#5a2a2a"), f1=0.004)
    # anticipation: the staff dips before the sea splits
    P = ease_out_back(prog(t, 0.6, 2.0), 0.9)
    a, b = 36 * P, 380 * P
    hA, hB = 50 * P, 820 * P
    # sand path
    poly(cr, [(W / 2 - a, y0), (W / 2 + a, y0), (W / 2 + b, H + 2), (W / 2 - b, H + 2)], hexc("#c79a63"))
    for side in (-1, 1):
        ex_far, ex_near = W / 2 + side * a, W / 2 + side * b
        edge = -400 if side < 0 else W + 400
        # the top of the wall runs toward the vanishing point; extend it off-screen
        top_far, top_near = y0 - hA, H - hB
        slope = (top_near - top_far) / (ex_near - ex_far) if abs(ex_near - ex_far) > 1e-6 else 0.0
        top_edge = top_far + slope * (edge - ex_far)
        g = cairo.LinearGradient(0, min(top_near, top_far), 0, H)
        g.add_color_stop_rgb(0, *hexc("#4f9ccc"))
        g.add_color_stop_rgb(0.5, *hexc("#23608f"))
        g.add_color_stop_rgb(1, *hexc("#123452"))
        cr.move_to(ex_far, y0)
        cr.line_to(ex_far, top_far)
        cr.line_to(edge, top_edge)
        cr.line_to(edge, H + 2)
        cr.line_to(ex_near, H + 2)
        cr.close_path()
        cr.set_source(g)
        cr.fill()
        if P > 0.02:
            # flowing streaks on the wall face, converging on the vanishing point
            cr.set_line_width(2.5)
            cr.set_dash([60, 40], -side * t * 140)
            for f in (0.18, 0.36, 0.54, 0.72, 0.88):
                cr.move_to(ex_far, lerp(y0, top_far, f))
                cr.line_to(ex_near, lerp(H, top_near, f))
                src(cr, (0.85, 0.95, 1), 0.18)
                cr.stroke()
            cr.set_dash([])
            # foam along the crest of the wall
            for i in range(30):
                u = i / 29
                fx = lerp(ex_far, ex_near, u)
                fy = lerp(top_far, top_near, u) + math.sin(t * 6 + i) * 5 * u
                circle(cr, fx, fy, 3 + 22 * u, (0.92, 0.97, 1), 0.9)
        else:
            cr.set_line_width(2)
            for k in range(10):
                yy = y0 + k * k * 5.5 + 8
                xx = W / 2 + side * (120 + k * 40) + math.sin(t * 2 + k) * 30
                cr.move_to(xx, yy)
                cr.line_to(xx + side * (100 + k * 16), yy)
                src(cr, (0.8, 0.9, 1), 0.25)
                cr.stroke()
    # the people cross (overlapping action: staggered walkers, depth-scaled)
    walkers = []
    rnd = random.Random(8)
    for i in range(18):
        u = ease_in_out(prog(t, 1.8 + i * 0.12, 1.8 + i * 0.12 + 3.2)) * 0.95
        lane = rnd.uniform(-0.6, 0.6)
        walkers.append((u, lane, i))
    for u, lane, i in sorted(walkers, key=lambda w: -w[0]):
        if u <= 0:
            continue
        depth = (1 - u) ** 1.6
        y = lerp(y0, H + 20, depth)
        half = lerp(a, b, depth)
        s = lerp(0.18, 2.6, depth)
        figure(cr, W / 2 + lane * half * 0.8, y, s, hexc("#2a1620"), bob=abs(math.sin(t * 8 + i)) * 3)
    # Moses in the foreground: dip (anticipation), then staff raised high
    dip = math.sin(prog(t, 0.0, 0.6) * math.pi) * 0.35
    up = ease_out_back(prog(t, 0.45, 1.1), 2.2)
    mu = ease_in_out(prog(t, 2.6, 5.5)) * 0.35
    md = (1 - mu) ** 1.6
    figure(cr, W / 2 - lerp(0, 80, md), lerp(y0, H + 40, md), lerp(0.18, 3.0, md), hexc("#1a0e16"),
           arm=lerp(0.5, 2.7, up) - dip, staff=True, arm2=0.3)
    cr.restore()
    caption(cr, t, d, "Rescued from slavery", "Exodus 14", t_in=1.6)


def crown(cr, x, y, s, rot, sq):
    cr.save()
    cr.translate(x, y)
    cr.rotate(rot)
    cr.scale(s * (1 + sq), s * (1 - sq))
    pts = [(-90, 40), (-100, -50), (-50, 0), (0, -70), (50, 0), (100, -50), (90, 40)]
    poly(cr, pts, hexc("#f2c14e"))
    poly(cr, [(-90, 40), (90, 40), (86, 58), (-86, 58)], hexc("#d49a2a"))
    for jx, jc in ((-50, "#d8342c"), (0, "#3f86d6"), (50, "#2f9a5a")):
        circle(cr, jx, 30, 10, hexc(jc))
    for px, py in ((-100, -50), (0, -70), (100, -50)):
        circle(cr, px, py, 10, hexc("#fff0b0"))
    cr.restore()


def s_kings(cr, t, d):
    sky(cr, [(0, hexc("#3a1f14")), (0.6, hexc("#c07a33")), (1, hexc("#f6d38a"))])
    cr.save()
    camera(cr, lerp(1.05, 1.0, ease_out(t / d)))
    rays(cr, W / 2, H * 0.5, 16, 1400, t * 0.12, (1, 0.9, 0.6), 0.22)
    glow(cr, W / 2, H * 0.45, 600, (1, 0.9, 0.65), 0.35)
    gy = H * 0.82
    hill(cr, gy + 10, 8, 0.4, hexc("#6b3e1e"), f1=0.002)
    # temple builds itself: steps, then columns (staggered), then the roof drops
    for k in range(3):
        p = ease_out(prog(t, 0.1 + k * 0.1, 0.5 + k * 0.1))
        w = 820 - k * 60
        yy = gy - k * 22
        poly(cr, [(W / 2 - w / 2, yy), (W / 2 + w / 2, yy), (W / 2 + w / 2, yy - 22 * p), (W / 2 - w / 2, yy - 22 * p)],
             hexc("#e9d6ae") if k % 2 else hexc("#d9c095"))
    top = gy - 66
    for i in range(8):
        p = ease_out_back(prog(t, 0.45 + i * 0.07, 0.95 + i * 0.07), 1.6)
        if p <= 0:
            continue
        cx = W / 2 - 315 + i * 90
        h = 300 * p
        poly(cr, [(cx - 22, top), (cx + 22, top), (cx + 18, top - h), (cx - 18, top - h)], hexc("#f3e6c8"))
        poly(cr, [(cx - 28, top - h), (cx + 28, top - h), (cx + 28, top - h - 14 * p), (cx - 28, top - h - 14 * p)], hexc("#d9c095"))
    rp = ease_out_bounce(prog(t, 1.2, 2.1))
    if rp > 0:
        ry = lerp(-500, top - 314, rp)
        poly(cr, [(W / 2 - 390, ry), (W / 2 + 390, ry), (W / 2 + 390, ry - 30), (W / 2 - 390, ry - 30)], hexc("#e2cb9c"))
        poly(cr, [(W / 2 - 400, ry - 30), (W / 2, ry - 150), (W / 2 + 400, ry - 30)], hexc("#f0dfb8"))
    # prophets arrive on the steps
    for i, xf in enumerate((0.3, 0.7)):
        a = ease_out(prog(t, 1.6 + i * 0.2, 2.2 + i * 0.2))
        if a > 0:
            x = W * xf + (1 - a) * (-200 if i == 0 else 200)
            figure(cr, x, gy + 2, 1.8, hexc("#3a1e12"), bob=abs(math.sin(t * 8)) * 3 * (1 - a),
                   arm=lerp(0.3, 2.3, ease_out_back(prog(t, 2.4, 3.0))) if i == 0 else None,
                   arm2=lerp(0.3, 2.3, ease_out_back(prog(t, 2.6, 3.2))) if i == 1 else None)
    # the crown drops: gravity with squash on each impact
    cp = prog(t, 2.0, 3.0)
    if cp > 0:
        target = top - 520
        cy = lerp(-200, target, ease_out_bounce(cp))
        prox = max(0.0, 1 - abs(target - cy) / 30) * (1 - cp * 0.7)
        crown(cr, W / 2, cy, 1.1, math.sin(t * 3) * 0.04 * (1 - cp), 0.18 * prox)
        glow(cr, W / 2, cy, 260, (1, 0.9, 0.6), 0.35 * cp)
    cr.restore()
    caption(cr, t, d, "Kings, prophets & the temple", "1 Samuel – Malachi", t_in=0.8)


def s_nativity(cr, t, d):
    sky(cr, [(0, hexc("#050817")), (0.7, hexc("#1b2350")), (1, hexc("#3a3563"))])
    cr.save()
    camera(cr, lerp(1.0, 1.08, ease_in_out(t / d)), cy=H * 0.6)
    stars(cr, 180, 31, t, 0.7, y_max=H * 0.6)
    # the star travels along a curve with a fading trail
    def star_pos(u):
        u = ease_in_out(u)
        x = lerp(W * 0.08, W * 0.5, u)
        y = lerp(H * 0.08, H * 0.2, u) - math.sin(u * math.pi) * 90
        return x, y
    p = prog(t, 0.0, 2.2)
    for k in range(18):
        up = p - k * 0.012
        if up > 0 and p < 1:
            x, y = star_pos(up)
            circle(cr, x, y, 7 - k * 0.35, (1, 0.95, 0.8), 0.6 * (1 - k / 18))
    sx, sy = star_pos(p)
    arrive = prog(t, 2.1, 2.8)
    pulse = 1 + 0.12 * math.sin(t * 5) * arrive
    if arrive > 0:
        g = cairo.LinearGradient(0, sy, 0, H * 0.8)
        g.add_color_stop_rgba(0, 1, 0.95, 0.8, 0.35 * arrive)
        g.add_color_stop_rgba(1, 1, 0.95, 0.8, 0.0)
        cr.move_to(sx - 8, sy)
        cr.line_to(sx + 8, sy)
        cr.line_to(W / 2 + 190, H * 0.8)
        cr.line_to(W / 2 - 190, H * 0.8)
        cr.close_path()
        cr.set_source(g)
        cr.fill()
    rays(cr, sx, sy, 8, 180 * pulse * (0.4 + arrive), t * 0.3, (1, 0.95, 0.8), 0.6)
    glow(cr, sx, sy, 120 * pulse, (1, 0.95, 0.8), 0.8)
    circle(cr, sx, sy, 10, (1, 1, 0.95))
    # Bethlehem skyline, windows flicker
    town = hexc("#0a0b1c")
    rnd = random.Random(4)
    x = -60
    while x < W + 60:
        w = rnd.uniform(90, 170)
        h = rnd.uniform(60, 150)
        by = H * 0.8
        poly(cr, [(x, by), (x, by - h), (x + w, by - h), (x + w, by)], town)
        if rnd.random() < 0.35:
            cr.arc(x + w / 2, by - h, w * 0.3, math.pi, 0)
            src(cr, town)
            cr.fill()
        for _ in range(rnd.randint(0, 2)):
            wx, wy = x + rnd.uniform(15, w - 25), by - rnd.uniform(20, h - 20)
            f = 0.6 + 0.4 * math.sin(t * rnd.uniform(4, 9) + wx)
            poly(cr, [(wx, wy), (wx + 12, wy), (wx + 12, wy + 16), (wx, wy + 16)], (1, 0.75, 0.35), 0.8 * f)
        x += w + rnd.uniform(-10, 20)
    hill(cr, H * 0.86, 8, 1.3, hexc("#07081a"), f1=0.002)
    # stable and manger glow
    bx, by = W / 2, H * 0.86
    poly(cr, [(bx - 230, by), (bx - 230, by - 170), (bx, by - 260), (bx + 230, by - 170), (bx + 230, by)], hexc("#2a1c22"))
    poly(cr, [(bx - 190, by), (bx - 190, by - 150), (bx + 190, by - 150), (bx + 190, by)], hexc("#140e16"))
    glow(cr, bx, by - 30, 220 * (1 + 0.05 * math.sin(t * 4)), (1, 0.8, 0.45), 0.75)
    poly(cr, [(bx - 50, by), (bx - 40, by - 34), (bx + 40, by - 34), (bx + 50, by)], hexc("#3a2418"))
    circle(cr, bx, by - 40, 16, (1, 0.93, 0.78))
    figure(cr, bx - 110, by, 1.7, hexc("#1b3a6a"), kneel=True, head_tilt=1.5, arm=1.2)
    figure(cr, bx + 115, by, 1.9, hexc("#3a2616"), head_tilt=-1.2, arm2=0.5, staff=False)
    cr.restore()
    caption(cr, t, d, "Jesus, the Savior, is born", "Luke 2", t_in=1.2)


def s_ministry(cr, t, d):
    sky(cr, [(0, hexc("#5b9fe0")), (1, hexc("#fff1d0"))])
    cr.save()
    camera(cr, lerp(1.06, 1.0, ease_out(t / d)))
    cloud(cr, W * 0.2 + t * 14, H * 0.18, 1.1, (1, 1, 1), 0.85)
    cloud(cr, W * 0.8 + t * 9, H * 0.12, 0.9, (1, 1, 1), 0.8)
    hill(cr, H * 0.52, 26, 2.0, hexc("#7e9fb0"))
    # Sea of Galilee with moving shimmer
    poly(cr, [(-400, H * 0.54), (W + 400, H * 0.54), (W + 400, H * 0.75), (-400, H * 0.75)], hexc("#3f84b4"))
    rnd = random.Random(2)
    cr.set_line_width(2.5)
    for _ in range(40):
        x = (rnd.uniform(0, W) + t * rnd.uniform(15, 40)) % (W + 200) - 100
        y = rnd.uniform(H * 0.56, H * 0.73)
        cr.move_to(x, y)
        cr.line_to(x + rnd.uniform(20, 60), y)
        src(cr, (1, 1, 1), 0.3 + 0.3 * math.sin(t * 3 + x))
        cr.stroke()
    # fishing boat bobbing
    bx = W * 0.78 - t * 12
    by = H * 0.64 + math.sin(t * 2.2) * 5
    cr.save()
    cr.translate(bx, by)
    cr.rotate(math.sin(t * 2.2 - 0.6) * 0.04)
    poly(cr, [(-80, 0), (80, 0), (60, 26), (-60, 26)], hexc("#5a3a22"))
    poly(cr, [(0, -4), (0, -120), (60, -12)], hexc("#f5ecd8"))
    cr.restore()
    gy = H * 0.84
    hill(cr, gy, 26, 0.5, hexc("#5f9a4a"), f1=0.0025)
    jx = W * 0.5
    jy = ridge_y(jx, gy, 26, 0.5, 0.0025) - 34
    poly(cr, [(jx - 120, jy + 60), (jx - 60, jy), (jx + 60, jy), (jx + 120, jy + 60)], hexc("#6aa652"))
    # healing / teaching: rings of light radiate outward
    for k in range(3):
        rp = ((t * 0.55) + k / 3) % 1
        cr.set_line_width(4)
        cr.arc(jx, jy - 80, 60 + rp * 520, 0, 2 * math.pi)
        src(cr, (1, 0.97, 0.8), 0.45 * (1 - rp))
        cr.stroke()
    glow(cr, jx, jy - 80, 200, (1, 0.97, 0.85), 0.8)
    open_ = ease_out_back(prog(t, 0.6, 1.5), 1.8)
    figure(cr, jx, jy + 2, 2.3, (0.99, 0.97, 0.93), arm=lerp(0.2, 1.3, open_), arm2=lerp(0.2, 1.3, open_))
    # crowd walks in from both sides, then settles (ease-out + walk cycle)
    rnd = random.Random(12)
    cols = [hexc(h) for h in ("#8a3b2e", "#3b5a8a", "#6a5a2e", "#5a3a6a", "#2e6a5a", "#a0663a")]
    people = []
    for i in range(18):
        side = -1 if i % 2 == 0 else 1
        tx = jx + side * rnd.uniform(170, 800)
        depth = rnd.random()
        people.append((depth, tx, side, i, rnd.choice(cols)))
    for depth, tx, side, i, c in sorted(people):
        p = ease_out(prog(t, 0.2 + i * 0.07, 1.8 + i * 0.07))
        x = lerp(tx + side * 1100, tx, p)
        y = ridge_y(x, gy, 26, 0.5, 0.0025) + 20 + depth * 90
        s = 1.2 + depth * 0.8
        bob = abs(math.sin(t * 9 + i)) * 4 * (1 - p)
        look = -side * 1.5 * p
        figure(cr, x, y, s, c, bob=bob, head_tilt=look,
               arm=lerp(0.2, 2.4, ease_out_back(prog(t, 2.6 + i * 0.05, 3.1 + i * 0.05))) if i % 5 == 0 else None)
    cr.restore()
    caption(cr, t, d, "He teaches, heals & forgives", "Matthew – John", t_in=1.0)


def s_cross(cr, t, d):
    D = ease_in_out(prog(t, 0.8, 4.0))
    sky(cr, [(0, mix(hexc("#41161a"), hexc("#07030a"), D)), (0.7, mix(hexc("#d2552c"), hexc("#2a0a10"), D)),
             (1, mix(hexc("#ffb05a"), hexc("#4a1410"), D))])
    cr.save()
    camera(cr, lerp(1.0, 1.14, ease_in_out(t / d)), cy=H * 0.45)
    # the sun sinks and darkens ("darkness came over the whole land")
    sy = lerp(H * 0.6, H * 0.78, ease_in_out(t / d))
    glow(cr, W / 2, sy, 520, (1, 0.6, 0.3), 0.7 * (1 - D))
    circle(cr, W / 2, sy, 110, mix((1, 0.75, 0.45), (0.35, 0.08, 0.08), D))
    for i in range(6):
        x = (W * i / 5 + t * (30 + i * 8)) % (W + 600) - 300
        cloud(cr, x, H * (0.18 + (i % 3) * 0.08), 1.6, mix(hexc("#6a2a2a"), hexc("#140608"), D), 0.7)
    base = H * 0.78
    cr.move_to(-400, H + 400)
    cr.line_to(-400, base + 60)
    cr.curve_to(W * 0.25, base + 40, W * 0.38, base - 120, W / 2, base - 130)
    cr.curve_to(W * 0.62, base - 120, W * 0.75, base + 40, W + 400, base + 60)
    cr.line_to(W + 400, H + 400)
    cr.close_path()
    src(cr, hexc("#0d0608"))
    cr.fill()
    col = hexc("#0d0608")
    for cx, cyb, s in ((W / 2, base - 126, 1.0), (W / 2 - 300, base - 74, 0.72), (W / 2 + 300, base - 74, 0.72)):
        poly(cr, [(cx - 14 * s, cyb + 10), (cx - 14 * s, cyb - 420 * s), (cx + 14 * s, cyb - 420 * s), (cx + 14 * s, cyb + 10)], col)
        poly(cr, [(cx - 130 * s, cyb - 320 * s), (cx + 130 * s, cyb - 320 * s), (cx + 130 * s, cyb - 292 * s), (cx - 130 * s, cyb - 292 * s)], col)
    # wind through the grass
    cr.set_line_width(2)
    src(cr, col)
    rnd = random.Random(9)
    for _ in range(90):
        x = rnd.uniform(0, W)
        yb = H * 0.95 + rnd.uniform(0, 60)
        h = rnd.uniform(20, 55)
        sw = math.sin(t * 2.5 + x * 0.01) * 10
        cr.move_to(x, yb)
        cr.curve_to(x, yb - h * 0.5, x + sw * 0.5, yb - h * 0.8, x + sw, yb - h)
        cr.stroke()
    cr.restore()
    caption(cr, t, d, "He gave His life for us", "John 19  ·  Romans 5:8", t_in=1.0)


def s_resurrection(cr, t, d):
    S = ease_in_out(prog(t, 2.0, 4.2))
    sky(cr, [(0, mix(hexc("#0b1230"), hexc("#6fa8e0"), S)), (0.7, mix(hexc("#2a2a55"), hexc("#ffc4a0"), S)),
             (1, mix(hexc("#3a3060"), hexc("#fff0c0"), S))])
    cr.save()
    camera(cr, lerp(1.08, 1.0, ease_out(t / d)))
    # dawn: the sun rises behind the hills
    sp = ease_out(prog(t, 2.2, 4.6))
    glow(cr, W * 0.2, lerp(H * 0.9, H * 0.32, sp), 520, (1, 0.85, 0.55), 0.8 * sp)
    circle(cr, W * 0.2, lerp(H * 0.9, H * 0.32, sp), 70, (1, 0.95, 0.75), sp)
    stars(cr, 90, 41, t, 0.8 * (1 - S))
    hill(cr, H * 0.7, 30, 1.5, mix(hexc("#1a2140"), hexc("#7aa36a"), S))
    # rock tomb
    rock = mix(hexc("#2a2a3a"), hexc("#b3a58f"), S)
    ox, oy, orr = W * 0.6, H * 0.64, 120
    cr.move_to(W * 0.35, H * 0.86)
    cr.curve_to(W * 0.38, H * 0.38, W * 0.82, H * 0.36, W * 0.9, H * 0.86)
    cr.close_path()
    src(cr, rock)
    cr.fill()
    circle(cr, ox, oy, orr, hexc("#0a0a10"))
    # light pours out of the empty tomb
    L = ease_out(prog(t, 2.1, 3.2))
    if L > 0:
        cr.save()
        cr.arc(ox, oy, orr, 0, 2 * math.pi)
        cr.clip()
        fill_all(cr, (1, 0.97, 0.85), L)
        cr.restore()
        rays(cr, ox, oy, 20, 1500 * L, t * 0.25, (1, 0.96, 0.8), 0.35 * L)
        glow(cr, ox, oy, 380 * L, (1, 0.97, 0.85), 0.8 * L)
    # the stone: tremble -> rock back (anticipation) -> roll (rotation = distance / radius)
    tremble = math.sin(t * 55) * 3.5 * prog(t, 0.5, 1.4) * (1 - prog(t, 1.45, 1.5))
    back = -34 * ease_in_out(prog(t, 1.4, 1.8))
    roll = 330 * ease_in_out(prog(t, 1.8, 3.0))
    sx = ox + tremble + back + roll
    sr = orr + 14
    cr.save()
    cr.translate(sx, oy)
    cr.rotate((back + roll) / sr)
    circle(cr, 0, 0, sr, mix(hexc("#3c3a48"), hexc("#8c7f6c"), S))
    cr.set_line_width(5)
    src(cr, mix(hexc("#2a2834"), hexc("#6a604f"), S))
    cr.arc(0, 0, sr * 0.62, 0, 2 * math.pi)
    cr.stroke()
    cr.move_to(-sr * 0.6, 0)
    cr.line_to(sr * 0.6, 0)
    cr.stroke()
    cr.restore()
    gy = H * 0.86
    hill(cr, gy, 14, 0.2, mix(hexc("#141a30"), hexc("#4f8a44"), S), f1=0.002)
    # flowers bloom, staggered with overshoot
    rnd = random.Random(6)
    for i in range(16):
        x = rnd.uniform(40, W - 40)
        y = ridge_y(x, gy, 14, 0.2, 0.002) + rnd.uniform(20, 120)
        g = ease_out_back(prog(t, 2.9 + i * 0.07, 3.5 + i * 0.07), 2.5)
        if g <= 0:
            continue
        cr.set_line_width(3)
        src(cr, hexc("#2f6b30"))
        cr.move_to(x, y)
        cr.line_to(x, y - 40 * g)
        cr.stroke()
        c = hexc(rnd.choice(("#ffffff", "#f7d24a", "#f28ab0", "#b58cf0")))
        for k in range(5):
            ang = k * 2 * math.pi / 5 + t
            circle(cr, x + math.cos(ang) * 9 * g, y - 40 * g + math.sin(ang) * 9 * g, 7 * g, c)
        circle(cr, x, y - 40 * g, 5 * g, hexc("#f5a623"))
    cr.restore()
    caption(cr, t, d, "He is risen!", "Matthew 28  ·  1 Corinthians 15", t_in=2.3)


def s_church(cr, t, d):
    fill_all(cr, hexc("#060a1a"))
    stars(cr, 200, 51, t, 0.6, y_max=H)
    cr.save()
    camera(cr, lerp(0.92, 1.02, ease_out(t / d)), cy=H * 0.46)
    cx, cy, R = W / 2, H * 0.46, 330
    glow(cr, cx, cy, R * 1.6, (0.5, 0.7, 1.0), 0.35)
    g = cairo.RadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R)
    g.add_color_stop_rgb(0, *hexc("#3a88d0"))
    g.add_color_stop_rgb(1, *hexc("#0f2a5a"))
    cr.arc(cx, cy, R, 0, 2 * math.pi)
    cr.set_source(g)
    cr.fill()
    rot = t * 0.22 - 0.35

    def proj(lon, lat):
        x = cx + R * math.cos(lat) * math.sin(lon + rot)
        y = cy - R * math.sin(lat)
        z = math.cos(lat) * math.cos(lon + rot)
        return x, y, z

    # continents: blobs on the sphere
    cr.save()
    cr.arc(cx, cy, R, 0, 2 * math.pi)
    cr.clip()
    rnd = random.Random(14)
    for _ in range(46):
        lon, lat, r = rnd.uniform(-math.pi, math.pi), rnd.uniform(-1.0, 1.1), rnd.uniform(30, 70)
        x, y, z = proj(lon, lat)
        if z > 0:
            cr.save()
            cr.translate(x, y)
            cr.scale(max(0.05, z), 1)
            circle(cr, 0, 0, r, hexc("#3f8f5a"), 0.9)
            cr.restore()
    # lines of longitude for rotation cues
    cr.set_line_width(1.2)
    for k in range(12):
        lon = k * math.pi / 6
        pts = [proj(lon, la / 20 * math.pi - math.pi / 2) for la in range(21)]
        if any(p[2] > 0 for p in pts):
            cr.move_to(pts[0][0], pts[0][1])
            for p in pts[1:]:
                cr.line_to(p[0], p[1])
            src(cr, (1, 1, 1), 0.08)
            cr.stroke()
    cr.restore()
    # the Good News spreads from Jerusalem: arcs + glowing points, timed by distance
    origin = (0.35, 0.55)
    ox, oy, oz = proj(*origin)
    rnd = random.Random(15)
    for i in range(34):
        lon = origin[0] + rnd.uniform(-1.4, 1.4)
        lat = clamp(origin[1] + rnd.uniform(-1.1, 0.5), -1.2, 1.2)
        dist = math.hypot(lon - origin[0], lat - origin[1])
        t0 = 0.4 + dist * 1.3
        p = ease_in_out(prog(t, t0, t0 + 0.7))
        x, y, z = proj(lon, lat)
        if p <= 0 or z <= 0 or oz <= 0:
            continue
        mx, my = (ox + x) / 2, (oy + y) / 2
        nx, ny = mx - cx, my - cy
        nl = math.hypot(nx, ny) or 1
        lift = 40 + dist * 90
        qx, qy = mx + nx / nl * lift, my + ny / nl * lift
        cr.move_to(ox, oy)
        for k in range(1, 21):
            u = p * k / 20
            bx = (1 - u) ** 2 * ox + 2 * (1 - u) * u * qx + u * u * x
            by = (1 - u) ** 2 * oy + 2 * (1 - u) * u * qy + u * u * y
            cr.line_to(bx, by)
        cr.set_line_width(2.2)
        src(cr, GOLD, 0.8 * z)
        cr.stroke()
        pop = ease_out_back(prog(t, t0 + 0.6, t0 + 0.95), 3)
        if pop > 0:
            glow(cr, x, y, 34 * pop, (1, 0.85, 0.5), 0.8 * z)
            circle(cr, x, y, 5 * pop, (1, 0.97, 0.85), z)
    if oz > 0:
        glow(cr, ox, oy, 70 + 10 * math.sin(t * 6), (1, 0.8, 0.45), 0.9)
        circle(cr, ox, oy, 8, (1, 1, 0.9))
    cr.restore()
    caption(cr, t, d, "The Good News spreads", "Acts – Jude", t_in=0.7)


def s_new(cr, t, d):
    sky(cr, [(0, hexc("#7ab0e8")), (0.55, hexc("#ffe0a8")), (1, hexc("#fff6dc"))])
    cr.save()
    camera(cr, lerp(1.14, 1.0, ease_in_out(prog(t, 0, 3.6))), cy=H * 0.55)
    rays(cr, W / 2, H * 0.45, 22, 1600, t * 0.1, (1, 1, 0.9), 0.35)
    glow(cr, W / 2, H * 0.45, 800, (1, 0.97, 0.85), 0.8)
    hill(cr, H * 0.72, 18, 0.9, hexc("#8fc27a"))
    # the holy city comes down out of heaven (ease-out-back settle)
    drop = ease_out_back(prog(t, 0.1, 1.9), 0.8)
    oy = lerp(-760, 0, drop)
    wall_y = H * 0.7 + oy
    gold, light = hexc("#f2cf72"), hexc("#fff3c8")
    rnd = random.Random(16)
    for i in range(13):
        x = W / 2 - 600 + i * 100
        h = 120 + rnd.uniform(0, 220) + (220 if 5 <= i <= 7 else 0)
        poly(cr, [(x - 38, wall_y), (x - 38, wall_y - h), (x + 38, wall_y - h), (x + 38, wall_y)], light if i % 2 else gold)
        poly(cr, [(x - 44, wall_y - h), (x, wall_y - h - 50), (x + 44, wall_y - h)], gold)
        for k in range(int(h // 60)):
            poly(cr, [(x - 8, wall_y - 40 - k * 60), (x + 8, wall_y - 40 - k * 60), (x + 8, wall_y - 62 - k * 60), (x - 8, wall_y - 62 - k * 60)],
                 (1, 1, 1), 0.7)
    poly(cr, [(W / 2 - 660, wall_y + 2), (W / 2 - 660, wall_y - 110), (W / 2 + 660, wall_y - 110), (W / 2 + 660, wall_y + 2)], gold)
    for gx in (-440, -220, 0, 220, 440):
        cr.arc(W / 2 + gx, wall_y - 40, 34, math.pi, 0)
        cr.line_to(W / 2 + gx + 34, wall_y + 2)
        cr.line_to(W / 2 + gx - 34, wall_y + 2)
        cr.close_path()
        src(cr, (1, 1, 0.95))
        cr.fill()
    glow(cr, W / 2, wall_y - 120, 500, (1, 1, 0.9), 0.5 * drop)
    # river of life flows from the throne, with flowing highlights
    rp = ease_out(prog(t, 1.4, 2.6))
    if rp > 0:
        yb = lerp(wall_y, H + 20, rp)
        poly(cr, [(W / 2 - 34, wall_y), (W / 2 + 34, wall_y), (W / 2 + lerp(34, 300, rp), yb), (W / 2 - lerp(34, 300, rp), yb)], hexc("#7fd0f0"))
        cr.set_line_width(3)
        for k in range(14):
            u = ((t * 0.5 + k / 14) % 1)
            if H * 0.7 + u * (H * 0.3) > yb:
                continue
            yy = wall_y + u * (H + 20 - wall_y)
            hw = lerp(34, 300, u) * 0.7
            cr.move_to(W / 2 - hw * 0.5 + math.sin(k) * hw * 0.3, yy)
            cr.line_to(W / 2 - hw * 0.1 + math.sin(k) * hw * 0.3, yy)
            src(cr, (1, 1, 1), 0.7)
            cr.stroke()
    # tree of life on both banks, fruiting
    for i, x in enumerate((W / 2 - 520, W / 2 + 520, W / 2 - 820, W / 2 + 820)):
        g = ease_out_back(prog(t, 1.9 + i * 0.12, 2.5 + i * 0.12), 2)
        tree(cr, x, H * 0.97, 1.5 if i < 2 else 1.1, g, hexc("#5a3a22"), hexc("#3c9a4a"), t, fruit=hexc("#f5b43a"))
    cr.restore()
    caption(cr, t, d, "All things made new", "Revelation 21 – 22", t_in=1.4, t_out=3.9)
    # end card
    e = ease_in_out(prog(t, 3.8, 4.6))
    if e > 0:
        fill_all(cr, (0.03, 0.02, 0.05), 0.72 * e)
        glow(cr, W / 2, H / 2, 800, (1, 0.8, 0.45), 0.25 * e)
        letters_c(cr, "GOD'S STORY OF LOVE", W / 2, H / 2 - 10, 92, CREAM, t, 3.95, 0.035, spacing=8, bold=True)
        a = ease_out(prog(t, 4.6, 5.3))
        text_c(cr, "“Behold, I make all things new.”  — Revelation 21:5", W / 2, H / 2 + 80, 40, GOLD, a, italic=True)


SCENES = [
    (s_title, 3.5, None),
    (s_creation, 6.0, "Creation"),
    (s_fall, 5.0, "The Fall"),
    (s_flood, 5.0, "The Flood"),
    (s_abraham, 4.0, "Abraham"),
    (s_exodus, 5.5, "Exodus"),
    (s_kings, 4.5, "Kings"),
    (s_nativity, 4.5, "Jesus' Birth"),
    (s_ministry, 4.5, "Ministry"),
    (s_cross, 4.5, "The Cross"),
    (s_resurrection, 5.0, "Resurrection"),
    (s_church, 4.0, "The Church"),
    (s_new, 6.5, "New Creation"),
]

STARTS = []
_acc = 0.0
for i, (_, dur, _) in enumerate(SCENES):
    STARTS.append(_acc)
    _acc += dur - XF
TOTAL = STARTS[-1] + SCENES[-1][1]
NFRAMES = int(round(TOTAL * FPS))


# --------------------------------------------------------------------------
# Global overlays: story timeline, vignette, grain, fades
# --------------------------------------------------------------------------

def timeline(cr, T):
    labels = [s[2] for s in SCENES[1:]]
    n = len(labels)
    a = ease_out(prog(T, STARTS[1], STARTS[1] + 0.8)) * (1 - ease_in_out(prog(T, STARTS[-1] + 3.6, STARTS[-1] + 4.2)))
    if a <= 0:
        return
    # continuous marker position: owned interval of scene i is [start_i + XF/2, start_{i+1} + XF/2]
    pos = 0.0
    for i in range(1, len(SCENES)):
        s0 = STARTS[i] + XF / 2
        s1 = STARTS[i + 1] + XF / 2 if i + 1 < len(SCENES) else STARTS[i] + SCENES[i][1] - 1.5
        if T >= s0:
            pos = (i - 1) + clamp((T - s0) / (s1 - s0))
    pos = clamp(pos - 0.5, 0, n - 1)
    x0, x1, y = 150, W - 150, 54
    step = (x1 - x0) / (n - 1)
    g = cairo.LinearGradient(0, 0, 0, 120)
    g.add_color_stop_rgba(0, 0, 0, 0, 0.45 * a)
    g.add_color_stop_rgba(1, 0, 0, 0, 0)
    cr.rectangle(0, 0, W, 120)
    cr.set_source(g)
    cr.fill()
    cr.set_line_width(2)
    src(cr, CREAM, 0.3 * a)
    cr.move_to(x0, y)
    cr.line_to(x1, y)
    cr.stroke()
    cr.set_line_width(3)
    src(cr, GOLD, 0.9 * a)
    cr.move_to(x0, y)
    cr.line_to(x0 + pos * step, y)
    cr.stroke()
    set_font(cr, BODY_FONT, 21)
    for i, lab in enumerate(labels):
        x = x0 + i * step
        near = max(0.0, 1 - abs(pos - i))
        done = pos >= i - 0.02
        circle(cr, x, y, 5 + 3 * near, GOLD if done else CREAM, a * (0.95 if done else 0.45))
        w = cr.text_extents(lab).x_advance
        src(cr, mix(CREAM, GOLD, near), a * (0.5 + 0.5 * near))
        cr.move_to(x - w / 2, y + 34)
        cr.show_text(lab)
    mx = x0 + pos * step
    glow(cr, mx, y, 30, (1, 0.85, 0.5), a)
    circle(cr, mx, y, 6, (1, 0.98, 0.9), a)


_cache = {}


def overlays():
    if "vig" not in _cache:
        vig = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        c = cairo.Context(vig)
        g = cairo.RadialGradient(W / 2, H / 2, H * 0.45, W / 2, H / 2, W * 0.62)
        g.add_color_stop_rgba(0, 0, 0, 0, 0)
        g.add_color_stop_rgba(1, 0, 0, 0, 0.55)
        c.set_source(g)
        c.paint()
        grains = []
        rng = np.random.default_rng(1)
        for _ in range(6):
            gw, gh = W // 2, H // 2
            n = rng.integers(0, 256, (gh, gw), dtype=np.uint8)
            arr = np.empty((gh, gw, 4), dtype=np.uint8)
            arr[..., 0] = arr[..., 1] = arr[..., 2] = n
            arr[..., 3] = 255
            s = cairo.ImageSurface.create_for_data(bytearray(arr.tobytes()), cairo.FORMAT_ARGB32, gw, gh)
            grains.append(s)
        _cache["vig"], _cache["grain"] = vig, grains
    return _cache["vig"], _cache["grain"]


def draw_scene(surface, i, T):
    fn, dur, _ = SCENES[i]
    cr = cairo.Context(surface)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    fn(cr, T - STARTS[i], dur)


def render_frame(f, surf, tmp):
    T = f / FPS
    active = [i for i in range(len(SCENES)) if STARTS[i] <= T < STARTS[i] + SCENES[i][1]]
    if not active:
        active = [len(SCENES) - 1]
    draw_scene(surf, active[0], T)
    cr = cairo.Context(surf)
    if len(active) > 1:
        draw_scene(tmp, active[1], T)
        cr.set_source_surface(tmp, 0, 0)
        cr.paint_with_alpha(ease_in_out((T - STARTS[active[1]]) / XF))
    timeline(cr, T)
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
        fill_all(cr, (0, 0, 0), 1 - ease_in_out(fade))
    surf.flush()


def render_chunk(args):
    f0, f1, path = args
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    tmp = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "21",
           "-pix_fmt", "yuv420p", "-r", str(FPS), path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(f0, f1):
        render_frame(f, surf, tmp)
        proc.stdin.write(bytes(surf.get_data()))
    proc.stdin.close()
    proc.wait()
    return path


# --------------------------------------------------------------------------
# Soundtrack: a synthesised ambient pad that follows each scene's mood,
# with soft bell accents on key story beats.
# --------------------------------------------------------------------------

CHORDS = [
    [48, 55, 64, 67, 72], [41, 53, 60, 65, 69], [45, 52, 57, 60, 64], [38, 50, 57, 62, 65],
    [43, 55, 62, 67, 71], [40, 52, 59, 64, 67], [41, 53, 60, 65, 69, 72], [48, 55, 64, 67, 72, 76],
    [43, 55, 62, 67, 71, 74], [45, 52, 57, 60, 64], [48, 55, 64, 67, 72, 79], [41, 53, 60, 65, 69, 72],
    [48, 55, 64, 67, 72, 76, 79],
]
# (scene, local time, midi) accents on story beats
BELLS = [(0, 0.3, 84), (1, 1.2, 88), (3, 3.1, 84), (4, 0.5, 91), (5, 0.7, 79), (6, 2.8, 86),
         (7, 2.1, 88), (10, 2.0, 84), (10, 2.2, 91), (11, 0.5, 86), (12, 0.3, 88), (12, 3.9, 84), (12, 4.0, 91)]


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def make_audio(path, sr=48000):
    n = int(TOTAL * sr) + sr
    t = np.arange(n) / sr
    L = np.zeros(n)
    R = np.zeros(n)
    for i, notes in enumerate(CHORDS):
        s0 = STARTS[i] - 0.6
        s1 = STARTS[i] + SCENES[i][1] + 0.4
        a, b = max(0, int(s0 * sr)), min(n, int(s1 * sr))
        tt = t[a:b]
        env = np.clip((tt - s0) / 1.0, 0, 1) * np.clip((s1 - tt) / 1.0, 0, 1)
        env = np.sin(env * np.pi / 2) ** 2
        for j, m in enumerate(notes):
            f = midi_hz(m)
            amp = (0.07 if j == 0 else 0.045) * (0.8 if m > 76 else 1.0)
            trem = 1 + 0.15 * np.sin(2 * np.pi * (0.2 + j * 0.07) * tt + j)
            for det, ch in ((0.997, L), (1.003, R)):
                ph = 2 * np.pi * f * det * tt
                ch[a:b] += amp * env * trem * (np.sin(ph) + 0.22 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph))
    for sc, lt, m in BELLS:
        t0 = STARTS[sc] + lt
        a = int(t0 * sr)
        b = min(n, a + sr * 4)
        tt = t[a:b] - t0
        f = midi_hz(m)
        bell = sum(w * np.sin(2 * np.pi * f * k * tt) * np.exp(-tt * (1.2 + k * 0.9))
                   for k, w in ((1, 1.0), (2.01, 0.35), (2.76, 0.2), (5.4, 0.08)))
        bell *= np.clip(tt / 0.005, 0, 1) * 0.12
        L[a:b] += bell * 0.9
        R[a:b] += bell * 1.1
    # cheap reverb: a few feedback-free delays
    for ch in (L, R):
        wet = np.zeros_like(ch)
        for dly, g in ((0.043, 0.35), (0.071, 0.3), (0.113, 0.25), (0.157, 0.2), (0.233, 0.15)):
            k = int(dly * sr * (1.03 if ch is R else 1.0))
            wet[k:] += ch[:-k] * g
        ch += wet
    # master fades + normalise
    fade = np.clip(t / 0.8, 0, 1) * np.clip((TOTAL - t) / 1.5, 0, 1)
    L *= fade
    R *= fade
    peak = max(np.abs(L).max(), np.abs(R).max())
    stereo = np.stack([L, R], axis=1) / peak * 0.8
    pcm = (stereo[: int(TOTAL * sr)] * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main():
    args = sys.argv[1:]
    if "--preview" in args:
        k = args.index("--preview")
        times = [float(x) for x in args[k + 1:]]
        os.makedirs("preview", exist_ok=True)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        tmp = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        for tm in times:
            render_frame(int(tm * FPS), surf, tmp)
            surf.write_to_png(f"preview/t{tm:05.2f}.png")
        return
    out = args[0] if args else os.path.join(HERE, "the_story_of_the_bible.mp4")
    work = os.path.join(HERE, ".build")
    os.makedirs(work, exist_ok=True)
    print(f"{NFRAMES} frames, {TOTAL:.2f}s at {FPS} fps, {W}x{H}; fonts: {DISPLAY_FONT} / {BODY_FONT}")
    nproc = max(1, os.cpu_count() or 1)
    per = math.ceil(NFRAMES / nproc)
    chunks = [(i, min(NFRAMES, i + per), os.path.join(work, f"part{k:02d}.mp4"))
              for k, i in enumerate(range(0, NFRAMES, per))]
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
