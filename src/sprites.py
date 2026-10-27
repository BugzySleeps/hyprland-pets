"""Turn the configured image into the two walking sprites (facing right, facing left)."""
import hashlib
import json
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
LARRY_HELD = HERE / "larry-held.png"     # made by tools/make_falling_larry.py, with larry-held.json
LARRY_TYPING = HERE / "larry-typing.png"
LARRY_RIDING = HERE / "larry-riding.png"   # sitting on a vehicle, pedalling (+ seat / pedal points)
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


def to_surface(im):
    r, g, b, a = im.split()
    prem = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a), ImageChops.multiply(r, a), a))
    return cairo.ImageSurface.create_for_data(bytearray(prem.tobytes()), cairo.FORMAT_ARGB32, im.width, im.height,
                                              im.width * 4)


def composite(cfg, edit_pet=None):
    """The pet with its accessories, facing right, before the outline: (PIL image, ox, oy, pw, ph)
    where the pet itself sits at (ox, oy) and is pw x ph. edit_pet(im) changes the bare pet
    picture first (under the accessories)."""
    basep = base(cfg, cfg["size"] - 2 * PAD)
    items = cfg.get("accessories", {})
    if edit_pet:
        im = Image.open(basep).convert("RGBA")
        edit_pet(im)
        pet = to_surface(im)
    else:
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
    return to_pil(surf), ox, oy, pw, ph


def sticker(sprite, cfg):
    if not cfg["outline"]:
        return sprite
    halo = sprite.getchannel("A").filter(ImageFilter.MaxFilter(5))
    out = Image.new("RGBA", sprite.size, (255, 255, 255, 0))
    out.putalpha(halo)
    out.alpha_composite(sprite)
    return out


def sprite_key(cfg, extra=""):
    basep = base(cfg, cfg["size"] - 2 * PAD)
    sig = f"{basep.name}|{cfg['outline']}|{accessories.signature(cfg.get('accessories', {}))}{extra}"
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


def build(cfg):
    """Render the sprite pair as PNGs in the cache (reused until a setting or the image changes)."""
    key = sprite_key(cfg)
    out = CACHE / f"{key}-right.png", CACHE / f"{key}-left.png"
    if all(p.exists() for p in out):
        return out
    sprite = sticker(composite(cfg)[0], cfg)
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


# Larry's idle poses are cut from his standing picture (so accessories stay on): where things are
# in larry.png's own pixels
LARRY_EYES = ((371, 149, 384, 161), (313, 173, 341, 198))   # small (far) eye, big (near) eye
LARRY_BELLY = 398        # sleeping: everything below this (the legs) is tucked away
LARRY_HIPS = (222, 392)  # sitting: hind legs = left of x, below y
LARRY_SIT_TILT = 14      # degrees he leans back when sitting


def is_larry(cfg):
    return Path(cfg["image"]).resolve() == LARRY and not cfg.get("faces_left")


def seal_bottom(im, depth):
    """Black along the bottom of every opaque column (cut-off legs read as tucked hooves)."""
    a = im.getchannel("A").load()
    px = im.load()
    w, h = im.size
    for x in range(w):
        for y in range(h - 1, -1, -1):
            if a[x, y] > 128:
                for yy in range(max(0, y - depth), y + 1):
                    if a[x, yy]:
                        px[x, yy] = (0, 0, 0, a[x, yy])
                break
    return im


def pose_maps(cfg, eyes=None):
    """composite + a function mapping larry.png pixels to composite pixels, the scale and the feet
    line. eyes = "closed" / "open" paints his eyes out on the bare picture (under accessories)."""
    bx0, by0, bx1, by1 = Image.open(LARRY).getchannel("A").getbbox()
    edit = None
    if eyes:
        def edit(pet):
            k = pet.width / (bx1 - bx0)
            paint_out_eyes(pet, lambda x, y: ((x - bx0) * k, (y - by0) * k), k, eyes == "closed")
    im, ox, oy, pw, ph = composite(cfg, edit)
    k = pw / (bx1 - bx0)
    return im, (lambda x, y: (ox + (x - bx0) * k, oy + (y - by0) * k)), k, oy + ph


