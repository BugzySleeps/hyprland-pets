"""Your own pictures, one folder per use under ~/.config/larry/:
accessories/, decorations/, grounds/, skies/. Each picture's id is "img-<file stem>"."""
import os
import re
from pathlib import Path

import cairo

ROOT = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "larry"
# cutout: remove a solid background; trim: crop empty edges; size: longest side kept
KINDS = {
    "accessories": {"cutout": True, "trim": True, "size": 512},
    "decorations": {"cutout": True, "trim": True, "size": 512},
    "grounds": {"cutout": False, "trim": True, "size": 512},
    "skies": {"cutout": False, "trim": False, "size": 1920},
}
NAME = re.compile(r"[a-z0-9_-]+")
_surfaces = {}


def is_custom(item_id):
    return isinstance(item_id, str) and item_id.startswith("img-") and bool(NAME.fullmatch(item_id[4:]))


def path(kind, item_id):
    return ROOT / kind / f"{item_id[4:]}.png"


def valid(kind, item_id):
    return is_custom(item_id) and path(kind, item_id).is_file()


def title(item_id):
    return item_id[4:].replace("-", " ").replace("_", " ")


def items(kind):
    """[(id, title)], oldest first (so new pictures land at the end)."""
    try:
        files = sorted((ROOT / kind).glob("*.png"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    return [(f"img-{p.stem}", title(f"img-{p.stem}")) for p in files if NAME.fullmatch(p.stem)]


def surface(kind, item_id):
    """The picture as a cairo surface (cached until the file changes), or None."""
    p = path(kind, item_id)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    hit = _surfaces.get(p)
    if not hit or hit[0] != mtime:
        try:
            hit = (mtime, cairo.ImageSurface.create_from_png(str(p)))
        except Exception:
            return None
        _surfaces[p] = hit
    return hit[1]


def mtime(kind, item_id):
    try:
        return path(kind, item_id).stat().st_mtime
    except OSError:
        return 0


def import_image(kind, src):
    """Copy a picture in (as a PNG, tidied up for its use) and return its id."""
    from PIL import Image

    import sprites
    opts = KINDS[kind]
    im = Image.open(src).convert("RGBA")
    im.thumbnail((opts["size"], opts["size"]), Image.LANCZOS)
    if opts["cutout"] and not sprites.has_transparency(src):
        im = sprites.remove_background(im)
    if opts["trim"]:
        bbox = im.getchannel("A").getbbox()
        if bbox:
            im = im.crop(bbox)
    stem = re.sub(r"[^a-z0-9_-]+", "-", Path(src).stem.lower()).strip("-")[:32] or "image"
    folder = ROOT / kind
    folder.mkdir(parents=True, exist_ok=True)
    name, n = stem, 2
    while (folder / f"{name}.png").exists():
        name, n = f"{stem}-{n}", n + 1
    im.save(folder / f"{name}.png")
    return f"img-{name}"


def delete(kind, item_id):
    try:
        path(kind, item_id).unlink()
    except OSError:
        pass
