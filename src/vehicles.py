"""Things the pet rides now and then instead of walking: a mini motorcycle, a car, a one-person
helicopter and a bike.

Drawn in Larry's own style: one bold black ink line around everything, flat fills, chunky cartoon
shapes, and the same white sticker outline his picture has. Everything here is in "pet heights"
(L): the pet's feet line is y = 0, its middle is x = 0, and it faces right (the caller mirrors it to
face left). draw() paints the vehicle's back, then calls rider() to draw the pet (cr at the origin:
the caller puts it in the seat, see SEAT / RIDER), then the parts that go in front of it.
"""
import math

import cairo

KINDS = {"motorcycle": "Motorcycle", "car": "Car", "helicopter": "Helicopter", "bike": "Bike"}
DEFAULT = "motorcycle"
SPEED = {"motorcycle": 2.7, "car": 2.6, "helicopter": 2.2, "bike": 1.8}   # times walking speed
EXTENT = {   # (furthest back, furthest forward, top above the feet line), in L
    "motorcycle": (-0.72, 0.66, 1.2), "car": (-1.1, 1.1, 1.18),
    "helicopter": (-1.12, 1.12, 1.66), "bike": (-0.86, 0.9, 1.4),
}   # (the helicopter's top really depends on how tall its rider sits: see top())
RIDER = {    # where a pet standing on it goes: (x, how far its feet are lifted, scale)
    "motorcycle": (-0.08, 0.22, 1.0), "car": (-0.2, 0.12, 0.95),
    "helicopter": (-0.06, 0.24, 1.0), "bike": (-0.1, 0.40, 1.0),
}
SEAT = {     # where a sitting rider's butt goes (Larry's riding pose): (x, height)
    "motorcycle": (-0.24, 0.42), "car": (-0.3, 0.22), "helicopter": (-0.18, 0.44), "bike": (-0.15, 0.6),
}
BIKE_BB = (0.13, -0.4)   # the bike's pedals' middle
WHEEL = {"motorcycle": 0.15, "car": 0.21, "bike": 0.27}
WHEELIE_PIVOT = -0.44    # the mini motorcycle's back wheel
PEDAL_GEAR = 0.6         # bike: crank turns per wheel turn
COLORS = {"motorcycle": (0.95, 0.33, 0.3), "car": (0.36, 0.64, 0.97),
          "helicopter": (1.0, 0.78, 0.24), "bike": (0.27, 0.8, 0.64)}

INK = (0.06, 0.06, 0.07)
WHITE = (1, 1, 1)
METAL = (0.78, 0.8, 0.84)
DARK = (0.36, 0.37, 0.42)
LINE = 0.045             # the ink line (Larry's own outline, at his size)
HALO = 2.0               # px of white sticker outline, like the pet picture's
_grow = 0.0              # while drawing the outline's silhouette: how much fatter every line is (L)


def top(kind, head=1.3):
    """Highest point above the feet line (in L), with the rider's head `head` high."""
    if kind == "helicopter":
        return head + 0.36    # the rotor sits just over its head
    return max(EXTENT[kind][2], head + 0.05)


def margin(kind):
    """How far the vehicle reaches past the pet's middle, either way (in L)."""
    x0, x1, _top = EXTENT[kind]
    return max(-x0, x1)


def crank(kind, dist, L):
    """The bike's pedal angle after riding dist px."""
    return dist / (WHEEL["bike"] * L) * PEDAL_GEAR if kind == "bike" else 0.0


def _shade(rgb, k):
    return tuple(max(0.0, min(1.0, c * k)) for c in rgb)


# ── ink helpers (all in L units) ────────────────────────────────────────────
def _ink(cr, fill, width=LINE):
    """Fill the current path flat and go round it with the ink line."""
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_source_rgb(*fill)
    cr.fill_preserve()
    cr.set_source_rgb(*INK)
    cr.set_line_width(width + 2 * _grow)
    cr.stroke()


