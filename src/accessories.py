"""Things your pet can wear: a built-in wardrobe (drawn here, no image files) plus your own pictures.

Every accessory is painted in a unit box (1 wide, `aspect` tall, centred on the origin). Where it sits
on the pet is a small table in the config:
    x, y    centre, as a fraction of the pet's width / height (0,0 = top-left; may go outside 0..1)
    scale   width, as a fraction of the pet's height
    rotate  degrees clockwise
    flip    mirror it
    behind  draw it behind the pet instead of in front
always in the pet's facing-right frame (the facing-left sprite is a mirror of the whole thing).
"""
import datetime
import json
import math
import os

import cairo

import library

INK = (0.09, 0.08, 0.1)
LW = 0.04
LARRY_ANCHOR = (0.71, 0.19)   # top of Larry's head, which the defaults below are measured from
SCALE_MIN, SCALE_MAX = 0.04, 2.5


# ── drawing helpers ─────────────────────────────────────────────────────────
def inked(cr, fill, lw=LW):
    cr.set_source_rgb(*fill)
    cr.fill_preserve()
    cr.set_source_rgb(*INK)
    cr.set_line_width(lw)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.stroke()


def ellipse(cr, cx, cy, rx, ry):
    cr.save()
    cr.translate(cx, cy)
    cr.scale(rx, ry)
    cr.new_sub_path()
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()


def circle(cr, cx, cy, r):
    cr.new_sub_path()
    cr.arc(cx, cy, r, 0, 2 * math.pi)


def rrect(cr, x0, y0, x1, y1, r):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    cr.new_sub_path()
    cr.arc(x1 - r, y0 + r, r, -math.pi / 2, 0)
    cr.arc(x1 - r, y1 - r, r, 0, math.pi / 2)
    cr.arc(x0 + r, y1 - r, r, math.pi / 2, math.pi)
    cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def poly(cr, *pts):
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    cr.close_path()


def star(cr, cx, cy, r, points=5):
    for i in range(points * 2):
        a = -math.pi / 2 + i * math.pi / points
        rr = r if i % 2 == 0 else r * 0.45
        (cr.move_to if i == 0 else cr.line_to)(cx + rr * math.cos(a), cy + rr * math.sin(a))
    cr.close_path()


def mirrored(cr, draw):
    """draw() once as is and once mirrored left<->right."""
    draw()
    cr.save()
    cr.scale(-1, 1)
    draw()
    cr.restore()


def shine(cr, x0, y0, x1, y1, w=0.05, a=0.35):
    cr.set_source_rgba(1, 1, 1, a)
    cr.set_line_width(w)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.move_to(x0, y0)
    cr.line_to(x1, y1)
    cr.stroke()


# ── the wardrobe ────────────────────────────────────────────────────────────
def top_hat(cr):
    dark = (0.17, 0.17, 0.2)
    ellipse(cr, 0, 0.34, 0.5, 0.09)
    inked(cr, dark)
    poly(cr, (-0.27, 0.34), (-0.31, -0.4), (0.31, -0.4), (0.27, 0.34))
    inked(cr, dark)
    poly(cr, (-0.282, 0.12), (-0.276, 0.26), (0.276, 0.26), (0.282, 0.12))
    inked(cr, (0.78, 0.16, 0.22))
    ellipse(cr, 0, -0.4, 0.31, 0.055)
    inked(cr, (0.26, 0.26, 0.3))
    shine(cr, -0.19, -0.3, -0.17, 0.06)


def party_hat(cr):
    poly(cr, (-0.38, 0.5), (0.38, 0.5), (0, -0.42))
    cr.save()
    cr.clip_preserve()
    cr.set_source_rgb(0.98, 0.42, 0.62)
    cr.fill()
    cr.set_source_rgb(1.0, 0.85, 0.3)
    for k in range(-3, 4):
        y = k * 0.26
        poly(cr, (-1, y + 0.3), (1, y - 0.1), (1, y + 0.02), (-1, y + 0.42))
        cr.fill()
    cr.restore()
    poly(cr, (-0.38, 0.5), (0.38, 0.5), (0, -0.42))
    cr.set_source_rgb(*INK)
    cr.set_line_width(LW)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.stroke()
    circle(cr, 0, -0.46, 0.12)
    inked(cr, (0.45, 0.85, 0.95))


def crown(cr):
    gold = (0.98, 0.78, 0.2)
    for x, y in ((-0.48, -0.2), (0, -0.3), (0.48, -0.2)):
        circle(cr, x, y - 0.04, 0.055)
        inked(cr, gold)
    poly(cr, (-0.44, 0.28), (-0.48, -0.2), (-0.23, 0.02), (0, -0.3), (0.23, 0.02), (0.48, -0.2), (0.44, 0.28))
    inked(cr, gold)
    poly(cr, (-0.455, 0.12), (0.455, 0.12), (0.44, 0.28), (-0.44, 0.28))
    inked(cr, (0.9, 0.58, 0.12))
    for x, r, c in ((-0.27, 0.045, (0.25, 0.5, 0.95)), (0, 0.055, (0.9, 0.15, 0.25)), (0.27, 0.045, (0.2, 0.75, 0.4))):
        circle(cr, x, 0.2, r)
        inked(cr, c, LW * 0.7)
    shine(cr, -0.3, -0.02, -0.36, -0.1, 0.04, 0.5)


