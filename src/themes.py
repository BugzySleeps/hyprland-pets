"""Colour themes for the box, the tab and the settings window.

Each palette has the same five colours the rest of the program draws with:
  bg0 (window / deepest background), bg1 (cards, the box), fg (text),
  accent (lines, quiet details) and accent2 (highlights, the selected thing).
"Desktop" isn't a palette: it follows the rice theme switcher if you use it, otherwise your GTK
theme's colours.
"""

THEMES = {   # key: (title, palette, light?)
    "dark": ("Dark", {"bg0": "#111216", "bg1": "#1b1d23", "fg": "#e6e8ee", "accent": "#b8bdca",
                      "accent2": "#8ab4f8"}, False),
    "desktop": ("Desktop", None, False),
    "light": ("Light", {"bg0": "#eef0f4", "bg1": "#ffffff", "fg": "#1d2026", "accent": "#5a6070",
                        "accent2": "#3b82f6"}, True),
    "gruvbox": ("Gruvbox", {"bg0": "#1d2021", "bg1": "#282828", "fg": "#ebdbb2", "accent": "#bdae93",
                            "accent2": "#fabd2f"}, False),
    "evergreen": ("Evergreen", {"bg0": "#232a2e", "bg1": "#2d353b", "fg": "#d3c6aa", "accent": "#9da9a0",
                                "accent2": "#a7c080"}, False),
    "nord": ("Nord", {"bg0": "#2e3440", "bg1": "#3b4252", "fg": "#eceff4", "accent": "#d8dee9",
                      "accent2": "#88c0d0"}, False),
    "catppuccin": ("Catppuccin", {"bg0": "#1e1e2e", "bg1": "#313244", "fg": "#cdd6f4", "accent": "#a6adc8",
                                  "accent2": "#cba6f7"}, False),
    "tokyonight": ("Tokyo Night", {"bg0": "#1a1b26", "bg1": "#24283b", "fg": "#c0caf5", "accent": "#a9b1d6",
                                   "accent2": "#7aa2f7"}, False),
    "dracula": ("Dracula", {"bg0": "#21222c", "bg1": "#282a36", "fg": "#f8f8f2", "accent": "#bfbfcf",
                            "accent2": "#bd93f9"}, False),
    "rosepine": ("Rosé Pine", {"bg0": "#191724", "bg1": "#1f1d2e", "fg": "#e0def4", "accent": "#908caa",
                               "accent2": "#ebbcba"}, False),
    "solarized": ("Solarized Light", {"bg0": "#fdf6e3", "bg1": "#eee8d5", "fg": "#073642", "accent": "#586e75",
                                      "accent2": "#268bd2"}, True),
    "sakura": ("Cherry Blossom", {"bg0": "#fbeff2", "bg1": "#ffffff", "fg": "#4a2b36", "accent": "#8a5a6a",
                                  "accent2": "#e86a92"}, True),
}
DEFAULT = "dark"


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def palette(key):
    """The theme's colours as 0-1 RGB tuples (None for "desktop": that's worked out live)."""
    pal = THEMES.get(key, THEMES[DEFAULT])[1]
    return {k: rgb(v) for k, v in pal.items()} if pal else None


def is_light(colors):
    r, g, b = colors["bg0"]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5


# ── your own themes, made from a palette (e.g. one downloaded from coolors.co) ─────────────────
import colorsys  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402
from pathlib import Path  # noqa: E402

CUSTOM_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "larry" / "themes"
CUSTOM_PREFIX = "custom-"
COOLORS = "https://coolors.co/palettes/trending"
PALETTE_FILES = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.svg", "*.css", "*.scss", "*.less", "*.json", "*.txt",
                 "*.ase", "*.gpl", "*.pdf", "*.xml", "*.js")
MAX_FILE = 8 * 1024 * 1024
HEX = re.compile(r"(?<![0-9A-Za-z])#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?(?![0-9A-Za-z])")   # #rrggbb(aa)
BARE = re.compile(r"(?<![0-9A-Za-z#])([0-9a-fA-F]{6})(?![0-9A-Za-z])")                   # rrggbb


def find_hex(text):
    """Colour codes in text: #rrggbb (or #rrggbbaa) if there are any, else bare rrggbb."""
    words = lambda c: c.isalpha() and c.islower() and f'"{c}"' not in text and f"'{c}'" not in text
    return HEX.findall(text) or [c for c in BARE.findall(text) if not words(c)]   # (not "facade" or "decade")


class PaletteError(Exception):
    pass


def is_custom(key):
    return key.startswith(CUSTOM_PREFIX)


