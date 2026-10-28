"""Is there a newer hyprland-pets? Asks GitHub for the latest release (no account, about twice a
day), so the pet and the settings window can tell you, and a click runs the installer in a terminal
(it updates in place; your settings are never touched). Nothing is ever installed by itself."""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from version import VERSION

REPO = "BugzySleeps/hyprland-pets"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases"
INSTALL = f"curl -fsSL https://github.com/{REPO}/releases/latest/download/install.sh | bash"
EVERY = 12 * 3600
STATE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "larry" / "update.json"
TERMINALS = ["kitty", "foot", "alacritty", "wezterm", "ghostty", "konsole", "gnome-terminal", "xterm"]


class UpdateError(Exception):
    pass


def parse(v):
    """ "v1.10.2" -> (1, 10, 2) (anything that isn't numbers counts as 0)."""
    return tuple(int(x) if x.isdigit() else 0 for x in re.findall(r"\d+|[^\d.]+", v.lstrip("v")) if x != ".")[:3]


def newer(latest, current=VERSION):
    return parse(latest) > parse(current)


def load_state():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d))
    except OSError:
        pass


def fetch():
    """The latest release: {"version", "url", "notes"}. Raises UpdateError."""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"hyprland-pets/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read(500_000).decode())
    except (OSError, ValueError) as e:
        raise UpdateError(f"couldn't reach GitHub ({e})") from e
    tag = d.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateError("GitHub sent something unexpected")
    return {"version": tag.lstrip("v"), "url": d.get("html_url") or RELEASES,
            "notes": (d.get("body") or "")[:4000]}


def check(force=False):
    """The latest release (cached; asks GitHub at most every EVERY seconds unless forced)."""
    st = load_state()
    if not force and st.get("latest") and time.time() - st.get("checked", 0) < EVERY:
        return st["latest"]
    latest = fetch()
    st.update(latest=latest, checked=time.time())
    save_state(st)
    return latest


def available():
    """The newer release we know about (from the last check), or None."""
    latest = load_state().get("latest")
    return latest if latest and newer(latest["version"]) else None


def should_announce(version):
    """True once per new version (so the pet only tells you about it the one time)."""
    st = load_state()
    if st.get("announced") == version:
        return False
    st["announced"] = version
    save_state(st)
    return True


def run_installer(classes=()):
    """Open a terminal running the installer. True if one could be started."""
    names = [c.lower() for c in classes] + TERMINALS
    cmd = f"{INSTALL}; echo; read -rp 'Done. Press Enter to close… '"
    for name in dict.fromkeys(names):
        exe = shutil.which(name)
        if not exe:
            continue
        flag = {"gnome-terminal": "--", "wezterm": "start --", "konsole": "-e"}.get(name, "-e")
        args = [exe, *flag.split(), "bash", "-c", cmd]
        try:
            subprocess.Popen(args, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False