def cowboy_hat(cr):
    brown, band = (0.62, 0.4, 0.22), (0.32, 0.2, 0.12)
    cr.move_to(-0.25, 0.12)
    cr.curve_to(-0.29, -0.18, -0.2, -0.27, -0.08, -0.21)
    cr.curve_to(-0.02, -0.17, 0.02, -0.17, 0.08, -0.21)
    cr.curve_to(0.2, -0.27, 0.29, -0.18, 0.25, 0.12)
    cr.close_path()
    inked(cr, brown)
    poly(cr, (-0.262, 0.0), (0.262, 0.0), (0.256, 0.08), (-0.256, 0.08))
    inked(cr, band)
    cr.move_to(-0.5, -0.04)
    cr.curve_to(-0.36, 0.26, 0.36, 0.26, 0.5, -0.04)
    cr.curve_to(0.3, 0.1, -0.3, 0.1, -0.5, -0.04)
    cr.close_path()
    inked(cr, brown)


def beanie(cr):
    blue = (0.26, 0.56, 0.88)
    circle(cr, 0, -0.27, 0.12)
    inked(cr, (0.96, 0.96, 0.98))
    cr.move_to(-0.39, 0.15)
    cr.curve_to(-0.4, -0.33, 0.4, -0.33, 0.39, 0.15)
    cr.close_path()
    inked(cr, blue)
    rrect(cr, -0.44, 0.07, 0.44, 0.32, 0.07)
    inked(cr, (0.18, 0.42, 0.72))
    cr.set_source_rgba(*INK, 0.35)
    cr.set_line_width(LW * 0.6)
    for i in range(1, 9):
        x = -0.44 + i * 0.88 / 9
        cr.move_to(x, 0.11)
        cr.line_to(x, 0.28)
    cr.stroke()


def wizard_hat(cr):
    purple = (0.38, 0.24, 0.66)
    ellipse(cr, 0, 0.5, 0.5, 0.1)
    inked(cr, purple)
    cr.move_to(-0.28, 0.5)
    cr.curve_to(-0.22, 0.1, -0.1, -0.35, 0.22, -0.62)
    cr.curve_to(0.05, -0.3, 0.2, 0.1, 0.28, 0.5)
    cr.close_path()
    inked(cr, purple)
    yellow = (1.0, 0.86, 0.3)
    for x, y, r in ((-0.08, 0.22, 0.09), (0.08, -0.08, 0.065), (0.12, 0.38, 0.05), (-0.13, 0.42, 0.04)):
        star(cr, x, y, r)
        inked(cr, yellow, LW * 0.5)


def chef_hat(cr):
    for cx, cy, r in ((-0.25, -0.05, 0.22), (0.25, -0.05, 0.22), (0, -0.2, 0.28)):
        circle(cr, cx, cy, r)
    rrect(cr, -0.3, 0.0, 0.3, 0.46, 0.04)
    cr.set_source_rgb(*INK)
    cr.set_line_width(LW * 2)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.stroke_preserve()                   # thick outline first, then fill: one merged outline
    cr.set_source_rgb(0.98, 0.98, 0.98)
    cr.fill()
    cr.set_source_rgb(*INK)
    cr.set_line_width(LW)
    cr.move_to(-0.3, 0.16)
    cr.line_to(0.3, 0.16)
    cr.stroke()
    cr.set_source_rgba(*INK, 0.3)
    for x in (-0.15, 0, 0.15):
        cr.move_to(x, 0.0)
        cr.line_to(x, 0.12)
    cr.stroke()


def grad_cap(cr):
    dark = (0.15, 0.15, 0.18)
    cr.move_to(-0.27, -0.04)
    cr.line_to(0.27, -0.04)
    cr.line_to(0.25, 0.22)
    cr.curve_to(0.1, 0.28, -0.1, 0.28, -0.25, 0.22)
    cr.close_path()
    inked(cr, dark)
    poly(cr, (0, -0.28), (0.5, -0.1), (0, 0.08), (-0.5, -0.1))
    inked(cr, (0.22, 0.22, 0.26))
    gold = (1.0, 0.78, 0.22)
    cr.set_source_rgb(*gold)
    cr.set_line_width(LW * 0.9)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.move_to(0, -0.1)
    cr.line_to(0.36, -0.04)
    cr.line_to(0.38, 0.14)
    cr.stroke()
    rrect(cr, 0.34, 0.12, 0.42, 0.27, 0.02)
    inked(cr, gold, LW * 0.6)
    circle(cr, 0, -0.1, 0.035)
    inked(cr, gold, LW * 0.6)


