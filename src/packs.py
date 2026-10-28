"""Your saved pets, and pet packs: a pet in one file you can share.

Each saved pet is a folder in ~/.config/larry/pets/<id>/:
    pet.json     its name and look: {"format", "name", "author", "description", "settings", "image", "fall_image"}
    pet.png      its picture (none for Larry himself: "image" is "builtin")
    fall.png     its own falling / held picture, if it has one
The pet you're using saves itself as you change it, so switching never loses anything.

A pet pack (.larrypet) is a zip of that folder plus the pictures of any custom accessories it
wears (accessories/<name>.png). Importing one never trusts it: only those exact file names are
read, sizes are capped, every picture is decoded and re-saved as a fresh PNG, and the settings go
through the same checks as the config file.
"""
import copy
import datetime
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import anim
import config
import library

ROOT = library.ROOT / "pets"
EXT = ".larrypet"
FORMAT = 1
# what belongs to the pet (everything else, like the theme or the box, is yours)
PET_KEYS = ("name", "size", "faces_left", "remove_bg", "outline", "outline_color", "outline_width", "coat",
            "accessories", "animation")
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
MAX_FILES = 80
MAX_FILE = 16 << 20          # bytes, uncompressed, per file
MAX_TOTAL = 64 << 20
MAX_PIXELS = 24_000_000      # per picture
PIC_SIZE = 1024              # pet pictures are kept at most this big (they're shown at <100 px)
LARRY_IMAGE = config.DEFAULTS["image"]


class PackError(Exception):
    """Something's wrong with a pet pack (the message says what, for people)."""


# ── saved pets ──────────────────────────────────────────────────────────────
def folder(slug):
    if not (isinstance(slug, str) and SLUG.fullmatch(slug)):
        return None
    return ROOT / slug


def read(slug):
    """A saved pet's pet.json (checked a little), or None."""
    d = folder(slug)
    try:
        info = json.loads((d / "pet.json").read_text())
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("settings"), dict):
        return None
    return info


def saved():
    """[(slug, info)] of every saved pet, oldest first."""
    try:
        dirs = [d for d in ROOT.iterdir() if d.is_dir()]
    except OSError:
        return []
    out = []
    for d in dirs:
        info = read(d.name)
        if info:
            out.append((d.name, info))
    return sorted(out, key=lambda p: (str(p[1].get("created", "")), p[0]))


def image_path(slug, info):
    if info.get("image") == "pet.png" and (folder(slug) / "pet.png").is_file():
        return str(folder(slug) / "pet.png")
    return LARRY_IMAGE


def fall_path(slug, info):
    v = info.get("fall_image")
    if v == "fall.png" and (folder(slug) / "fall.png").is_file():
        return str(folder(slug) / "fall.png")
    return v if v in ("auto", "none") else "auto"


def pet_cfg(cfg, slug, info):
    """cfg as it'd be with this saved pet (a copy; checked like the config file)."""
    user = copy.deepcopy(cfg)
    s = info.get("settings", {})
    for k in PET_KEYS:
        if k in s:
            user[k] = s[k]
    user["image"] = image_path(slug, info)
    user["fall_image"] = fall_path(slug, info)
    user["pet"] = slug
    return config.parse(user)


def new_slug(name):
    stem = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")[:32] or "pet"
    if not stem[0].isalnum():
        stem = "pet-" + stem
    slug, n = stem, 2
    while (ROOT / slug).exists():
        slug, n = f"{stem}-{n}", n + 1
    return slug


def _write_info(slug, info):
    d = folder(slug)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "pet.json.tmp"
    tmp.write_text(json.dumps(info, indent=1))
    tmp.replace(d / "pet.json")


