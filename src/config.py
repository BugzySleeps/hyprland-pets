"""Settings file: ~/.config/larry/config.toml (written by the settings window, hand-editable)."""
import copy
import os
import tomllib
from pathlib import Path

import accessories
import anim
import library
import scene
import themes
import tomlw

HERE = Path(__file__).resolve().parent
DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "larry"
FILE = DIR / "config.toml"

DEFAULTS = {
    "name": "Larry",                   # your pet's name (shown in the settings window)
    "theme": themes.DEFAULT,           # colours of the box and settings: dark | desktop | light | gruvbox | ...
    "image": str(HERE / "larry.png"),  # any PNG/JPG/WebP; transparent PNGs look best
    "size": 44,                        # sprite height in px
    "faces_left": False,               # the image's character looks left (so walking flips correctly)
    "remove_bg": False,                # flood-fill the solid background away (for images without transparency)
    "outline": True,                   # white sticker outline, so dark images show on dark windows
    "fall_image": "auto",              # picture while falling or held: auto | none | a path
    "tab": {
        "edge": "top",                 # top | bottom | left | right
        "position": 72,                # % along that edge (left->right, or top->bottom)
    },
    "terminals": {
        "enabled": True,               # drag the pet onto a terminal to put it inside
        "classes": ["kitty", "Alacritty", "foot", "org.wezfurlong.wezterm", "com.mitchellh.ghostty",
                    "konsole", "org.gnome.Ptyxis", "org.gnome.Console", "xterm", "st", "urxvt"],
    },
    "behavior": {
        "watch": True,                 # stops and looks at the cursor when it comes close
        "sit": True,                   # sits down now and then (Larry)
        "sleep": True,                 # dozes off when you leave the mouse alone
        "sleep_after": 60,             # seconds of a still mouse before he falls asleep
    },
    "reactions": {
        "packages": True,              # cheers when a package manager finishes (sad if it failed)
        "downloads": True,             # cheers when a download lands in your Downloads folder
        "bubble": True,                # with a little speech bubble saying what finished
    },
    "chat": {
        "typing": False,               # napping in a terminal while you're away, it types silly messages there
        "every": 4,                    # minutes between messages (while you stay away)
    },
    "game": True,                      # catch game: throw the pet up, catch it on the way down
    "pet_sounds": False,               # moo/"weee!" when thrown, a blip when caught (off: could get annoying)
    "sounds": True,                    # clicks and ticks in the settings window
    "volume": 70,                      # 0-100
    "box": {
        "ground": "grass",             # grass | dirt | sand | snow | stone | none | img-<your picture>
        "ground_height": scene.GROUND_H,
        "background": "theme",         # theme | day | sunset | night | none | img-<your picture>
        "sky_x": 0.5,                  # framing of a sky picture: pan (0-1) and zoom (1 = just covers the box)
        "sky_y": 0.5,
        "sky_zoom": 1.0,
        "colors": "theme",             # theme | natural (decoration colours)
        "match_theme": True,           # tint the built-in skies to the colour theme
        "items": [],                   # decorations, each placed on its own (see scene.py)
    },
    # what the pet wears, in drawing order: {id: {x, y, scale, rotate, flip, behind}} (see accessories.py)
    "accessories": {},
    # the animation in use: the preset it started from + every value (see anim.py)
    "animation": {"preset": "Default", **anim.default()},
}
SIZE_MIN, SIZE_MAX = 24, 96
SLEEP_MIN, SLEEP_MAX = 10, 600
CHAT_MIN, CHAT_MAX = 1, 30

