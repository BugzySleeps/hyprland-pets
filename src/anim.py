"""Animation settings: the tunable numbers, the shape curves, and saved presets.

A preset is one dict: every PARAMS key plus `curves` (name -> [[x, y], ...]). The working
copy lives in config.toml's [animation] table; saved presets are separate files in
~/.config/larry/animations/, next to the read-only built-ins below.
"""
import copy
import os
import re
import tomllib
from pathlib import Path

import tomlw

USER_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "larry" / "animations"

# key: (label, min, max, step, digits, default, unit)
PARAMS = {
    "walk_speed":  ("Walk speed (box)",     5, 120, 1, 0, 28, "px/s"),
    "free_speed":  ("Walk speed (screen)",  5, 160, 1, 0, 38, "px/s"),
    "step_length": ("Step length",          2, 40, 1, 0, 5, "px"),
    "tilt":        ("Waddle tilt",          0, 30, 1, 0, 5, "°"),
    "bob":         ("Bob height",           0, 16, 0.5, 1, 2, "px"),
    "squash":      ("Squash & stretch",     0, 40, 1, 0, 0, "%"),
    "stop_every":  ("Stops every",          0, 30, 0.5, 1, 6, "s"),
    "stop_min":    ("Shortest stop",        0.1, 10, 0.1, 1, 0.8, "s"),
    "stop_max":    ("Longest stop",         0.1, 10, 0.1, 1, 2.5, "s"),
    "turn_chance": ("Turn around on stop",  0, 100, 5, 0, 50, "%"),
    "gravity":     ("Gravity",              100, 4000, 50, 0, 1800, "px/s²"),
    "throw":       ("Throw strength",       0, 3, 0.1, 1, 1.0, "×"),
    "bounce":      ("Wall bounce",          0, 1, 0.05, 2, 0.5, ""),
    "open_time":   ("Box open time",        0.05, 1.5, 0.05, 2, 0.17, "s"),
}
GROUPS = [
    ("Walking", ["walk_speed", "free_speed", "step_length", "tilt", "bob", "squash"]),
    ("Wandering", ["stop_every", "stop_min", "stop_max", "turn_chance"]),
    ("Physics", ["gravity", "throw", "bounce"]),
    ("Box", ["open_time"]),
]
HINTS = {"stop_every": "0 = never stops"}

# key: (label, cyclic, y range, help, default points)
CURVES = {
    "tilt": ("Waddle tilt", True, (-1, 1),
             "Lean over one step: up = lean forward, down = lean back (× Waddle tilt)",
             [[0, 0], [0.25, 1], [0.5, 0], [0.75, -1], [1, 0]]),
    "bob": ("Bob", True, (0, 1),
            "Height over one step (× Bob height)",
            [[0, 0], [0.25, 1], [0.5, 0], [0.75, 1], [1, 0]]),
    "squash": ("Squash", True, (-1, 1),
               "Up = squashed flat, down = stretched tall, over one step (× Squash & stretch)",
               [[0, 1], [0.25, 0], [0.5, 1], [0.75, 0], [1, 1]]),
    "open": ("Box open", False, (-0.25, 1.25),
             "How the box slides down over its open time; above the top line it overshoots and springs back",
             [[0, 0], [0.3, 0.72], [1, 1]]),
}


def default():
    d = {k: v[5] for k, v in PARAMS.items()}
    d["curves"] = {k: copy.deepcopy(v[4]) for k, v in CURVES.items()}
    return d


def _preset(**changes):
    d = default()
    curves = changes.pop("curves", {})
    d.update(changes)
    d["curves"].update(curves)
    return d


BUILTINS = {
    "Default": default(),
    "Bouncy": _preset(walk_speed=34, free_speed=46, step_length=9, tilt=3, bob=7, squash=18,
                      bounce=0.85, gravity=1500, open_time=0.4,
                      curves={"open": [[0, 0], [0.5, 1.18], [0.75, 0.94], [1, 1]],
                              "squash": [[0, 1], [0.15, -0.4], [0.5, 1], [0.65, -0.4], [1, 1]]}),
    "Lazy": _preset(walk_speed=12, free_speed=16, step_length=8, tilt=3, bob=1, stop_every=3,
                    stop_min=2, stop_max=6, turn_chance=30, open_time=0.5,
                    curves={"open": [[0, 0], [0.25, 0.06], [0.75, 0.94], [1, 1]]}),
    "Hyper": _preset(walk_speed=70, free_speed=95, step_length=6, tilt=9, bob=3, stop_every=2.5,
                     stop_min=0.2, stop_max=0.6, turn_chance=80, open_time=0.1),
    "Floaty": _preset(walk_speed=20, free_speed=26, step_length=14, tilt=2, bob=4, gravity=300,
                      throw=1.5, bounce=0.9, open_time=0.6,
                      curves={"bob": [[0, 0.5], [0.25, 1], [0.5, 0.5], [0.75, 0], [1, 0.5]]}),
}