def paint_out_eyes(im, at, k, closed):
    d = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in LARRY_EYES:
        (X0, Y0), (X1, Y1) = at(x0, y0), at(x1, y1)
        pad = 3 * k
        d.ellipse((X0 - pad, Y0 - pad, X1 + pad, Y1 + pad), fill=(255, 255, 255, 255))
        if closed:   # a little downward curve: asleep
            cy, rx = (Y0 + Y1) / 2, (X1 - X0) / 2
            d.arc((X0 - pad, cy - rx * 0.9, X1 + pad, cy + rx * 0.9), 20, 160, fill=(0, 0, 0, 255),
                  width=max(1, round(5 * k)))


def pose_sleep(cfg):
    im, at, k, feet = pose_maps(cfg, eyes="closed")
    cut = round(at(0, LARRY_BELLY)[1])
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.alpha_composite(im.crop((0, 0, im.width, cut)), (0, feet - cut))   # lie down: belly on the ground
    return seal_bottom(out, max(1, round(9 * k)))


def pose_sit(cfg):
    im, at, k, feet = pose_maps(cfg)
    hx, hy = at(*LARRY_HIPS)
    ImageDraw.Draw(im).rectangle((0, hy, hx, im.height), fill=(0, 0, 0, 0))   # tuck the hind legs away
    P = im.width   # room to rotate into
    big = Image.new("RGBA", (im.width + 2 * P, im.height + 2 * P), (0, 0, 0, 0))
    big.alpha_composite(im, (P, P))
    big = big.rotate(LARRY_SIT_TILT, resample=Image.BICUBIC, center=(P + at(150, 0)[0], P + hy))
    x0, y0, x1, y1 = big.getchannel("A").getbbox()
    # same horizontal centre as the standing sprite (so he doesn't jump), feet on the bottom
    cx = P + im.width / 2
    half = math.ceil(max(im.width / 2, cx - x0 + PAD, x1 - cx + PAD))
    top = min(y0 - PAD, y1 + PAD - im.height)
    out = big.crop((round(cx - half), top, round(cx + half), y1 + PAD))
    return seal_bottom(out, max(1, round(9 * k)))


# held without the falling pose: his legs paddle in the air (larry.png pixels)
LARRY_LEGS = (                     # (x0, x1, cut line y, pivot): cut below his belly line, where it's
    (228, 345, 385, (288, 385)),   # front pair       only legs, and swing from the middle of the cut
    (60, 190, 400, (125, 400)),    # back pair (his tail, left of x=60, stays put)
)
DANGLE_FRAMES = 8


def paddle_legs(pet, frame, bbox):
    """Swing his front and back legs (in opposite directions) for one frame, in place on the bare
    picture. The swung legs go underneath the body, which hides the joins at the hips."""
    bx0, by0, bx1, _by1 = bbox
    k = pet.width / (bx1 - bx0)
    at = lambda x, y: ((x - bx0) * k, (y - by0) * k)
    phase = 2 * math.pi * frame / DANGLE_FRAMES
    body = pet.copy()
    under = Image.new("RGBA", pet.size, (0, 0, 0, 0))
    erase = ImageDraw.Draw(body)
    for i, (x0, x1, cut, hip) in enumerate(LARRY_LEGS):
        angle = 14 * math.sin(phase + (math.pi if i else 0))      # front forward while back goes back
        (X0, Y0), (X1, _y) = at(x0, cut), at(x1, cut)
        overlap = 6 * k                                            # a sliver above the cut hides the join
        piece = Image.new("RGBA", pet.size, (0, 0, 0, 0))
        region = pet.crop((round(X0), round(Y0 - overlap), round(X1), pet.height))
        piece.alpha_composite(region, (round(X0), round(Y0 - overlap)))
        under.alpha_composite(piece.rotate(angle, resample=Image.BICUBIC, center=at(*hip)))
        erase.rectangle((X0, Y0, X1, pet.height), fill=(0, 0, 0, 0))
    under.alpha_composite(body)
    pet.paste(under)


