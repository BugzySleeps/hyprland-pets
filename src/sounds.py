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


# ── the pet's own sounds (thrown, caught...) ─────────────────────────────────
def formant_gain(f, formants):
    """How loud a harmonic at f comes out of a vocal tract with these (freq, bandwidth, level)."""
    return sum(level / (1 + ((f - fc) / bw) ** 2) for fc, bw, level in formants)


OO = ((320, 90, 1.0), (800, 120, 0.5), (2500, 300, 0.05))     # "oo" / the w
EE = ((300, 90, 0.7), (2500, 220, 1.0), (3300, 300, 0.45))     # "ee"
AH = ((750, 120, 1.0), (1200, 140, 0.6), (2600, 300, 0.15))    # "ah"/"o" for whoa
YI = ((280, 80, 0.8), (2300, 200, 0.9), (3000, 300, 0.4))      # a tighter "i"


MM = ((250, 60, 1.0), (1000, 200, 0.12), (2200, 300, 0.03))   # closed-mouth hum: "mm"


def lowpass(samples, cutoff, q=0.7):
    """Biquad low-pass (RBJ cookbook)."""
    w = 2 * math.pi * cutoff / RATE
    alpha = math.sin(w) / (2 * q)
    cw = math.cos(w)
    b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
    a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    out, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for x in samples:
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, x, y1, y
        out.append(y)
    return out


def hood(samples, cutoff=1050):
    """Through a parka hood (Kenny-style): treble soaked up, a little boxy boom left over."""
    muffled = lowpass(lowpass(samples, cutoff), cutoff * 1.3)
    boom = lowpass(samples, 260, q=1.4)
    return [0.85 * m + 0.35 * b for m, b in zip(muffled, boom)]


def lerp_pts(pts, k):
    """Pitch at k (0..1) along [(k, f), ...], eased between points."""
    for (k0, f0), (k1, f1) in zip(pts, pts[1:]):
        if k <= k1:
            u = (k - k0) / max(k1 - k0, 1e-6)
            return f0 + (f1 - f0) * (1 - (1 - u) ** 2)
    return pts[-1][1]


def voice(length, pitch, vowels=(OO, EE), morph=0.13, vib=7.5, depth=0.035, gain=0.55, seed=7, crack=None,
          rasp=0.0, growl=0.0):
    """One syllable of a cartoon voice: pitch follows `pitch` [(k, Hz)...], the vowel slides from
    vowels[0] to vowels[1] over `morph` seconds, with a wobble. crack=(k, factor) briefly jumps
    the pitch, like a voice cracking with excitement."""
    a, b = vowels
    rnd = random.Random(seed)
    out, phase = [], 0.0
    n = int(RATE * length)
    for i in range(n):
        t = i / RATE
        k = t / length
        f0 = lerp_pts(pitch, k)
        f0 *= 1 + depth * math.sin(2 * math.pi * vib * t) * min(1, t / 0.15)
        if crack and abs(k - crack[0]) < 0.04:
            f0 *= crack[1]
        phase += 2 * math.pi * f0 / RATE
        m = min(1, t / morph) if morph else 1
        formants = [(x[0] + (y[0] - x[0]) * m, x[1] + (y[1] - x[1]) * m, x[2] + (y[2] - x[2]) * m)
                    for x, y in zip(a, b)]
        v = 0.0
        h = 1
        while h * f0 < RATE / 2 - 500 and h <= 9:
            v += formant_gain(h * f0, formants) / h * math.sin(h * phase)
            h += 1
        v += (rnd.random() * 2 - 1) * 0.02                       # a little breath
        if growl:                                                # period-doubling: a low bovine rumble
            v *= 1 + growl * math.sin(phase / 2)
        if rasp:                                                 # a scratchy, strained edge
            v *= 1 + rasp * (rnd.random() * 2 - 1) * (0.5 + 0.5 * math.sin(phase * 0.5))
        env = min(1, t / 0.025) * min(1, (length - t) / min(0.18, length / 3))
        out.append(gain * 0.6 * v * env)
    return out


