"""The pet's box: a soft card with a sky and a floor, drawn with cairo.

Kept quiet on purpose: calm gradients, one smooth floor, a gentle inner shadow where the box hangs
from the screen edge. The floor and the sky can also be your own pictures (see library.py).

The static scene is rendered once into a surface (`BoxCache`) and reused every frame; only the pet
moves on top of it.
"""
import math

import cairo

import library

GROUNDS = [("grass", "Grass"), ("dirt", "Soil"), ("sand", "Sand"), ("snow", "Snow"),
           ("stone", "Stone"), ("none", "None")]
BACKGROUNDS = [("theme", "Theme"), ("day", "Day"), ("sunset", "Sunset"),
               ("night", "Night"), ("none", "None")]
COLOR_MODES = [("theme", "Theme colours"), ("natural", "Natural colours")]
GROUND_H = 12
GROUND_MIN, GROUND_MAX = 4, 48
RADIUS = 16
SKY_ZOOM_MAX = 4.0


def ground_height(box):
    return 0 if box["ground"] == "none" else box.get("ground_height", GROUND_H)


def mix(a, b, t):
    return tuple(x * (1 - t) + y * t for x, y in zip(a, b))


def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


EDGES = [("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right")]
# which corners are rounded (top-left, top-right, bottom-right, bottom-left): the side away from the edge
_ROUND = {"top": (0, 0, 1, 1), "bottom": (1, 1, 0, 0), "left": (0, 1, 1, 0), "right": (1, 0, 0, 1)}


def box_path(cr, w, h, r=RADIUS, edge="top"):
    """Flat against the screen edge it hangs from, rounded on the opposite side."""
    tl, tr, br, bl = _ROUND[edge]
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    if tl:
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
    else:
        cr.move_to(0, 0)
    if tr:
        cr.arc(w - r, r, r, -math.pi / 2, 0)
    else:
        cr.line_to(w, 0)
    if br:
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
    else:
        cr.line_to(w, h)
    if bl:
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
    else:
        cr.line_to(0, h)
    cr.close_path()


# ── sky ─────────────────────────────────────────────────────────────────────
NATURAL_SKIES = {   # (top, bottom)
    "day": ((0.55, 0.74, 0.93), (0.86, 0.92, 0.97)),
    "sunset": ((0.42, 0.36, 0.58), (0.96, 0.72, 0.6)),
    "night": ((0.06, 0.07, 0.15), (0.14, 0.16, 0.3)),
}


def sky_colours(kind, c, match):
    """(top, bottom) of a sky: the theme's own card colours, or a day/sunset/night sky (in the
    theme's hues if `match`, keeping how light or dark that sky is)."""
    if kind == "theme":
        base = c["bg1"]
        lift = (1, 1, 1) if lum(base) < 0.5 else (0, 0, 0)
        return mix(base, c["accent2"], 0.06), mix(base, lift, 0.035)
    top, bottom = NATURAL_SKIES[kind]
    if match:
        if kind == "night":
            top, bottom = mix(top, mix(c["bg0"], c["accent2"], 0.1), 0.55), mix(bottom, mix(c["bg1"], c["accent2"], 0.25), 0.5)
        elif kind == "day":
            top, bottom = mix(top, mix(c["accent2"], (1, 1, 1), 0.35), 0.5), mix(bottom, mix(c["accent2"], (1, 1, 1), 0.8), 0.5)
        else:
            top, bottom = mix(top, mix(c["bg1"], c["accent2"], 0.5), 0.5), mix(bottom, mix(c["accent"], (1, 1, 1), 0.45), 0.45)
    return top, bottom


def background(cr, w, h, box, c):
    kind = box["background"]
    if library.is_custom(kind):
        sky_picture(cr, w, h, box)
        return
    if kind == "none" or kind not in ("theme", *NATURAL_SKIES):
        return
    top, bottom = sky_colours(kind, c, box.get("match_theme", True))
    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgba(0, *top, 0.96)
    g.add_color_stop_rgba(1, *bottom, 0.96)
    cr.set_source(g)
    cr.paint()
    # a soft glow high up: depth without any clutter (warm low sun for sunset, faint moonlight at night)
    glow = {"theme": (c["accent2"], 0.07), "day": ((1, 1, 1), 0.22), "sunset": ((1.0, 0.82, 0.62), 0.28),
            "night": ((0.75, 0.8, 1.0), 0.08)}[kind]
    gx, gy = w * 0.72, h * (0.95 if kind == "sunset" else 0.15)
    rg = cairo.RadialGradient(gx, gy, 0, gx, gy, max(w, h) * 0.55)
    rg.add_color_stop_rgba(0, *glow[0], glow[1])
    rg.add_color_stop_rgba(1, *glow[0], 0)
    cr.set_source(rg)
    cr.paint()
    if kind == "night":                       # a few tiny, faint stars, always in the same places
        for i in range(max(6, int(w / 45))):
            x = (i * 0.618034 % 1) * w
            y = ((i * 0.381966 + 0.13) % 1) * h * 0.6 + 4
            cr.new_path()
            cr.arc(x, y, 0.7 + (i % 3) * 0.3, 0, 2 * math.pi)
            cr.set_source_rgba(1, 1, 1, 0.35 + (i % 4) * 0.12)
            cr.fill()