def save(cfg, slug=None):
    """Store the pet in cfg as a saved pet (a new one unless slug is given). Its pictures are copied
    in, so it keeps working if the originals move. Returns (slug, cfg pointing at the copies)."""
    old = read(slug) if slug else None
    slug = slug if old else new_slug(cfg["name"])
    d = folder(slug)
    d.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(cfg)
    info = {"format": FORMAT, "name": cfg["name"],
            "author": (old or {}).get("author", ""), "description": (old or {}).get("description", ""),
            "created": (old or {}).get("created") or datetime.datetime.now().isoformat(timespec="seconds"),
            "settings": {k: cfg[k] for k in PET_KEYS}}
    if Path(cfg["image"]).resolve() == Path(LARRY_IMAGE).resolve():
        info["image"] = "builtin"
    else:
        if Path(cfg["image"]).resolve() != (d / "pet.png").resolve():
            _store_picture(Path(cfg["image"]).read_bytes(), d / "pet.png")
            cfg["image"] = str(d / "pet.png")
        info["image"] = "pet.png"
    if cfg["fall_image"] in ("auto", "none"):
        info["fall_image"] = cfg["fall_image"]
    else:
        if Path(cfg["fall_image"]).resolve() != (d / "fall.png").resolve():
            _store_picture(Path(cfg["fall_image"]).read_bytes(), d / "fall.png")
            cfg["fall_image"] = str(d / "fall.png")
        info["fall_image"] = "fall.png"
    _write_info(slug, info)
    cfg["pet"] = slug
    return slug, cfg


def sync(cfg):
    """The pet you're using changed: save it into its folder (if it has one). Returns the cfg
    (its pictures may now point at the copies) and whether that changed anything."""
    if not read(cfg.get("pet")):
        return cfg, False
    _slug, new = save(cfg, cfg["pet"])
    return new, new != cfg


def update_info(slug, **fields):
    info = read(slug)
    if info:
        info.update({k: str(v)[:300] for k, v in fields.items()})
        _write_info(slug, info)


def delete(slug):
    d = folder(slug)
    if d and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


# ── pictures ────────────────────────────────────────────────────────────────
def _decode(data):
    """Bytes -> a fresh RGBA PIL image, refusing anything that isn't a sane picture."""
    import warnings
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            probe = Image.open(io.BytesIO(data))
        with probe:
            if probe.format not in ("PNG", "JPEG", "WEBP", "GIF", "BMP"):
                raise PackError("a picture in it isn't a PNG, JPEG, WebP, GIF or BMP")
            if probe.width * probe.height > MAX_PIXELS:
                raise PackError("a picture in it is too big")
            probe.verify()
        im = Image.open(io.BytesIO(data))
        im.load()
        return im.convert("RGBA")
    except PackError:
        raise
    except Exception:
        raise PackError("a picture in it is broken") from None


def _store_picture(data, dest, size=PIC_SIZE):
    from PIL import Image
    im = _decode(data)
    im.thumbnail((size, size), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "PNG")


# ── packs ───────────────────────────────────────────────────────────────────
def export(slug, dest):
    """Write a saved pet as a .larrypet file."""
    info = read(slug)
    if not info:
        raise PackError("that pet isn't saved")
    d = folder(slug)
    out = {k: info.get(k, "") for k in ("format", "name", "author", "description", "created")}
    out["app"] = "hyprland-pets"
    out["settings"] = copy.deepcopy(info["settings"])
    out["image"] = info.get("image", "builtin")
    out["fall_image"] = info.get("fall_image", "auto")
    dest = Path(dest)
    if dest.suffix != EXT:
        dest = dest.with_name(dest.name + EXT)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("pet.png", "fall.png"):
            if out.get("image") == name or out.get("fall_image") == name:
                z.write(d / name, name)
        for acc_id in out["settings"].get("accessories", {}):
            if library.is_custom(acc_id) and library.valid("accessories", acc_id):
                z.write(library.path("accessories", acc_id), f"accessories/{acc_id[4:]}.png")
        z.writestr("pet.json", json.dumps(out, indent=1))
    return dest


def _member_ok(name):
    return name in ("pet.json", "pet.png", "fall.png") or bool(
        re.fullmatch(r"accessories/[a-z0-9_-]{1,64}\.png", name))


def peek(path):
    """(info, preview PIL image or None) of a pack without installing it."""
    info, files = _open(path)
    pic = _decode(files["pet.png"]) if "pet.png" in files else None
    return info, pic


