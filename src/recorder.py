"""Screen recording for the pet's "start recording" / "stop recording" voice commands, with
wl-screenrec. Recordings go to ~/Videos/Recordings, with what you hear (desktop audio).

It keeps its state in the same files as the bugzysdotfiles Waybar record button
($XDG_RUNTIME_DIR/waybar-record.*), so if you use that button it shows the timer for a recording
your pet started, and either one can stop the other's recording.
"""
import datetime
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "waybar-record"
PIDF, FILEF, STARTF, LOGF = (RUN.with_name(RUN.name + ext) for ext in (".pid", ".file", ".start", ".log"))
DIR = Path(os.environ.get("XDG_VIDEOS_DIR", Path.home() / "Videos")) / "Recordings"


class RecordError(Exception):
    pass


def available():
    return shutil.which("wl-screenrec") is not None


def _pid():
    try:
        pid = int(PIDF.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def recording():
    return _pid() is not None


def _poke():
    """Wake the Waybar button's status loop (if you use it) so it updates right away."""
    for f in RUN.parent.glob(RUN.name + ".fifo.*"):
        try:
            fd = os.open(f, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, b"\n")
            os.close(fd)
        except OSError:
            pass


def _notify(*args):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Screen recorder", "-i", "media-record", *args],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _focused_monitor():
    try:
        mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True,
                                         timeout=3).stdout)
        return next((m["name"] for m in mons if m.get("focused")), None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def start(audio=True):
    """Record the monitor you're on. Returns the file it's writing. Raises RecordError."""
    if not available():
        raise RecordError("wl-screenrec isn't installed")
    if recording():
        raise RecordError("already recording")
    args = ["wl-screenrec"]
    mon = _focused_monitor()
    if mon:
        args += ["-o", mon]
    if audio:
        try:
            sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            sink = ""
        if sink:
            args += ["--audio", "--audio-device", sink + ".monitor"]
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"recording-{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}.mp4"
    with open(LOGF, "w") as log:
        proc = subprocess.Popen(args + ["-f", str(out)], stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    PIDF.write_text(f"{proc.pid}\n")
    FILEF.write_text(f"{out}\n")
    STARTF.write_text(f"{int(time.time())}\n")
    time.sleep(0.6)
    if proc.poll() is not None:                       # it gave up straight away
        for f in (PIDF, STARTF):
            f.unlink(missing_ok=True)
        _poke()
        try:
            why = LOGF.read_text().strip().splitlines()[-1]
        except (OSError, IndexError):
            why = "it stopped straight away"
        raise RecordError(why)
    _poke()
    return out


def stop():
    """Stop and save. Returns the file, or None if nothing was recording."""
    pid = _pid()
    if pid is None:
        return None
    try:
        out = Path(FILEF.read_text().strip())
    except OSError:
        out = None
    os.kill(pid, signal.SIGINT)                       # lets it finish writing the file
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.1)
    for f in (PIDF, STARTF):
        f.unlink(missing_ok=True)
    _poke()
    if out:
        _notify("Recording saved", str(out).replace(str(Path.home()), "~", 1))
    return out
