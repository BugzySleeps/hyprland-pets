"""Voice commands, offline: say "Larry, come here" and he does.

Speech is recognised on your own computer by Vosk (alphacephei.com/vosk) with its small English
model (~40 MB), listening only for the phrases below, so it's light and nothing ever leaves your
machine. Vosk lives in its own little Python environment under ~/.local/share/larry/voice/ (set up
from the settings window), so your system Python isn't touched.

Two roles:
  - imported (by the pet and the settings window): setup(), ready(), COMMANDS, and Listener, which
    runs this file in that environment and hands back what it heard.
  - run as `voice.py --listen NAME...` inside that environment: records the default microphone with
    parec, recognises, and prints one JSON line per command heard.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "larry" / "voice"
VENV = ROOT / "venv"
MODEL = ROOT / "model"
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
LOG = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "larry" / "voice.log"
RATE = 16000
ARMED = 5.0      # seconds after hearing just his name that a command on its own counts

# what you can say (after his name), and what each means
COMMANDS = {
    "come": ["come here", "come", "come on", "come to me", "come over", "come over here", "over here",
             "here boy", "here girl", "here", "get over here", "to me", "follow me", "this way",
             "walk over here", "come closer", "come on over", "where are you"],
    "dance": ["dance", "dance for me", "do a dance", "show me your moves", "party", "lets dance",
              "lets party", "boogie", "groove", "bust a move", "shake it", "dance party", "get down"],
    "sit": ["sit", "sit down", "take a seat", "have a seat", "sit still", "stay", "stay there", "wait",
            "hold on", "stop", "freeze", "chill"],
    "sleep": ["sleep", "go to sleep", "go to bed", "bed time", "bedtime", "nap", "take a nap",
              "have a nap", "rest", "get some rest", "lie down", "good night", "night night", "sleepy time"],
    "wake": ["wake up", "get up", "rise and shine", "good morning", "morning", "up you get",
             "time to get up", "are you awake"],
    "jump": ["jump", "hop", "jump up", "jump around", "leap", "bounce", "jump jump", "hop hop", "up up"],
    "ride": ["go for a ride", "ride", "drive", "go for a drive", "take a ride", "go riding", "lets ride",
             "lets go for a ride", "road trip", "vroom", "get in the car", "fly"],
    "home": ["go home", "go away", "get in your box", "go to your box", "back in your box", "in your box",
             "go back", "go inside", "hide", "go hide", "bye", "goodbye", "see you", "see you later",
             "shoo", "leave"],
    "out": ["come out", "come out here", "get out", "out you come", "hello", "hi", "hey", "hey there",
            "where are you hiding", "peek a boo", "show yourself"],
    "moo": ["moo", "speak", "say something", "talk", "make a noise", "say moo", "what does the cow say",
            "sing", "talk to me", "say hello"],
    "good": ["good boy", "good girl", "good cow", "good job", "well done", "i love you", "love you",
             "you are cute", "so cute", "who is a good boy", "nice", "awesome", "thank you", "thanks",
             "good", "best cow", "i like you"],
}
COMMANDS["record"] = ["start recording", "record", "record my screen", "record the screen", "start a recording",
                      "hit record", "roll camera", "lights camera action", "action", "begin recording",
                      "capture my screen", "start a video", "record this"]
COMMANDS["unrecord"] = ["stop recording", "stop the recording", "cut", "thats a wrap", "end recording",
                        "end the recording", "stop filming", "finish recording", "save the recording",
                        "done recording", "stop the video", "save it"]
COMMANDS["time"] = ["what time is it", "whats the time", "what is the time", "tell me the time", "the time",
                    "time", "time check", "what time", "check the time"]
COMMANDS["screenshot"] = ["screenshot", "take a screenshot", "grab a screenshot", "screen shot", "take a screen shot",
                          "snap", "take a picture", "take a photo", "snap a picture"]
COMMANDS["screenshot_all"] = ["screenshot everything", "screenshot the whole screen", "screenshot the screen",
                              "full screenshot", "take a picture of the screen", "screenshot all of it"]
COMMANDS["pause"] = ["pause", "pause the music", "pause music", "stop the music", "stop music", "quiet", "shh",
                     "hush", "silence", "pause the song", "stop the song"]
COMMANDS["play"] = ["play", "play the music", "play music", "play some music", "resume", "resume the music",
                    "hit play", "keep playing", "music", "play the song"]
COMMANDS["next"] = ["next song", "next", "skip", "skip this", "skip song", "skip this song", "next track",
                    "skip it"]
COMMANDS["previous"] = ["previous song", "last song", "previous", "previous track", "play that again",
                        "go back a song", "back a song"]
COMMANDS["mean"] = [   # (not listed anywhere: be mean to him and he's sad)
    "bad boy", "bad girl", "bad cow", "stupid", "stupid cow", "you are stupid", "idiot", "you idiot",
    "dumb", "dumb cow", "you are dumb", "ugly", "ugly cow", "you are ugly", "i hate you", "you suck",
    "loser", "you are a loser", "shut up", "fuck off", "fuck you", "screw you", "shit", "you are shit",
    "piece of shit", "damn you", "bitch", "asshole", "you are an asshole", "jerk", "moron", "useless",
    "you are useless", "worst cow", "you are the worst", "annoying", "you are annoying", "get lost",
    "go die", "bastard", "dick", "you stink", "smelly cow", "fat cow", "lazy cow", "terrible", "awful",
    "hamburger", "beef", "i will eat you",
]
HIDDEN = {"mean"}
SAD = ["…", ":(", "hey…", "that's mean", "ouch", "why…", "sniff"]
SAY = {   # (what he says when he hears it)
    "come": "Coming!", "dance": "♪", "sit": "Okay", "sleep": "Zzz…", "wake": "I'm up!", "jump": "Hup!",
    "ride": "Vroom!", "home": "Bye!", "out": "Hi!", "moo": "Moo!", "good": "♥",
    "record": "● Recording", "unrecord": "Saved!", "pause": "⏸", "play": "▶", "next": "⏭", "previous": "⏮",
}


def python():
    return VENV / "bin" / "python"


def ready():
    """Set up and good to go?"""
    return python().exists() and (MODEL / "am").is_dir()


def mics():
    """Your microphones: [(source name, description)], monitors left out."""
    try:
        out = subprocess.run(["pactl", "list", "sources"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found, name = [], None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Name: "):
            name = line[6:]
        elif line.startswith("Description: ") and name and not name.endswith(".monitor"):
            found.append((name, line[13:]))
            name = None
    return found


def last_error():
    """The last thing the recogniser complained about (from its log), or ""."""
    try:
        lines = [ln.strip() for ln in LOG.read_text().splitlines() if ln.strip()]
    except OSError:
        return ""
    return lines[-1][-160:] if lines else ""


def wake_words(name):
    """His name(s): always "larry", plus your pet's name if it's one plain word."""
    words = ["larry"]
    n = re.sub(r"[^a-z ]", "", name.lower()).strip()
    if n and " " not in n and n not in words:
        words.append(n)
    return words


# ── setting up (from the settings window, on a worker thread) ──────────────
class SetupError(Exception):
    pass


def setup(progress):
    """Make the environment, install Vosk into it and download the model. progress(text, fraction)."""
    ROOT.mkdir(parents=True, exist_ok=True)
    if not python().exists():
        progress("Making a little Python environment…", 0.05)
        r = subprocess.run([sys.executable, "-m", "venv", str(VENV)], capture_output=True, text=True)
        if r.returncode:
            raise SetupError("couldn't make a Python environment: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    progress("Installing Vosk (the speech recogniser)…", 0.15)
    r = subprocess.run([str(python()), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "vosk"],
                       capture_output=True, text=True)
    if r.returncode:
        raise SetupError("couldn't install Vosk: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    if not (MODEL / "am").is_dir():
        zpath = ROOT / "model.zip"
        progress("Downloading the English model (about 40 MB)…", 0.3)
        try:
            req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "hyprland-pets"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(zpath, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0) or 41_000_000
                got = 0
                while chunk := resp.read(1 << 16):
                    f.write(chunk)
                    got += len(chunk)
                    progress(f"Downloading the English model… {got // 1_000_000} / {total // 1_000_000} MB",
                             0.3 + 0.6 * min(1.0, got / total))
        except OSError as e:
            raise SetupError(f"couldn't download the model ({e})") from e
        progress("Unpacking…", 0.92)
        tmp = ROOT / "model.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            with zipfile.ZipFile(zpath) as z:
                for m in z.infolist():                   # (only plain paths inside the folder)
                    p = Path(m.filename)
                    if p.is_absolute() or ".." in p.parts:
                        raise SetupError("the model download looks wrong")
                z.extractall(tmp)
        except zipfile.BadZipFile as e:
            raise SetupError("the model download was damaged; try again") from e
        inner = next((d for d in tmp.iterdir() if d.is_dir()), None)
        if not inner or not (inner / "am").is_dir():
            raise SetupError("the model download looks wrong")
        shutil.rmtree(MODEL, ignore_errors=True)
        inner.rename(MODEL)
        shutil.rmtree(tmp, ignore_errors=True)
        zpath.unlink(missing_ok=True)
    progress("Ready", 1.0)


def remove():
    shutil.rmtree(ROOT, ignore_errors=True)


# ── listening, from the pet's side ──────────────────────────────────────────
class Listener:
    """Runs the recogniser in its environment; on_command(cmd, heard) for each command heard."""

    def __init__(self, on_command, on_wake=None):
        self.on_command, self.on_wake = on_command, on_wake
        self.proc = None
        self.watch = None
        self.buf = b""
        self.names = None
        self.want = None          # (name, mic) while it should be listening: restarted if it stops
        self.retry = None
        self.fails = 0

    def start(self, name, mic=""):
        from gi.repository import GLib
        names = wake_words(name)
        self.want = (name, mic)
        if self.running and self.names == (names, mic):
            return True
        self.stop(keep_wanting=True)
        if not ready():
            return False
        self.names = (names, mic)
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            log = open(LOG, "w")
            args = [str(python()), str(HERE / "voice.py"), "--listen", *names]
            if mic:
                args += ["--mic", mic]
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL,
                                         start_new_session=True)
            log.close()
        except OSError as e:
            self.proc = None
            LOG.write_text(f"couldn't start the recogniser: {e}\n")
            return False
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.watch = GLib.io_add_watch(self.proc.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                                       GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_data)
        return True

    def on_data(self, fd, cond):
        try:
            self.buf += os.read(fd, 4096)
        except BlockingIOError:
            return True
        except OSError:
            cond |= 1 << 30
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("cmd") in COMMANDS:
                self.on_command(d["cmd"], d.get("heard", ""))
            elif d.get("wake") and self.on_wake:
                self.on_wake()
        from gi.repository import GLib
        if cond & (GLib.IO_HUP | GLib.IO_ERR) or cond & (1 << 30):
            self.watch = None
            self.stop(keep_wanting=True)
            self.restart_later()
            return False
        self.fails = 0
        return True

    def restart_later(self):
        """It stopped by itself (the mic went away, say): try again in a bit, backing off."""
        from gi.repository import GLib
        if not self.want or self.retry:
            return
        self.fails += 1
        if self.fails > 6:
            return
        self.retry = GLib.timeout_add_seconds(min(60, 3 * 2 ** self.fails), self._retry)

    def _retry(self):
        self.retry = None
        if self.want:
            self.start(*self.want)
        return False

    def stop(self, keep_wanting=False):
        from gi.repository import GLib
        if not keep_wanting:
            self.want = None
            self.fails = 0
            if self.retry:
                GLib.source_remove(self.retry)
                self.retry = None
        if self.watch:
            GLib.source_remove(self.watch)
            self.watch = None
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        self.names = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None


# ── listening, inside the environment ───────────────────────────────────────
def listen(names, mic=""):
    import vosk   # (only exists in the environment)
    vosk.SetLogLevel(-1)
    import time
    model = vosk.Model(str(MODEL))
    alone = sorted(set(sum(COMMANDS.values(), [])))
    phrases = sorted({f"{n} {p}" for n in names for p in alone}) + list(names) + alone
    lookup = {p: cmd for cmd, ps in COMMANDS.items() for p in ps}
    rec = vosk.KaldiRecognizer(model, RATE, json.dumps(phrases + ["[unk]"]))
    armed_until = 0.0     # just heard his name: a command on its own counts until then
    rec.SetWords(True)
    args = ["parec", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le", "--latency-msec=100",
            "--client-name=larry-voice"]
    if mic:
        args.append(f"--device={mic}")
    rec_proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    print(f"listening on {mic or 'the default microphone'} for: {', '.join(names)}", file=sys.stderr, flush=True)
    try:
        while chunk := rec_proc.stdout.read(3200):     # 0.1 s at a time
            if not rec.AcceptWaveform(chunk):
                continue
            res = json.loads(rec.Result())
            words = res.get("result") or []
            text = res.get("text", "")
            if not words or sum(w["conf"] for w in words) / len(words) < 0.75:
                continue                                 # nothing, or not sure enough: probably noise
            now = time.monotonic()
            if words[0]["word"] in names:
                rest = text.split(" ", 1)[1] if " " in text else ""
                if not rest:                             # just his name: he's all ears for a bit
                    armed_until = now + ARMED
                    print(json.dumps({"wake": True, "heard": text}), flush=True)
                    continue
                cmd = lookup.get(rest)                   # name and command in one go
            elif now < armed_until:
                cmd = lookup.get(text)                   # a command right after his name
            else:
                continue                                 # no name, and not waiting for a command: ignored
            if cmd:
                armed_until = 0.0
                print(json.dumps({"cmd": cmd, "heard": text}), flush=True)
        print(f"the microphone stopped (parec exited with {rec_proc.wait()})", file=sys.stderr, flush=True)
    finally:
        rec_proc.terminate()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--listen":
        rest = sys.argv[2:]
        mic = ""
        if "--mic" in rest:
            i = rest.index("--mic")
            mic = rest[i + 1] if i + 1 < len(rest) else ""
            rest = rest[:i] + rest[i + 2:]
        listen(rest, mic)