def _open(path):
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        raise PackError("it isn't a pet pack (not a zip file)") from None
    files, total = {}, 0
    with z:
        entries = z.infolist()
        if len(entries) > MAX_FILES:
            raise PackError("it has too many files in it")
        for e in entries:
            if e.is_dir():
                continue
            if not _member_ok(e.filename):
                continue                       # anything else is ignored, never extracted
            if e.file_size > MAX_FILE or total + e.file_size > MAX_TOTAL:
                raise PackError("it's too big")
            with z.open(e) as f:
                data = f.read(MAX_FILE + 1)    # the header could lie about the size
            if len(data) > MAX_FILE:
                raise PackError("it's too big")
            total += len(data)
            files[e.filename] = data
    try:
        info = json.loads(files["pet.json"])
    except (KeyError, ValueError, UnicodeDecodeError):
        raise PackError("it's missing its pet.json") from None
    if not isinstance(info, dict) or not isinstance(info.get("settings"), dict):
        raise PackError("its pet.json doesn't look right")
    if not isinstance(info.get("format"), int) or info["format"] > FORMAT:
        raise PackError("it was made by a newer version: update hyprland-pets to use it")
    if info.get("image") == "pet.png" and "pet.png" not in files:
        raise PackError("its picture is missing")
    return info, files


def install(path):
    """Add a .larrypet file to your saved pets. Returns the new pet's slug."""
    info, files = _open(path)
    raw = info["settings"]
    name = raw.get("name") if isinstance(raw.get("name"), str) else ""
    name = name.strip()[:32] or (info.get("name") if isinstance(info.get("name"), str) else "") or "Pet"
    slug = new_slug(name)
    d = ROOT / slug
    try:
        d.mkdir(parents=True)
        image = "builtin"
        if info.get("image") == "pet.png":
            _store_picture(files["pet.png"], d / "pet.png")
            image = "pet.png"
        fall = info.get("fall_image") if info.get("fall_image") in ("auto", "none") else "auto"
        if info.get("fall_image") == "fall.png" and "fall.png" in files:
            _store_picture(files["fall.png"], d / "fall.png")
            fall = "fall.png"
        # its own accessory pictures join your library (renamed so they never replace yours)
        renamed = {}
        for member, data in files.items():
            if member.startswith("accessories/"):
                stem = member[len("accessories/"):-4]
                new = _library_name(f"{slug}-{stem}"[:60])
                _store_picture(data, library.ROOT / "accessories" / f"{new}.png", library.KINDS["accessories"]["size"])
                renamed[f"img-{stem}"] = f"img-{new}"
        acc = raw.get("accessories") if isinstance(raw.get("accessories"), dict) else {}
        acc = {renamed.get(k, k): v for k, v in acc.items() if isinstance(k, str)}
        # the same checks as the config file
        checked = config.parse({"name": name, "size": raw.get("size"), "faces_left": raw.get("faces_left"),
                                "remove_bg": raw.get("remove_bg"), "outline": raw.get("outline"),
                                "outline_color": raw.get("outline_color"), "outline_width": raw.get("outline_width"),
                                "coat": raw.get("coat"), "animation": raw.get("animation"), "accessories": acc})
        settings = {k: checked[k] for k in PET_KEYS}
        if not isinstance(raw.get("animation"), dict):
            settings["animation"] = {"preset": "Default", **anim.default()}
        text = lambda k: info[k][:300] if isinstance(info.get(k), str) else ""
        _write_info(slug, {"format": FORMAT, "name": settings["name"], "author": text("author"),
                           "description": text("description"),
                           "created": datetime.datetime.now().isoformat(timespec="seconds"),
                           "settings": settings, "image": image, "fall_image": fall})
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return slug


def _library_name(stem):
    stem = re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-") or "image"
    folder_ = library.ROOT / "accessories"
    name, n = stem, 2
    while (folder_ / f"{name}.png").exists():
        name, n = f"{stem}-{n}", n + 1
    return name

