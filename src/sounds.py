"""UI sounds for the settings window, synthesized on the spot (no audio files).

One GStreamer pipeline (appsrc -> pulsesink) stays open while the window is; a tiny mixer
fills it on demand, so sounds overlap instead of cutting each other off.
"""
import array
import atexit
import math
import random
import threading
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

RATE = 22050
CHUNK = 256          # samples per push (~12 ms)


# ── synthesis ───────────────────────────────────────────────────────────────
def render(fn, seconds):
    n = int(RATE * seconds)
    return [fn(i / RATE) for i in range(n)]


def marimba(f, length=0.09, decay=0.018, gain=0.5):
    """Wooden mallet: fundamental + a fast-dying 4x partial + a hint of strike noise."""
    rnd = random.Random(int(f))

    def s(t):
        body = math.sin(2 * math.pi * f * t) * math.exp(-t / decay)
        ping = 0.35 * math.sin(2 * math.pi * f * 3.98 * t) * math.exp(-t / (decay / 4))
        strike = (rnd.random() * 2 - 1) * 0.25 * math.exp(-t / 0.0012)
        return gain * (body + ping + strike)
    return render(s, length)


def pop(f0=900, f1=320, length=0.06, gain=0.6):
    """Soft bubble pop: a quick downward pitch sweep."""
    def s(t):
        k = t / length
        f = f0 + (f1 - f0) * (1 - (1 - k) ** 3)
        return gain * math.sin(2 * math.pi * f * t) * math.exp(-t / 0.014)
    return render(s, length)


def concat(*parts, gap=0.0):
    out = []
    for p in parts:
        out += p + [0.0] * int(RATE * gap)
    return out


def mix(*parts):
    n = max(len(p) for p in parts)
    return [sum(p[i] for p in parts if i < len(p)) for i in range(n)]


def note(semitones_from_a4):
    return 440 * 2 ** (semitones_from_a4 / 12)


def build_bank():
    # sliders: a pentatonic run over two octaves, low -> high as the value rises
    penta = [0, 2, 4, 7, 9]
    ticks = [marimba(note(3 + 12 * (i // 5) + penta[i % 5]), length=0.07, decay=0.012, gain=0.35)
             for i in range(11)]
    return {
        "ticks": ticks,
        "click": mix(pop(1100, 420, 0.05, 0.5), marimba(note(15), 0.05, 0.006, 0.12)),
        "on": concat(marimba(note(15), 0.05, 0.012, 0.4), marimba(note(22), 0.1, 0.02, 0.4), gap=0.0),
        "off": concat(marimba(note(22), 0.05, 0.012, 0.35), marimba(note(15), 0.1, 0.02, 0.35)),
        "select": mix(marimba(note(19), 0.12, 0.03, 0.3), marimba(note(26), 0.16, 0.04, 0.18)),
        "whoosh": mix(marimba(note(14), 0.2, 0.05, 0.25), marimba(note(21), 0.25, 0.06, 0.2),
                      marimba(note(26), 0.3, 0.07, 0.12)),
        "pop_up": pop(500, 1300, 0.07, 0.5),
        "pop_down": pop(1200, 300, 0.08, 0.5),
        "grab": pop(800, 600, 0.04, 0.35),
    }


# ── playback ────────────────────────────────────────────────────────────────
class Player:
    def __init__(self, enabled=lambda: True, volume=lambda: 0.7):
        self.enabled, self.volume = enabled, volume
        self.voices = []           # [samples, position, gain]
        self.lock = threading.Lock()
        self.last_tick = 0.0
        self.last_tick_idx = None
        self.pipeline = None
        try:
            Gst.init(None)
            self.bank = build_bank()
            self.pipeline = Gst.parse_launch(
                "appsrc name=src format=time is-live=false block=false max-bytes=2048 "
                f"caps=audio/x-raw,format=S16LE,rate={RATE},channels=1,layout=interleaved "
                "! audioconvert ! audioresample "
                "! pulsesink buffer-time=60000 latency-time=10000 client-name=larry")
            self.src = self.pipeline.get_by_name("src")
            self.src.connect("need-data", self.on_need_data)
            self.pts = 0
            self.pipeline.set_state(Gst.State.PLAYING)
            atexit.register(self.close)  # stop the audio thread before Python tears down
        except Exception:  # no audio stack: stay silent
            self.pipeline = None

    def on_need_data(self, src, length, chunk=CHUNK, rate=RATE):
        if self.pipeline is None:
            return
        out = [0.0] * chunk
        with self.lock:
            alive = []
            for v in self.voices:
                samples, pos, gain = v
                end = min(pos + chunk, len(samples))
                for i in range(end - pos):
                    out[i] += samples[pos + i] * gain
                v[1] = end
                if end < len(samples):
                    alive.append(v)
            self.voices = alive
        pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32000) for s in out)).tobytes()
        buf = Gst.Buffer.new_wrapped(pcm)
        buf.pts = self.pts
        buf.duration = Gst.util_uint64_scale(chunk, Gst.SECOND, rate)
        self.pts += buf.duration
        src.emit("push-buffer", buf)

    def play(self, name, gain=1.0):
        if not self.pipeline or not self.enabled():
            return
        samples = self.bank[name] if isinstance(name, str) else name
        with self.lock:
            if len(self.voices) < 8:
                self.voices.append([samples, 0, gain * self.volume()])

    def tick(self, frac):
        """Slider tick at a pitch for 0..1; repeats of the same note are spaced out."""
        ticks = self.bank["ticks"] if self.pipeline else None
        if not ticks:
            return
        idx = round(min(max(frac, 0), 1) * (len(ticks) - 1))
        now = time.monotonic()
        if now - self.last_tick < 0.035 or (idx == self.last_tick_idx and now - self.last_tick < 0.09):
            return
        self.last_tick, self.last_tick_idx = now, idx
        self.play(ticks[idx])

    def close(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
