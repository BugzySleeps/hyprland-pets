"""Settings file: ~/.config/larry/config.toml (written by the settings window, hand-editable)."""
import copy
import os
import re
import tomllib
from pathlib import Path

import accessories
import anim
import library
import scene
import themes
import tomlw
import vehicles

HERE = Path(__file__).resolve().parent
DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "larry"
FILE = DIR / "config.toml"

DEFAULTS = {
    "name": "Larry",                   # your pet's name (shown in the settings window)
    "pet": "",                         # which of your saved pets this is (~/.config/larry/pets/<id>/)
    "theme": themes.DEFAULT,           # colours of the box and settings: dark | desktop | light | gruvbox | ...
    "image": str(HERE / "larry.png"),  # any PNG/JPG/WebP; transparent PNGs look best
    "size": 44,                        # sprite height in px
    "faces_left": False,               # the image's character looks left (so walking flips correctly)
    "remove_bg": False,                # flood-fill the solid background away (for images without transparency)
    "outline": True,                   # white sticker outline, so dark images show on dark windows
    "outline_color": "#ffffff",        # its colour
    "outline_width": 2,                # and how thick it is, px
    "fall_image": "auto",              # picture while falling or held: auto | none | a path
    "box_tab": True,                   # the pull-down box and its tab (off: just the pet, e.g. with the Waybar module)
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
        "peek": True,                  # with the box shut, pokes his head out beside the tab now and then
        "petting": True,               # hold the middle mouse button (scroll wheel) and stroke him
        "greet": True,                 # climbs out and stretches when you log in (excited after a few days away)
        "goodbye": False,              # waves goodbye in the middle of the screen when you shut down or reboot
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
    "ride": {
        "enabled": True,               # now and then it hops on a vehicle instead of walking
        "vehicle": "motorcycle",       # motorcycle | car | helicopter | bike | random
        "every": 3,                    # minutes between rides, roughly
    },
    "dance": {
        "enabled": True,               # dances while music is playing (any MPRIS player)
        "beat": True,                  # listen with cava to dance in time (if cava is installed)
        "notes": True,                 # music notes float up while it dances
    },
    "voice": {
        "enabled": False,              # voice commands ("Larry, come here"), recognised offline (see voice.py)
        "mic": "",                     # which microphone (a PipeWire/Pulse source name; "" = the default one)
    },
    "updates": True,                   # check GitHub for new releases (and tell you; never installs by itself)
    "waybar": False,                   # Larry in your Waybar (a module on the left; see waybar.py)
    "weather": {
        "enabled": False,              # dress for your local weather (Open-Meteo: no account needed)
        "place": "",                   # where (as found by the settings window's search)
        "lat": 0.0,
        "lon": 0.0,
        "effects": True,               # rain and snow falling in the box
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
        "colors": "theme",             # theme | natural (floor and sky colours)
        "match_theme": True,           # tint the built-in skies to the colour theme
    },
    "coat": {                          # Larry's colours (only his own pictures can be recoloured)
        "skin": "#ffffff",
        "spots": "#000000",
        "lines": "#000000",
    },
    # what the pet wears, in drawing order: {id: {x, y, scale, rotate, flip, behind}} (see accessories.py)
    "accessories": {},
    # the animation in use: the preset it started from + every value (see anim.py)
    "animation": {"preset": "Default", **anim.default()},
}
SIZE_MIN, SIZE_MAX = 24, 96
SLEEP_MIN, SLEEP_MAX = 10, 600
CHAT_MIN, CHAT_MAX = 1, 30
RIDE_MIN, RIDE_MAX = 1, 30