def viking_helmet(cr):
    def horn():
        cr.move_to(-0.29, 0.06)
        cr.curve_to(-0.45, 0.02, -0.53, -0.15, -0.48, -0.3)
        cr.curve_to(-0.4, -0.2, -0.33, -0.13, -0.2, -0.08)
        cr.close_path()
        inked(cr, (0.96, 0.91, 0.78))
    mirrored(cr, horn)
    cr.move_to(-0.32, 0.2)
    cr.curve_to(-0.32, -0.27, 0.32, -0.27, 0.32, 0.2)
    cr.close_path()
    inked(cr, (0.66, 0.69, 0.75))
    bronze = (0.78, 0.56, 0.26)
    rrect(cr, -0.045, -0.14, 0.045, 0.16, 0.02)
    inked(cr, bronze, LW * 0.7)
    rrect(cr, -0.36, 0.13, 0.36, 0.27, 0.04)
    inked(cr, bronze)
    cr.set_source_rgb(*INK)
    for x in (-0.25, -0.12, 0.12, 0.25):
        circle(cr, x, 0.2, 0.018)
    cr.fill()
    shine(cr, -0.18, -0.06, -0.24, 0.06)


def halo(cr):
    ellipse(cr, 0, 0, 0.42, 0.1)
    cr.set_source_rgba(1.0, 0.9, 0.4, 0.3)
    cr.set_line_width(0.14)
    cr.stroke_preserve()
    cr.set_source_rgb(1.0, 0.84, 0.25)
    cr.set_line_width(0.06)
    cr.stroke()


def devil_horns(cr):
    def horn():
        cr.move_to(-0.38, 0.2)
        cr.curve_to(-0.43, -0.03, -0.41, -0.12, -0.48, -0.22)
        cr.curve_to(-0.3, -0.18, -0.2, 0.0, -0.2, 0.2)
        cr.close_path()
        inked(cr, (0.86, 0.16, 0.16))
    mirrored(cr, horn)


def sunglasses(cr):
    def lens(cx):
        cr.move_to(cx - 0.2, -0.1)
        cr.line_to(cx + 0.2, -0.1)
        cr.curve_to(cx + 0.2, 0.08, cx + 0.12, 0.14, cx, 0.14)
        cr.curve_to(cx - 0.12, 0.14, cx - 0.2, 0.08, cx - 0.2, -0.1)
        cr.close_path()
        inked(cr, (0.07, 0.07, 0.1))
        shine(cr, cx - 0.1, -0.04, cx - 0.03, 0.06, 0.035, 0.55)
    lens(-0.26)
    lens(0.26)
    cr.set_source_rgb(*INK)
    cr.set_line_width(0.05)
    cr.move_to(-0.48, -0.1)
    cr.line_to(0.48, -0.1)
    cr.stroke()


def nerd_glasses(cr):
    for cx in (-0.25, 0.25):
        circle(cr, cx, 0, 0.16)
        cr.set_source_rgba(0.7, 0.88, 1.0, 0.35)
        cr.fill_preserve()
        cr.set_source_rgb(*INK)
        cr.set_line_width(0.06)
        cr.stroke()
        shine(cr, cx - 0.08, -0.06, cx - 0.02, -0.1, 0.03, 0.7)
    cr.set_source_rgb(*INK)
    cr.set_line_width(0.05)
    cr.arc(0, 0.02, 0.09, math.pi * 1.15, math.pi * 1.85)
    cr.stroke()
    cr.move_to(-0.41, -0.02)
    cr.line_to(-0.5, -0.06)
    cr.move_to(0.41, -0.02)
    cr.line_to(0.5, -0.06)
    cr.stroke()


def bow_tie(cr):
    red = (0.82, 0.13, 0.22)
    mirrored(cr, lambda: (poly(cr, (-0.06, 0), (-0.45, -0.21), (-0.45, 0.21)), inked(cr, red)))
    rrect(cr, -0.09, -0.11, 0.09, 0.11, 0.04)
    inked(cr, (0.65, 0.08, 0.16))


def hair_bow(cr):
    pink = (0.98, 0.46, 0.66)

    def side():
        cr.move_to(-0.03, 0.05)
        cr.line_to(-0.2, 0.28)
        cr.line_to(-0.08, 0.27)
        cr.line_to(0.0, 0.08)
        cr.close_path()
        inked(cr, pink)
        cr.move_to(0, 0)
        cr.curve_to(-0.2, -0.36, -0.52, -0.3, -0.46, 0)
        cr.curve_to(-0.52, 0.3, -0.2, 0.32, 0, 0)
        inked(cr, pink)
    mirrored(cr, side)
    circle(cr, 0, 0, 0.085)
    inked(cr, (0.9, 0.3, 0.52))


def flower(cr):
    for i in range(5):
        cr.save()
        cr.rotate(i * 2 * math.pi / 5)
        ellipse(cr, 0, -0.24, 0.15, 0.22)
        cr.restore()
        inked(cr, (1.0, 0.72, 0.82))
    circle(cr, 0, 0, 0.14)
    inked(cr, (1.0, 0.82, 0.25))