COMMENTS = {
    "name": "your pet's name",
    "match_theme": "tint the built-in skies (day, sunset, night) to the colour theme",
    "theme": "colours: " + " | ".join(themes.THEMES) + " (desktop follows rice / your GTK theme)",
    "image": "picture to use (path); delete the line to go back to Larry",
    "size": f"height in pixels ({SIZE_MIN}-{SIZE_MAX})",
    "faces_left": "true if the character in the image looks to the left",
    "remove_bg": "cut out a solid-colour background (for images without transparency)",
    "outline": "white sticker outline around the image",
    "fall_image": "picture while falling or held: auto (Larry's arms-up pose when the pet is Larry), none, or a path",
    "edge": "screen edge the tab sits on: top | bottom | left | right",
    "position": "where along that edge, in % (left to right / top to bottom)",
    "enabled": "the pet can live inside terminals (drag it onto one)",
    "classes": "window classes that count as terminals (hyprctl clients shows them)",
    "watch": "stop and look at the cursor when it comes close (Larry's eyes follow it)",
    "sit": "sit down now and then (only Larry has a sitting pose)",
    "sleep": "doze off when the mouse is left alone; wake up when it comes close",
    "typing": "napping in a terminal while you're away, it wakes up now and then and types something silly "
              "(on screen only: never typed into your shell)",
    "every": f"minutes between messages while you're away ({CHAT_MIN}-{CHAT_MAX})",
    "game": "catch game: throw the pet up and catch it on the way down (+1, in a row); best in the box",
    "pet_sounds": "the pet's own sounds: a moo (Larry) or weee when thrown, a blip when caught (off by default)",
    "packages": "react when apt, pacman, an AUR helper, emerge, dnf, zypper, flatpak... finishes",
    "downloads": "react when a download finishes in your Downloads folder",
    "bubble": "show a speech bubble saying what finished",
    "sleep_after": f"seconds of a still mouse before falling asleep ({SLEEP_MIN}-{SLEEP_MAX})",
    "sounds": "click and tick sounds in the settings window",
    "volume": "sound volume (0-100)",
    "ground": "grass | dirt | sand | snow | stone | none, or img-<name> for ~/.config/larry/grounds/<name>.png",
    "ground_height": f"how thick the ground is, in px ({scene.GROUND_MIN}-{scene.GROUND_MAX})",
    "background": "theme | day | sunset | night | none, or img-<name> for ~/.config/larry/skies/<name>.png",
    "sky_x": "sky picture framing: left-right pan (0-1)",
    "sky_y": "sky picture framing: up-down pan (0-1)",
    "sky_zoom": f"sky picture zoom (1-{scene.SKY_ZOOM_MAX:g})",
    "colors": "decoration colours: theme | natural",
    "items": "decorations: kind (" + ", ".join(scene.DECOR) + " or img-<name> from ~/.config/larry/decorations/), "
             "x (0-1 across), y (px above the ground), scale, flip, front (over the ground), seed",
    "preset": "animation preset these values came from (built-in, or ~/.config/larry/animations/<name>.toml)",
}
CHOICES = {"colors": [k for k, _ in scene.COLOR_MODES]}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(FILE, "rb") as f:
            user = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        user = {}
    for key, default in DEFAULTS.items():
        if not isinstance(default, dict) and isinstance(user.get(key), type(default)):
            cfg[key] = user[key]

    ubox = user.get("box") if isinstance(user.get("box"), dict) else {}
    box = cfg["box"]
    for key in ("colors",):
        if ubox.get(key) in CHOICES[key]:
            box[key] = ubox[key]
    g = ubox.get("ground")
    if g in [k for k, _ in scene.GROUNDS] or library.valid("grounds", g):
        box["ground"] = g
    bg = ubox.get("background")
    if bg in [k for k, _ in scene.BACKGROUNDS] or library.valid("skies", bg):
        box["background"] = bg
    for key, lo, hi in (("ground_height", scene.GROUND_MIN, scene.GROUND_MAX), ("sky_x", 0, 1), ("sky_y", 0, 1),
                        ("sky_zoom", 1, scene.SKY_ZOOM_MAX)):
        v = ubox.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = min(max(v, lo), hi)
            box[key] = round(v) if key == "ground_height" else round(float(v), 3)
    if isinstance(ubox.get("match_theme"), bool):
        box["match_theme"] = ubox["match_theme"]
    if "items" in ubox:
        box["items"] = scene.clean_items(ubox["items"])
    elif isinstance(ubox.get("decorations"), list):   # settings from before decorations could move
        seed = ubox.get("seed") if isinstance(ubox.get("seed"), int) else 1
        box["items"] = scene.legacy_items([d for d in ubox["decorations"] if d in scene.DECOR], seed,
                                          scene.ground_height(box))

    utab = user.get("tab") if isinstance(user.get("tab"), dict) else {}
    if utab.get("edge") in [k for k, _ in scene.EDGES]:
        cfg["tab"]["edge"] = utab["edge"]
    pos = utab.get("position")
    if isinstance(pos, (int, float)) and not isinstance(pos, bool):
        cfg["tab"]["position"] = max(0, min(100, round(pos)))

    ubeh = user.get("behavior") if isinstance(user.get("behavior"), dict) else {}
    for key in ("watch", "sit", "sleep"):
        if isinstance(ubeh.get(key), bool):
            cfg["behavior"][key] = ubeh[key]
    v = ubeh.get("sleep_after")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        cfg["behavior"]["sleep_after"] = max(SLEEP_MIN, min(SLEEP_MAX, round(v)))

    uchat = user.get("chat") if isinstance(user.get("chat"), dict) else {}
    if isinstance(uchat.get("typing"), bool):
        cfg["chat"]["typing"] = uchat["typing"]
    v = uchat.get("every")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        cfg["chat"]["every"] = max(CHAT_MIN, min(CHAT_MAX, round(v)))

    ureact = user.get("reactions") if isinstance(user.get("reactions"), dict) else {}
    for key in ("packages", "downloads", "bubble"):
        if isinstance(ureact.get(key), bool):
            cfg["reactions"][key] = ureact[key]

    uterm = user.get("terminals") if isinstance(user.get("terminals"), dict) else {}
    if isinstance(uterm.get("enabled"), bool):
        cfg["terminals"]["enabled"] = uterm["enabled"]
    if isinstance(uterm.get("classes"), list):
        cfg["terminals"]["classes"] = [c for c in uterm["classes"] if isinstance(c, str) and c.strip()]

    uanim = user.get("animation") if isinstance(user.get("animation"), dict) else {}
    preset = uanim.get("preset") if isinstance(uanim.get("preset"), str) else "Default"
    cfg["animation"] = {"preset": preset, **anim.clean(uanim)}

    cfg["accessories"] = accessories.clean(user.get("accessories"))

    cfg["image"] = os.path.expanduser(cfg["image"])
    if not Path(cfg["image"]).is_file():
        cfg["image"] = DEFAULTS["image"]
    if cfg["fall_image"] not in ("auto", "none"):
        cfg["fall_image"] = os.path.expanduser(cfg["fall_image"])
        if not Path(cfg["fall_image"]).is_file():
            cfg["fall_image"] = "auto"
    cfg["name"] = cfg["name"].strip()[:32] or DEFAULTS["name"]
    if cfg["theme"] not in themes.THEMES:
        cfg["theme"] = themes.DEFAULT
    cfg["size"] = max(SIZE_MIN, min(SIZE_MAX, cfg["size"]))
    cfg["volume"] = max(0, min(100, cfg["volume"]))
    return cfg


def save(cfg):
    DIR.mkdir(parents=True, exist_ok=True)
    text = "# larry settings (the settings window rewrites this file)\n\n" + tomlw.dump(cfg, comments=COMMENTS)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(FILE)