def pose_dangle(frame):
    def make(cfg):
        bbox = Image.open(LARRY).getchannel("A").getbbox()
        return composite(cfg, lambda pet: paddle_legs(pet, frame, bbox))[0]
    return make


def pose_eyeless(cfg):
    return pose_maps(cfg, eyes="open")[0]


EYEWEAR = {"sunglasses", "glasses"}   # with these on, his eyes don't follow the cursor


def eye_spots(cfg, scale=1):
    """Larry's eyes in the right-facing sprite, logical px: [(cx, cy, rx, ry), ...] (far eye first)."""
    _im, at, _k, _feet = pose_maps({**cfg, "size": round(cfg["size"] * scale)} if scale != 1 else cfg)
    spots = []
    for x0, y0, x1, y1 in LARRY_EYES:
        (X0, Y0), (X1, Y1) = at(x0, y0), at(x1, y1)
        spots.append(((X0 + X1) / 2 / scale, (Y0 + Y1) / 2 / scale, (X1 - X0) / 2 / scale, (Y1 - Y0) / 2 / scale))
    return spots


POSES = {"sleep": pose_sleep, "sit": pose_sit, "eyeless": pose_eyeless,
         **{f"dangle{i}": pose_dangle(i) for i in range(DANGLE_FRAMES)}}


def load_poses(cfg, scale=1):
    """Larry's idle poses: {"sleep": [right, left], "sit": [...], "eyeless": [...], "eyes": spots},
    or {} for other pets (they get the parts of each behaviour that don't need a pose)."""
    if not is_larry(cfg):
        return {}
    names = [n for n in POSES if n != "eyeless" or not EYEWEAR & set(cfg.get("accessories", {}))]
    c = {**cfg, "size": round(cfg["size"] * scale)} if scale != 1 else cfg
    poses = {}
    for name in names:
        make = POSES[name]
        key = sprite_key(c, "|pose-" + name + "-1")
        out = CACHE / f"{key}-{name}-right.png", CACHE / f"{key}-{name}-left.png"
        if not all(p.exists() for p in out):
            sprite = sticker(make(c), c)
            sprite.save(out[0])
            sprite.transpose(Image.FLIP_LEFT_RIGHT).save(out[1])
        surfaces = [cairo.ImageSurface.create_from_png(str(p)) for p in out]
        if scale != 1:
            for surf in surfaces:
                surf.set_device_scale(scale, scale)
        poses[name] = surfaces
    if "eyeless" in poses:
        poses["eyes"] = eye_spots(cfg, scale)
    return poses


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
    """[facing right, facing left] surfaces for the falling pose, or None. Larry's own pose wears
    his accessories; your own falling picture doesn't (they wouldn't line up)."""
    src = fall_source(cfg)
    if not src:
        return None
    sub = {"image": str(src), "faces_left": False, "remove_bg": not has_transparency(src)}
    k = LARRY_FALL_SCALE if src == LARRY_FALLING else 1
    basep = base(sub, round((cfg["size"] - 2 * PAD) * k * scale))
    items = cfg.get("accessories", {}) if src == LARRY_FALLING else {}
    meta_path = LARRY_FALLING.with_suffix(".json")
    if items and not meta_path.is_file():
        items = {}
    sig = f"{basep.name}|{cfg['outline']}|fall" + ("|acc-" + acc_tag(items) if items else "")
    key = hashlib.sha1(sig.encode()).hexdigest()[:16]
    out = CACHE / f"{key}-fall-right.png", CACHE / f"{key}-fall-left.png"
    if not all(p.exists() for p in out):
        pet = Image.open(basep).convert("RGBA")
        if items:
            decorate, _grow = wearing(items, json.loads(meta_path.read_text())["pet_box"], pet.width, pet.height)
            pet = decorate(pet)
        pad = round(PAD * scale)
        sprite = Image.new("RGBA", (pet.width + 2 * pad, pet.height + 2 * pad), (255, 255, 255, 0))
        sprite.alpha_composite(pet, (pad, pad))
        sprite = sticker(sprite, cfg)
        sprite.save(out[0])
        sprite.transpose(Image.FLIP_LEFT_RIGHT).save(out[1])
    surfaces = [cairo.ImageSurface.create_from_png(str(p)) for p in out]
    if scale != 1:
        for surf in surfaces:
            surf.set_device_scale(scale, scale)
    return surfaces