# key: (title, aspect, painter, Larry's placement (x, y, scale))
PREMADE = {
    "top_hat":   ("Top hat", 0.9, top_hat, (0.71, 0.05, 0.34)),
    "party_hat": ("Party hat", 1.2, party_hat, (0.71, 0.04, 0.26)),
    "crown":     ("Crown", 0.65, crown, (0.71, 0.11, 0.3)),
    "cowboy":    ("Cowboy hat", 0.55, cowboy_hat, (0.71, 0.09, 0.5)),
    "beanie":    ("Beanie", 0.8, beanie, (0.71, 0.1, 0.34)),
    "wizard":    ("Wizard hat", 1.3, wizard_hat, (0.71, -0.06, 0.42)),
    "chef":      ("Chef hat", 1.0, chef_hat, (0.71, 0.05, 0.32)),
    "grad_cap":  ("Grad cap", 0.6, grad_cap, (0.71, 0.1, 0.42)),
    "viking":    ("Viking helmet", 0.6, viking_helmet, (0.71, 0.1, 0.44)),
    "halo":      ("Halo", 0.3, halo, (0.71, -0.06, 0.32)),
    "horns":     ("Devil horns", 0.45, devil_horns, (0.71, 0.12, 0.34)),
    "sunglasses": ("Sunglasses", 0.35, sunglasses, (0.705, 0.33, 0.32)),
    "glasses":   ("Nerd glasses", 0.35, nerd_glasses, (0.705, 0.33, 0.3)),
    "bow_tie":   ("Bow tie", 0.5, bow_tie, (0.68, 0.67, 0.2)),
    "bow":       ("Bow", 0.6, hair_bow, (0.59, 0.2, 0.18)),
    "flower":    ("Flower", 1.0, flower, (0.89, 0.19, 0.13)),
}


# ── seasonal: only claimable around their holiday, yours forever once claimed ──
def heart(cr, cx, cy, r):
    cr.move_to(cx, cy + r * 0.9)
    cr.curve_to(cx - r * 1.3, cy + r * 0.05, cx - r * 0.9, cy - r * 1.05, cx, cy - r * 0.35)
    cr.curve_to(cx + r * 0.9, cy - r * 1.05, cx + r * 1.3, cy + r * 0.05, cx, cy + r * 0.9)
    cr.close_path()


