"""Turn the configured image into the two walking sprites (facing right, facing left)."""
import hashlib
import math
import os
from pathlib import Path

import cairo
from PIL import Image, ImageChops, ImageDraw, ImageFilter

import accessories

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "larry"
PAD = 3
KEY = (255, 0, 254)  # flood-fill marker for background removal
HERE = Path(__file__).resolve().parent
LARRY = HERE / "larry.png"
LARRY_FALLING = HERE / "larry-falling.png"
LARRY_FALL_SCALE = 1.625  # upright with his arms up he's taller than standing; same head size


def remove_background(im, tolerance=48):
    """Make the solid area connected to the corners transparent."""
    rgb = im.convert("RGB")
    w, h = rgb.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if rgb.getpixel(corner) != KEY:
            ImageDraw.floodfill(rgb, corner, KEY, thresh=tolerance)
    # 0 exactly where the pixel is the marker colour (summed per-channel difference)
    r, g, b = ImageChops.difference(rgb, Image.new("RGB", rgb.size, KEY)).split()
    diff = ImageChops.add(ImageChops.add(r, g), b)
    keep = diff.point(lambda v: 255 if v else 0)
    alpha = ImageChops.multiply(im.getchannel("A"), keep)
    im.putalpha(alpha.filter(ImageFilter.MinFilter(3)))  # eat the anti-aliased fringe
    return im


def base(cfg, height):
    """The pet alone, facing right, `height` px tall (background removed, cropped). Cached as a PNG."""
    src = Path(cfg["image"])
    sig = f"{src.resolve()}|{src.stat().st_mtime}|{height}|{cfg['faces_left']}|{cfg['remove_bg']}"
    path = CACHE / f"{hashlib.sha1(sig.encode()).hexdigest()[:16]}-base.png"
    if path.exists():
        return path
    CACHE.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGBA")
    if im.height > height * 8:  # work at a sane size; flood fill is per-pixel Python
        im = im.resize((max(1, round(im.width * height * 8 / im.height)), height * 8), Image.LANCZOS)
    if cfg["remove_bg"]:
        im = remove_background(im)
    bbox = im.getchannel("A").getbbox()
    if bbox:
        im = im.crop(bbox)
    width = max(1, round(im.width * height / im.height))
    im = im.resize((width, height), Image.LANCZOS)
    if cfg["faces_left"]:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    im.save(path)
    return path


def head_anchor(cfg):
    """Roughly where the top of the pet's head is (x, y as fractions), for placing new accessories."""
    if Path(cfg["image"]).resolve() == LARRY:
        return accessories.LARRY_ANCHOR
    try:
        alpha = Image.open(base(cfg, 120)).getchannel("A")
    except Exception:
        return accessories.LARRY_ANCHOR
    w, h = alpha.size
    px = alpha.load()
    tops = {}
    for x in range(int(w * 0.4), w):   # pets face right: the head is up front
        for y in range(h):
            if px[x, y] > 128:
                tops[x] = y
                break
    if not tops:
        return 0.5, 0.0
    best = min(tops.values())
    cols = [x for x, y in tops.items() if y <= best + h * 0.06]
    return round(sum(cols) / len(cols) / w, 3), round(best / h, 3)


def to_pil(surf):
    surf.flush()
    return Image.frombuffer("RGBA", (surf.get_width(), surf.get_height()), bytes(surf.get_data()),
                            "raw", "BGRa", surf.get_stride(), 1)


def build(cfg):
    """Render the sprite pair as PNGs in the cache (reused until a setting or the image changes)."""
    basep = base(cfg, cfg["size"] - 2 * PAD)
    items = cfg.get("accessories", {})
    sig = f"{basep.name}|{cfg['outline']}|{accessories.signature(items)}"
    key = hashlib.sha1(sig.encode()).hexdigest()[:16]
    out = CACHE / f"{key}-right.png", CACHE / f"{key}-left.png"
    if all(p.exists() for p in out):
        return out

    pet = cairo.ImageSurface.create_from_png(str(basep))
    pw, ph = pet.get_width(), pet.get_height()
    # grow the canvas for whatever sticks out, evenly left/right so turning around doesn't jump,
    # never below the feet (they stay on the ground)
    left, top, right = accessories.extent(items, pw, ph)
    side = math.ceil(max(-left, right - pw, 0))
    up = math.ceil(-top)
    ox, oy = PAD + side, PAD + up
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw + 2 * ox, ph + oy + PAD)
    cr = cairo.Context(surf)
    cr.rectangle(0, 0, surf.get_width(), oy + ph)
    cr.clip()
    cr.translate(ox, oy)
    accessories.draw(cr, items, pw, ph, behind=True)
    cr.set_source_surface(pet, 0, 0)
    cr.paint()
    accessories.draw(cr, items, pw, ph, behind=False)
    sprite = to_pil(surf)
    if cfg["outline"]:
        halo = sprite.getchannel("A").filter(ImageFilter.MaxFilter(5))
        sticker = Image.new("RGBA", sprite.size, (255, 255, 255, 0))
        sticker.putalpha(halo)
        sticker.alpha_composite(sprite)
        sprite = sticker
    sprite.save(out[0])
    sprite.transpose(Image.FLIP_LEFT_RIGHT).save(out[1])
    return out


