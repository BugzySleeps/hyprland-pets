"""Is music playing, and where's the beat? So the pet can dance.

  - playing: any MPRIS player (Spotify, mpv, a browser tab, ...) says it's Playing, asked over D-Bus.
  - the beat: if cava is installed, it listens to what your speakers are playing and the bass hits
    nudge a steady beat clock into time with the song. Without cava the clock just runs at 120 BPM.
cava only runs while something's playing.
"""
import os
import shutil
import statistics
import subprocess
import tempfile
import time

from gi.repository import Gio, GLib

MPRIS = "org.mpris.MediaPlayer2."
DEFAULT_PERIOD = 0.5          # 120 BPM
MIN_PERIOD, MAX_PERIOD = 60 / 170, 60 / 75
CAVA_CONF = """[general]
bars = 16
framerate = 60
autosens = 1

[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 1000
channels = mono

[smoothing]
noise_reduction = 12
monstercat = 0
"""


def have_cava():
    return shutil.which("cava") is not None


class Music:
    def __init__(self):
        self.playing = False
        self.listen = False              # use cava for the beat
        self.enabled = False
        self.bus = None
        self.poll = None
        self.statuses = {}
        self.cava = None
        self.cava_watch = None
        self.conf = None
        self.buf = b""
        # the beat clock: beats elapsed (float), advanced at 1/period per second
        self.beats = 0.0
        self.period = DEFAULT_PERIOD
        self.clock_t = time.monotonic()
        self.energy = 0.0                # 0-1: how loud the bass is lately
        self.avg = 0.0
        self.prev = 0.0
        self.last_onset = 0.0
        self.onsets = []
        self.locked_until = 0.0          # recent onsets: the beat is following the music

    def configure(self, enabled, listen):
        self.enabled, self.listen = enabled, listen
        if enabled and not self.poll:
            try:
                self.bus = self.bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
            except GLib.Error:
                return
            self.check()
            self.poll = GLib.timeout_add(1500, self.check)
        elif not enabled and self.poll:
            GLib.source_remove(self.poll)
            self.poll = None
            self.playing = False
        self.update_cava()

    # ── MPRIS ───────────────────────────────────────────────────────────────
    def check(self):
        self.bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
                      None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 500, None, self.on_names)
        return True

    def on_names(self, bus, res):
        try:
            names = [n for n in bus.call_finish(res).unpack()[0] if n.startswith(MPRIS)]
        except GLib.Error:
            return
        self.statuses = {n: s for n, s in self.statuses.items() if n in names}
        for n in names:
            bus.call(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get",
                     GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "PlaybackStatus")),
                     GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 500, None, self.on_status, n)
        if not names:
            self.set_playing(False)

    def on_status(self, bus, res, name):
        try:
            self.statuses[name] = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            self.statuses.pop(name, None)
        self.set_playing(any(s == "Playing" for s in self.statuses.values()))

    def set_playing(self, playing):
        playing = playing and self.enabled
        if playing != self.playing:
            self.playing = playing
            self.update_cava()

    # ── cava ────────────────────────────────────────────────────────────────
    def update_cava(self):
        want = self.playing and self.listen and have_cava()
        if want and not self.cava:
            self.start_cava()
        elif not want and self.cava:
            self.stop_cava()

    def start_cava(self):
        try:
            fd, self.conf = tempfile.mkstemp(prefix="larry-cava-", suffix=".conf")
            with os.fdopen(fd, "w") as f:
                f.write(CAVA_CONF)
            self.cava = subprocess.Popen(["cava", "-p", self.conf], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            self.cava = None
            return
        os.set_blocking(self.cava.stdout.fileno(), False)
        self.buf = b""
        self.cava_watch = GLib.io_add_watch(self.cava.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                                            GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_cava)

    def stop_cava(self):
        if self.cava_watch:
            GLib.source_remove(self.cava_watch)
            self.cava_watch = None
        if self.cava:
            self.cava.terminate()
            try:
                self.cava.wait(1)
            except subprocess.TimeoutExpired:
                self.cava.kill()
            self.cava = None
        if self.conf:
            try:
                os.unlink(self.conf)
            except OSError:
                pass
            self.conf = None
        self.energy = 0.0

    def close(self):
        self.stop_cava()

    def on_cava(self, fd, cond):
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            self.cava_watch = None
            self.stop_cava()
            return False
        try:
            self.buf += os.read(fd, 65536)
        except BlockingIOError:
            return True
        except OSError:
            self.cava_watch = None
            self.stop_cava()
            return False
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines[-4:]:          # only the latest frames matter
            try:
                bars = [int(v) for v in line.split(b";") if v]
            except ValueError:
                continue
            if bars:
                self.frame(bars)
        return True

    def frame(self, bars):
        """One frame of cava: watch the bass for hits."""
        now = time.monotonic()
        e = sum(bars[:3]) / 3 / 1000
        self.energy += (e - self.energy) * 0.08
        self.avg += (e - self.avg) * 0.05
        rising = e - self.prev
        self.prev = e
        if e > self.avg * 1.2 + 0.06 and rising > 0.04 and now - self.last_onset > MIN_PERIOD * 0.8:
            self.onset(now)

    def onset(self, now):
        gap = now - self.last_onset
        self.last_onset = now
        if MIN_PERIOD * 0.9 < gap < MAX_PERIOD * 2.1:
            while gap > MAX_PERIOD:      # a hit every other beat: still counts
                gap /= 2
            self.onsets = (self.onsets + [gap])[-10:]
            if len(self.onsets) >= 4:
                target = min(MAX_PERIOD, max(MIN_PERIOD, statistics.median(self.onsets)))
                self.period += (target - self.period) * 0.3
        b = self.now_beats(now)
        off = b - round(b)               # pull the clock toward the hit
        self.beats -= off * 0.35
        self.locked_until = now + 3

    # ── the beat ────────────────────────────────────────────────────────────
    def now_beats(self, now=None):
        now = now or time.monotonic()
        self.beats += (now - self.clock_t) / self.period
        self.clock_t = now
        if now > self.locked_until and not self.cava:
            self.period += (DEFAULT_PERIOD - self.period) * 0.01
        return self.beats

    def strength(self):
        """How big to dance: bigger to loud bass (when cava's listening)."""
        if not self.cava:
            return 0.85
        return max(0.45, min(1.0, 0.45 + self.energy * 1.1))