def weee(length=0.75, f_start=560, f_end=1010, gain=0.55):
    """The classic "weee!"."""
    return voice(length, [(0, f_start), (1, f_end)], gain=gain)


# a cow's mouth: nasal "mm", round "oo", open "oh"
MOO_M = ((220, 60, 1.0), (900, 200, 0.10), (2100, 300, 0.02))
MOO_OO = ((330, 100, 1.0), (700, 140, 0.55), (2300, 300, 0.05))
MOO_OH = ((520, 120, 1.0), (900, 150, 0.6), (2400, 300, 0.08))


def moo(length, pitch, vowels=(MOO_M, MOO_OO), morph=0.18, **kw):
    """Larry's thrown "mooo!": low, through the nose, a bit of a growl, warm (not too bright)."""
    kw.setdefault("growl", 0.35)
    kw.setdefault("rasp", 0.15)
    kw.setdefault("vib", 5.5)
    kw.setdefault("depth", 0.04)
    kw.setdefault("gain", 0.8)
    return lowpass(voice(length, pitch, vowels, morph, **kw), 2200)


# Larry's set: real moos, all different (same picking rules as WEEES)
MOOS = {
    "moo": (lambda: moo(0.9, [(0, 185), (0.35, 225), (1, 165)], seed=21), False),
    "moo-short": (lambda: moo(0.45, [(0, 200), (1, 175)], morph=0.12, depth=0.02, seed=22), False),
    "moo-low": (lambda: moo(1.3, [(0, 140), (0.3, 175), (1, 125)], vowels=(MOO_M, MOO_OH), morph=0.4, vib=4,
                            depth=0.05, growl=0.5, seed=23), True),
    "moo-calf": (lambda: moo(0.7, [(0, 255), (0.4, 300), (1, 235)], growl=0.2, seed=24), False),
    "moo-moo": (lambda: concat(moo(0.36, [(0, 195), (1, 180)], morph=0.1, seed=25),
                               moo(0.42, [(0, 205), (0.4, 220), (1, 170)], morph=0.1, seed=26), gap=0.07), False),
    "moo-wobble": (lambda: moo(1.15, [(0, 170), (0.3, 215), (1, 160)], vowels=(MOO_M, MOO_OH), morph=0.5,
                               vib=5, depth=0.09, seed=27), True),
    "moo-surprised": (lambda: moo(0.55, [(0, 195), (1, 275)], vowels=(MOO_M, MOO_OH), morph=0.1, growl=0.25,
                                  seed=28), False),
}


def kenny(length, pitch, vowels=(MM, EE), morph=0.16, **kw):
    """A muffled, hummy kid's "mmweee!" from inside a parka."""
    kw.setdefault("rasp", 0.35)
    kw.setdefault("gain", 0.8)
    return hood(voice(length, pitch, vowels, morph, **kw))


# every throw picks one of these (never the same twice running); "long" ones suit a big throw
WEEES = {
    "weee": (lambda: kenny(0.8, [(0, 330), (1, 600)]), False),
    "wee-short": (lambda: kenny(0.45, [(0, 420), (1, 700)], vib=9, depth=0.03, seed=2), False),
    "wheee-long": (lambda: kenny(1.1, [(0, 310), (0.5, 600), (1, 680)], vib=6, depth=0.06, seed=3), True),
    "wooo": (lambda: kenny(0.8, [(0, 260), (0.6, 360), (1, 400)], vowels=(MM, OO), vib=5.5, depth=0.06,
                           seed=11), False),
    "wee-hee": (lambda: concat(kenny(0.34, [(0, 370), (1, 580)], seed=5),
                               kenny(0.32, [(0, 540), (1, 760)], vowels=(MM, EE), morph=0.06, vib=9, seed=6),
                               gap=0.04), False),
    "yippee": (lambda: concat(kenny(0.16, [(0, 380), (1, 430)], vowels=(MM, YI), morph=0.08, depth=0, seed=8),
                              kenny(0.55, [(0, 540), (1, 740)], vowels=(MM, EE), morph=0.07, vib=8, seed=9),
                              gap=0.035), False),
    "whoa-ee": (lambda: kenny(1.0, [(0, 390), (0.3, 310), (1, 650)], vowels=(AH, EE), morph=0.45, vib=6.5,
                              depth=0.05, seed=12), True),
    "weee-squeak": (lambda: kenny(0.85, [(0, 450), (1, 780)], vib=8, depth=0.03, seed=13, crack=(0.7, 1.4),
                                  rasp=0.5), True),
}


