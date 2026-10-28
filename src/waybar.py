#!/usr/bin/env python3
"""Larry in your Waybar.

As a module: Waybar's image module shows a little square with your pet's face in it, looking
however it feels (happy, asleep, startled, sad...). The pet draws those pictures itself and keeps
NOW up to date (the picture's path, then the tooltip); Waybar just reads that file once a second.
`waybar.py pop` pops the pet out (or back into its box), `waybar.py settings` opens the settings
(its clicks).

As a helper (the settings window's Waybar switch): install() adds the module to your Waybar
config, on the left, and remove() takes it out again. Everything it adds sits between marker
comments. If your config can't be edited safely it's left alone and a snippet is written to
~/.config/larry/waybar/ for you to add by hand.

Kept free of GTK and the rest of the program so Waybar can start it quickly.
"""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "image#larry"
OLD_NAMES = ("custom/larry",)   # earlier versions' module, cleaned out on install
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "larry"
ICONS = CACHE / "waybar"
NOW = ICONS / "now"


def blank():
    """Point the module at an empty picture (the pet quit): Waybar keeps the last one otherwise."""
    try:
        ICONS.mkdir(parents=True, exist_ok=True)
        empty = ICONS / "empty.png"
        if not empty.exists():   # a 1x1 transparent PNG
            empty.write_bytes(bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                "1f15c4890000000d49444154789c6360000002000005000148ee8e0000000049454e44ae426082"))
        if NOW.exists():
            NOW.write_text(f"{empty}\n")
    except OSError:
        pass
BEGIN, END = "// >>> hyprland-pets (Larry in Waybar; the settings window adds and removes this)", "// <<< hyprland-pets"
CSS_BEGIN, CSS_END = "/* >>> hyprland-pets */", "/* <<< hyprland-pets */"
CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
SNIPPETS = CONF / "larry" / "waybar"
SOCKET = "\0larry-the-cow"


# ── talking to the pet ──────────────────────────────────────────────────────
def ask(cmd, timeout=1.0):
    """Send a command to the running pet; its reply (bytes) or None if it isn't running."""
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(SOCKET)
            s.sendall(cmd.encode())
            s.shutdown(socket.SHUT_WR)
            out = b""
            while chunk := s.recv(4096):
                out += chunk
            return out
    except OSError:
        return None


SAYS = {   # what he's doing, for the tooltip
    "walk": "wandering about", "sleep": "asleep", "sit": "sitting down", "dance": "dancing",
    "type": "typing in your terminal", "watch": "watching your cursor", "pet": "loving the pets",
    "held": "being held", "fly": "flying through the air", "ride": "out for a ride", "box": "in the box",
    "away": "tucked away (click to bring them out)",
    "happy": "happy", "sad": "a bit sad",
}


def tooltip(status):
    doing = status.get("doing", "walk")
    said = SAYS.get(doing, doing)
    if doing == "ride" and status.get("vehicle"):
        said = f"riding the {status['vehicle']}"
    out = f"{status.get('name', 'Larry')} is {said}"
    if status.get("where"):
        out += f" {status['where']}"
    if status.get("best"):
        out += f" · catch best {status['best']}"
    return out + " · click: pop out / back in · right-click: settings"


# ── adding it to your Waybar config ─────────────────────────────────────────
def config_path():
    for name in ("config.jsonc", "config", "config.json"):
        p = CONF / "waybar" / name
        if p.is_file():
            return p
    return None


def module_def(size=20):
    exe = f"{shutil.which('python3') or 'python3'} {HERE / 'waybar.py'}"
    return {"exec": f"cat {NOW} 2>/dev/null", "interval": 1, "size": size, "tooltip": True,
            "on-click": f"{exe} pop", "on-click-right": f"{exe} settings"}


def bar_size(config_text):
    """How big the square can be: a little under the bar's height (if it says)."""
    m = re.search(r'"height"\s*:\s*(\d+)', config_text)
    return max(14, min(40, int(m.group(1)) - 2)) if m else 20


def jsonc_ok(text):
    """Does it still parse (comments and trailing commas allowed, as Waybar does)?"""
    t = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', lambda m: m.group(0) if m.group(0)[0] == '"' else "",
               text, flags=re.S)
    t = re.sub(r",(\s*[}\]])", r"\1", t)
    try:
        json.loads(t)
        return True
    except ValueError:
        return False