def _rrect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def _circle(cr, x, y, r, fill, width=LINE):
    cr.new_sub_path()
    cr.arc(x, y, r, 0, 2 * math.pi)
    _ink(cr, fill, width)


def _tube(cr, pts, fill, w):
    """A rounded bar through the points: ink, with the colour inside it."""
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    for colour, width in ((INK, w + 2 * LINE * 0.8), (fill, w)):
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.set_source_rgb(*colour)
        cr.set_line_width(width + 2 * _grow)
        cr.stroke()


def _wheel(cr, x, y, r, angle):
    """A chunky cartoon wheel: black tyre, white hub, two tread marks that show it turning."""
    _circle(cr, x, y, r, INK)
    cr.set_source_rgb(*WHITE)
    cr.set_line_width(r * 0.13)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for a in (angle, angle + math.pi):
        cr.new_sub_path()
        cr.arc(x, y, r * 0.76, a - 0.3, a + 0.3)
        cr.stroke()
    _circle(cr, x, y, r * 0.42, WHITE, LINE * 0.7)
    cr.arc(x, y, r * 0.12, 0, 2 * math.pi)
    cr.set_source_rgb(*INK)
    cr.fill()


def _bike_wheel(cr, x, y, r, angle):
    """A skinny bicycle wheel: a thick black ring and three spokes."""
    cr.new_sub_path()
    cr.arc(x, y, r - 0.035, 0, 2 * math.pi)
    cr.set_source_rgb(*INK)
    cr.set_line_width(0.075 + 2 * _grow)
    cr.stroke()
    cr.set_line_width(0.022)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for i in range(3):
        a = angle + i * 2 * math.pi / 3
        cr.move_to(x, y)
        cr.line_to(x + math.cos(a) * (r - 0.06), y + math.sin(a) * (r - 0.06))
    cr.stroke()
    _circle(cr, x, y, 0.045, WHITE, LINE * 0.7)


def _clouds(cr, x, y, t):
    """Little cartoon exhaust clouds puffing out of (x, y) and drifting back."""
    for i in range(3):
        p = (t * 2.2 + i / 3) % 1
        r = 0.035 + 0.06 * math.sin(math.pi * min(p * 1.3, 1))
        if r > 0.02:
            _circle(cr, x - p * 0.5, y - p * 0.16, r, WHITE, LINE * 0.6)


# ── the vehicles: back(cr, s), then the rider, then front(cr, s) ─────────────
def moto_back(cr, s):
    r = WHEEL["motorcycle"]
    a = s["dist"] / (r * s["L"])
    if s["moving"]:
        _clouds(cr, -0.66, -0.24, s["t"])
    _tube(cr, [(-0.08, -0.18), (-0.58, -0.24)], METAL, 0.06)                   # exhaust
    _wheel(cr, WHEELIE_PIVOT, -r, r, a)
    cr.move_to(-0.64, -0.3)                                                    # the body: a fat bean
    cr.curve_to(-0.64, -0.42, -0.56, -0.46, -0.44, -0.46)
    cr.line_to(-0.04, -0.42)
    cr.curve_to(0.06, -0.5, 0.26, -0.52, 0.36, -0.46)
    cr.curve_to(0.46, -0.41, 0.48, -0.32, 0.42, -0.26)
    cr.curve_to(0.3, -0.18, -0.1, -0.16, -0.3, -0.2)
    cr.curve_to(-0.5, -0.22, -0.64, -0.24, -0.64, -0.3)
    cr.close_path()
    _ink(cr, s["color"])
    _circle(cr, -0.42, -0.33, 0.065, WHITE)                                    # racing number disc
    _rrect(cr, -0.54, -0.52, 0.5, 0.09, 0.045)                                 # seat
    _ink(cr, INK)