def tube(cr, pts, w, colour):
    """A thick inked stroke (antlers, stalks)."""
    for width, c in ((w + LW * 2, INK), (w, colour)):
        cr.set_source_rgb(*c)
        cr.set_line_width(width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for a, b in pts:
            cr.move_to(*a)
            cr.line_to(*b)
        cr.stroke()


def pumpkin(cr):
    orange, deep = (0.98, 0.55, 0.16), (0.9, 0.42, 0.1)
    tube(cr, [((0.0, -0.24), (0.06, -0.42))], 0.07, (0.42, 0.3, 0.16))
    cr.move_to(0.04, -0.33)
    cr.curve_to(0.18, -0.46, 0.32, -0.38, 0.3, -0.3)
    cr.curve_to(0.2, -0.26, 0.1, -0.28, 0.04, -0.33)
    inked(cr, (0.38, 0.68, 0.3), LW * 0.8)
    for cx, rx in ((-0.25, 0.22), (0.25, 0.22)):
        ellipse(cr, cx, 0.06, rx, 0.3)
        inked(cr, deep)
    ellipse(cr, 0, 0.05, 0.25, 0.32)
    inked(cr, orange)
    glow = (1.0, 0.86, 0.3)
    for sx in (-1, 1):
        poly(cr, (sx * 0.1, 0.0), (sx * 0.26, 0.0), (sx * 0.19, -0.13))
        inked(cr, glow, LW * 0.7)
    cr.move_to(-0.19, 0.08)
    cr.curve_to(-0.12, 0.3, 0.12, 0.3, 0.19, 0.08)
    cr.curve_to(0.08, 0.15, -0.08, 0.15, -0.19, 0.08)
    cr.close_path()
    inked(cr, glow, LW * 0.7)
    for x in (-0.07, 0.05):                  # two snaggle teeth
        rrect(cr, x, 0.12, x + 0.05, 0.18, 0.01)
        inked(cr, orange, LW * 0.6)
    shine(cr, -0.14, -0.16, -0.18, -0.04, 0.04, 0.4)


def witch_hat(cr):
    dark = (0.22, 0.17, 0.3)
    ellipse(cr, 0, 0.44, 0.5, 0.1)
    inked(cr, dark)
    cr.move_to(-0.27, 0.44)
    cr.curve_to(-0.22, 0.05, -0.12, -0.25, 0.0, -0.38)
    cr.curve_to(0.12, -0.5, 0.26, -0.5, 0.36, -0.42)
    cr.curve_to(0.22, -0.4, 0.12, -0.3, 0.1, -0.15)
    cr.curve_to(0.12, 0.1, 0.2, 0.3, 0.27, 0.44)
    cr.close_path()
    inked(cr, dark)
    cr.move_to(-0.255, 0.3)
    cr.line_to(0.25, 0.3)
    cr.line_to(0.27, 0.43)
    cr.curve_to(0.1, 0.47, -0.1, 0.47, -0.268, 0.43)
    cr.close_path()
    inked(cr, (0.95, 0.52, 0.16))
    rrect(cr, -0.08, 0.28, 0.08, 0.46, 0.02)
    inked(cr, (1.0, 0.82, 0.25), LW * 0.8)
    rrect(cr, -0.035, 0.32, 0.035, 0.42, 0.01)
    inked(cr, (0.95, 0.52, 0.16), LW * 0.6)
    shine(cr, -0.14, 0.2, -0.06, -0.12)


def santa_hat(cr):
    red = (0.86, 0.16, 0.2)
    cr.move_to(-0.36, 0.24)
    cr.curve_to(-0.3, -0.2, 0.0, -0.42, 0.24, -0.32)
    cr.curve_to(0.4, -0.25, 0.44, -0.05, 0.4, 0.06)
    cr.curve_to(0.3, -0.06, 0.24, -0.06, 0.2, 0.0)
    cr.line_to(0.36, 0.24)
    cr.close_path()
    inked(cr, red)
    shine(cr, -0.2, 0.06, -0.08, -0.2)
    for cx, cy, r in ((0.38, 0.12, 0.1),):
        circle(cr, cx, cy, r)
        inked(cr, (0.98, 0.98, 0.98))
    cr.move_to(-0.44, 0.22)
    for i in range(9):
        x = -0.44 + i * 0.11
        cr.curve_to(x + 0.02, 0.17, x + 0.09, 0.17, x + 0.11, 0.21 + (0.01 if i % 2 else -0.01))
    cr.curve_to(0.5, 0.33, 0.47, 0.44, 0.42, 0.44)
    for i in range(9):
        x = 0.42 - i * 0.107
        cr.curve_to(x - 0.02, 0.48, x - 0.09, 0.48, x - 0.107, 0.44)
    cr.curve_to(-0.5, 0.42, -0.5, 0.26, -0.44, 0.22)
    cr.close_path()
    inked(cr, (0.98, 0.98, 0.98))


def antlers(cr):
    brown = (0.6, 0.4, 0.24)

    def side():
        tube(cr, [((-0.13, 0.26), (-0.27, 0.0)), ((-0.27, 0.0), (-0.38, -0.24)),
                  ((-0.24, -0.06), (-0.1, -0.22)), ((-0.33, -0.14), (-0.48, -0.1)),
                  ((-0.37, -0.22), (-0.3, -0.36))], 0.065, brown)
    mirrored(cr, side)
    for sx in (-1, 1):                      # little furry bases
        ellipse(cr, sx * 0.14, 0.27, 0.08, 0.05)
        inked(cr, (0.48, 0.3, 0.18), LW * 0.8)


def star_glasses(cr):
    gold = (1.0, 0.8, 0.22)
    for cx in (-0.25, 0.25):
        star(cr, cx, 0.0, 0.25)
        inked(cr, gold)
        circle(cr, cx, 0.02, 0.09)
        inked(cr, (0.12, 0.1, 0.18), LW * 0.7)
        shine(cr, cx - 0.04, -0.02, cx - 0.01, -0.05, 0.025, 0.7)
    for x, y, r, c in ((-0.05, -0.17, 0.03, (0.98, 0.45, 0.66)), (0.48, -0.17, 0.035, (0.45, 0.85, 0.95)),
                       (-0.47, 0.14, 0.03, (0.6, 0.9, 0.45))):
        star(cr, x, y, r * 1.6)
        cr.set_source_rgb(*c)
        cr.fill()


def heart_boppers(cr):
    pink = (0.98, 0.4, 0.58)
    cr.set_source_rgb(*INK)
    cr.set_line_width(0.025)
    for sx in (-1, 1):                      # springy stalks
        cr.move_to(sx * 0.2, 0.28)
        for i in range(1, 7):
            cr.line_to(sx * (0.2 + 0.03 * i / 6) + (0.035 if i % 2 else -0.035), 0.28 - i * 0.065)
        cr.stroke()
    cr.arc(0, 0.62, 0.42, math.pi * 1.22, math.pi * 1.78)
    tube_path = cr.copy_path()
    cr.new_path()
    for w, c in ((0.08 + LW * 2, INK), (0.08, pink)):
        cr.append_path(tube_path)
        cr.set_source_rgb(*c)
        cr.set_line_width(w)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.stroke()
    for sx in (-1, 1):
        heart(cr, sx * 0.25, -0.2, 0.17)
        inked(cr, (0.92, 0.18, 0.34))
        shine(cr, sx * 0.25 - 0.08, -0.26, sx * 0.25 - 0.05, -0.2, 0.03, 0.55)


def lucky_hat(cr):
    green, dark = (0.2, 0.62, 0.32), (0.13, 0.44, 0.22)
    ellipse(cr, 0, 0.3, 0.5, 0.1)
    inked(cr, green)
    poly(cr, (-0.28, 0.3), (-0.32, -0.3), (0.32, -0.3), (0.28, 0.3))
    inked(cr, green)
    ellipse(cr, 0, -0.3, 0.32, 0.055)
    inked(cr, dark)
    poly(cr, (-0.29, 0.1), (-0.285, 0.24), (0.285, 0.24), (0.29, 0.1))
    inked(cr, (0.14, 0.12, 0.12))
    rrect(cr, -0.08, 0.08, 0.08, 0.26, 0.02)
    inked(cr, (1.0, 0.8, 0.22), LW * 0.8)
    rrect(cr, -0.035, 0.12, 0.035, 0.22, 0.01)
    inked(cr, (0.14, 0.12, 0.12), LW * 0.5)
    for i in range(3):                       # a shamrock tucked in the band
        cr.save()
        cr.translate(0.22, 0.02)
        cr.rotate(-0.3 + i * 2 * math.pi / 3)
        heart(cr, 0, -0.07, 0.07)
        cr.restore()
        inked(cr, (0.45, 0.85, 0.4), LW * 0.6)
    shine(cr, -0.2, -0.2, -0.18, 0.04)


def bunny_ears(cr):
    def ear():
        cr.save()
        cr.translate(-0.17, 0.16)
        cr.rotate(-0.22)
        ellipse(cr, 0, -0.2, 0.13, 0.32)
        inked(cr, (0.98, 0.97, 0.96))
        ellipse(cr, 0, -0.17, 0.06, 0.23)
        cr.set_source_rgb(1.0, 0.7, 0.78)
        cr.fill()
        cr.restore()
    mirrored(cr, ear)
    cr.arc(0, 0.75, 0.42, math.pi * 1.25, math.pi * 1.75)
    path = cr.copy_path()
    cr.new_path()
    for w, c in ((0.07 + LW * 2, INK), (0.07, (1.0, 0.7, 0.78))):
        cr.append_path(path)
        cr.set_source_rgb(*c)
        cr.set_line_width(w)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.stroke()


# key: (title, (month, day) first day, (month, day) last day)
SEASONS = {
    "halloween": ("Halloween", (10, 15), (11, 3)),
    "christmas": ("Christmas", (12, 1), (12, 27)),
    "newyear":   ("New Year", (12, 28), (1, 7)),
    "valentine": ("Valentine's Day", (2, 7), (2, 16)),
    "stpatrick": ("St. Patrick's Day", (3, 10), (3, 20)),
    "spring":    ("Spring", (3, 25), (4, 25)),
}
# key: (title, aspect, painter, Larry's placement (x, y, scale), season)
SEASONAL = {
    "pumpkin":       ("Pumpkin", 1.0, pumpkin, (0.71, 0.04, 0.36), "halloween"),
    "witch_hat":     ("Witch hat", 1.0, witch_hat, (0.71, -0.02, 0.46), "halloween"),
    "santa_hat":     ("Santa hat", 0.95, santa_hat, (0.71, 0.06, 0.38), "christmas"),
    "antlers":       ("Antlers", 0.7, antlers, (0.71, 0.06, 0.42), "christmas"),
    "star_glasses":  ("Star glasses", 0.55, star_glasses, (0.705, 0.35, 0.38), "newyear"),
    "heart_boppers": ("Heart boppers", 0.95, heart_boppers, (0.71, 0.06, 0.36), "valentine"),
    "lucky_hat":     ("Lucky hat", 0.75, lucky_hat, (0.71, 0.05, 0.38), "stpatrick"),
    "bunny_ears":    ("Bunny ears", 1.15, bunny_ears, (0.71, -0.02, 0.36), "spring"),
}
CLAIMS = library.ROOT / "claimed.json"


def _window(season, today):
    """(first, last) dates of this season's window that today is in or comes before."""
    _t, (m0, d0), (m1, d1) = SEASONS[season]
    for year in (today.year - 1, today.year):
        first = datetime.date(year, m0, d0)
        last = datetime.date(year + ((m1, d1) < (m0, d0)), m1, d1)
        if today <= last:
            return first, last
    return datetime.date(today.year + 1, m0, d0), datetime.date(today.year + 1 + ((m1, d1) < (m0, d0)), m1, d1)


def in_season(season, today=None):
    today = today or datetime.date.today()
    first, last = _window(season, today)
    return first <= today <= last


def season_ends(season, today=None):
    return _window(season, today or datetime.date.today())[1]


def season_starts(season, today=None):
    """The next first day of the season (today's window if it hasn't started yet)."""
    today = today or datetime.date.today()
    first, last = _window(season, today)
    if first <= today:
        first = datetime.date(first.year + 1, first.month, first.day)
    return first


def _load_claims():
    try:
        with open(CLAIMS) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_claims(data):
    try:
        CLAIMS.parent.mkdir(parents=True, exist_ok=True)
        tmp = CLAIMS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, CLAIMS)
    except OSError:
        pass