def strip_ours(text):
    text = re.sub(r"[ \t]*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"[^\n]*\n?", "", text, flags=re.S)
    for name in (NAME,) + OLD_NAMES:
        q = re.escape(f'"{name}"')
        text = re.sub(q + r"\s*,\s*", "", text)
        text = re.sub(r",\s*" + q + r"(\s*\])", r"\1", text)
        text = re.sub(r"(\[\s*)" + q + r"(\s*\])", r"\1\2", text)
    return text


def installed(text=None):
    """Is the module in your config (and its look in your style, if you have one)?"""
    p = config_path()
    try:
        if text is None:
            if not p:
                return False
            text = p.read_text()
        s = style_path()
        styled = not s or CSS in s.read_text()
    except OSError:
        return False
    return (styled and BEGIN in text and not any(f'"{n}"' in text for n in OLD_NAMES)
            and re.search(r'"modules-left"\s*:\s*\[\s*' + re.escape(f'"{NAME}"'), text) is not None)


def add_to(text):
    """The config with our module in it (first on the left), or None if it doesn't look safe."""
    text = strip_ours(text)
    m = re.search(r'^([ \t]*)"modules-left"\s*:\s*\[', text, flags=re.M)
    block = json.dumps(module_def(bar_size(text)), indent=4).replace("\n", "\n    ")
    if m:
        indent = m.group(1)
        entry = f"{indent}{BEGIN}\n{indent}\"{NAME}\": {block},\n{indent}{END}\n"
        start = m.start()
        close = text.index("]", m.end())
        sep = ", " if text[m.end():close].strip() else ""
        text = text[:m.end()] + f'"{NAME}"{sep}' + text[m.end():]     # first: the far left of the bar
        text = text[:start] + entry + text[start:]
    else:   # no modules-left yet: add one, right after the (first) bar's opening brace
        m = re.search(r"\{", text)
        if not m:
            return None
        entry = f"\n    {BEGIN}\n    \"modules-left\": [\"{NAME}\"],\n    \"{NAME}\": {block},\n    {END}\n"
        text = text[:m.end()] + entry + text[m.end():]
    return text if jsonc_ok(text) else None


CSS = f"{CSS_BEGIN}\n#image.larry {{ padding: 0 2px; margin: 0 2px 0 8px; background: transparent; }}\n{CSS_END}\n"


def style_path():
    p = CONF / "waybar" / "style.css"
    return p if p.is_file() else None


def reload_waybar():
    """Restart any running Waybar the way it was started (same arguments), so it reads the new
    config. (Not every Waybar reloads on SIGUSR2.)"""
    for pid in subprocess.run(["pgrep", "-x", "waybar"], capture_output=True, text=True).stdout.split():
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            cwd = os.readlink(f"/proc/{pid}/cwd")
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            continue
        for _ in range(30):                   # let it go before the new one claims the bar
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.05)
        subprocess.Popen([a.decode() for a in args], cwd=cwd, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def write_snippets():
    SNIPPETS.mkdir(parents=True, exist_ok=True)
    (SNIPPETS / "module.jsonc").write_text(
        f"// Add \"{NAME}\" to \"modules-left\" in your Waybar config, and this next to the other modules:\n"
        f"\"{NAME}\": {json.dumps(module_def(), indent=4)}\n")
    (SNIPPETS / "style.css").write_text(CSS)
    return SNIPPETS


def install():
    """Add the module (on the right). Returns (ok, message for the settings window)."""
    snippets = write_snippets()
    p = config_path()
    if not p:
        return False, f"No Waybar config found. The module is ready in {snippets}: add it to yours"
    try:
        text = p.read_text()
        new = add_to(text)
        if new is None:
            return False, (f"Couldn't add it to {p} safely, so it wasn't touched. The module is ready in "
                           f"{snippets}: add it by hand")
        if new != text:
            backup = snippets / f"{p.name}.before-larry"      # (kept here, not next to your config)
            if not backup.exists():
                backup.write_text(text)
            tmp = p.with_name(f".{p.name}.larry-tmp")
            tmp.write_text(new)
            tmp.replace(p.resolve()) if p.is_symlink() else tmp.replace(p)
        s = style_path()
        if s:
            css = s.read_text()
            if CSS not in css:                 # (replacing an older version's block)
                css = re.sub(r"\n?" + re.escape(CSS_BEGIN) + r".*?" + re.escape(CSS_END) + r"\n?", "\n", css,
                             flags=re.S).rstrip("\n")
                s.write_text(css + "\n\n" + CSS)
        reload_waybar()
        return True, f"Added to your Waybar, on the left ({p})"
    except OSError as e:
        return False, f"Couldn't edit {p}: {e}. The module is ready in {snippets}: add it by hand"


def remove():
    p = config_path()
    try:
        if p:
            text = p.read_text()
            new = strip_ours(text)
            if new != text and jsonc_ok(new):
                tmp = p.with_name(f".{p.name}.larry-tmp")
                tmp.write_text(new)
                tmp.replace(p.resolve()) if p.is_symlink() else tmp.replace(p)
        s = style_path()
        if s:
            css = s.read_text()
            new = re.sub(r"\n?" + re.escape(CSS_BEGIN) + r".*?" + re.escape(CSS_END) + r"\n?", "\n", css, flags=re.S)
            if new != css:
                s.write_text(new.rstrip("\n") + "\n")
        reload_waybar()
        return True, "Taken out of your Waybar"
    except OSError as e:
        return False, f"Couldn't edit your Waybar config: {e}"


def bar_edge():
    """Which screen edge your bar is on ("top" unless its config says otherwise)."""
    p = config_path()
    try:
        m = re.search(r'"position"\s*:\s*"(\w+)"', p.read_text()) if p else None
    except OSError:
        m = None
    return m.group(1) if m else "top"


def config_mtime():
    p = config_path()
    try:
        return p.stat().st_mtime if p else 0
    except OSError:
        return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("pop", "toggle", "settings") and ask(arg) is None and arg == "settings":
        subprocess.Popen([sys.executable, str(HERE / "larry.py"), "--settings"], start_new_session=True)