# ── validation ──────────────────────────────────────────────────────────────
def clean_curve(key, pts):
    _label, cyclic, (lo, hi), _help, fallback = CURVES[key]
    try:
        pts = sorted((min(max(float(x), 0), 1), min(max(float(y), lo), hi)) for x, y in pts)
    except (TypeError, ValueError):
        return copy.deepcopy(fallback)
    if len(pts) < 2:
        return copy.deepcopy(fallback)
    pts[0] = (0.0, pts[0][1])
    pts[-1] = (1.0, pts[-1][1])
    if cyclic:
        pts[-1] = (1.0, pts[0][1])       # loops seamlessly
    if key == "open":
        pts[0], pts[-1] = (0.0, 0.0), (1.0, 1.0)  # starts shut, ends open
    return [[round(x, 4), round(y, 4)] for x, y in pts]


def clean(d):
    """Any dict (from a file) -> a complete, in-range animation dict."""
    out = default()
    if not isinstance(d, dict):
        return out
    for key, (_l, lo, hi, *_rest) in PARAMS.items():
        v = d.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = min(max(v, lo), hi)
    curves = d.get("curves") if isinstance(d.get("curves"), dict) else {}
    for key in CURVES:
        if isinstance(curves.get(key), list):
            out["curves"][key] = clean_curve(key, curves[key])
    return out


def same(a, b):
    """Equal as animations (ignores int/float and rounding noise)."""
    if any(abs(a[k] - b[k]) > 1e-6 for k in PARAMS):
        return False
    return all(a["curves"][k] == b["curves"][k] for k in CURVES)


# ── curves at runtime ───────────────────────────────────────────────────────
def sample(points, cyclic, n=256):
    """Smooth curve through the points (cubic Hermite, cardinal tangents) as an n+1 lookup table."""
    pts = [tuple(p) for p in points]
    last = len(pts) - 1

    def neighbour(i):
        if 0 < i < last:
            return pts[i - 1], pts[i + 1]
        if cyclic and last >= 2:
            prev = (pts[-2][0] - 1, pts[-2][1]) if i == 0 else pts[i - 1]
            nxt = (pts[1][0] + 1, pts[1][1]) if i == last else pts[i + 1]
            return prev, nxt
        return (pts[0], pts[1]) if i == 0 else (pts[-2], pts[-1])

    tangents = []
    for i in range(len(pts)):
        (x0, y0), (x1, y1) = neighbour(i)
        tangents.append((y1 - y0) / (x1 - x0) if x1 != x0 else 0)

    lut, seg = [], 0
    for j in range(n + 1):
        x = j / n
        while seg < last - 1 and x > pts[seg + 1][0]:
            seg += 1
        (xa, ya), (xb, yb) = pts[seg], pts[seg + 1]
        h = xb - xa or 1e-9
        t = min(max((x - xa) / h, 0), 1)
        t2, t3 = t * t, t * t * t
        lut.append((2 * t3 - 3 * t2 + 1) * ya + (t3 - 2 * t2 + t) * h * tangents[seg]
                   + (-2 * t3 + 3 * t2) * yb + (t3 - t2) * h * tangents[seg + 1])
    return lut


class Curve:
    def __init__(self, points, cyclic):
        self.cyclic = cyclic
        self.lut = sample(points, cyclic)
        self.n = len(self.lut) - 1

    def __call__(self, x):
        x = x % 1 if self.cyclic else min(max(x, 0), 1)
        f = x * self.n
        i = min(int(f), self.n - 1)
        return self.lut[i] + (self.lut[i + 1] - self.lut[i]) * (f - i)


class Compiled:
    """An animation dict with its curves turned into fast lookups: a.tilt_curve(phase) etc."""

    def __init__(self, d):
        self.__dict__.update({k: d[k] for k in PARAMS})
        for key, (_l, cyclic, *_rest) in CURVES.items():
            setattr(self, f"{key}_curve", Curve(d["curves"][key], cyclic))

    def pose(self, phase, walking):
        """(tilt radians, bob px upward, squash fraction) at this point of the step cycle."""
        if not walking:
            return 0.0, 0.0, 0.0
        import math
        return (math.radians(self.tilt) * self.tilt_curve(phase),
                self.bob * self.bob_curve(phase),
                self.squash / 100 * self.squash_curve(phase))


# ── presets on disk ─────────────────────────────────────────────────────────
def user_names():
    try:
        return sorted(p.stem for p in USER_DIR.glob("*.toml"))
    except OSError:
        return []


def get(name):
    if name in BUILTINS:
        return copy.deepcopy(BUILTINS[name])
    try:
        with open(USER_DIR / f"{name}.toml", "rb") as f:
            return clean(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError):
        return None


def valid_name(name):
    name = name.strip()
    if not name or name in BUILTINS or not re.fullmatch(r"[\w .()+-]{1,40}", name):
        return None
    return name


def save(name, d):
    USER_DIR.mkdir(parents=True, exist_ok=True)
    (USER_DIR / f"{name}.toml").write_text(f"# larry animation preset: {name}\n\n" + tomlw.dump(d))


def delete(name):
    try:
        (USER_DIR / f"{name}.toml").unlink()
    except OSError:
        pass