def claimed(acc_id):
    return acc_id in (_load_claims().get("claimed") or {})


def claimable(acc_id):
    return acc_id in SEASONAL and not claimed(acc_id) and in_season(SEASONAL[acc_id][4])


def claim(acc_id):
    """Keep it for good. Only works while its season is on."""
    if not claimable(acc_id):
        return False
    data = _load_claims()
    data.setdefault("claimed", {})[acc_id] = datetime.date.today().isoformat()
    _save_claims(data)
    return True


def owned_seasonal():
    have = _load_claims().get("claimed") or {}
    return [k for k in SEASONAL if k in have]


def new_season():
    """The season with something left to claim that hasn't been announced yet this year, or None.
    Marks it announced."""
    data = _load_claims()
    have = data.get("claimed") or {}
    told = data.setdefault("announced", [])
    for season in SEASONS:
        if not in_season(season):
            continue
        tag = f"{season}-{season_ends(season).year}"
        if tag in told or all(k in have for k, v in SEASONAL.items() if v[4] == season):
            continue
        told.append(tag)
        data["announced"] = told[-24:]
        _save_claims(data)
        return season
    return None


# ── weather: put on by the pet itself when it rains, snows or gets cold (never in your wardrobe) ──
def umbrella_hat(cr):
    """A little umbrella on a headband: keeps the rain off without needing hands."""
    red, white = (0.92, 0.27, 0.3), (0.98, 0.97, 0.95)
    cr.move_to(0, -0.02)                                  # the pole
    cr.line_to(0, 0.33)
    cr.set_source_rgb(*INK)
    cr.set_line_width(LW * 1.6)
    cr.stroke()
    n = 6                                                 # canopy: panels in two colours, scalloped edge
    for i in range(n):
        a0, a1 = math.pi + i * math.pi / n, math.pi + (i + 1) * math.pi / n
        cr.move_to(0, -0.06)
        cr.line_to(0.5 * math.cos(a0), -0.06 + 0.4 * math.sin(a0))
        cr.line_to(0.5 * math.cos(a1), -0.06 + 0.4 * math.sin(a1))
        cr.close_path()
        cr.set_source_rgb(*(red if i % 2 else white))
        cr.fill()
    cr.move_to(-0.5, -0.06)
    cr.curve_to(-0.5, -0.56, 0.5, -0.56, 0.5, -0.06)
    for i in range(n):                                    # the scallops along the bottom
        x0 = 0.5 - i / n
        x1 = 0.5 - (i + 1) / n
        cr.curve_to(x0 - 0.02, 0.0, x1 + 0.02, 0.0, x1, -0.06)
    cr.close_path()
    cr.set_source_rgb(*INK)
    cr.set_line_width(LW)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.stroke()
    circle(cr, 0, -0.42, 0.035)                           # the tip
    inked(cr, INK, LW * 0.6)
    ellipse(cr, 0, 0.36, 0.2, 0.065)                      # headband
    inked(cr, (0.24, 0.24, 0.3))