def wearing(items, pet_box, fw, fh, centred=True):
    """Put the accessories (fitted to the standing picture) on one of Larry's drawn poses, whose
    head is copied from that picture: pet_box says where the standing picture's box lands, as
    fractions of the fw x fh frame. Returns (decorate(frame) -> bigger frame, (gl, gt, gr) growth).
    centred grows both sides evenly, for poses drawn centred on him (so he doesn't shift)."""
    bx0, by0, bx1, by1 = pet_box
    px, py = bx0 * fw, by0 * fh
    pw, ph = (bx1 - bx0) * fw, (by1 - by0) * fh
    left, top, right = accessories.extent(items, pw, ph)
    gl = math.ceil(max(0, -(px + left)))
    gt = math.ceil(max(0, -(py + top)))
    gr = math.ceil(max(0, px + right - fw))
    if centred:
        gl = gr = max(gl, gr)

    def decorate(frame):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, frame.width + gl + gr, frame.height + gt)
        cr = cairo.Context(surf)
        cr.translate(gl + px, gt + py)
        accessories.draw(cr, items, pw, ph, behind=True)
        cr.identity_matrix()
        cr.set_source_surface(to_surface(frame), gl, gt)
        cr.paint()
        cr.translate(gl + px, gt + py)
        accessories.draw(cr, items, pw, ph, behind=False)
        return to_pil(surf)
    return decorate, (gl, gt, gr)


def acc_tag(items):
    return hashlib.sha1(accessories.signature(items).encode()).hexdigest()[:10]


def sheet_wearing(cfg, sheet, scale, centred=True):
    """(decorate, growth, frame w, frame h, tag suffix) to put the accessories on a drawn sheet, or
    None when there's nothing to wear (or the sheet doesn't say where his head is)."""
    items = cfg.get("accessories", {})
    meta = json.loads(sheet.with_suffix(".json").read_text())
    if not items or "pet_box" not in meta:
        return None
    fh = round((cfg["size"] - 2 * PAD) * meta["scale"] * scale)
    fw = max(1, round(meta["frame_w"] * fh / meta["frame_h"]))
    decorate, grow = wearing(items, meta["pet_box"], fw, fh, centred)
    return decorate, grow, fw, fh, "-acc-" + acc_tag(items)


def load_sheet(cfg, sheet, tag, scale=1, decorate=None):
    """Frames from one of Larry's drawn animation sheets (made by tools/make_falling_larry.py, with a
    .json beside it) at this pet size: a list of [right, left] cairo surfaces. decorate(frame), if
    given, changes each resized frame before the outline goes on (and `tag` must say how)."""
    meta = json.loads(sheet.with_suffix(".json").read_text())
    n, fw, fh = meta["frames"], meta["frame_w"], meta["frame_h"]
    height = round((cfg["size"] - 2 * PAD) * meta["scale"] * scale)
    key = hashlib.sha1(f"{sheet.stat().st_mtime}|{height}|{cfg['outline']}|{tag}".encode()).hexdigest()[:16]
    img = None
    frames = []
    for i in range(n):
        out = CACHE / f"{key}-{tag}{i}-right.png", CACHE / f"{key}-{tag}{i}-left.png"
        if not all(p.exists() for p in out):
            if img is None:
                img = Image.open(sheet).convert("RGBA")
                CACHE.mkdir(parents=True, exist_ok=True)
            frame = img.crop((i * fw, 0, (i + 1) * fw, fh))
            frame = frame.resize((max(1, round(fw * height / fh)), height), Image.LANCZOS)
            if decorate:
                frame = decorate(frame)
            pad = round(PAD * scale)
            sprite = Image.new("RGBA", (frame.width + 2 * pad, frame.height + 2 * pad), (255, 255, 255, 0))
            sprite.alpha_composite(frame, (pad, pad))
            sprite = sticker(sprite, cfg)
            sprite.save(out[0])
            sprite.transpose(Image.FLIP_LEFT_RIGHT).save(out[1])
        surfaces = [cairo.ImageSurface.create_from_png(str(p)) for p in out]
        if scale != 1:
            for surf in surfaces:
                surf.set_device_scale(scale, scale)
        frames.append(surfaces)
    return frames