def load(cfg, scale=1):
    """[facing right, facing left] cairo surfaces. scale > 1 renders a sharper copy for a zoomed
    preview; it still measures (and paints) in normal pixels thanks to the device scale."""
    paths = build({**cfg, "size": round(cfg["size"] * scale)} if scale != 1 else cfg)
    surfaces = [cairo.ImageSurface.create_from_png(str(p)) for p in paths]
    if scale != 1:
        for surf in surfaces:
            surf.set_device_scale(scale, scale)
    return surfaces


def fall_source(cfg):
    """The picture shown while the pet falls or is held, or None to keep the normal one.
    "auto" means Larry's own falling pose, but only while the pet is Larry."""
    v = cfg.get("fall_image", "auto")
    if v == "none":
        return None
    if v == "auto":
        return LARRY_FALLING if Path(cfg["image"]).resolve() == LARRY and LARRY_FALLING.is_file() else None
    return Path(v) if Path(v).is_file() else None


def load_fall(cfg, scale=1):
    """[facing right, facing left] surfaces for the falling pose, or None. Accessories aren't
    drawn on it: they're fitted to the standing picture and wouldn't line up."""
    src = fall_source(cfg)
    if not src:
        return None
    sub = {"image": str(src), "faces_left": False, "remove_bg": not has_transparency(src)}
    k = LARRY_FALL_SCALE if src == LARRY_FALLING else 1
    basep = base(sub, round((cfg["size"] - 2 * PAD) * k * scale))
    sig = f"{basep.name}|{cfg['outline']}|fall"
    key = hashlib.sha1(sig.encode()).hexdigest()[:16]
    out = CACHE / f"{key}-fall-right.png", CACHE / f"{key}-fall-left.png"
    if not all(p.exists() for p in out):
        pet = Image.open(basep).convert("RGBA")
        pad = round(PAD * scale)
        sprite = Image.new("RGBA", (pet.width + 2 * pad, pet.height + 2 * pad), (255, 255, 255, 0))
        sprite.alpha_composite(pet, (pad, pad))
        if cfg["outline"]:
            halo = sprite.getchannel("A").filter(ImageFilter.MaxFilter(5))
            sticker = Image.new("RGBA", sprite.size, (255, 255, 255, 0))
            sticker.putalpha(halo)
            sticker.alpha_composite(sprite)
            sprite = sticker
        sprite.save(out[0])
        sprite.transpose(Image.FLIP_LEFT_RIGHT).save(out[1])
    surfaces = [cairo.ImageSurface.create_from_png(str(p)) for p in out]
    if scale != 1:
        for surf in surfaces:
            surf.set_device_scale(scale, scale)
    return surfaces


def draw_centered(cr, sprite, cx, cy, tilt):
    """Sprite centred on (cx, cy), spun by tilt (the falling pose has no feet to stand on)."""
    w, h = logical_size(sprite)
    cr.save()
    cr.translate(cx, cy)
    cr.rotate(tilt)
    cr.set_source_surface(sprite, -w / 2, -h / 2)
    cr.paint()
    cr.restore()


def has_transparency(path):
    try:
        im = Image.open(path)
        if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
            return im.convert("RGBA").getchannel("A").getextrema()[0] < 250
    except OSError:
        pass
    return False


def draw_pet(cr, sprite, cx, feet, tilt, bob, squash):
    """Sprite standing at (cx, feet), leaning/bobbing/squashing around its feet."""
    w, h = logical_size(sprite)
    cr.save()
    cr.translate(cx, feet - bob)
    cr.rotate(tilt)
    if squash:
        cr.scale(1 + squash / 2, 1 - squash)
    cr.set_source_surface(sprite, -w / 2, -h)
    cr.paint()
    cr.restore()


def logical_size(sprite):
    """Size in drawing units (a zoomed sprite has more pixels but the same logical size)."""
    sx, sy = sprite.get_device_scale()
    return sprite.get_width() / sx, sprite.get_height() / sy