def sky_frame(w, h, box, surf):
    """(offset x, offset y, scale) of a sky picture: covers the box, then zoomed and panned."""
    iw, ih = surf.get_width(), surf.get_height()
    k = max(w / iw, h / ih) * box.get("sky_zoom", 1.0)
    return (w - iw * k) * box.get("sky_x", 0.5), (h - ih * k) * box.get("sky_y", 0.5), k


def sky_picture(cr, w, h, box):
    surf = library.surface("skies", box["background"])
    if not surf:
        return
    ox, oy, k = sky_frame(w, h, box, surf)
    cr.save()
    cr.translate(ox, oy)
    cr.scale(k, k)
    cr.set_source_surface(surf, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint_with_alpha(0.96)
    cr.restore()


# ── floor ───────────────────────────────────────────────────────────────────
NATURAL_FLOORS = {"grass": (0.47, 0.68, 0.42), "dirt": (0.55, 0.42, 0.32), "sand": (0.87, 0.78, 0.6),
                  "snow": (0.93, 0.95, 0.98), "stone": (0.56, 0.57, 0.6)}


def floor_colour(kind, c, mode):
    if mode == "natural":
        return NATURAL_FLOORS[kind]
    return {"grass": mix(c["bg1"], c["accent2"], 0.62), "dirt": mix(c["bg1"], c["accent"], 0.42),
            "sand": mix(c["bg1"], mix(c["accent"], c["fg"], 0.5), 0.6), "snow": mix(c["bg1"], c["fg"], 0.82),
            "stone": mix(c["bg1"], c["fg"], 0.32)}[kind]


SWELL = 2.5      # px: how much the floor rises in the middle


def floor_top(cr, w, gy):
    cr.move_to(0, gy + SWELL * 0.6)
    cr.curve_to(w * 0.3, gy - SWELL, w * 0.62, gy - SWELL, w, gy + SWELL * 0.3)


def floor_path(cr, w, gy, h):
    """The floor's top: one long, gentle swell (never a flat stripe, never bumpy)."""
    floor_top(cr, w, gy)
    cr.line_to(w, h + 1)
    cr.line_to(0, h + 1)
    cr.close_path()


def far_hill(cr, w, gy, col, sky_bottom):
    """One faint, far-off hill behind the floor: a little depth, nothing to look at."""
    hh = min(18, 6 + gy * 0.12)
    cr.move_to(0, gy - hh * 0.35)
    cr.curve_to(w * 0.22, gy - hh * 1.05, w * 0.42, gy - hh * 1.1, w * 0.62, gy - hh * 0.55)
    cr.curve_to(w * 0.78, gy - hh * 0.15, w * 0.9, gy - hh * 0.7, w, gy - hh * 0.6)
    cr.line_to(w, gy + 4)
    cr.line_to(0, gy + 4)
    cr.close_path()
    cr.set_source_rgba(*mix(sky_bottom, col, 0.45), 0.7)
    cr.fill()


def ground(cr, w, gy, gh, kind, c, mode, h, sky_bottom=None):
    if library.is_custom(kind):
        ground_picture(cr, w, gy, gh, kind)
        return
    if kind not in NATURAL_FLOORS or gh <= 0:
        return
    col = floor_colour(kind, c, mode)
    far_hill(cr, w, gy, col, sky_bottom or c["bg1"])
    dark = mix(col, (0, 0, 0), 0.18)
    floor_path(cr, w, gy, h)
    g = cairo.LinearGradient(0, gy - 2, 0, h)
    g.add_color_stop_rgb(0, *col)
    g.add_color_stop_rgb(1, *dark)
    cr.set_source(g)
    cr.fill()
    cr.save()                                  # a thin lit edge along the top
    floor_path(cr, w, gy, h)
    cr.clip()
    floor_top(cr, w, gy)
    cr.set_source_rgba(*mix(col, (1, 1, 1), 0.55), 0.55)
    cr.set_line_width(2)
    cr.stroke()
    cr.restore()


def ground_picture(cr, w, gy, gh, kind):
    """Your picture as the floor: scaled to the floor's height and repeated across."""
    surf = library.surface("grounds", kind)
    if not surf or gh <= 0:
        return
    k = gh / surf.get_height()
    cr.save()
    cr.rectangle(0, gy, w, gh)
    cr.clip()
    cr.translate(0, gy)
    cr.scale(k, k)
    pat = cairo.SurfacePattern(surf)
    pat.set_extend(cairo.EXTEND_REPEAT)
    pat.set_filter(cairo.FILTER_GOOD)
    cr.set_source(pat)
    cr.paint()
    cr.restore()


# ── the whole box ───────────────────────────────────────────────────────────
def draw_static(cr, w, h, colors, box, edge="top"):
    """Everything except the pet and the border, in box coordinates."""
    cr.set_source_rgba(*colors["bg1"], 0.96)       # the card itself (so "no sky" is still a box)
    cr.paint()
    background(cr, w, h, box, colors)
    gh = ground_height(box)
    kind = box["background"]
    bottom = sky_colours(kind, colors, box.get("match_theme", True))[1] if kind in ("theme", *NATURAL_SKIES) \
        else colors["bg1"]
    ground(cr, w, h - gh, gh, box["ground"], colors, box.get("colors", "theme"), h, bottom)
    inner_shadow(cr, w, h, edge)


def inner_shadow(cr, w, h, edge):
    """A soft shade along the screen edge the box comes out of, as if it slides out from under it."""
    d = 10
    x0, y0, x1, y1 = {"top": (0, 0, 0, d), "bottom": (0, h, 0, h - d),
                      "left": (0, 0, d, 0), "right": (w, 0, w - d, 0)}[edge]
    g = cairo.LinearGradient(x0, y0, x1, y1)
    g.add_color_stop_rgba(0, 0, 0, 0, 0.22)
    g.add_color_stop_rgba(1, 0, 0, 0, 0)
    cr.set_source(g)
    cr.paint()


def draw_border(cr, w, h, colors, edge="top"):
    """A quiet edge (no outline): a faint light line round the rounded sides."""
    cr.save()
    keep = {"top": (0, 1.5, w, h), "bottom": (0, 0, w, h - 1.5),
            "left": (1.5, 0, w, h), "right": (0, 0, w - 1.5, h)}[edge]
    cr.rectangle(*keep)
    cr.clip()
    cr.translate(0.5, 0.5)
    box_path(cr, w - 1, h - 1, RADIUS, edge)
    light = lum(colors["bg1"]) < 0.5
    cr.set_source_rgba(*((1, 1, 1) if light else (0, 0, 0)), 0.1 if light else 0.08)
    cr.set_line_width(1)
    cr.stroke()
    cr.restore()


class BoxCache:
    """The static scene as a surface, rebuilt only when size, colours or settings change."""

    def __init__(self, scale=1):
        self.key = None
        self.surface = None
        self.scale = scale   # render at this zoom (for big previews), still painted in box units

    def get(self, w, h, colors, box, edge="top"):
        key = (w, h, edge, tuple(sorted(colors.items())), repr(sorted(box.items())))
        if key != self.key:
            self.key = key
            s = self.scale
            self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, round(w * s), round(h * s))
            self.surface.set_device_scale(s, s)
            cr = cairo.Context(self.surface)
            box_path(cr, w, h, RADIUS, edge)
            cr.clip()
            draw_static(cr, w, h, colors, box, edge)
        return self.surface

    def paint(self, cr, x, y, w, h, colors, box, pet=None, edge="top"):
        """Box at (x, y), flat against `edge`; `pet(cr)` draws the pet clipped inside it."""
        cr.save()
        cr.set_source_surface(self.get(w, h, colors, box, edge), x, y)
        cr.paint()
        if pet:
            cr.translate(x, y)
            box_path(cr, w, h, RADIUS, edge)
            cr.clip()
            cr.translate(-x, -y)
            pet(cr)
        cr.restore()
        cr.save()
        cr.translate(x, y)
        draw_border(cr, w, h, colors, edge)
        cr.restore()
