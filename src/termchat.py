"""The pet "typing" in your terminal while you're away.

It writes to the terminal's screen the way `write`/`wall` do (straight to the terminal device):
the text only appears on screen; it's never typed into your shell's input, so nothing runs. And it
only writes when the shell is sitting at its prompt: never over a program (an editor, htop, ...).
"""
import os
import random
import time

MESSAGES = [
    "u there?", "hellooo?", "*taps screen*", "i'm bored", "is this thing on?", "knock knock",
    "did you leave me here", "ok i'm pressing random keys now: asdfghjkl", "brb", "...",
    "your terminal is very comfy", "can we go outside", "i could fix that bug in 5 min",
    "sudo make me a sandwich", "have you tried turning it off and on again", "ping", "pong?",
    "i'm not saying i'm bored. but i'm bored", "when are you coming back", "hi :)",
    "i read your bash history. no comment", "rm -rf boredom", "this is fine", "zzz.. oh. hi",
    "it's quiet. too quiet", "i counted all the pixels. there are a lot", "type faster. oh wait. that's me",
]
COW_MESSAGES = [
    "moo?", "mooooo", "u there? moo", "brb eating grass", "is it grass o'clock yet",
    "i ate your keyboard shortcuts", "moo moo (that means hi)", "udderly bored",
    "gentoo? more like gen-moo", "compiling my feelings. ETA: 3 hours", "emerge --ask cow",
    "this terminal needs more hay", "i'm herd you were busy", "holy cow it's quiet",
]


def message(is_cow):
    pool = MESSAGES + COW_MESSAGES * 2 if is_cow else MESSAGES
    return random.choice(pool)


def _stat(pid):
    """(state, ppid, pgrp, session, tty_nr, tpgid) of a process, or None."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            rest = f.read().rsplit(")", 1)[1].split()
        return rest[0], int(rest[1]), int(rest[2]), int(rest[3]), int(rest[4]), int(rest[5])
    except (OSError, IndexError, ValueError):
        return None


def _children():
    kids = {}
    for d in os.listdir("/proc"):
        if d.isdigit() and (st := _stat(d)):
            kids.setdefault(st[1], []).append(int(d))
    return kids


def find_shell(term_pid):
    """The terminal's most recently used shell: (tty path, at its prompt?, seconds since last
    input), or None. Looks two levels down (some terminals run a helper between them and the shell)."""
    kids = _children()
    found = []
    todo = [(term_pid, 0)]
    while todo:
        pid, depth = todo.pop()
        for child in kids.get(pid, []):
            st = _stat(child)
            if not st:
                continue
            _state, _ppid, pgrp, session, tty_nr, tpgid = st
            if tty_nr and session == child:          # a session leader with a terminal: the shell
                try:
                    tty = os.readlink(f"/proc/{child}/fd/0")
                except OSError:
                    continue
                if tty.startswith("/dev/pts/"):
                    found.append((tty, tpgid == pgrp))
            elif depth < 2:
                todo.append((child, depth + 1))
    if not found:
        return None
    best, best_t = None, -1
    for tty, idle in found:
        try:
            t = os.stat(tty).st_atime                 # the last time you typed into it
        except OSError:
            continue
        if t > best_t:
            best, best_t = (tty, idle), t
    return (best[0], best[1], time.time() - best_t) if best else None


class Typist:
    """Types one message into a terminal a character at a time."""

    def __init__(self, tty, name, text):
        self.tty, self.text, self.i = tty, text, 0
        self.prefix = f"\r\n\x1b[1;35m{name}:\x1b[0m "
        self.next_t = time.monotonic() + 0.6        # sits down and gets ready first
        self.started = False

    def _write(self, s):
        try:
            fd = os.open(self.tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                os.write(fd, s.encode())
            finally:
                os.close(fd)
            return True
        except OSError:
            return False

    def step(self, now):
        """Type whatever's due. Returns False once the message is done (or can't be written)."""
        if now < self.next_t:
            return True
        if not self.started:
            self.started = True
            if not self._write(self.prefix):
                return False
        if self.i >= len(self.text):
            self._write("\r\n")
            return False
        ch = self.text[self.i]
        self.i += 1
        if not self._write(ch):
            return False
        delay = random.uniform(0.06, 0.17)
        if ch in ".,?!":
            delay += 0.25
        elif ch == " " and random.random() < 0.15:
            delay += 0.4                               # a little think
        self.next_t = now + delay
        return True

    def stop(self):
        """Interrupted (you came back): end the line tidily."""
        if self.started and self.i < len(self.text):
            self._write("\r\n")
