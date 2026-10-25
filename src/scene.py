"""The pet's box: sky, ground and decorations, drawn with cairo.

Decorations are separate objects you can move: each one sits on its bottom-centre at
    x       fraction of the box width (0 = left edge, 1 = right edge)
    y       pixels above the top of the ground (0 = standing on it)
    scale   1 = natural size;  flip mirrors it;  front draws it over the ground
    seed    its own little bit of randomness (where the stars in a cluster are, etc.)
The ground and the sky can also be your own pictures (see library.py).

The static scene is rendered once into a surface (`BoxCache`) and reused every frame;
only the pet moves on top of it.
"""
import math
import random

import cairo

import library

GROUNDS = [("grass", "Grass"), ("dirt", "Dirt"), ("sand", "Sand"), ("snow", "Snow"),
           ("stone", "Stone"), ("none", "None")]
BACKGROUNDS = [("theme", "Theme"), ("day", "Day sky"), ("sunset", "Sunset"),
               ("night", "Night"), ("none", "None")]
COLOR_MODES = [("theme", "Theme colours"), ("natural", "Natural colours")]
GROUND_H = 12
GROUND_MIN, GROUND_MAX = 4, 48
RADIUS = 12
SCALE_MIN, SCALE_MAX = 0.3, 5.0
SKY_ZOOM_MAX = 4.0
PICTURE_H = 24        # a custom decoration's natural height


def ground_height(box):
    return 0 if box["ground"] == "none" else box.get("ground_height", GROUND_H)


def mix(a, b, t):
    return tuple(x * (1 - t) + y * t for x, y in zip(a, b))


def palette(c, mode):
    if mode == "natural":
        return {
            "grass": (0.42, 0.66, 0.30), "dirt": (0.45, 0.30, 0.18), "sand": (0.88, 0.78, 0.52),
            "snow": (0.94, 0.96, 0.99), "stone": (0.52, 0.52, 0.56),
            "leaf": (0.33, 0.60, 0.27), "leaf_dark": (0.22, 0.44, 0.19), "trunk": (0.42, 0.27, 0.15),
            "wood": (0.62, 0.45, 0.28), "petals": [(0.96, 0.55, 0.70), (1.0, 0.86, 0.35), (0.97, 0.97, 0.97)],
            "pistil": (1.0, 0.75, 0.2), "rock": (0.56, 0.56, 0.60), "sun": (1.0, 0.84, 0.30),
            "moon": (0.95, 0.94, 0.85), "cloud": (1, 1, 1), "star": (1, 1, 0.92),
            "cap": (0.85, 0.22, 0.20), "stalk": (0.95, 0.92, 0.85), "hay": (0.88, 0.72, 0.36),
            "alpha": 1.0,
        }
    return {
        "grass": c["accent2"], "dirt": mix(c["accent"], c["bg0"], 0.55), "sand": mix(c["accent"], c["fg"], 0.3),
        "snow": c["fg"], "stone": mix(c["fg"], c["bg0"], 0.6),
        "leaf": c["accent2"], "leaf_dark": mix(c["accent2"], c["bg0"], 0.35), "trunk": mix(c["accent"], c["bg0"], 0.5),
        "wood": mix(c["accent"], c["bg0"], 0.35), "petals": [c["accent"], c["fg"], mix(c["accent2"], c["fg"], 0.5)],
        "pistil": c["accent2"], "rock": mix(c["fg"], c["bg0"], 0.55), "sun": c["accent"],
        "moon": c["fg"], "cloud": c["fg"], "star": c["fg"],
        "cap": c["accent"], "stalk": c["fg"], "hay": mix(c["accent"], c["fg"], 0.25),
        "alpha": 0.85,
    }


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