COMMENTS = {
    "name": "your pet's name",
    "updates": "check GitHub about twice a day for a new version, and tell you (nothing installs by itself)",
    "box_tab": "show the pull-down box and its tab (turn off to keep just the pet, e.g. with the Waybar module)",
    "waybar": "show Larry in your Waybar (the settings window adds the module on the left)",
    "mic": "microphone for voice commands (a source name from `pactl list sources`; empty = your default)",
    "place": "where the weather is checked for (search for it in the settings window)",
    "lat": "its latitude",
    "lon": "its longitude",
    "effects": "rain and snow fall in the box when it's raining or snowing there",
    "skin": "Larry's skin colour, #rrggbb",
    "spots": "Larry's spot colour, #rrggbb",
    "lines": "Larry's outline colour (his line work, not the white sticker edge), #rrggbb",
    "pet": "which saved pet this is: a folder in ~/.config/larry/pets/ (changes to the pet are saved there too)",
    "match_theme": "tint the built-in skies (day, sunset, night) to the colour theme",
    "theme": "colours: " + " | ".join(themes.THEMES) + " (desktop follows rice / your GTK theme)",
    "image": "picture to use (path); delete the line to go back to Larry",
    "size": f"height in pixels ({SIZE_MIN}-{SIZE_MAX})",
    "faces_left": "true if the character in the image looks to the left",
    "remove_bg": "cut out a solid-colour background (for images without transparency)",
    "outline": "white sticker outline around the image",
    "outline_color": "the sticker outline's colour, #rrggbb",
    "outline_width": "the sticker outline's thickness in px (1-8)",
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
    "ride.enabled": "now and then the pet hops on a vehicle instead of walking",
    "ride.vehicle": "which one: " + " | ".join(vehicles.KINDS) + " | random",
    "ride.every": f"minutes between rides, roughly ({RIDE_MIN}-{RIDE_MAX})",
    "dance.enabled": "dance while music is playing (Spotify, mpv, a browser... anything that shows up in playerctl)",
    "dance.beat": "listen with cava to dance in time with the song (needs cava; otherwise a steady 120 BPM)",
    "dance.notes": "music notes float up while it dances",
    "game": "catch game: throw the pet up and catch it on the way down (+1, in a row); best in the box",
    "pet_sounds": "the pet's own sounds: a moo (Larry) or weee when thrown, a blip when caught (off by default)",
    "packages": "react when apt, pacman, an AUR helper, emerge, dnf, zypper, flatpak... finishes",
    "downloads": "react when a download finishes in your Downloads folder",
    "bubble": "show a speech bubble saying what finished",
    "sleep_after": f"seconds of a still mouse before falling asleep ({SLEEP_MIN}-{SLEEP_MAX})",
    "petting": "hold the middle mouse button (scroll wheel) and move over the pet to pet it",
    "peek": "with the box closed, the pet pokes its head out beside the tab now and then",
    "goodbye": "when you shut down or reboot, the pet waves goodbye in the middle of the screen and floats away (off by default)",
    "greet": "when you log in, the pet climbs out of its box and stretches (extra excited if you've been away a few days)",
    "sounds": "click and tick sounds in the settings window",
    "volume": "sound volume (0-100)",
    "ground": "grass | dirt | sand | snow | stone | none, or img-<name> for ~/.config/larry/grounds/<name>.png",
    "ground_height": f"how thick the ground is, in px ({scene.GROUND_MIN}-{scene.GROUND_MAX})",
    "background": "theme | day | sunset | night | none, or img-<name> for ~/.config/larry/skies/<name>.png",
    "sky_x": "sky picture framing: left-right pan (0-1)",
    "sky_y": "sky picture framing: up-down pan (0-1)",
    "sky_zoom": f"sky picture zoom (1-{scene.SKY_ZOOM_MAX:g})",
    "colors": "floor and sky colours: theme | natural",
    "preset": "animation preset these values came from (built-in, or ~/.config/larry/animations/<name>.toml)",
}
CHOICES = {"colors": [k for k, _ in scene.COLOR_MODES]}


def load():
    try:
        with open(FILE, "rb") as f:
            user = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        user = {}
    return parse(user)


def parse(user):
    """Settings as read from the file (or any dict shaped like it), checked and filled in."""
    cfg = copy.deepcopy(DEFAULTS)
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
    # (decorations are gone: old "items" / "decorations" in the file are simply left out)

    utab = user.get("tab") if isinstance(user.get("tab"), dict) else {}
    if utab.get("edge") in [k for k, _ in scene.EDGES]:
        cfg["tab"]["edge"] = utab["edge"]
    pos = utab.get("position")
    if isinstance(pos, (int, float)) and not isinstance(pos, bool):
        cfg["tab"]["position"] = max(0, min(100, round(pos)))

    ubeh = user.get("behavior") if isinstance(user.get("behavior"), dict) else {}
    for key in ("watch", "sit", "sleep", "petting", "peek", "greet", "goodbye"):
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

    uride = user.get("ride") if isinstance(user.get("ride"), dict) else {}
    if isinstance(uride.get("enabled"), bool):
        cfg["ride"]["enabled"] = uride["enabled"]
    if uride.get("vehicle") in (*vehicles.KINDS, "random"):
        cfg["ride"]["vehicle"] = uride["vehicle"]
    v = uride.get("every")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        cfg["ride"]["every"] = max(RIDE_MIN, min(RIDE_MAX, round(v)))

    udance = user.get("dance") if isinstance(user.get("dance"), dict) else {}
    for key in ("enabled", "beat", "notes"):
        if isinstance(udance.get(key), bool):
            cfg["dance"][key] = udance[key]

    uvoice = user.get("voice") if isinstance(user.get("voice"), dict) else {}
    if isinstance(uvoice.get("enabled"), bool):
        cfg["voice"]["enabled"] = uvoice["enabled"]
    if isinstance(uvoice.get("mic"), str) and re.fullmatch(r"[\w.:-]{0,200}", uvoice["mic"]):
        cfg["voice"]["mic"] = uvoice["mic"]

    uweather = user.get("weather") if isinstance(user.get("weather"), dict) else {}
    for key in ("enabled", "effects"):
        if isinstance(uweather.get(key), bool):
            cfg["weather"][key] = uweather[key]
    if isinstance(uweather.get("place"), str):
        cfg["weather"]["place"] = uweather["place"].strip()[:80]
    for key, lim in (("lat", 90), ("lon", 180)):
        v = uweather.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and -lim <= v <= lim:
            cfg["weather"][key] = float(v)

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

    ucoat = user.get("coat") if isinstance(user.get("coat"), dict) else {}
    for key in ("skin", "spots", "lines"):
        v = ucoat.get(key)
        if isinstance(v, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", v.strip()):
            cfg["coat"][key] = "#" + v.strip().lstrip("#").lower()

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
    if isinstance(user.get("outline_width"), bool):
        cfg["outline_width"] = DEFAULTS["outline_width"]
    cfg["outline_width"] = max(1, min(8, cfg["outline_width"]))
    oc = cfg["outline_color"].strip()
    cfg["outline_color"] = "#" + oc.lstrip("#").lower() if re.fullmatch(r"#?[0-9a-fA-F]{6}", oc) else "#ffffff"
    cfg["volume"] = max(0, min(100, cfg["volume"]))
    return cfg


def save(cfg):
    DIR.mkdir(parents=True, exist_ok=True)
    text = "# larry settings (the settings window rewrites this file)\n\n" + tomlw.dump(cfg, comments=COMMENTS)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(FILE)