CLIPS = {   # name -> synthesizer (bump the version suffix when one changes, so caches refresh)
    **{f"{name}-2": make for name, (make, _long) in WEEES.items()},   # -2: Kenny-style
    **{f"{name}-2": make for name, (make, _long) in MOOS.items()},     # -2: all real moos
    "catch-1": lambda: concat(marimba(note(19), 0.05, 0.012, 0.45), marimba(note(26), 0.14, 0.03, 0.45)),
    "best-1": lambda: concat(*(marimba(note(n), 0.07, 0.02, 0.4) for n in (14, 19, 23)),
                             marimba(note(26), 0.3, 0.07, 0.45)),
    "miss-1": lambda: pop(700, 220, 0.16, 0.45),
    "trick-1": lambda: concat(*(marimba(note(n), 0.05, 0.012, 0.45) for n in (19, 23)),
                              marimba(note(31), 0.18, 0.04, 0.5)),
}


def save_wav(path, samples):
    import wave
    peak = max(1e-6, max(abs(s) for s in samples))
    k = min(1.0, 0.95 / peak)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(array.array("h", (int(s * k * 32000) for s in samples)).tobytes())


class Clips:
    """Short sounds played on demand (a playbin per sound, released when it ends): nothing runs
    in between, unlike the settings window's always-open mixer."""

    def __init__(self, cache, enabled=lambda: True, volume=lambda: 0.7):
        self.cache, self.enabled, self.volume = cache, enabled, volume
        self.players = {}
        try:
            Gst.init(None)
            self.ok = Gst.ElementFactory.find("playbin") is not None
        except Exception:
            self.ok = False

    def path(self, name):
        full = next(k for k in CLIPS if k.rsplit("-", 1)[0] == name)
        p = self.cache / f"sound-{full}.wav"
        if not p.exists():
            self.cache.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(f".{threading.get_ident()}.tmp")
            save_wav(tmp, CLIPS[full]())
            tmp.replace(p)            # appears whole, never half-written
        return p

    def prepare(self):
        """Render every clip ahead of time (run it in a thread: first renders take ~0.5 s each)."""
        for full in sorted(CLIPS, key=lambda n: not n.startswith("moo")):   # Larry's first
            try:
                self.path(full.rsplit("-", 1)[0])
            except Exception:
                pass

    def weee(self, big=False, cow=False):
        """A random weee (never the one from last time); a big throw prefers the long ones.
        cow: Larry's moo versions."""
        bank = MOOS if cow else WEEES
        names = [n for n, (_m, long) in bank.items() if long] if big else list(bank)
        names = [n for n in names if n != getattr(self, "last_weee", None)] or names
        self.last_weee = random.choice(names)
        self.play(self.last_weee)

    def play(self, name):
        if not self.ok or not self.enabled():
            return
        try:
            pb = self.players.get(name)
            if pb is None:
                pb = Gst.ElementFactory.make("playbin", None)
                pb.set_property("uri", self.path(name).as_uri())
                bus = pb.get_bus()
                bus.add_signal_watch()
                bus.connect("message::eos", lambda *_: pb.set_state(Gst.State.NULL))
                bus.connect("message::error", lambda *_: pb.set_state(Gst.State.NULL))
                self.players[name] = pb
            pb.set_state(Gst.State.NULL)
            pb.set_property("volume", max(0.0, min(1.0, self.volume())))
            pb.set_state(Gst.State.PLAYING)
        except Exception:
            self.ok = False