def moto_front(cr, s):
    r = WHEEL["motorcycle"]
    a = s["dist"] / (r * s["L"])
    fx = 0.5
    _tube(cr, [(fx, -r), (0.36, -0.5), (0.3, -0.7)], METAL, 0.05)             # fork
    _wheel(cr, fx, -r, r, a)
    cr.new_sub_path()                                                          # mudguard
    cr.arc(fx, -r, r + 0.06, math.radians(-165), math.radians(-30))
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_source_rgb(*INK)
    cr.set_line_width(0.07 + 2 * LINE * 0.8 + 2 * _grow)
    cr.stroke_preserve()
    cr.set_source_rgb(*s["color"])
    cr.set_line_width(0.07)
    cr.stroke()
    _tube(cr, [(0.3, -0.7), (0.17, -0.73)], INK, 0.05)                         # handlebar
    _circle(cr, 0.46, -0.4, 0.055, WHITE)                                      # headlight


def car_back(cr, s):
    if s["moving"]:
        _clouds(cr, -1.08, -0.22, s["t"])
    cr.translate(0, s["bob"])
    _rrect(cr, -0.72, -0.9, 0.22, 0.46, 0.09)                                  # seat back
    _ink(cr, _shade(s["color"], 0.55))


def car_front(cr, s):
    r = WHEEL["car"]
    a = s["dist"] / (r * s["L"])
    cr.save()
    cr.translate(0, s["bob"])
    _tube(cr, [(0.34, -0.56), (0.16, -0.66)], INK, 0.035)                     # steering wheel
    cr.save()
    cr.translate(0.15, -0.67)
    cr.rotate(-0.5)
    cr.scale(0.035, 0.1)
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()
    cr.set_source_rgb(*INK)
    cr.fill()
    cr.move_to(0.42, -0.58)                                                    # windscreen
    cr.line_to(0.27, -0.92)
    cr.line_to(0.36, -0.92)
    cr.line_to(0.52, -0.58)
    cr.close_path()
    cr.set_source_rgba(0.82, 0.93, 1.0, 0.6)
    cr.fill_preserve()
    cr.set_source_rgb(*INK)
    cr.set_line_width(LINE + 2 * _grow)
    cr.stroke()
    # the body: a round tub with the wheel arches cut out of it
    cr.move_to(1.0, -0.2)
    cr.line_to(0.88, -0.2)
    cr.arc_negative(0.62, -0.2, 0.26, 0, -math.pi)
    cr.line_to(-0.36, -0.2)
    cr.arc_negative(-0.62, -0.2, 0.26, 0, -math.pi)
    cr.line_to(-0.98, -0.2)
    cr.curve_to(-1.04, -0.3, -1.04, -0.5, -0.98, -0.56)
    cr.curve_to(-0.94, -0.6, -0.9, -0.61, -0.84, -0.61)
    cr.line_to(0.36, -0.61)
    cr.curve_to(0.66, -0.6, 0.92, -0.56, 1.0, -0.48)
    cr.curve_to(1.07, -0.41, 1.07, -0.26, 1.0, -0.2)
    cr.close_path()
    _ink(cr, s["color"])
    cr.move_to(-0.34, -0.58)                                                   # door
    cr.line_to(-0.34, -0.3)
    cr.move_to(0.3, -0.58)
    cr.line_to(0.3, -0.3)
    cr.set_source_rgb(*INK)
    cr.set_line_width(LINE * 0.8)
    cr.stroke()
    _rrect(cr, 0.12, -0.5, 0.1, 0.035, 0.017)
    cr.fill()
    _circle(cr, 0.97, -0.43, 0.055, WHITE)                                     # headlight
    _rrect(cr, -1.05, -0.5, 0.06, 0.1, 0.03)                                   # tail light
    _ink(cr, (0.95, 0.3, 0.3), LINE * 0.8)
    cr.restore()
    _wheel(cr, -0.62, -r, r, a)
    _wheel(cr, 0.62, -r, r, a)


