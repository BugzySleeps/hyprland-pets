"""Notice when something finishes downloading, so the pet can react.

Two sources, both distro-neutral:
  - package managers: any of them running (apt, pacman, AUR helpers, emerge, dnf, zypper, xbps,
    apk, flatpak, snap, nix, brew...) is seen in /proc; when the last one exits, that's a finished
    session. Where the package manager's log is readable, it says whether it worked.
  - the Downloads folder: a browser/wget/aria2 download finishing (its temporary file becomes
    the real one, or the file is closed for the last time).
"""
import os
import time
from pathlib import Path

from gi.repository import Gio, GLib

# process name -> label shown in the bubble
MANAGERS = {
    "pacman": "pacman", "yay": "yay", "paru": "paru", "pikaur": "pikaur", "trizen": "trizen",
    "aura": "aura", "pamac": "pamac", "apt": "apt", "apt-get": "apt", "aptitude": "aptitude",
    "nala": "nala", "emerge": "emerge", "dnf": "dnf", "dnf5": "dnf", "yum": "yum", "zypper": "zypper",
    "xbps-install": "xbps", "apk": "apk", "eopkg": "eopkg", "swupd": "swupd", "flatpak": "flatpak",
    "snap": "snap", "nix-env": "nix", "nix": "nix", "brew": "brew", "pip": "pip", "pip3": "pip",
    "pipx": "pipx", "cargo": "cargo", "npm": "npm",
}
# these do lots of things besides installing: only count them doing one of these
NEEDS_VERB = {
    "flatpak": {"install", "update", "upgrade", "uninstall", "remove"},
    "snap": {"install", "refresh", "remove"},
    "nix": {"install", "upgrade"},
    "brew": {"install", "upgrade", "reinstall"},
    "pip": {"install"}, "pip3": {"install"}, "pipx": {"install", "upgrade", "upgrade-all"},
    "cargo": {"install"}, "npm": {"install", "i", "update"},
}
# looking things up isn't a download
QUERY_VERBS = {"search", "show", "list", "info", "policy", "depends", "rdepends", "changelog", "provides",
               "repoquery", "se", "if", "query", "files", "why", "help"}
QUERY_FLAGS = {"--search", "-s", "--pretend", "-p", "--info", "--searchdesc", "-S", "--help", "-h",
               "--version", "-V"}   # emerge's; pacman's are checked separately

LOGS = {   # log -> (success marker(s), failure marker(s)); read only what was added during the session
    "/var/log/pacman.log": (("transaction completed", "synchronizing package lists"), ("transaction failed",)),
    "/var/log/apt/history.log": (("End-Date:",), ("Error:",)),
    "/var/log/emerge.log": (("exiting successfully", "Sync completed"), ("exiting unsuccessfully",)),
    "/var/log/dnf5.log": ((), ()),
    "/var/log/dnf.log": ((), ()),
}
MIN_SECONDS = 3   # shorter than this and nothing was logged: probably cancelled at the prompt

TEMP_SUFFIXES = (".part", ".crdownload", ".download", ".tmp", ".partial", ".opdownload", ".!qb", ".aria2")


def is_query(name, args):
    if name in ("pacman", "yay", "paru", "pikaur", "trizen", "aura"):
        ops = [a for a in args if a.startswith("-") and not a.startswith("--")]
        if any(o.startswith("-Q") or o.startswith("-F") or o.startswith("-T") for o in ops):
            return True
        if any(o.startswith("-S") and ("s" in o[2:] or "i" in o[2:] or "l" in o[2:] or "g" in o[2:]) for o in ops):
            return True   # -Ss / -Si / -Sl / -Sg
        if not args and name != "pacman":
            return False  # bare `yay`: a full upgrade
        return False
    verbs = [a for a in args if not a.startswith("-")]
    if name in NEEDS_VERB:
        return not (verbs and verbs[0] in NEEDS_VERB[name])
    if verbs and verbs[0] in QUERY_VERBS:
        return True
    return name == "emerge" and any(a in QUERY_FLAGS for a in args)