# ── sky and ground ──────────────────────────────────────────────────────────
def background(cr, w, h, box, c):
    kind = box["background"]
    if library.is_custom(kind):
        sky_picture(cr, w, h, box)
        return
    stops = {
        "theme": [(0, *c["bg0"], 0.92), (1, *c["bg1"], 0.92)],
        "day": [(0, 0.38, 0.64, 0.93, 0.95), (1, 0.74, 0.87, 0.98, 0.95)],
        "sunset": [(0, 0.30, 0.22, 0.50, 0.95), (0.6, 0.86, 0.44, 0.46, 0.95), (1, 0.99, 0.70, 0.42, 0.95)],
        "night": [(0, 0.02, 0.03, 0.10, 0.95), (1, 0.09, 0.11, 0.27, 0.95)],
    }.get(kind)
    if not stops:
        return
    g = cairo.LinearGradient(0, 0, 0, h)
    for st in stops:
        g.add_color_stop_rgba(*st)
    cr.set_source(g)
    cr.paint()


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
    cr.paint_with_alpha(0.95)
    cr.restore()


def ground(cr, w, gy, gh, kind, p):
    if library.is_custom(kind):
        ground_picture(cr, w, gy, gh, kind)
        return
    a = p["alpha"]
    col = p.get(kind)
    if kind == "grass":
        cr.set_source_rgba(*col, a * 0.55)
        cr.rectangle(0, gy, w, gh)
        cr.fill()
        cr.set_source_rgba(*col, a)
        cr.set_line_width(1.2)
        for i in range(9, int(w), 17):
            t = 3 + (i * 7) % 4
            cr.move_to(i, gy + 1)
            cr.line_to(i - 2, gy - t)
            cr.move_to(i, gy + 1)
            cr.line_to(i + 2, gy - t + 1)
        cr.stroke()
    elif kind == "dirt":
        cr.set_source_rgba(*col, a)
        cr.rectangle(0, gy, w, gh)
        cr.fill()
        rng = random.Random(3)
        cr.set_source_rgba(*mix(col, (0, 0, 0), 0.35), a)
        for _ in range(int(w * gh / 108)):
            cr.arc(rng.uniform(0, w), rng.uniform(gy + 3, gy + gh), rng.uniform(0.6, 1.3), 0, 2 * math.pi)
            cr.fill()
    elif kind in ("sand", "snow"):
        cr.set_source_rgba(*col, a)
        cr.move_to(0, gy + 2)
        for x in range(0, int(w) + 4, 4):
            cr.line_to(x, gy + 1.5 * math.sin(x / (14 if kind == "sand" else 22)) + 1)
        cr.line_to(w, gy + gh)
        cr.line_to(0, gy + gh)
        cr.close_path()
        cr.fill()
        if kind == "sand":
            cr.set_source_rgba(*mix(col, (0, 0, 0), 0.2), a * 0.7)
            cr.set_line_width(0.8)
            for row in range(int((gh - 3) // 9) + 1):
                y = gy + 6 + row * 9
                for x in range(6 + row * 11, int(w), 23):
                    cr.move_to(x, y)
                    cr.curve_to(x + 3, y - 1.5, x + 6, y + 1.5, x + 9, y)
            cr.stroke()
        else:
            cr.set_source_rgba(0.6, 0.75, 1.0, 0.25)
            cr.rectangle(0, gy + gh - 3, w, 3)
            cr.fill()
    elif kind == "stone":
        cr.set_source_rgba(*col, a)
        cr.rectangle(0, gy, w, gh)
        cr.fill()
        cr.set_source_rgba(*mix(col, (0, 0, 0), 0.4), a)
        cr.set_line_width(1)
        for row in range(int(math.ceil(gh / 6))):
            y = gy + row * 6
            cr.move_to(0, y + 0.5)
            cr.line_to(w, y + 0.5)
            for x in range(9 * (row % 2), int(w), 18):
                cr.move_to(x + 0.5, y)
                cr.line_to(x + 0.5, min(y + 6, gy + gh))
        cr.stroke()


def ground_picture(cr, w, gy, gh, kind):
    """Your picture as the ground: scaled to the ground's height and repeated across."""
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


# ── decorations: each drawn standing on (0, 0) at natural size ─────────────
def d_sun(cr, p, rng, night):
    x, y, r = 0, -10, 8
    if night:
        cr.save()
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.clip()
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.new_sub_path()
        cr.arc(x + 4.5, y - 3, r, 0, 2 * math.pi)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.set_source_rgb(*p["moon"])
        cr.fill()
        cr.restore()
        return
    glow = cairo.RadialGradient(x, y, r * 0.6, x, y, r * 2.4)
    glow.add_color_stop_rgba(0, *p["sun"], 0.45)
    glow.add_color_stop_rgba(1, *p["sun"], 0)
    cr.set_source(glow)
    cr.arc(x, y, r * 2.4, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(*p["sun"])
    cr.arc(x, y, r, 0, 2 * math.pi)
    cr.fill()


def d_cloud(cr, p, rng, night):
    cr.set_source_rgba(*p["cloud"], 0.85)
    for dx, dy, r in ((-9, -5, 5), (-2, -9, 7), (7, -6, 5.5), (12, -4, 3.5)):
        cr.arc(dx, dy, r, 0, 2 * math.pi)
        cr.fill()
    cr.rectangle(-9, -6, 21, 5)
    cr.fill()


def d_stars(cr, p, rng, night):
    for _ in range(7):
        cr.set_source_rgba(*p["star"], rng.uniform(0.4, 0.95))
        cr.arc(rng.uniform(-20, 20), rng.uniform(-20, -2), rng.uniform(0.5, 1.2), 0, 2 * math.pi)
        cr.fill()


def d_tree(cr, p, rng, night):
    cr.set_source_rgb(*p["trunk"])
    cr.rectangle(-2.5, -17, 5, 18)
    cr.fill()
    for dx, dy, r, col in ((-7, -22, 9, "leaf_dark"), (7, -23, 9, "leaf_dark"),
                           (0, -30, 11, "leaf"), (-6, -24, 8, "leaf"), (6, -25, 8, "leaf")):
        cr.set_source_rgb(*p[col])
        cr.arc(dx, dy, r, 0, 2 * math.pi)
        cr.fill()


def d_fence(cr, p, rng, night):
    cr.set_source_rgba(*p["wood"], 0.9)
    for x in (-32, -12, 8, 28):
        cr.move_to(x, 0)
        cr.line_to(x, -15)
        cr.line_to(x + 2, -18)
        cr.line_to(x + 4, -15)
        cr.line_to(x + 4, 0)
        cr.close_path()
        cr.fill()
    cr.rectangle(-36, -13, 72, 2.5)
    cr.rectangle(-36, -6, 72, 2.5)
    cr.fill()


def d_bush(cr, p, rng, night):
    for dx, dy, r, col in ((-6, -4, 5.5, "leaf_dark"), (5, -4, 5.5, "leaf_dark"), (0, -7, 6.5, "leaf")):
        cr.set_source_rgb(*p[col])
        cr.arc(dx, dy, r, 0, 2 * math.pi)
        cr.fill()


def d_flowers(cr, p, rng, night):
    for i, x in enumerate((-7, 0, 7)):
        stem = rng.uniform(6, 10)
        cr.set_source_rgb(*p["leaf"])
        cr.set_line_width(1)
        cr.move_to(x, 2)
        cr.line_to(x, -stem)
        cr.stroke()
        cr.set_source_rgb(*p["petals"][(i + rng.randrange(3)) % len(p["petals"])])
        for k in range(5):
            a = k * 2 * math.pi / 5
            cr.arc(x + 2 * math.cos(a), -stem + 2 * math.sin(a), 1.5, 0, 2 * math.pi)
            cr.fill()
        cr.set_source_rgb(*p["pistil"])
        cr.arc(x, -stem, 1.1, 0, 2 * math.pi)
        cr.fill()


def d_rock(cr, p, rng, night):
    cr.set_source_rgb(*p["rock"])
    cr.move_to(-7, 2)
    cr.curve_to(-7, -5, -2, -7, 2, -6)
    cr.curve_to(6, -5, 8, -2, 7, 2)
    cr.close_path()
    cr.fill()
    cr.set_source_rgba(1, 1, 1, 0.25)
    cr.arc(-1.5, -3.5, 1.6, 0, 2 * math.pi)
    cr.fill()


def d_mushrooms(cr, p, rng, night):
    for x, s in ((-3, 1.0), (4.5, 0.75)):
        cr.set_source_rgb(*p["stalk"])
        cr.rectangle(x - 1.5 * s, -6 * s, 3 * s, 7 * s)
        cr.fill()
        cr.set_source_rgb(*p["cap"])
        cr.arc(x, -6 * s, 5 * s, math.pi, 2 * math.pi)
        cr.close_path()
        cr.fill()
        cr.set_source_rgb(*p["stalk"])
        for dx, dy in ((-2.5, -8), (1.5, -9.5), (3, -7)):
            cr.arc(x + dx * s, dy * s, 0.8 * s, 0, 2 * math.pi)
            cr.fill()


def d_hay(cr, p, rng, night):
    cr.set_source_rgb(*p["hay"])
    cr.rectangle(-11, -12, 22, 13)
    cr.fill()
    cr.set_source_rgba(*mix(p["hay"], (0, 0, 0), 0.3), 1)
    cr.set_line_width(1)
    for dy in (-9, -5, -1.5):
        cr.move_to(-11, dy)
        cr.line_to(11, dy)
    cr.stroke()
    cr.set_source_rgba(*mix(p["hay"], (0.4, 0.15, 0.05), 0.5), 1)
    cr.rectangle(-4, -12, 1.5, 13)
    cr.rectangle(3, -12, 1.5, 13)
    cr.fill()


# key: (title, painter, bounds (x0, y0, x1, y1) at natural size, starting height, in front of the ground)
DECOR = {
    "sun":       ("Sun / moon", d_sun, (-10, -20, 10, 0), 50, False),
    "clouds":    ("Cloud", d_cloud, (-15, -16, 16, 0), 46, False),
    "stars":     ("Stars", d_stars, (-22, -22, 22, 0), 40, False),
    "tree":      ("Tree", d_tree, (-16, -41, 16, 1), 0, False),
    "fence":     ("Fence", d_fence, (-36, -18, 36, 0), 0, False),
    "bush":      ("Bush", d_bush, (-12, -14, 12, 0), 0, False),
    "flowers":   ("Flowers", d_flowers, (-10, -13, 10, 2), 0, True),
    "rocks":     ("Rock", d_rock, (-7, -7, 7, 2), 0, True),
    "mushrooms": ("Mushrooms", d_mushrooms, (-8, -12, 9, 1), 0, True),
    "hay":       ("Hay bale", d_hay, (-11, -12, 11, 1), 0, True),
}
DECORATIONS = [(k, v[0]) for k, v in DECOR.items()]


def deco_title(kind):
    return DECOR[kind][0] if kind in DECOR else library.title(kind)


def deco_known(kind):
    return kind in DECOR or library.valid("decorations", kind)


def bounds(kind):
    """Natural-size bounds around the standing point."""
    if kind in DECOR:
        return DECOR[kind][2]
    surf = library.surface("decorations", kind)
    w = PICTURE_H * surf.get_width() / surf.get_height() if surf else PICTURE_H
    return -w / 2, -PICTURE_H, w / 2, 0


def paint_deco(cr, item, p, night):
    """Draw one decoration at natural size, standing on (0, 0)."""
    kind = item["kind"]
    cr.save()
    if kind in DECOR:
        DECOR[kind][1](cr, p, random.Random(item.get("seed", 1)), night)
    else:
        surf = library.surface("decorations", kind)
        if surf:
            k = PICTURE_H / surf.get_height()
            cr.scale(k, k)
            cr.set_source_surface(surf, -surf.get_width() / 2, -surf.get_height())
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
    cr.restore()


def place(cr, item, w, gy):
    cr.translate(item["x"] * w, gy - item["y"])
    cr.scale(item["scale"], item["scale"])
    if item["flip"]:
        cr.scale(-1, 1)


def item_rect(item, w, gy):
    """(x0, y0, x1, y1) of a placed decoration, in box coordinates."""
    x0, y0, x1, y1 = bounds(item["kind"])
    if item["flip"]:
        x0, x1 = -x1, -x0
    s, cx, cy = item["scale"], item["x"] * w, gy - item["y"]
    return cx + x0 * s, cy + y0 * s, cx + x1 * s, cy + y1 * s


def new_item(kind, rng=random):
    _t, _f, _b, y, front = DECOR.get(kind, (None, None, None, 0, True))
    return {"kind": kind, "x": round(rng.uniform(0.12, 0.88), 3), "y": y, "scale": 1.0,
            "flip": False, "front": front, "seed": rng.randint(1, 99999)}


def clean_items(items):
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict) or not deco_known(it.get("kind")):
            continue
        d = new_item(it["kind"])

        def num(k, lo, hi):
            v = it.get(k)
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
            return round(min(max(float(v), lo), hi), 3) if ok else d[k]
        seed = it.get("seed")
        out.append({"kind": it["kind"], "x": num("x", -0.5, 1.5), "y": num("y", -60, 400),
                    "scale": num("scale", SCALE_MIN, SCALE_MAX),
                    "flip": it.get("flip") if isinstance(it.get("flip"), bool) else False,
                    "front": it.get("front") if isinstance(it.get("front"), bool) else d["front"],
                    "seed": seed if isinstance(seed, int) and not isinstance(seed, bool) else d["seed"]})
    return out


def legacy_items(names, seed, gh):
    """Turn the old "decorations = [names] + seed" settings into placed objects, roughly where they were."""
    w, gy = 250, 92 - gh
    rng = lambda name: random.Random(f"{seed}-{name}")  # noqa: E731
    out = []

    def add(kind, x, y=None, scale=1.0, n=1):
        it = new_item(kind, random.Random(f"{seed}-{kind}-{n}"))
        it.update(x=round(x / w, 3), scale=round(scale, 3))
        if y is not None:
            it["y"] = round(y, 1)
        out.append(it)
    for name in names:
        r = rng(name)
        if name == "sun":
            add("sun", w - 26, gy - 30)
        elif name == "clouds":
            for i in range(2):
                cx = r.uniform(20, w * 0.6) + i * w * 0.25
                cy, s = r.uniform(13, 26), r.uniform(0.8, 1.15)
                add("clouds", cx, gy - cy - 6 * s, s, i)
        elif name == "stars":
            for i, x in enumerate((0.2, 0.5, 0.8)):
                add("stars", x * w, gy - 4 - 22 - i % 2 * 8, 1.0, i)
        elif name == "fence":
            for i in range(4):
                add("fence", 36 + i * 72, 0, 1.0, i)
        elif name == "tree":
            add("tree", r.choice((26, w - 30)))
        elif name in ("bush", "rocks", "mushrooms"):
            for i in range(2):
                add(name, r.uniform(20, w - 20), None, r.uniform(0.85, 1.2) if name == "rocks" else 1.0, i)
        elif name == "flowers":
            for i in range(2):
                add("flowers", r.uniform(14, w - 14), None, 1.0, i)
        elif name == "hay":
            add("hay", r.uniform(30, w - 30))
    return out


# ── the whole box ───────────────────────────────────────────────────────────
def draw_static(cr, w, h, colors, box):
    """Everything except the pet and the border, in box coordinates."""
    p = palette(colors, box["colors"])
    gh = ground_height(box)
    gy = h - gh
    night = box["background"] == "night"
    background(cr, w, h, box, colors)
    for front in (False, True):
        if front:
            ground(cr, w, gy, gh, box["ground"], p)
        for it in box["items"]:
            if it["front"] == front:
                cr.save()
                place(cr, it, w, gy)
                paint_deco(cr, it, p, night)
                cr.restore()


def draw_border(cr, w, h, colors, edge="top"):
    """Outline everything except the side touching the screen edge."""
    cr.save()
    keep = {"top": (0, 1.5, w, h), "bottom": (0, 0, w, h - 1.5),
            "left": (1.5, 0, w, h), "right": (0, 0, w - 1.5, h)}[edge]
    cr.rectangle(*keep)
    cr.clip()
    cr.translate(0.5, 0.5)
    box_path(cr, w - 1, h - 1, RADIUS, edge)
    cr.set_source_rgba(*colors["accent"], 0.55)
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
            draw_static(cr, w, h, colors, box)
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