def heli_frame(cr, s):
    """It leans into it as it flies, and sways a little: everything (him too) swings from the seat."""
    tilt = (0.07 if s["moving"] else 0.0) + math.sin(s["t"] * 2.1) * 0.03
    cr.translate(0, -0.5)
    cr.rotate(tilt)
    cr.translate(0, 0.5)


def heli_back(cr, s):
    hub = -(s["head"] + 0.1)
    for foot in ((-0.4, -0.06), (0.44, -0.07)):                               # far landing legs
        _tube(cr, [(0.0, -0.32), foot], _shade(METAL, 0.75), 0.035)
        _circle(cr, *foot, 0.04, _shade(WHITE, 0.8), LINE * 0.7)
    _tube(cr, [(-0.42, -0.44), (-0.42, hub + 0.1), (-0.12, hub + 0.05)], DARK, 0.055)   # frame
    _rrect(cr, -0.66, -1.02, 0.22, 0.42, 0.11)                                 # fuel tank
    _ink(cr, s["color"])


def heli_front(cr, s):
    hub = -(s["head"] + 0.1)
    t = s["t"]
    _rrect(cr, -0.46, -0.46, 0.5, 0.09, 0.045)                                 # his seat
    _ink(cr, INK)
    _tube(cr, [(0.0, -0.4), (0.0, -0.32)], DARK, 0.06)                         # leg hub
    for foot in ((-0.8, -0.04), (0.82, -0.04)):                                # near landing legs
        _tube(cr, [(0.0, -0.32), foot], METAL, 0.04)
        _circle(cr, *foot, 0.05, WHITE)
    _tube(cr, [(0.08, hub + 0.06), (0.3, -0.78), (0.23, -0.75)], DARK, 0.035)  # control stick
    _circle(cr, 0.23, -0.75, 0.04, INK)
    _tube(cr, [(0.0, hub), (0.0, hub - 0.22)], DARK, 0.045)                    # rotor shaft
    _rrect(cr, -0.22, hub - 0.05, 0.44, 0.17, 0.085)                           # engine
    _ink(cr, WHITE)
    _rrect(cr, -0.12, hub, 0.24, 0.07, 0.035)
    _ink(cr, s["color"], LINE * 0.7)
    for y, ra in ((hub - 0.12, t * 26), (hub - 0.22, -t * 26 + 0.8)):          # two rotors, opposite ways
        cr.save()                                                              # the blur they make
        cr.translate(0, y)
        cr.scale(1.1, 0.06)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        cr.set_source_rgba(*INK, 0.12)
        cr.fill()
        for k in (math.cos(ra), math.sin(ra)):
            half = max(0.12, 1.1 * abs(k))                                      # seen side on, blades shorten
            _rrect(cr, -half, y - 0.022, 2 * half, 0.044, 0.022)
            _ink(cr, INK, 0.01)
    _circle(cr, 0, hub - 0.22, 0.045, METAL, LINE * 0.7)


def bike_back(cr, s):
    r = WHEEL["bike"]
    a = s["dist"] / (r * s["L"])
    pa = crank("bike", s["dist"], s["L"])
    pedal = s["pedal"]
    R, F = (-0.55, -r), (0.6, -r)
    BB, S, H, Hb = BIKE_BB, (-0.13, -0.56), (0.42, -0.72), (0.48, -0.56)
    _bike_wheel(cr, *R, r, a)
    _bike_wheel(cr, *F, r, a)
    far = (BB[0] - math.cos(pa) * pedal, BB[1] - math.sin(pa) * pedal)        # far crank
    _tube(cr, [BB, far], _shade(METAL, 0.7), 0.03)
    _tube(cr, [R, BB, S, R], s["color"], 0.045)                                # back triangle
    _tube(cr, [S, H, Hb, BB], s["color"], 0.05)                                # main triangle
    _tube(cr, [Hb, F], METAL, 0.04)                                            # fork
    _rrect(cr, -0.28, -0.64, 0.26, 0.08, 0.04)                                 # saddle
    _ink(cr, INK)


