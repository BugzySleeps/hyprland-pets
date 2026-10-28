"""Little desktop jobs for the pet's voice commands: screenshots (grim, plus slurp to pick an area)
and music controls (playerctl). Run them off the main thread: a screenshot waits for you to drag.

Screenshots go to ~/Pictures/Screenshots and onto the clipboard too (if wl-copy is installed).
"""
import datetime
import json
import os
import shutil
import subprocess
from pathlib import Path

DIR = Path(os.environ.get("XDG_PICTURES_DIR", Path.home() / "Pictures")) / "Screenshots"


class DesktopError(Exception):
    pass


def _notify(app, icon, *args):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", app, "-i", icon, *args],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _focused_monitor():
    try:
        mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True,
                                         timeout=3).stdout)
        return next((m["name"] for m in mons if m.get("focused")), None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def screenshot(area=True):
    """Pick an area with slurp (or the whole monitor you're on) and save it. Returns the file, or None
    if you cancelled the selection. Raises DesktopError."""
    need = ["grim", "slurp"] if area else ["grim"]
    missing = [n for n in need if not shutil.which(n)]
    if missing:
        raise DesktopError(f"{missing[0]} isn't installed")
    args = ["grim"]
    if area:
        r = subprocess.run(["slurp"], capture_output=True, text=True)
        if r.returncode or not r.stdout.strip():
            return None                                  # (Esc, or clicked away: never mind)
        args += ["-g", r.stdout.strip()]
    else:
        mon = _focused_monitor()
        if mon:
            args += ["-o", mon]
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"screenshot-{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}.png"
    r = subprocess.run(args + [str(out)], capture_output=True, text=True)
    if r.returncode:
        raise DesktopError((r.stderr.strip().splitlines() or ["grim failed"])[-1])
    if shutil.which("wl-copy"):
        with open(out, "rb") as f:
            subprocess.Popen(["wl-copy", "--type", "image/png"], stdin=f, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    _notify("Screenshot", str(out), "Screenshot saved", str(out).replace(str(Path.home()), "~", 1))
    return out


def music(action):
    """play / pause / next / previous on whatever's playing (playerctl). Returns True if a player
    took it, False if nothing's playing. Raises DesktopError."""
    if not shutil.which("playerctl"):
        raise DesktopError("playerctl isn't installed")
    verb = {"play": "play", "pause": "pause", "next": "next", "previous": "previous"}[action]
    r = subprocess.run(["playerctl", verb], capture_output=True, text=True, timeout=5)
    return r.returncode == 0