def scarf(cr):
    """A chunky knitted scarf seen from the side: wrapped down the neck (from the back of it to the
    chest), one end hanging down over the chest with a fringe. Drawn for Larry's neck, which runs
    down the left of his big head."""
    red, dark = (0.86, 0.22, 0.26), (0.62, 0.12, 0.17)
    # the hanging end, behind the wrap
    cr.move_to(0.02, 0.18)
    cr.curve_to(0.0, 0.36, 0.04, 0.52, 0.1, 0.66)
    cr.line_to(0.32, 0.6)
    cr.curve_to(0.26, 0.46, 0.24, 0.32, 0.26, 0.16)
    cr.close_path()
    inked(cr, red)
    cr.set_source_rgba(1, 1, 1, 0.9)                      # two stripes across it
    cr.set_line_width(0.045)
    for t in (0.38, 0.5):
        cr.move_to(0.03 + t * 0.06, t)
        cr.line_to(0.27 + t * 0.03, t - 0.04)
    cr.stroke()
    cr.set_source_rgb(*INK)                               # fringe
    cr.set_line_width(LW * 0.8)
    for k in range(5):
        x = 0.12 + k * 0.045
        cr.move_to(x, 0.66 - k * 0.012)
        cr.line_to(x - 0.01, 0.75 - k * 0.012)
    cr.stroke()
    # the wrap: a thick band down the neck, curving forward onto the chest
    cr.move_to(-0.36, -0.62)
    cr.curve_to(-0.12, -0.7, 0.02, -0.66, 0.12, -0.58)    # top (back of the neck)
    cr.curve_to(0.24, -0.3, 0.34, -0.02, 0.44, 0.2)       # front edge, down to the chest
    cr.curve_to(0.28, 0.32, 0.02, 0.32, -0.12, 0.24)      # bottom
    cr.curve_to(-0.2, -0.04, -0.3, -0.34, -0.36, -0.62)   # back edge
    cr.close_path()
    inked(cr, red)
    cr.set_source_rgba(*dark, 0.9)                        # knit ridges across the band
    cr.set_line_width(LW * 0.75)
    for k in range(1, 8):
        t = k / 8
        ax, ay = -0.36 + 0.24 * t, -0.62 + 0.86 * t
        bx, by = 0.12 + 0.32 * t, -0.58 + 0.78 * t
        cr.move_to(ax + 0.03, ay + 0.01)
        cr.curve_to(ax + 0.12, ay + 0.05, bx - 0.12, by + 0.04, bx - 0.03, by)
    cr.stroke()


WEATHER = {   # id: (title, aspect, painter, placement on Larry)
    "umbrella_hat": ("Umbrella hat", 0.9, umbrella_hat, (0.7, -0.05, 0.66)),
    "scarf": ("Scarf", 1.5, scarf, (0.55, 0.555, 0.27)),
}
HATS = {"top_hat", "party_hat", "crown", "cowboy", "beanie", "wizard", "chef", "grad_cap", "viking", "halo",
        "horns", "witch_hat", "santa_hat", "lucky_hat", "bunny_ears", "antlers", "pumpkin", "heart_boppers"}