class Watcher:
    """Calls on_done(kind, ok, label) on the GLib main loop: kind is "package" or "download",
    ok is False when it failed (as far as can be told), label is a short description."""

    def __init__(self, on_done):
        self.on_done = on_done
        self.poll = None
        self.session = None      # {pid: (name, is_query)}, start time, log sizes
        self.monitor = None
        self.recent = {}         # download path -> time reported (one reaction per file)
        self.pending = {}        # path -> GLib source checking a freshly written file

    def configure(self, packages, downloads):
        if packages and not self.poll:
            self.poll = GLib.timeout_add(1500, self.scan)
        elif not packages and self.poll:
            GLib.source_remove(self.poll)
            self.poll, self.session = None, None
        if downloads and not self.monitor:
            self.watch_downloads()
        elif not downloads and self.monitor:
            self.monitor.cancel()
            self.monitor = None

    # ── package managers ───────────────────────────────────────────────────
    @staticmethod
    def running():
        found = {}
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open(f"/proc/{d}/comm") as f:
                    name = f.read().strip()
                if name not in MANAGERS:
                    continue
                with open(f"/proc/{d}/stat") as f:
                    if f.read().rsplit(")", 1)[-1].split()[0] == "Z":
                        continue   # exited, just not reaped yet
                with open(f"/proc/{d}/cmdline", "rb") as f:
                    args = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
            except OSError:
                continue
            # scripts (emerge, dnf, pip) show up as `python3 /usr/bin/emerge ...`
            while args and (os.path.basename(args[0]) != name):
                args.pop(0)
            found[int(d)] = (name, is_query(name, args[1:]))
        return found

    @staticmethod
    def log_sizes():
        sizes = {}
        for path in LOGS:
            try:
                if os.access(path, os.R_OK):
                    sizes[path] = os.path.getsize(path)
            except OSError:
                pass
        return sizes

    def scan(self):
        now = self.running()
        if now and not self.session:
            self.session = {"procs": {}, "start": time.monotonic(), "logs": self.log_sizes()}
        if self.session:
            self.session["procs"].update(now)
            if not now:          # the last one exited
                session, self.session = self.session, None
                self.finished(session)
        return True

    def finished(self, session):
        procs = session["procs"]
        if all(q for _n, q in procs.values()):
            return               # only lookups
        # the label: the outermost tool you ran (an AUR helper over the pacman it calls)
        names = [n for n, q in procs.values() if not q]
        order = list(MANAGERS)
        name = min(names, key=lambda n: (n in ("pacman", "dpkg"), order.index(n)))
        logged, ok = False, True
        for path, size in session["logs"].items():
            good, bad = LOGS[path]
            try:
                with open(path, errors="replace") as f:
                    f.seek(size)
                    added = f.read(1 << 20)
            except OSError:
                continue
            if not added:
                continue
            if any(m in added for m in bad):
                logged, ok = True, False
            elif any(m in added for m in good):
                logged = True
        if not logged and time.monotonic() - session["start"] < MIN_SECONDS:
            return               # quick and left no trace: cancelled, or nothing to do
        self.on_done("package", ok, f"{MANAGERS[name]} {'done' if ok else 'failed'}")

    # ── downloads folder ───────────────────────────────────────────────────
    def watch_downloads(self):
        d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or str(Path.home() / "Downloads")
        if not os.path.isdir(d):
            return
        self.monitor = Gio.File.new_for_path(d).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", self.on_change)

    @staticmethod
    def temp(name):
        return name.startswith(".") or name.lower().endswith(TEMP_SUFFIXES)

    def on_change(self, _mon, f, other, event):
        E = Gio.FileMonitorEvent
        name = f.get_basename() or ""
        if event == E.RENAMED and other:
            new = other.get_basename() or ""
            if self.temp(name) and not self.temp(new):     # browser: file.part -> file
                self.done(other.get_path())
        elif event == E.DELETED and name.endswith(".aria2"):  # aria2 drops its control file when done
            self.done(f.get_path()[: -len(".aria2")])
        elif event in (E.CHANGES_DONE_HINT, E.MOVED_IN) and not self.temp(name):
            # wget/curl write the real name directly: wait a moment, make sure it's real and done
            path = f.get_path()
            if path in self.pending:
                GLib.source_remove(self.pending[path])
            self.pending[path] = GLib.timeout_add(1200, self.check_written, path)

    def check_written(self, path):
        self.pending.pop(path, None)
        try:
            if os.path.getsize(path) == 0:
                return False       # a browser's placeholder; the rename comes later
        except OSError:
            return False
        stem = os.path.basename(path)
        folder = os.path.dirname(path)
        if any(os.path.exists(os.path.join(folder, stem + s)) for s in TEMP_SUFFIXES):
            return False           # still downloading next to it
        self.done(path)
        return False

    def done(self, path):
        now = time.monotonic()
        self.recent = {p: t for p, t in self.recent.items() if now - t < 15}
        if path in self.recent or not os.path.exists(path):
            return
        self.recent[path] = now
        name = os.path.basename(path)
        if len(name) > 24:
            name = name[:15] + "…" + name[-7:]
        self.on_done("download", True, f"{name} downloaded")