def load_held(cfg, scale=1):
    """Larry waddling all four legs while you hold him (upright, with the falling pose on), or None."""
    if fall_source(cfg) != LARRY_FALLING or not LARRY_HELD.is_file():
        return None
    w = sheet_wearing(cfg, LARRY_HELD, scale)
    if w:
        return load_sheet(cfg, LARRY_HELD, "held-2" + w[4], scale, w[0])
    return load_sheet(cfg, LARRY_HELD, "held-2", scale)


def load_typing(cfg, scale=1):
    """Larry sitting on his butt typing on a mini keyboard, or None (other pets get a drawn keyboard)."""
    if not is_larry(cfg) or not LARRY_TYPING.is_file():
        return None
    w = sheet_wearing(cfg, LARRY_TYPING, scale)
    if w:
        return load_sheet(cfg, LARRY_TYPING, "typing-1" + w[4], scale, w[0])
    return load_sheet(cfg, LARRY_TYPING, "typing-1", scale)


def load_riding(cfg, scale=1):
    """Larry sitting on a vehicle, side on: (frames, meta) or None (other pets stand on it).
    meta["seat"] / meta["crank"] are his butt and the pedals' middle, as fractions of a frame."""
    if not is_larry(cfg) or not LARRY_RIDING.is_file():
        return None
    meta = json.loads(LARRY_RIDING.with_suffix(".json").read_text())
    w = sheet_wearing(cfg, LARRY_RIDING, scale, centred=False)   # placed by his seat, not centred
    if not w:
        return load_sheet(cfg, LARRY_RIDING, "riding-1", scale), meta
    # the frame grows for whatever sticks out, and the seat / pedal points move with it
    decorate, (gl, gt, gr), fw, height, tag = w
    W, H = fw + gl + gr, height + gt
    meta = {**meta,
            "seat": [(meta["seat"][0] * fw + gl) / W, (meta["seat"][1] * height + gt) / H],
            "crank": [(meta["crank"][0] * fw + gl) / W, (meta["crank"][1] * height + gt) / H],
            "pedal": meta["pedal"] * height / H}
    return load_sheet(cfg, LARRY_RIDING, "riding" + tag, scale, decorate), meta


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


def draw_pet(cr, sprite, cx, feet, tilt, bob, squash, extra=None):
    """Sprite standing at (cx, feet), leaning/bobbing/squashing around its feet. extra(cr), if
    given, draws on top in the sprite's own coordinates (top-left = 0, 0), e.g. Larry's pupils."""
    w, h = logical_size(sprite)
    cr.save()
    cr.translate(cx, feet - bob)
    cr.rotate(tilt)
    if squash:
        cr.scale(1 + squash / 2, 1 - squash)
    cr.set_source_surface(sprite, -w / 2, -h)
    cr.paint()
    if extra:
        cr.translate(-w / 2, -h)
        extra(cr)
    cr.restore()


def logical_size(sprite):
    """Size in drawing units (a zoomed sprite has more pixels but the same logical size)."""
    sx, sy = sprite.get_device_scale()
    return sprite.get_width() / sx, sprite.get_height() / sy