def bike_front(cr, s):
    pa = crank("bike", s["dist"], s["L"])
    pedal = s["pedal"]
    BB, H = BIKE_BB, (0.42, -0.72)
    _tube(cr, [H, (0.4, -0.9)], METAL, 0.04)                                   # stem
    _tube(cr, [(0.4, -0.9), (0.26, -0.91)], INK, 0.045)                        # handlebar
    _circle(cr, *BB, 0.075, METAL)                                             # chainring
    near = (BB[0] + math.cos(pa) * pedal, BB[1] + math.sin(pa) * pedal)
    _tube(cr, [BB, near], METAL, 0.03)                                         # near crank + pedal
    _rrect(cr, near[0] - 0.05, near[1] - 0.02, 0.1, 0.04, 0.02)
    _ink(cr, INK, LINE * 0.6)


PARTS = {   # kind: (back, front, frame transform or None)
    "motorcycle": (moto_back, moto_front, None),
    "car": (car_back, car_front, None),
    "helicopter": (heli_back, heli_front, heli_frame),
    "bike": (bike_back, bike_front, None),
}


def draw(cr, kind, L, rider, t, dist=0.0, moving=True, color=None, head=1.3, pedal=0.13, halo=True):
    """Draw it at the origin (feet line, pet's middle, facing right). rider() draws the pet, with
    cr still at the origin. head: how high the rider's head is (L); pedal: the bike's crank length;
    halo: the white sticker outline (the pet's own "outline" setting)."""
    back, front, frame = PARTS[kind]
    s = {"L": L, "t": t, "dist": dist, "moving": moving, "color": color or COLORS[kind], "head": head,
         "pedal": pedal, "bob": math.sin(t * 15) * 0.008 if moving and kind == "car" else 0.0}
    x0, x1, _top = EXTENT[kind]
    hi = top(kind, head)
    bounds = (x0 - 0.7) * L, -(hi + 0.3) * L, (x1 - x0 + 1.4) * L, (hi + 0.5) * L

    def layer(part):
        global _grow
        cr.save()
        cr.scale(L, L)
        if halo:                     # white sticker outline: the same drawing with every line fatter,
            cr.save()                # as one white silhouette underneath
            cr.rectangle(bounds[0] / L, bounds[1] / L, bounds[2] / L, bounds[3] / L)
            cr.clip()                # (keeps the offscreen layer small)
            cr.push_group()
            _grow = math.hypot(*cr.device_to_user_distance(HALO, 0)) or HALO / L
            try:
                part(cr, s)
            finally:
                _grow = 0.0
            pat = cr.pop_group()
            cr.set_source_rgb(*WHITE)
            cr.mask(pat)
            cr.restore()
        part(cr, s)
        cr.restore()

    cr.save()
    if frame:
        cr.scale(L, L)
        frame(cr, s)
        cr.scale(1 / L, 1 / L)
    layer(back)
    if kind == "car":                # sitting down in it: nothing pokes out underneath
        cr.save()
        cr.rectangle(-4 * L, -4 * L, 8 * L, (4 - 0.3) * L)
        cr.clip()
        rider()
        cr.restore()
    else:
        rider()
    layer(front)
    cr.restore()


def poof(cr, x, y, L, p):
    """A ring of little cartoon clouds as a vehicle appears or disappears (p goes 0 -> 1)."""
    cr.save()
    cr.translate(x, y)
    cr.scale(L, L)
    for i in range(7):
        a = i * 2 * math.pi / 7 + 0.4
        d = 0.3 + 0.5 * p
        r = 0.13 * (1 - p) ** 0.7
        if r > 0.01:
            _circle(cr, math.cos(a) * d * 1.3, math.sin(a) * d * 0.55, r, WHITE, LINE * 0.6)
    cr.restore()