def load_custom():
    """Add your saved themes to THEMES (after the built-in ones)."""
    for key in [k for k in THEMES if is_custom(k)]:
        del THEMES[key]
    if not CUSTOM_DIR.is_dir():
        return
    for f in sorted(CUSTOM_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            d = json.loads(f.read_text())
            pal = {k: _hex(d["colors"][k]) for k in ("bg0", "bg1", "fg", "accent", "accent2")}
            THEMES[CUSTOM_PREFIX + f.stem] = (str(d["name"])[:40] or f.stem, pal, bool(d.get("light")))
        except (OSError, ValueError, KeyError, TypeError):
            continue


def save_custom(name, pal, light, source=()):
    """Save a theme you made; returns its key."""
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "theme"
    stem, n = slug, 2
    while (CUSTOM_DIR / f"{stem}.json").exists():
        stem, n = f"{slug}-{n}", n + 1
    data = {"name": name[:40], "light": bool(light), "colors": pal, "palette": list(source)}
    tmp = CUSTOM_DIR / f".{stem}.tmp"
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(CUSTOM_DIR / f"{stem}.json")
    load_custom()
    return CUSTOM_PREFIX + stem


def delete_custom(key):
    if is_custom(key):
        (CUSTOM_DIR / f"{key[len(CUSTOM_PREFIX):]}.json").unlink(missing_ok=True)
        load_custom()


def _hex(s):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", s.strip())
    if not m:
        raise ValueError(s)
    return "#" + m.group(1).lower()


def _unique(colors, limit=12):
    out = []
    for c in colors:
        c = "#" + c.lstrip("#").lower()
        if c not in out:
            out.append(c)
    return out[:limit]


# ── reading a palette ───────────────────────────────────────────────────────
def read_palette(source):
    """Colours (as "#rrggbb", in order) from a coolors link or code, or a palette file: an image,
    SVG, CSS/SCSS/JSON/text, Adobe swatches (.ase), GIMP palette (.gpl) or PDF."""
    if not isinstance(source, Path):
        text = str(source).strip()
        m = re.search(r"([0-9a-fA-F]{6}(?:-[0-9a-fA-F]{6})+)", text)   # coolors.co/264653-2a9d8f-...
        cols = m.group(1).split("-") if m else find_hex(text)
        return _check(_unique(cols))
    if source.stat().st_size > MAX_FILE:
        raise PaletteError("that file is too big to be a palette")
    data = source.read_bytes()
    ext = source.suffix.lower()
    if data[:4] == b"ASEF":
        return _check(_from_ase(data))
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif") or data[:8] == b"\x89PNG\r\n\x1a\n":
        return _check(_from_image(source))
    if data[:5] == b"%PDF-":
        return _check(_from_pdf(data))
    text = data.decode("utf-8", "replace")
    if ext == ".svg" or "<svg" in text[:2000]:
        rects = re.findall(r"<rect[^>]*?fill\s*[=:]\s*[\"']?#([0-9a-fA-F]{6})", text)
        if len(rects) >= 2:                     # the swatches, not the labels' text colour
            return _check(_unique(rects))
    if text.lstrip().startswith("GIMP Palette"):
        cols = ["%02x%02x%02x" % tuple(int(v) for v in ln.split()[:3])
                for ln in text.splitlines() if re.match(r"\s*\d+\s+\d+\s+\d+", ln)]
        return _check(_unique(cols))
    return _check(_unique(find_hex(text)))


def _check(cols):
    if len(cols) < 2:
        raise PaletteError("couldn't find at least two colours in it")
    return cols


def _from_ase(data):
    """Adobe Swatch Exchange: colour blocks with a name and RGB/CMYK/Gray/LAB floats."""
    cols, pos = [], 12
    try:
        (n,) = struct.unpack(">I", data[8:12])
        for _ in range(n):
            kind, length = struct.unpack(">HI", data[pos:pos + 6])
            body = data[pos + 6:pos + 6 + length]
            pos += 6 + length
            if kind != 0x0001:
                continue
            (nlen,) = struct.unpack(">H", body[:2])
            p = 2 + nlen * 2
            model = body[p:p + 4]
            p += 4
            if model == b"RGB ":
                r, g, b = struct.unpack(">fff", body[p:p + 12])
            elif model == b"Gray":
                (g,) = struct.unpack(">f", body[p:p + 4])
                r = b = g
            elif model == b"CMYK":
                c, m, y, k = struct.unpack(">ffff", body[p:p + 16])
                r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
            else:
                continue
            cols.append("%02x%02x%02x" % tuple(round(max(0, min(1, v)) * 255) for v in (r, g, b)))
    except struct.error:
        pass
    return _unique(cols)


def _from_image(path):
    """A palette picture (coolors' image export: a row of colour blocks, labels underneath).
    Walk across it a little way down and keep every long run of one colour; the page background
    (all four corners the same) doesn't count."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1200, 1200))
    w, h = im.size
    px = im.load()
    corners = {px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]}
    bg = corners.pop() if len(corners) == 1 else None
    close = lambda a, b: sum(abs(x - y) for x, y in zip(a, b)) < 24
    best = []
    for frac in (0.25, 0.4, 0.15, 0.55):          # a few rows: take the one that finds most colours
        y = int(h * frac)
        runs, start = [], 0
        for x in range(1, w + 1):
            if x == w or not close(px[x, y], px[start, y]):
                if x - start >= w * 0.04:
                    runs.append(px[start + (x - start) // 2, y])
                start = x
        runs = [c for c in runs if not (bg and close(c, bg))]
        if len(runs) > len(best):
            best = runs
    if len(best) < 2:                             # not blocks: the most common colours instead
        q = im.quantize(8)
        pal = q.getpalette()
        counts = sorted(q.getcolors(), reverse=True)
        best = [tuple(pal[i * 3:i * 3 + 3]) for _n, i in counts if _n > w * h * 0.03]
        best = [c for c in best if not (bg and close(c, bg))]
    return _unique("%02x%02x%02x" % c for c in best)


def _from_pdf(data):
    """Coolors' PDF lists each colour's hex code: look for them in the page text."""
    texts = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            texts.append(zlib.decompress(m.group(1)))
        except zlib.error:
            pass
    cols = []
    for t in texts:
        cols += [c.decode() for c in re.findall(rb"\(#?([0-9A-Fa-f]{6})\)", t)]
        cols += [c.decode() for c in re.findall(rb"#([0-9A-Fa-f]{6})\b", t)]
    return _unique(cols)


# ── a theme from a palette ──────────────────────────────────────────────────
def _hls(hexs):
    return colorsys.rgb_to_hls(*rgb(hexs))


def _to_hex(h, l, s):
    return "#" + "".join(f"{round(max(0, min(1, v)) * 255):02x}" for v in colorsys.hls_to_rgb(h, l, s))


def _lum(hexs):
    r, g, b = rgb(hexs)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def guess_light(cols):
    """Light theme if the palette is mostly light and has no really dark colour."""
    lums = sorted(_lum(c) for c in cols)
    return lums[0] > 0.32 or (lums[len(lums) // 2] > 0.62 and lums[0] > 0.18)


def from_palette(cols, light=None):
    """The five theme colours from any palette: the backgrounds from its darkest (or lightest)
    colour, the text from the other end, the highlight from its most vivid colour. Lightness is
    nudged so text stays readable and highlights stand out."""
    if light is None:
        light = guess_light(cols)
    by_lum = sorted(cols, key=_lum)
    base = by_lum[-1] if light else by_lum[0]
    far = by_lum[0] if light else by_lum[-1]
    bh, bl, bs = _hls(base)
    bs = min(bs, 0.45)
    if light:
        bg0 = _to_hex(bh, max(0.92, min(bl, 0.95)), bs * 0.7)
        bg1 = _to_hex(bh, max(0.975, bl), bs * 0.5)
    else:
        bg0 = _to_hex(bh, min(max(bl * 0.55, 0.06), 0.11), bs * 0.8)
        bg1 = _to_hex(bh, min(max(bl * 0.55, 0.06), 0.11) + 0.055, bs * 0.7)
    fh, fl, fs = _hls(far)
    fg = _to_hex(fh, min(fl, 0.17), min(fs, 0.4)) if light else _to_hex(fh, max(fl, 0.88), min(fs, 0.3))
    rest = [c for c in cols if c not in (base,)] or cols
    vivid = sorted(rest, key=lambda c: -(_hls(c)[2] * (1 - abs(_hls(c)[1] - 0.55) * 1.4)))
    ah, al, as_ = _hls(vivid[0])
    accent2 = _to_hex(ah, min(max(al, 0.42), 0.58) if light else min(max(al, 0.6), 0.78),
                      min(max(as_, 0.4), 0.8 if light else 0.85))   # keeps the palette's mood (soft stays soft)
    second = vivid[1] if len(vivid) > 1 else far
    sh, sl, ss = _hls(second)
    accent = _to_hex(sh, 0.38 if light else 0.72, min(ss, 0.35))
    return {"bg0": bg0, "bg1": bg1, "fg": fg, "accent": accent, "accent2": accent2}, light


load_custom()