def is_hat(acc_id, place, anchor=LARRY_ANCHOR):
    """Worn on top of the head? The built-in hats, or one of your own pictures sitting up there
    (its middle above the top of the head, give or take)."""
    if acc_id in HATS:
        return True
    if _entry_builtin(acc_id):
        return False
    return place.get("y", 1) < anchor[1] + 0.02 and abs(place.get("x", 0) - anchor[0]) < 0.3


def _entry_builtin(acc_id):
    return PREMADE.get(acc_id) or SEASONAL.get(acc_id) or WEATHER.get(acc_id)


def _entry(acc_id):
    return _entry_builtin(acc_id)


# ── your own pictures (~/.config/larry/accessories/) ────────────────────────
def customs():
    return library.items("accessories")


def surface(acc_id):
    return library.surface("accessories", acc_id)


def import_image(src):
    return library.import_image("accessories", src)


def delete_image(acc_id):
    library.delete("accessories", acc_id)


# ── lookups ─────────────────────────────────────────────────────────────────
def known(acc_id):
    if acc_id in PREMADE:
        return True
    if acc_id in SEASONAL:
        return claimed(acc_id)
    return library.valid("accessories", acc_id)


def title(acc_id):
    if _entry(acc_id):
        return _entry(acc_id)[0]
    return library.title(acc_id)


def aspect(acc_id):
    if _entry(acc_id):
        return _entry(acc_id)[1]
    s = surface(acc_id)
    return s.get_height() / s.get_width() if s else 1.0


def paint(cr, acc_id):
    """Draw the accessory into its unit box (1 wide, centred on the origin)."""
    cr.save()
    if _entry(acc_id):
        _entry(acc_id)[2](cr)
    else:
        s = surface(acc_id)
        if s:
            w, h = s.get_width(), s.get_height()
            cr.scale(1 / w, 1 / w)
            cr.set_source_surface(s, -w / 2, -h / 2)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
    cr.restore()


def default_place(acc_id, anchor=LARRY_ANCHOR):
    """Starting spot: tuned on Larry, shifted to wherever this pet's head is."""
    x, y, scale = _entry(acc_id)[3] if _entry(acc_id) else (LARRY_ANCHOR[0], 0.02, 0.36)
    dx, dy = anchor[0] - LARRY_ANCHOR[0], anchor[1] - LARRY_ANCHOR[1]
    return {"x": round(x + dx, 4), "y": round(y + dy, 4), "scale": scale, "rotate": 0, "flip": False, "behind": False}


def clean(items):
    """Validate the [accessories] table from the config (unknown ones are dropped, values clamped)."""
    out = {}
    if not isinstance(items, dict):
        return out
    for acc_id, it in items.items():
        if not isinstance(it, dict) or not known(acc_id):
            continue
        d = default_place(acc_id)

        def num(k, lo, hi):
            v = it.get(k)
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
            return round(min(max(float(v), lo), hi), 4) if ok else d[k]
        out[acc_id] = {
            "x": num("x", -1.5, 2.5), "y": num("y", -1.5, 2.5), "scale": num("scale", SCALE_MIN, SCALE_MAX),
            "rotate": round(num("rotate", -180, 180), 1),
            "flip": it.get("flip") if isinstance(it.get("flip"), bool) else False,
            "behind": it.get("behind") if isinstance(it.get("behind"), bool) else False,
        }
    return out


# ── placement ───────────────────────────────────────────────────────────────
def place(cr, it, pw, ph):
    """Move cr into the accessory's unit box, for a pet drawn at (0, 0, pw, ph)."""
    cr.translate(it["x"] * pw, it["y"] * ph)
    cr.rotate(math.radians(it["rotate"]))
    s = it["scale"] * ph
    cr.scale(s, s)
    if it["flip"]:
        cr.scale(-1, 1)


def draw(cr, items, pw, ph, behind):
    for acc_id, it in items.items():
        if it["behind"] == behind:
            cr.save()
            place(cr, it, pw, ph)
            paint(cr, acc_id)
            cr.restore()


def corners(acc_id, it, pw, ph):
    """The accessory's box corners in pet pixels: top-left, top-right, bottom-right, bottom-left."""
    a = aspect(acc_id)
    s = it["scale"] * ph
    r = math.radians(it["rotate"])
    cx, cy = it["x"] * pw, it["y"] * ph
    out = []
    for u, v in ((-0.5, -a / 2), (0.5, -a / 2), (0.5, a / 2), (-0.5, a / 2)):
        x, y = u * s, v * s
        out.append((cx + x * math.cos(r) - y * math.sin(r), cy + x * math.sin(r) + y * math.cos(r)))
    return out


def extent(items, pw, ph):
    """(left, top, right) reach of all accessories, together with the pet's own box."""
    left, top, right = 0.0, 0.0, float(pw)
    for acc_id, it in items.items():
        for x, y in corners(acc_id, it, pw, ph):
            left, top, right = min(left, x), min(top, y), max(right, x)
    return left, top, right


def signature(items):
    """Changes whenever the accessories (or a custom picture's file) change."""
    parts = []
    for acc_id, it in items.items():
        extra = "" if _entry(acc_id) else library.mtime("accessories", acc_id)
        parts.append(f"{acc_id}:{sorted(it.items())}:{extra}")
    return ";".join(parts)
