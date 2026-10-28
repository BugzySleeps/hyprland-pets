#!/usr/bin/env python3
"""hyprland-pets: a little pet that lives in a pull-down box on the edge of your screen.

Hover the tab to pull the box out (click it to keep it open, right-click for settings); the
pet wanders around inside. Drag it out and it drops onto the screen, lands on window tops
(riding them when they move) or the bottom edge, and walks around on top of everything. Drag
it back into the open box to put it away. Hidden while a window is fullscreen. Colours follow
the `rice` theme switcher when it's installed, a neutral dark theme otherwise. Everything else
is set in the settings window (`--settings`) and saved to ~/.config/larry/config.toml.

One fullscreen transparent overlay layer surface; its input region only covers the tab/box
and the pet, so every other click goes straight through to the windows underneath.
"""
import copy
import hashlib
import json
import math
import os
import random
import socket
import sys
import threading
import time
import tomllib
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

import fonts  # noqa: E402
fonts.register()    # before any window: the settings window's font
import config  # noqa: E402
import accessories  # noqa: E402
import anim  # noqa: E402
import scene  # noqa: E402
import sounds  # noqa: E402
import music  # noqa: E402
import termchat  # noqa: E402
import themes  # noqa: E402
import vehicles
import waybar  # noqa: E402
import weather  # noqa: E402
import updates  # noqa: E402
import sprites  # noqa: E402
import watch  # noqa: E402

RICE = Path.home() / ".config/rice"

BOX_W, BOX_H = 250, 92          # the pull-down box (grows to fit a big pet)
TAB_W, TAB_H = 46, 12           # the handle hanging under it
FPS = 30

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "larry" / "game.json"
HYPR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "hypr" / os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")


# ── helpers ─────────────────────────────────────────────────────────────────
def hypr(cmd):
    """Query Hyprland over its socket (no hyprctl subprocess, so it's cheap to poll)."""
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(str(HYPR / ".socket.sock"))
            s.sendall(f"j/{cmd}".encode())
            data = b""
            while chunk := s.recv(65536):
                data += chunk
        return json.loads(data)
    except (OSError, json.JSONDecodeError):
        return None


def rgb(hexstr, fallback=(1, 1, 1)):
    try:
        h = hexstr.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (AttributeError, ValueError):
        return fallback


def theme_colors(key=themes.DEFAULT, widget=None):
    """The colours to draw with: a built-in theme, or (key "desktop") the rice theme switcher's
    current theme if you use it, else your GTK theme's colours."""
    if key != "desktop":
        return themes.palette(key)
    try:
        name = (RICE / "current").read_text().strip()
        with open(RICE / "themes" / name / "theme.toml", "rb") as f:
            c = tomllib.load(f).get("colors", {})
    except (OSError, tomllib.TOMLDecodeError):
        c = {}
    if not c and widget is not None:
        c = gtk_colors(widget)
    if not c:
        return themes.palette(themes.DEFAULT)
    return {
        "bg0": rgb(c.get("bg0"), (0.07, 0.07, 0.09)),
        "bg1": rgb(c.get("bg1"), (0.1, 0.1, 0.12)),
        "accent": rgb(c.get("accent"), (0.8, 0.8, 0.85)),
        "accent2": rgb(c.get("accent2"), (0.5, 0.7, 0.4)),
        "fg": rgb(c.get("fg"), (0.9, 0.9, 0.9)),
    }



def gtk_colors(widget):
    """The GTK theme's named colours as hex strings (empty if the theme doesn't name them)."""
    ctx = widget.get_style_context()
    out = {}
    for ours, names in (("bg0", ("theme_bg_color", "window_bg_color")),
                        ("bg1", ("theme_base_color", "view_bg_color", "theme_bg_color")),
                        ("fg", ("theme_fg_color", "window_fg_color")),
                        ("accent", ("insensitive_fg_color", "theme_unfocused_fg_color", "theme_fg_color")),
                        ("accent2", ("theme_selected_bg_color", "accent_bg_color", "accent_color"))):
        for n in names:
            ok, col = ctx.lookup_color(n)
            if ok:
                out[ours] = "#%02x%02x%02x" % (round(col.red * 255), round(col.green * 255), round(col.blue * 255))
                break
    return out if len(out) == 5 else {}


# ── the widget ──────────────────────────────────────────────────────────────
class Larry(Gtk.Window):
    def __init__(self):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "larry")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        self.set_app_paintable(True)
        self.set_visual(self.get_screen().get_rgba_visual())
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self.on_draw)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("leave-notify-event", self.on_leave)
        self.connect("size-allocate", lambda *_: self.update_input())
        self.connect("destroy", Gtk.main_quit)

        self.cfg = config.load()
        self.wear = {}            # what the weather has him wearing (weather.wear): baked into his sprites
        self.weather = None       # the latest weather (weather.fetch), or None
        self.weather_try = None   # the settings window's "Try it" (weather.SAMPLES key), or None
        self.weather_timer = None
        self.sprites = sprites.load(self.dress(self.cfg))
        self.fall_sprites = self.load_fall(self.dress(self.cfg))
        self.held_sprites = self.load_held(self.dress(self.cfg))
        self.typing_sprites = self.load_typing(self.dress(self.cfg))
        self.riding = self.load_riding(self.dress(self.cfg))
        self.sheet_lock = threading.Lock()   # rebuilding those four after a settings change (queue_sheets)
        self.sheet_token, self.sheet_job, self.sheet_busy = 0, None, False
        self.poses = self.load_poses(self.dress(self.cfg))
        self.lw, self.lh = self.sprites[0].get_width(), self.sprites[0].get_height()
        self.anim = anim.Compiled(self.cfg["animation"])
        self.walking = False
        self.settings = None
        self.box_cache = scene.BoxCache()
        self.colors = theme_colors(self.cfg["theme"], self)
        self.theme_mtime = self._theme_mtime()
        self.waybar_mtime = None          # (check_waybar: None so the first check looks)
        self.bar_timer, self.bar_text, self.bar_cache, self.bar_look = None, None, None, None   # the Waybar icon
        self.config_mtime = self._config_mtime()

        self.open = 0.0           # box pull-down progress 0..1
        self.pinned = bool(os.environ.get("LARRY_OPEN"))  # clicked open (LARRY_OPEN=1: start open)
        self.hover_until = 0.0    # keep open until this time after the pointer leaves
        self.pointer = None

        self.mode = "box"         # box | drag | free
        self.bx = (self.box_w - self.lw) / 2   # x inside the box
        self.x = self.y = 0.0     # top-left on screen (drag/free)
        self.vx = self.vy = 0.0
        self.dir = 1
        self.phase = 0.0          # position in the step cycle (cycles; the curves loop every 1.0)
        self.pause = 0.0          # seconds left standing still
        self.platform = None      # (address, left, right, top) he's standing on
        self.platforms = []
        self.walls = []           # window rects he bounces off while flying: (addr, x0, y0, x1, y1)
        self.clients = {}         # address -> Hyprland client, from the last refresh
        self.mon = None           # the monitor we're drawn on
        self.mon_t = 0.0
        self.act = None           # idle behaviour: None | "sit" | "sleep" | "type" | "dance"
        self.act_until = 0.0
        self.watching = False     # looking at the cursor
        self.cursor = None        # pointer position (ours, not just over our window), from Hyprland
        self.cursor_t = 0.0
        self.cursor_moved = time.monotonic()
        self.poked = time.monotonic()   # last time he was picked up or put down
        self.reaction = None      # {"mood": "happy"|"sad", "start", "until", "text"}
        self.typist = None        # termchat.Typist while he types in his terminal
        self.asleep_since = 0.0
        self.last_chat = 0.0
        self.chats = 0            # messages typed this nap
        self.ride = None          # riding a vehicle: {"kind", "start", "until", "end", "dist", "alt", ...}
        self.next_ride = time.monotonic() + self.ride_gap()
        self.watcher = watch.Watcher(self.on_finished)
        self.weather_checked = 0.0
        self.schedule_peek()
        GLib.timeout_add_seconds(45, self.check_updates)      # (then twice a day: see check_updates)
        if not self.has_box:          # no box to live in: start out on the desktop
            GLib.idle_add(lambda: self.mode == "box" and self.pop() and False)
        GLib.idle_add(lambda: self.start_weather() and False)   # (Open-Meteo: only if it's turned on)
        self.clips = sounds.Clips(sprites.CACHE, lambda: self.cfg["pet_sounds"], lambda: self.cfg["volume"] / 100)
        threading.Thread(target=self.clips.prepare, daemon=True).start()   # so the first throw doesn't stutter
        self.streak = 0           # catch game: catches in a row
        self.best = self.load_best()
        self.toss = None          # {"from": y thrown at, "peak": highest y} while a throw is in the air
        self.popups = []          # floating "+1" / "New best!" texts: {"text", "x", "y", "start", "big"}
        self.petting = False      # the middle button is held down (on him or his box): moving over him pets him
        self.pet_prev = None      # last pointer spot while petting
        self.pet_last = 0.0       # last stroke
        self.pet_love = 0.0       # how much petting he's had just now (fades): enough and he flops over
        self.pet_lean = 0.0       # leans into the strokes (-1 left .. 1 right)
        self.pet_dist = 0.0       # stroke length since the last heart
        self.flopped = False      # blissed out on his side
        self.hearts = []          # floating hearts from petting: {"x", "y" (screen), "start", "drift"}
        self.poofs = []           # puffs of smoke (popping out / back in): {"x", "y", "size", "start"}
        self.pop_start = None     # when he last popped out (he bounces in from small)
        self.peeking = None       # box closed: when he poked his head out from beside the tab (see peek_out)
        self.watcher.configure(self.cfg["reactions"]["packages"], self.cfg["reactions"]["downloads"])
        self.music = music.Music()
        self.music.configure(self.cfg["dance"]["enabled"], self.cfg["dance"]["beat"])
        self.dance_until = 0.0     # a dance lasts a while, then he takes a breather
        self.next_dance = 0.0
        self.dance_moves = []      # the moves for this dance, one per 8 beats
        self.notes = []            # floating music notes: {"x" (across him), "start", "drift", "kind"}
        self.last_note_beat = 0
        self.room = None          # address of the terminal he lives in (dragged into it), or None
        self.room_rect = None     # its inside: (left, top, right, bottom) on screen
        self.room_shown = True    # False while that terminal is on a workspace you're not looking at
        self.room_covers = []     # windows stacked above his terminal: he's hidden behind them
        self.poller = None
        self.follower = None      # fast poll of just his terminal (see follow_room)
        self.follow_interval = 0
        self.follow_fast_until = 0.0
        self.drag_off = (0, 0)
        self.drag_hist = []

        self.last = time.monotonic()
        self.dirty = []
        self.ticking = None
        self.input_key = None

        self.listen_events()
        GLib.timeout_add_seconds(2, self.check_theme)
        GLib.timeout_add_seconds(20, self.check_season)
        self.show_all()
        self.check_fullscreen()
        self.wake()

    # ── geometry ────────────────────────────────────────────────────────────
    def box_size_for(self, box):
        """(w, h) the box would have with these box settings (the ground's height changes it)."""
        return max(BOX_W, self.lw * 4), max(BOX_H, self.lh + scene.ground_height(box) + 24)

    @property
    def box_w(self):
        return max(BOX_W, self.lw * 4)

    @property
    def box_h(self):
        return max(BOX_H, self.lh + self.ground + 24)

    @property
    def ground(self):
        return scene.ground_height(self.cfg["box"])

    @property
    def W(self):
        return self.get_allocated_width() or 1600

    @property
    def H(self):
        return self.get_allocated_height() or 900

    def eased_open(self):
        """Open progress through the animation's "open" curve (can overshoot past 1)."""
        return self.anim.open_curve(self.open) if 0 < self.open < 1 else self.open

    @property
    def edge(self):
        return self.cfg["tab"]["edge"]

    def box_geom(self):
        """(x, y, w, h, stretch): where the unstretched box sits, sliding out from its edge.
        Past fully open (an overshooting curve) it stays put and stretches away from the edge."""
        e, edge = self.eased_open(), self.edge
        w, h, W, H = self.box_w, self.box_h, self.W, self.H
        f = self.cfg["tab"]["position"] / 100
        stretch, e = max(e, 1), min(e, 1)
        if edge in ("top", "bottom"):
            x = round(min(max(W * f - w / 2, 0), W - w))
            y = round((e - 1) * h) if edge == "top" else round(H - e * h)
        else:
            y = round(min(max(H * f - h / 2, 0), H - h))
            x = round((e - 1) * w) if edge == "left" else round(W - e * w)
        return x, y, w, h, stretch

    def box_rect(self):
        """What the box covers on screen right now (including any stretch)."""
        x, y, w, h, s = self.box_geom()
        if s == 1:
            return x, y, w, h
        return {"top": (x, 0, w, round(h * s)), "bottom": (x, round(self.H - h * s), w, round(h * s)),
                "left": (0, y, round(w * s), h), "right": (round(self.W - w * s), y, round(w * s), h)}[self.edge]

    def tab_rect(self):
        bx, by, bw, bh = self.box_rect()
        return {"top": (bx + (bw - TAB_W) // 2, by + bh, TAB_W, TAB_H),
                "bottom": (bx + (bw - TAB_W) // 2, by - TAB_H, TAB_W, TAB_H),
                "left": (bx + bw, by + (bh - TAB_W) // 2, TAB_H, TAB_W),
                "right": (bx - TAB_H, by + (bh - TAB_W) // 2, TAB_H, TAB_W)}[self.edge]

    def to_edge(self, r, pad=0):
        """Rect r grown by pad and stretched to touch the box's screen edge (so there's no gap
        between the edge and a tab/box for the pointer to fall through)."""
        x, y, w, h = r[0] - pad, r[1] - pad, r[2] + 2 * pad, r[3] + 2 * pad
        edge = self.edge
        if edge == "top":
            h, y = y + h, 0
        elif edge == "bottom":
            h = self.H - y
        elif edge == "left":
            w, x = x + w, 0
        else:
            w = self.W - x
        return x, y, max(w, 0), max(h, 0)

    def near_box(self, p, near=70):
        """Is p close to where the open box and its tab sit? (Carrying the pet there opens the box.)"""
        w, h, W, H = self.box_w, self.box_h, self.W, self.H
        f = self.cfg["tab"]["position"] / 100
        if self.edge in ("top", "bottom"):
            x = min(max(W * f - w / 2, 0), W - w)
            zone = (x, 0 if self.edge == "top" else H - h - TAB_H, w, h + TAB_H)
        else:
            y = min(max(H * f - h / 2, 0), H - h)
            zone = (0 if self.edge == "left" else W - w - TAB_H, y, w + TAB_H, h)
        return self.inside(p, zone, near)

    def visible_box(self):
        """The on-screen part of the box (it starts off screen and slides in)."""
        x, y, w, h = self.box_rect()
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, self.W), min(y + h, self.H)
        return x0, y0, max(x1 - x0, 0), max(y1 - y0, 0)

    def larry_pos(self):
        """Top-left of Larry on screen."""
        if self.mode == "box":
            bx, by, _, _, _ = self.box_geom()
            return bx + self.bx, by + self.box_h - self.ground - self.lh + (4 if self.ground else 1)
        return self.x, self.y

    def larry_rect(self):
        x, y = self.larry_pos()
        return x, y, self.lw, self.lh

    def hit_rect(self):
        """Where a click grabs him. In the air: his whole arms-up pose, plus some slack (catching a
        falling pet is hard enough)."""
        if self.ride and self.mode != "drag":
            return self.ride_rect()
        x, y, w, h = self.larry_rect()
        if self.mode == "free" and not self.platform and not self.room:
            top = h
            if self.fall_sprites:
                top = max(h, sprites.logical_size(self.fall_sprites[0])[1])
            slack = max(14, h * 0.35)
            return x - slack, y + h - top - slack, w + 2 * slack, top + 2 * slack
        return x, y, w, h

    @staticmethod
    def inside(p, r, pad=0):
        return p and r[0] - pad <= p[0] <= r[0] + r[2] + pad and r[1] - pad <= p[1] <= r[1] + r[3] + pad

    @property
    def has_box(self):
        """The pull-down box and its tab are shown (off: just the pet, summoned from Waybar)."""
        return self.cfg.get("box_tab", True)

    def hovering(self):
        if not self.has_box:
            return False
        if self.inside(self.pointer, self.to_edge(self.tab_rect(), 2)):
            return True
        return self.open > 0.05 and self.inside(self.pointer, self.to_edge(self.visible_box()))

    # ── input region: only the tab/box and Larry catch the mouse ───────────
    def update_input(self):
        if self.mode == "drag":
            rects = [(0, 0, self.W, self.H)]  # keep getting motion wherever he's dragged
        else:
            rects = [self.to_edge(self.tab_rect(), 5)] if self.has_box else []
            if self.open > 0.05 and self.has_box:
                rects.append(self.visible_box())
            if self.mode == "free" and (not self.room or self.room_shown):
                rects.append(tuple(round(v) for v in self.hit_rect()))
        key = tuple(tuple(int(v) for v in r) for r in rects)
        if key == self.input_key:
            return
        self.input_key = key
        region = cairo.Region()
        for r in key:
            region.union(cairo.RectangleInt(*r))
        self.input_shape_combine_region(region)

    # ── events ──────────────────────────────────────────────────────────────
    def on_motion(self, _w, ev):
        self.pointer = (ev.x, ev.y)
        if self.mode == "drag":
            self.damage_larry()
            self.x, self.y = ev.x - self.drag_off[0], ev.y - self.drag_off[1]
            self.drag_hist = [h for h in self.drag_hist if ev.time - h[0] < 80] + [(ev.time, ev.x, ev.y)]
            self.damage_larry()
        elif self.petting:
            self.stroke(self.pointer)
        self.wake()

    def on_leave(self, _w, ev):
        if self.mode != "drag":
            self.pointer = None
            self.wake()

    def on_press(self, _w, ev):
        p = (ev.x, ev.y)
        if ev.button == 3:
            self.open_settings()
            return
        if ev.button == 2:
            if self.cfg["behavior"]["petting"] and self.mode != "drag":
                self.petting, self.pet_prev = True, p
                self.stroke(p)
            return
        if ev.button != 1:
            return
        lx, ly = self.larry_pos()
        self.poked = time.monotonic()
        on_larry = self.inside(p, self.hit_rect()) and (self.mode == "free" or self.open > 0.6)
        if on_larry:
            self.stop_ride()
            if self.mode == "free" and not self.platform:
                self.try_catch()
            self.x, self.y = lx, ly
            self.drag_off = (ev.x - lx, ev.y - ly)
            self.drag_hist = [(ev.time, ev.x, ev.y)]
            self.mode, self.platform = "drag", None
            self.leave_room()
        elif self.has_box and self.inside(p, self.tab_rect(), 4):
            self.pinned = not self.pinned
        self.update_input()
        self.wake()

    def on_release(self, _w, ev):
        if ev.button == 2:
            self.petting, self.pet_prev = False, None
            return
        if ev.button != 1 or self.mode != "drag":
            return
        self.poked = time.monotonic()
        self.pointer = (ev.x, ev.y)
        bx, by, _, _, _ = self.box_geom()
        # how fast he was let go (from the last few motion samples): a fling is always a throw
        (t0, x0, y0), (t1, x1, y1) = self.drag_hist[0], self.drag_hist[-1]
        dt = max((t1 - t0) / 1000, 1e-3)
        fling = t1 > t0 and math.hypot(x1 - x0, y1 - y0) / dt > 400
        if self.open > 0.5 and self.inside(self.pointer, self.visible_box()):
            self.damage_larry()
            self.end_streak()
            self.mode = "box"
            self.bx = min(max(self.x - bx, 6), self.box_w - self.lw - 6)
        elif not fling and (term := self.terminal_at(self.pointer)):
            self.end_streak()
            self.mode, self.platform = "free", None
            self.room, self.room_rect = term, None
            self.vx = self.vy = 0          # set down gently, then he drops to the bottom
            self.update_room()
            self.restart_poller()
        else:
            # throw
            cap = 1400 * max(self.anim.throw, 0.01)
            k = self.anim.throw
            self.vx = max(-cap, min(cap, k * (x1 - x0) / dt)) if t1 > t0 else 0
            self.vy = max(-cap, min(cap, k * (y1 - y0) / dt)) if t1 > t0 else 0
            self.mode = "free"
            self.refresh_platforms()
            speed = math.hypot(self.vx, self.vy)
            if speed > 450:
                self.clips.weee(big=speed > 1100, cow=sprites.is_larry(self.cfg))   # Larry moos
            # catch game: any real throw is a try (bounces off the screen's sides and top are bonus
            # points); a gentle drop isn't, and ends a streak once he lands
            self.toss = ({"from": self.y, "peak": self.y, "hit": set()}
                         if self.cfg["game"] and (self.vy < -350 or speed > 450) else None)
        self.update_input()
        self.wake()

    # ── hyprland: fullscreen + window tops ──────────────────────────────────
    def listen_events(self):
        try:
            self.ev = socket.socket(socket.AF_UNIX)
            self.ev.connect(str(HYPR / ".socket2.sock"))
            self.ev.setblocking(False)
            self.ev_buf = b""
            GLib.io_add_watch(self.ev.fileno(), GLib.IO_IN | GLib.IO_HUP, self.on_event)
        except OSError:
            pass

    def on_event(self, _fd, cond):
        try:
            data = self.ev.recv(65536)
        except BlockingIOError:
            return True
        if not data or cond & GLib.IO_HUP:
            Gtk.main_quit()  # Hyprland is gone
            return False
        self.ev_buf += data
        *lines, self.ev_buf = self.ev_buf.split(b"\n")
        names = {l.split(b">>")[0] for l in lines}
        if names & {b"fullscreen", b"workspace", b"workspacev2", b"focusedmon", b"closewindow",
                    b"openwindow", b"movewindow", b"movewindowv2", b"activespecial"}:
            self.check_fullscreen()
            if self.mode == "free":
                self.refresh_platforms()
                self.wake()
        return True

    def check_fullscreen(self):
        ws = hypr("activeworkspace") or {}
        full = bool(ws.get("hasfullscreen"))
        if full and self.get_visible():
            self.hide()
        elif not full and not self.get_visible():
            self.show_all()
            self.input_key = None
            self.update_input()
            self.wake()

    def refresh_platforms(self):
        mons = hypr("monitors") or []
        mon = next((m for m in mons if m.get("focused")), mons[0] if mons else None)
        if not mon:
            return
        self.mon = mon
        ws = mon["activeWorkspace"]["id"]
        plats, walls = [], []
        clients = hypr("clients") or []
        self.clients = {c["address"]: c for c in clients}
        if self.room:
            self.update_room()
        for c in clients:
            if c["workspace"]["id"] != ws or not c.get("mapped", True) or c.get("hidden"):
                continue
            x, y = c["at"][0] - mon["x"], c["at"][1] - mon["y"]
            w, h = c["size"]
            if x + w <= 0 or x >= self.W or y + h <= 0 or y >= self.H:
                continue  # off screen (infinite desktop)
            walls.append((c["address"], x, y, x + w, y + h))   # he bounces off the sides and bottoms
            if y > 0:                                          # and lands on tops (not ones at the very top)
                plats.append((c["address"], max(x, 0), min(x + w, self.W), y))
        self.platforms, self.walls = plats, walls

    def poll_platforms(self):
        if self.mode != "free":
            self.poller = None
            return False
        self.refresh_platforms()
        return True

    def restart_poller(self):
        if self.poller:
            GLib.source_remove(self.poller)
            self.poller = None
        self.wake()

    FOLLOW_FAST, FOLLOW_IDLE = 16, 40   # ms between looks at his terminal: while it moves / while it's still

    def follow_room(self):
        """Keep up with his terminal while you drag it around. Asks only about that one window
        (the active window, if it's his, which it is while you drag it), then redraws at once
        instead of waiting for the next animation frame."""
        if self.mode != "free" or not self.room:
            self.follower = None
            return False
        old = self.room_rect
        aw = hypr("activewindow")
        if aw and aw.get("address") == self.room and self.room in self.clients:
            self.clients[self.room] = aw              # same place in the stacking order
        else:
            clients = hypr("clients")
            if clients is not None:
                self.clients = {c["address"]: c for c in clients}
        self.update_room()
        if self.room_rect != old:
            self.follow_fast_until = time.monotonic() + 0.6
        self.flush_damage()
        want = self.FOLLOW_FAST if time.monotonic() < self.follow_fast_until else self.FOLLOW_IDLE
        if want != self.follow_interval:              # change pace
            self.follow_interval = want
            self.follower = GLib.timeout_add(want, self.follow_room)
            return False
        return True

    def start_follower(self):
        if self.room and self.mode == "free" and not self.follower:
            self.follow_interval = self.FOLLOW_IDLE
            self.follower = GLib.timeout_add(self.FOLLOW_IDLE, self.follow_room)

    def flush_damage(self):
        for r in self.dirty:
            self.queue_draw_area(*r)
        self.dirty.clear()

    # ── terminals: he can live inside one ──────────────────────────────────
    def is_terminal(self, c):
        t = self.cfg["terminals"]
        names = {n.lower() for n in t["classes"]}
        return t["enabled"] and (c.get("class", "").lower() in names or c.get("initialClass", "").lower() in names)

    def visible_here(self, c):
        return (self.mon and c["workspace"]["id"] == self.mon["activeWorkspace"]["id"]
                and c.get("mapped", True) and not c.get("hidden"))

    def terminal_at(self, p):
        """The terminal under the pointer when he's let go (topmost window there), if it is one."""
        if not self.cfg["terminals"]["enabled"] or not p:
            return None
        self.refresh_platforms()
        if not self.mon:
            return None
        under = []
        for c in self.clients.values():
            if not self.visible_here(c):
                continue
            x, y = c["at"][0] - self.mon["x"], c["at"][1] - self.mon["y"]
            w, h = c["size"]
            if x <= p[0] <= x + w and y + 6 <= p[1] <= y + h:   # the body, not the very top edge
                under.append(c)
        if not under:
            return None
        top = min(under, key=lambda c: (not c.get("floating"), c.get("focusHistoryID", 99)))
        return top["address"] if self.is_terminal(top) else None

    def update_room(self):
        """Follow his terminal: move with it, hide while it's out of sight, fall out if it closes."""
        c = self.clients.get(self.room)
        if c is None or not self.is_terminal(c):
            self.leave_room()
            self.platform = None       # airborne: he drops onto whatever is below
            return
        shown = bool(self.visible_here(c))
        if shown != self.room_shown:
            self.damage_larry()
            self.room_shown = shown
            self.input_key = None
        if not shown:
            return
        x, y = c["at"][0] - self.mon["x"], c["at"][1] - self.mon["y"]
        w, h = c["size"]
        new = (x + 2, y + 2, x + w - 2, y + h - 2)
        old = self.room_rect
        if old and old != new:          # the window moved: take him along
            self.damage_larry()
            self.x += new[0] - old[0]
            self.y += new[1] - old[1]
            self.damage_larry()
        self.room_rect = new
        # what's on top of his terminal: floating windows over a tiled one, otherwise whatever
        # comes later in Hyprland's client list (it's kept in stacking order, bottom to top)
        covers = []
        order = list(self.clients)
        mine = order.index(self.room)
        for i, o in enumerate(self.clients.values()):
            if o["address"] == self.room or not self.visible_here(o):
                continue
            fo, fc = bool(o.get("floating")), bool(c.get("floating"))
            above = (fo and not fc) or (fo == fc and i > mine)
            if above:
                covers.append((o["at"][0] - self.mon["x"], o["at"][1] - self.mon["y"], *o["size"]))
        if covers != self.room_covers:
            self.room_covers = covers
            self.damage_larry()

    def leave_room(self):
        if self.room:
            self.room, self.room_rect, self.room_shown = None, None, True
            self.input_key = None
            if self.mode == "free":
                self.restart_poller()

    # ── settings ────────────────────────────────────────────────────────────
    @staticmethod
    def load_fall(cfg):
        try:
            return sprites.load_fall(cfg)
        except Exception as e:  # unreadable picture: just keep the normal pose in the air
            print(f"larry: can't use the falling picture: {e}", file=sys.stderr)
            return None

    @staticmethod
    def load_held(cfg):
        try:
            return sprites.load_held(cfg)
        except Exception as e:   # no waddle: he just holds the falling pose
            print(f"larry: can't load the held animation: {e}", file=sys.stderr)
            return None

    @staticmethod
    def load_typing(cfg):
        try:
            return sprites.load_typing(cfg)
        except Exception as e:
            print(f"larry: can't load the typing animation: {e}", file=sys.stderr)
            return None

    @staticmethod
    def load_riding(cfg):
        try:
            return sprites.load_riding(cfg)
        except Exception as e:   # he stands on the vehicles instead
            print(f"larry: can't load the riding pose: {e}", file=sys.stderr)
            return None

    @staticmethod
    def load_poses(cfg):
        try:
            return sprites.load_poses(cfg)
        except Exception as e:  # no poses: he just stands for every behaviour
            print(f"larry: can't make the idle poses: {e}", file=sys.stderr)
            return {}

    def open_settings(self):
        if self.settings:
            self.settings.present()
            return
        import settings
        self.settings = settings.Settings(self)

    def queue_sheets(self, cfg):
        """Rebuild the falling, held, typing and riding sprites on a worker thread (the first time
        for new colours or a new size that's about a second of image work); the old ones stay in
        use until the new ones are ready. Only the latest settings matter: older jobs are dropped."""
        with self.sheet_lock:
            self.sheet_token += 1
            self.sheet_job = (self.sheet_token, copy.deepcopy(cfg))
            if not self.sheet_busy:
                self.sheet_busy = True
                threading.Thread(target=self._sheet_worker, daemon=True).start()

    def _sheet_worker(self):
        while True:
            with self.sheet_lock:
                job, self.sheet_job = self.sheet_job, None
                if job is None:
                    self.sheet_busy = False
                    return
            token, cfg = job
            res = (self.load_fall(cfg), self.load_held(cfg), self.load_typing(cfg), self.load_riding(cfg))
            GLib.idle_add(self._sheets_ready, token, res)

    def _sheets_ready(self, token, res):
        if token == self.sheet_token:
            self.damage_larry()
            self.fall_sprites, self.held_sprites, self.typing_sprites, self.riding = res
            self.damage_larry()
            self.wake()
        return False

    def set_config(self, cfg):
        """Swap in new settings live (called by the settings window)."""
        self.watcher.configure(cfg["reactions"]["packages"], cfg["reactions"]["downloads"])
        self.music.configure(cfg["dance"]["enabled"], cfg["dance"]["beat"])
        theme_changed = cfg["theme"] != self.cfg["theme"]
        if cfg["ride"] != self.cfg["ride"]:
            if not cfg["ride"]["enabled"]:
                self.end_ride()
            self.next_ride = time.monotonic() + cfg["ride"]["every"] * 60 * random.uniform(0.6, 1.4)
        self.anim = anim.Compiled(cfg["animation"])
        weather_changed = cfg["weather"] != self.cfg["weather"]
        box_changed = cfg["box_tab"] != self.cfg["box_tab"]
        sprite_keys = ("image", "size", "faces_left", "remove_bg", "outline", "outline_color", "outline_width", "coat",
                       "accessories")
        if any(cfg[k] != self.cfg[k] for k in sprite_keys + ("fall_image",)):
            self.queue_sheets(self.dress(cfg))   # the big drawn poses: in the background, so nothing freezes
        if any(cfg[k] != self.cfg[k] for k in sprite_keys):
            self.poses = self.load_poses(self.dress(cfg))
        if all(cfg[k] == self.cfg[k] for k in sprite_keys):
            new = self.sprites
        else:
            try:
                new = sprites.load(self.dress(cfg))
            except Exception as e:  # unreadable image: keep the current pet
                print(f"larry: can't use {cfg['image']}: {e}", file=sys.stderr)
                cfg = {**cfg, **{k: self.cfg[k] for k in sprite_keys}}
                new = self.sprites
        feet = self.larry_pos()[1] + self.lh
        self.cfg, self.sprites = cfg, new
        self.lw, self.lh = new[0].get_width(), new[0].get_height()
        self.bx = min(max(self.bx, 6), self.box_w - self.lw - 6)
        if self.mode != "box":
            self.y = feet - self.lh   # keep his feet where they were
        self.queue_draw()
        self.input_key = None
        self.update_input()
        self.wake()
        if theme_changed:
            self.recolor()
        if weather_changed:
            self.start_weather()
        if box_changed:
            self.pinned, self.hover_until = False, 0.0
            self.damage_box()
            self.input_key = None
            self.update_input()
            self.queue_draw()
            if not cfg["box_tab"] and self.mode == "box":   # it's gone: out he comes
                self.pop()
        if self.settings and self.settings.cfg != cfg:
            self.settings.sync(cfg)

    # ── theme ───────────────────────────────────────────────────────────────
    def _theme_mtime(self):
        try:
            return (RICE / "current").stat().st_mtime
        except OSError:
            return 0

    def theme_preview(self, key):
        """A theme's colours (for the settings window's theme tiles)."""
        return theme_colors(key, self)

    def recolor(self):
        self.colors = theme_colors(self.cfg["theme"], self)
        self.queue_draw()
        if self.settings:
            self.settings.restyle()

    def status(self):
        """What he's up to, for the Waybar module."""
        now = time.monotonic()
        if self.being_petted(now):
            doing = "pet"
        elif self.mode == "drag":
            doing = "held"
        elif self.mode == "free" and not self.platform:
            doing = "fly"
        elif self.ride:
            doing = "ride"
        elif self.reaction:
            doing = self.reaction["mood"]
        elif self.act in ("sleep", "sit", "dance", "type"):
            doing = self.act
        elif self.watching:
            doing = "watch"
        elif self.mode == "box":
            doing = "box" if self.has_box else "away"
        else:
            doing = "walk"
        where = ""
        if self.mode == "free" and self.room:
            where = "in your terminal"
        elif self.mode == "free" and self.platform:
            where = "on your desktop" if self.platform[0] == "floor" else "on a window"
        return {"name": self.cfg["name"], "doing": doing, "where": where,
                "vehicle": self.ride["kind"] if self.ride else None, "streak": self.streak, "best": self.best}

    # ── the Waybar icon: a little square with his face, showing how he feels ───
    BAR_PX = 72          # the icon's size (Waybar shrinks it to fit the bar; this keeps it sharp)
    BAR_MOODS = {        # status -> (face, badge)
        "pet": ("happy", "heart"), "happy": ("happy", "heart"), "dance": ("happy", "note"),
        "sleep": ("sleep", "z"), "held": ("wide", "!"), "fly": ("wide", "!"), "sad": ("sad", "drop"),
        "type": ("plain", "dots"), "ride": ("happy", None),
    }

    def update_bar_icon(self):
        """Once a second while the Waybar module is on: redraw the icon if his mood changed, and
        tell the module (waybar.NOW: the picture's path, then the tooltip)."""
        if not self.cfg.get("waybar"):
            self.bar_timer = None
            return False
        try:
            st = self.status()
            face, badge = self.BAR_MOODS.get(st["doing"], ("plain", None))
            if self.bar_look is None or self.bar_look[0] is not self.sprites[0]:   # his look changed
                self.bar_look = (self.sprites[0], sprites.sprite_key(self.dress(self.cfg)))
            look = self.bar_look[1]
            sig = f"{face}|{badge}|{look}|{tuple(self.colors['bg1'])}|{tuple(self.colors['accent2'])}"
            path = waybar.ICONS / f"icon-{hashlib.sha1(sig.encode()).hexdigest()[:12]}.png"
            if not path.exists():
                waybar.ICONS.mkdir(parents=True, exist_ok=True)
                self.render_bar_icon(face, badge).write_to_png(str(path))
            text = f"{path}\n{waybar.tooltip(st)}"
            if text != self.bar_text:
                tmp = waybar.NOW.with_suffix(".tmp")
                tmp.write_text(text)
                tmp.replace(waybar.NOW)
                self.bar_text = text
        except Exception as e:   # never let the bar take the pet down
            print(f"larry: waybar icon: {e}", file=sys.stderr)
        return True

    def bar_sprites(self):
        """A sharper copy of his sprites for the icon (rebuilt when the pet changes)."""
        if self.bar_cache is None or self.bar_cache[0] is not self.sprites[0]:
            k = max(1.0, self.BAR_PX / (self.lh * 0.8))
            dressed = self.dress(self.cfg)
            poses = sprites.load_poses(dressed, k) if sprites.is_larry(self.cfg) else {}
            self.bar_cache = (self.sprites[0], sprites.load(dressed, k)[0], poses)
        return self.bar_cache[1], self.bar_cache[2]

    def render_bar_icon(self, face, badge):
        S = self.BAR_PX
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, S, S)
        cr = cairo.Context(surf)
        c = self.colors
        r = S * 0.24
        cr.new_sub_path()
        cr.arc(S - r - 1, r + 1, r, -math.pi / 2, 0)
        cr.arc(S - r - 1, S - r - 1, r, 0, math.pi / 2)
        cr.arc(r + 1, S - r - 1, r, math.pi / 2, math.pi)
        cr.arc(r + 1, r + 1, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgb(*c["bg1"])
        cr.fill_preserve()
        cr.save()
        cr.clip_preserve()
        stand, poses = self.bar_sprites()
        sprite, eyes = stand, None
        if face == "sleep" and "sleep" in poses:
            sprite = poses["sleep"][0]
        elif face in ("happy", "sad", "wide") and "eyeless" in poses:
            sprite, eyes = poses["eyeless"][0], poses["eyes"]
        w, h = sprites.logical_size(sprite)
        if poses:   # Larry: frame his head (where his eyes are), not the whole cow
            ex = sum(e[0] for e in poses["eyes"]) / 2
            ey = sum(e[1] for e in poses["eyes"]) / 2
            sw, sh = sprites.logical_size(stand)
            ey += h - sh                           # (lying down, his head is lower)
            ph = self.cfg["size"] - 2 * sprites.PAD   # Larry himself, not his hat as well
            side = ph * 0.82                       # his face (ears to muzzle) fills the square
            k = S / side
            ox, oy = S / 2 - (ex + ph * 0.06) * k, S * 0.5 - (ey + ph * 0.13) * k
        else:        # anyone else: the whole picture, fitted in
            k = S * 0.82 / max(w, h)
            ox, oy = (S - w * k) / 2, S - 4 - h * k
        cr.translate(ox, oy)
        cr.scale(k, k)
        cr.set_source_surface(sprite, 0, 0)
        cr.paint()
        if eyes:
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            for ex_, ey_, rx, ry in eyes:
                rr = max(rx, 0.9) * 1.25
                cr.new_path()
                if face == "happy":                   # ^ ^
                    cr.set_line_width(max(0.9, rr * 0.55))
                    cr.arc(ex_, ey_ + rr * 0.5, rr, math.pi * 1.15, math.pi * 1.85)
                    cr.stroke()
                elif face == "sad":                   # eyes cast down
                    cr.set_line_width(max(0.9, rr * 0.55))
                    cr.arc(ex_, ey_ - rr * 0.6, rr, math.pi * 0.2, math.pi * 0.8)
                    cr.stroke()
                else:                                 # wide open: white ring, small pupil
                    cr.arc(ex_, ey_, rr * 1.15, 0, 2 * math.pi)
                    cr.set_source_rgb(1, 1, 1)
                    cr.fill_preserve()
                    cr.set_source_rgb(0, 0, 0)
                    cr.set_line_width(max(0.7, rr * 0.3))
                    cr.stroke()
                    cr.arc(ex_, ey_, rr * 0.45, 0, 2 * math.pi)
                    cr.fill()
        cr.restore()
        cr.set_source_rgba(*c["accent2"], 0.55)
        cr.set_line_width(2)
        cr.stroke()
        if badge:
            self.draw_badge(cr, S * 0.79, S * 0.21, S * 0.17, badge)
        return surf

    def draw_badge(self, cr, x, y, r, badge):
        """The little emote in the icon's corner."""
        cr.new_path()
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.set_source_rgb(1, 1, 1)
        cr.fill_preserve()
        cr.set_source_rgba(0.06, 0.06, 0.07, 0.85)
        cr.set_line_width(r * 0.16)
        cr.stroke()
        if badge == "heart":
            self.heart(cr, x, y + r * 0.08, r * 0.42, (0.95, 0.33, 0.45, 1))
        elif badge == "note":
            cr.save()
            cr.translate(x, y)
            cr.scale(r * 1.25, r * 1.25)
            self.note_path(cr, 0)
            cr.set_source_rgb(0.06, 0.06, 0.07)
            cr.fill()
            cr.restore()
        elif badge == "drop":
            cr.move_to(x, y - r * 0.6)
            cr.curve_to(x + r * 0.55, y, x + r * 0.45, y + r * 0.55, x, y + r * 0.55)
            cr.curve_to(x - r * 0.45, y + r * 0.55, x - r * 0.55, y, x, y - r * 0.6)
            cr.set_source_rgb(0.35, 0.65, 0.98)
            cr.fill()
        elif badge == "dots":
            for i in (-1, 0, 1):
                cr.arc(x + i * r * 0.42, y, r * 0.13, 0, 2 * math.pi)
                cr.set_source_rgb(0.06, 0.06, 0.07)
                cr.fill()
        else:   # "z", "!": a letter
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(r * 1.35)
            e = cr.text_extents(badge)
            cr.move_to(x - e.x_bearing - e.width / 2, y - e.y_bearing - e.height / 2)
            cr.set_source_rgb(0.06, 0.06, 0.07)
            cr.show_text(badge)

    def check_waybar(self):
        """With the Waybar module on: put it back if your Waybar config was rewritten without it
        (a rice theme switch regenerates it, for one), and keep its icon up to date."""
        if not self.cfg.get("waybar"):
            return
        if not self.bar_timer:
            self.update_bar_icon()
            self.bar_timer = GLib.timeout_add(1000, self.update_bar_icon)
        m = waybar.config_mtime()
        if m != self.waybar_mtime:
            self.waybar_mtime = m
            if m and not waybar.installed():
                waybar.install()
                self.waybar_mtime = waybar.config_mtime()

    def check_theme(self):
        """Every 2 s: pick up a rice theme switch, or a hand edit of the config file."""
        self.check_waybar()
        m = self._theme_mtime()
        if m != self.theme_mtime:
            self.theme_mtime = m
            if self.cfg["theme"] == "desktop":   # the rice theme switcher changed theme
                self.recolor()
        m = self._config_mtime()
        if m != self.config_mtime:
            self.config_mtime = m
            cfg = config.load()
            if cfg != self.cfg:
                self.set_config(cfg)
        return True

    @staticmethod
    def _config_mtime():
        try:
            return config.FILE.stat().st_mtime
        except OSError:
            return 0

    # ── animation loop (only runs while something is moving or visible) ────
    def wake(self):
        if not self.ticking:
            self.last = time.monotonic()
            self.ticking = GLib.timeout_add(1000 // FPS, self.tick)
        if self.mode == "free" and not self.poller:
            self.poller = GLib.timeout_add(300, self.poll_platforms)
        self.start_follower()

    def damage(self, x, y, w, h, pad=8):
        self.dirty.append((int(x - pad), int(y - pad), int(w + 2 * pad), int(h + 2 * pad)))

    def damage_box(self):
        self.damage(*self.to_edge(self.box_rect()), pad=4)
        self.damage(*self.to_edge(self.tab_rect()), pad=4)

    def peek(self, seconds=1.5):
        """Pop the box open for a moment (the settings window does this while you move the tab)."""
        self.input_key = None
        self.queue_draw()
        self.hover_until = time.monotonic() + seconds
        self.wake()

    def damage_larry(self):
        pad = 12
        if self.fall_sprites:   # room for the (taller, wobbling) falling pose
            fw, fh = sprites.logical_size(self.fall_sprites[0])
            pad += max(0, math.hypot(fw, fh) - min(self.lw, self.lh) / 2)
        if self.act == "sleep":   # the z's float up above him
            pad += self.lh
        if self.act == "dance" or self.notes:   # hops, and the notes floating up
            pad += self.lh * 1.3
        if self.act == "type" and self.typing_sprites:   # sitting up typing: taller
            pad += sprites.logical_size(self.typing_sprites[0][0])[1]
        if self.reaction:         # hops, hearts and the speech bubble
            pad += self.lh * 1.4 + (len(self.reaction["text"] or "") * 4 if self.reaction["text"] else 0)
        self.damage(*self.larry_rect(), pad=pad)
        if self.ride:             # the vehicle, its exhaust and the puff it appears in
            self.damage(*self.ride_rect(), pad=12 + self.lh * 0.8 + (pad if self.reaction else 0))

    def tick(self):
        now = time.monotonic()
        dt = min(now - self.last, 0.1)
        self.last = now

        # box open/close
        # while you carry the pet, the box only opens when you bring it close (so it can be put away)
        if self.hovering() or (self.mode == "drag" and self.near_box(self.pointer)):
            self.hover_until = now + 0.45
        want = 1.0 if self.has_box and (self.pinned or now < self.hover_until) else 0.0
        if self.open != want:
            self.damage_box()
            if self.mode == "box":
                self.damage_larry()
            step = dt / self.anim.open_time
            self.open = min(want, self.open + step) if want > self.open else max(want, self.open - step)
            self.damage_box()

        if self.reaction and now > self.reaction["until"]:
            self.damage_larry()
            self.reaction = None
        if self.ride and self.grounded():
            self.update_ride(dt, now)
        if self.grounded():
            self.behave(now)
        elif self.mode != "box":     # up in the air: wide awake
            self.stop_ride()
            if self.typist:
                self.typist.stop()
                self.typist = None
            self.act, self.watching = None, False

        if self.mode == "box" and self.open > 0:
            self.damage_larry()
            self.walk_box(dt)
            self.damage_larry()
        elif self.mode == "free":
            self.damage_larry()
            self.step_free(dt)
            self.damage_larry()
        elif self.mode == "drag" and (self.fall_sprites or "dangle0" in self.poses):
            self.damage_larry()   # he flails / paddles while you hold him

        if self.peeking is not None:
            self.damage(*self.peek_rect())
        if self.open > 0 and self.weather_effect():   # rain / snow keeps falling in the open box
            self.damage_box()
        if self.poofs:
            for p_ in self.poofs:
                self.damage(*self.poof_rect(p_))
            self.poofs = [p_ for p_ in self.poofs if now - p_["start"] < self.POOF_TIME + 0.05]
        if self.pop_start is not None:
            self.damage_larry()
        if self.hearts or self.pet_love or self.flopped:
            self.update_petting(dt, now)
            if self.being_petted(now) or self.flopped:
                self.damage_larry()
        if self.popups:
            for p_ in self.popups:
                self.damage(*self.popup_rect(p_))
            self.popups = [p_ for p_ in self.popups
                           if now - p_["start"] < self.POPUP_TIME * (1.6 if p_["big"] else 1) + 0.1]

        self.flush_damage()
        self.update_input()

        busy = (self.open != want or self.open > 0 or self.mode in ("free", "drag") or self.popups or self.hearts
                or self.pet_love or self.poofs or self.pop_start is not None or self.peeking is not None)
        if not busy:
            self.ticking = None
            return False
        return True

    # ── weather ─────────────────────────────────────────────────────────────
    def dress(self, cfg):
        """cfg with the weather's outfit added to his accessories (an umbrella hat stands in for
        any hat he's wearing). Never saved: it comes and goes with the weather."""
        if not self.wear:
            return cfg
        acc = dict(cfg["accessories"])
        if "umbrella_hat" in self.wear:      # (your own hat pictures count too: see accessories.is_hat)
            anchor = accessories.LARRY_ANCHOR if sprites.is_larry(cfg) else sprites.head_anchor(cfg)
            acc = {k: v for k, v in acc.items() if not accessories.is_hat(k, v, anchor)}
        for acc_id in self.wear:
            acc[acc_id] = accessories.default_place(acc_id, sprites.head_anchor(cfg)) \
                if not sprites.is_larry(cfg) else accessories.default_place(acc_id)
        return {**cfg, "accessories": acc}

    def weather_now(self):
        """The weather that counts: the settings' "Try it", else the real thing (if it's on)."""
        if self.weather_try:
            return weather.SAMPLES[self.weather_try]
        return self.weather if self.cfg["weather"]["enabled"] else None

    def apply_weather(self):
        """Dress for the weather now (rebuilding his sprites if the outfit changed)."""
        w = self.weather_now()
        wear = weather.wear(w) if w else {}
        if wear != self.wear:
            self.wear = wear
            dressed = self.dress(self.cfg)
            self.damage_larry()
            self.sprites = sprites.load(dressed)
            self.lw, self.lh = self.sprites[0].get_width(), self.sprites[0].get_height()
            self.poses = self.load_poses(dressed)
            self.queue_sheets(dressed)
            self.queue_draw()
            self.wake()
            if self.settings:
                self.settings.refresh()          # his size (and so the box's) may have changed
        if self.settings:
            self.settings.show_weather()

    def check_weather(self, force=False):
        """Every half hour (and when the place changes): ask Open-Meteo, on a worker thread."""
        wc = self.cfg["weather"]
        if not wc["enabled"] or not wc["place"]:
            self.weather = None
            self.apply_weather()
            return True
        lat, lon = wc["lat"], wc["lon"]

        def work():
            try:
                w = weather.fetch(lat, lon)
            except weather.WeatherError as e:
                print(f"larry: weather: {e}", file=sys.stderr)
                w = None
            GLib.idle_add(done, w)

        def done(w):
            if w is not None or self.weather is None:
                self.weather = w
            self.weather_checked = time.monotonic()
            self.apply_weather()
            return False
        threading.Thread(target=work, daemon=True).start()
        return True

    def start_weather(self):
        if self.weather_timer:
            GLib.source_remove(self.weather_timer)
        self.weather_timer = GLib.timeout_add_seconds(weather.EVERY, self.check_weather)
        self.check_weather()

    def weather_effect(self):
        w = self.weather_now()
        return weather.effect(w) if w and (self.cfg["weather"]["effects"] or self.weather_try) else None

    def draw_weather(self, cr, bx, by, bw, bh, t):
        """Rain streaks or drifting snowflakes in the box (and the odd lightning flash)."""
        fx = self.weather_effect()
        if not fx:
            return
        cr.save()
        if fx in ("rain", "storm"):
            n = int(bw / 9)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_width(1.3)
            for i in range(n):
                sp = 260 + (i * 37) % 90                      # px a second
                x = bx + (i * 97.3 % bw + t * sp * 0.18) % bw
                y = by + (i * 53.7 % bh + t * sp) % (bh + 20) - 10
                cr.move_to(x, y)
                cr.line_to(x - 2.2, y + 9)
                cr.set_source_rgba(0.72, 0.84, 1.0, 0.55 + 0.25 * (i % 3) / 2)
                cr.stroke()
            if fx == "storm":                                 # lightning now and then
                ph = t % 7.3
                if ph < 0.09 or 0.18 < ph < 0.24:
                    cr.rectangle(bx, by, bw, bh)
                    cr.set_source_rgba(1, 1, 1, 0.35)
                    cr.fill()
        else:
            n = int(bw / 11)
            for i in range(n):
                sp = 22 + (i * 13) % 18
                y = by + (i * 41.9 % bh + t * sp) % (bh + 10) - 5
                x = bx + (i * 83.1 % bw + math.sin(t * 1.3 + i) * 6) % bw
                r = 1.3 + (i % 3) * 0.5
                cr.new_path()
                cr.arc(x, y, r, 0, 2 * math.pi)
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.fill()
        cr.restore()

    def draw_box_inside(self, cr):
        """What's in the open box: the weather, then him (if he's in there)."""
        bx, by, bw, bh, _s = self.box_geom()
        self.draw_weather(cr, bx, by, bw, bh, time.monotonic())
        if self.mode == "box":
            self.draw_larry(cr)

    # ── peeking out of the closed box ───────────────────────────────────────
    PEEK_UP, PEEK_HOLD, PEEK_DOWN = 0.45, 1.9, 0.28   # seconds: up, a look around, ducking back

    def schedule_peek(self):
        if getattr(self, "peek_timer", None):
            GLib.source_remove(self.peek_timer)
        self.peek_timer = GLib.timeout_add(int(random.uniform(25, 90) * 1000), self.peek_out)

    def can_peek(self):
        return (self.has_box and self.cfg["behavior"].get("peek", True) and self.mode == "box"
                and self.open == 0 and not self.pinned and self.get_visible())

    def peek_out(self):
        """Now and then, with the box shut, he pokes his head out from behind the tab, has a look
        round, and ducks back in."""
        self.peek_timer = None
        if self.can_peek():
            self.peeking = time.monotonic()
            self.damage(*self.peek_rect())
            self.wake()
        self.schedule_peek()
        return False

    def peek_frame(self):
        """(where on the screen edge, rotation, how far up 0..1, tilt) for the peek now, or None."""
        if self.peeking is None:
            return None
        t = time.monotonic() - self.peeking
        total = self.PEEK_UP + self.PEEK_HOLD + self.PEEK_DOWN
        if t >= total or not self.can_peek():
            self.peeking = None
            return None
        if t < self.PEEK_UP:
            p = t / self.PEEK_UP
            up = 1 + 2.2 * (p - 1) ** 3 + 1.2 * (p - 1) ** 2     # pops up, a touch too far, settles
        elif t < self.PEEK_UP + self.PEEK_HOLD:
            up = 1.0
        else:
            up = 1 - ((t - self.PEEK_UP - self.PEEK_HOLD) / self.PEEK_DOWN) ** 2   # quick duck
        h = t - self.PEEK_UP
        tilt = 0.16 * math.sin(h * 3.2) * (1 if 0 < h < self.PEEK_HOLD else 0)   # looks one way, the other
        tx, ty, tw, th = self.tab_rect()
        gap = tw / 2 + self.lw * 0.45 + 8
        edge = self.edge
        along, room = (tx + tw / 2, self.W) if edge in ("top", "bottom") else (ty + th / 2, self.H)
        if along + gap + self.lw * 0.6 > room:     # (tab near the end of the edge: peek out the other side)
            gap = -gap
        anchor = {"top": (tx + tw / 2 + gap, 0), "bottom": (tx + tw / 2 + gap, self.H),
                  "left": (0, ty + th / 2 + gap), "right": (self.W, ty + th / 2 + gap)}[edge]
        rot = {"bottom": 0.0, "top": math.pi, "left": math.pi / 2, "right": -math.pi / 2}[edge]
        return anchor, rot, max(0.0, up), tilt

    def peek_rect(self):
        tx, ty, tw, th = self.tab_rect()
        r = max(self.lw, self.lh) * 1.3 + tw
        cx, cy = tx + tw / 2, ty + th / 2
        return cx - r, cy - r, 2 * r, 2 * r

    def draw_peek(self, cr):
        f = self.peek_frame()
        if not f:
            return
        (ax, ay), rot, up, tilt = f
        sprite = self.sprites[0]
        w, h = sprites.logical_size(sprite)
        body = self.cfg["size"] - 2 * sprites.PAD      # (the picture's height without any hat on top)
        show = ((h - body) + body * 0.4) * up          # how much of him is out: hat and head
        hx = w * (0.68 if sprites.is_larry(self.cfg) else 0.5)   # his head's middle, across the picture
        cr.save()
        cr.translate(ax, ay)
        cr.rotate(rot)
        cr.rectangle(-w * 2, -h * 2, w * 4, h * 2)   # only what's past the screen edge shows
        cr.clip()
        cr.rotate(tilt)                                # (leaning from the edge, like peering round it)
        cr.set_source_surface(sprite, -hx, -show)
        cr.paint()
        cr.restore()

    # ── popping out (the Waybar icon's click) ───────────────────────────────
    POOF_TIME = 0.6
    POP_TIME = 0.42

    def pop(self):
        """Out of the box with a puff of smoke and a hop (from beside the Waybar icon), or, if
        he's already out, poof back into the box."""
        now = time.monotonic()
        if self.mode == "drag":
            return
        if self.mode == "free" and not self.room:          # out already: back in he goes
            x, y = self.larry_pos()
            self.add_poof(x + self.lw / 2, y + self.lh * 0.55, self.lh)
            self.stop_ride()
            self.end_streak()
            self.damage_larry()
            self.mode, self.platform, self.vx, self.vy = "box", None, 0.0, 0.0
            self.act, self.reaction = None, None
            self.bx = (self.box_w - self.lw) / 2
            self.peek(1.6)                                   # open up so you see him land
            self.pop_start = now
        else:                                                # in the box or a terminal: out!
            self.leave_room()
            self.stop_ride()
            if self.typist:
                self.typist.stop()
                self.typist = None
            self.end_streak()
            bottom = waybar.bar_edge() == "bottom"
            bx, by = 18, (self.H - 40 - self.lh) if bottom else 34   # right beside the icon
            self.add_poof(bx + self.lw / 2, by + self.lh / 2, self.lh * 1.2)
            self.mode, self.platform = "free", None
            self.x, self.y = bx, by
            self.vx, self.vy = 420.0, (-900.0 if bottom else -520.0)   # a hop out and away
            self.dir = 1
            self.act, self.reaction, self.watching = None, None, False
            self.pop_start = now
            self.refresh_platforms()
            self.clips.weee(big=False, cow=sprites.is_larry(self.cfg))
        self.poked = now
        self.input_key = None
        self.update_input()
        self.queue_draw()
        self.wake()

    def add_poof(self, x, y, size):
        self.poofs.append({"x": x, "y": y, "size": size, "start": time.monotonic()})

    def poof_rect(self, p):
        r = p["size"] * 1.4
        return p["x"] - r, p["y"] - r, 2 * r, 2 * r

    def draw_poofs(self, cr, now):
        """Cartoon puffs: a ring of little clouds flying apart and shrinking away."""
        for p in self.poofs:
            k = (now - p["start"]) / self.POOF_TIME
            if not 0 <= k < 1:
                continue
            size = p["size"]
            for i in range(8):
                a = i * math.pi / 4 + 0.3
                d = size * (0.18 + 0.62 * (1 - (1 - k) ** 2))
                r = size * 0.2 * (1 - k) ** 0.8 * (1.1 if i % 2 else 0.85)
                cx, cy = p["x"] + math.cos(a) * d, p["y"] + math.sin(a) * d * 0.7
                cr.new_path()
                cr.arc(cx, cy, r, 0, 2 * math.pi)
                cr.set_source_rgba(0.08, 0.08, 0.1, 0.55 * (1 - k))
                cr.set_line_width(max(1.0, size * 0.03))
                cr.stroke_preserve()
                cr.set_source_rgba(1, 1, 1, 0.95 * (1 - k))
                cr.fill()
            if k < 0.25:                                     # a flash at the start
                cr.new_path()
                cr.arc(p["x"], p["y"], size * (0.25 + k * 1.6), 0, 2 * math.pi)
                cr.set_source_rgba(1, 1, 1, 0.6 * (1 - k * 4))
                cr.fill()

    def pop_scale(self, now):
        """Popping out: he springs from small to a bit too big and settles (1 when done)."""
        if self.pop_start is None:
            return 1.0
        p = (now - self.pop_start) / self.POP_TIME
        if p >= 1:
            self.pop_start = None
            return 1.0
        p = max(p, 0.0)
        return 1 + 2.4 * (p - 1) ** 3 + 1.4 * (p - 1) ** 2

    # ── petting ─────────────────────────────────────────────────────────────
    PET_FLOP = 10.0     # pet heights of stroking (without a break) before he flops over, blissed out
    HEART_TIME = 1.3    # seconds a heart floats

    def pettable(self):
        if self.mode == "box":
            return self.open > 0.6
        return self.mode == "free" and bool(self.platform) and (not self.room or self.room_shown)

    def stroke(self, p):
        """The pointer moved over him with the middle button held: that's a pet."""
        prev, self.pet_prev = self.pet_prev, p
        if not prev or not self.pettable() or not self.inside(p, self.larry_rect(), 4):
            return
        dx, dy = p[0] - prev[0], p[1] - prev[1]
        d = math.hypot(dx, dy)
        if d < 0.5:
            return
        now = time.monotonic()
        if not self.being_petted(now):       # a new petting session: drop whatever he was doing
            self.stop_ride()
            if self.typist:
                self.typist.stop()
                self.typist = None
            self.act, self.watching, self.reaction, self.notes = None, False, None, []
        self.pet_last = self.poked = self.cursor_moved = now
        self.pet_love = min(self.pet_love + d / self.lh, self.PET_FLOP * 1.5)
        self.pet_lean += (max(-1, min(1, dx / 6)) - self.pet_lean) * 0.25
        self.pet_dist += d
        if self.pet_dist > self.lh * 0.7:
            self.pet_dist = 0
            self.add_heart(p[0], p[1] - self.lh * 0.1)
        if not self.flopped and self.pet_love >= self.PET_FLOP:
            self.flopped = True
            x, y = self.larry_pos()
            for i in range(6):
                self.add_heart(x + self.lw * (0.15 + 0.14 * i), y + self.lh * 0.3, delay=i * 0.06)
            self.clips.play("moo-calf" if sprites.is_larry(self.cfg) else "love")
        self.damage_larry()
        self.wake()

    def add_heart(self, x, y, delay=0.0):
        self.hearts.append({"x": x, "y": y, "start": time.monotonic() + delay, "drift": random.uniform(-1, 1)})
        self.hearts = self.hearts[-24:]

    def being_petted(self, now):
        return now - self.pet_last < (1.8 if self.flopped else 0.7)

    def update_petting(self, dt, now):
        if now - self.pet_last > 0.7:
            self.pet_love = max(0.0, self.pet_love - dt * self.PET_FLOP / 3)
            self.pet_lean *= max(0.0, 1 - dt * 4)
        if self.flopped and not self.being_petted(now):
            self.flopped = False
            self.damage_larry()
            self.pause = max(self.pause, 0.8)    # gets up, has a moment
        for h in self.hearts:
            self.damage(*self.heart_rect(h, now))
        self.hearts = [h for h in self.hearts if now - h["start"] < self.HEART_TIME]

    def heart_rect(self, h, now):
        p = max(0.0, (now - h["start"]) / self.HEART_TIME)
        x, y = self.heart_pos(h, p)
        s = self.lh * 0.16
        return x - s * 2.2, y - s * 2, s * 4.4, s * 3.4

    def heart_pos(self, h, p):
        return (h["x"] + h["drift"] * self.lh * 0.35 * p + math.sin(p * 8 + h["drift"] * 3) * 3,
                h["y"] - p * self.lh * 0.85)

    def draw_hearts(self, cr, now):
        for h in self.hearts:
            p = (now - h["start"]) / self.HEART_TIME
            if not 0 <= p < 1:
                continue
            x, y = self.heart_pos(h, p)
            s = self.lh * 0.075 * (0.6 + 0.6 * min(1, p * 4))
            self.heart(cr, x, y, s, (0.95, 0.33, 0.45, min(1, p * 6) * (1 - p) ** 0.8))

    def draw_petted(self, cr, x, y, side, t):
        """Eyes shut happy, leaning into your hand; flopped on his side once he's had enough."""
        if self.flopped and "sleep" in self.poses:
            sprite = self.poses["sleep"][side]
            tilt = 0.06 * math.sin(t * 5)              # a blissful little wriggle
            sprites.draw_pet(cr, sprite, x + self.lw / 2, y + self.lh, tilt, 0, 0.04 * math.sin(t * 7))
            return
        stroking = t - self.pet_last < 0.25
        tilt = self.pet_lean * 0.12 + (0.02 * math.sin(t * 9) if stroking else 0)
        squash = 0.05 + (0.025 * math.sin(t * 11) if stroking else 0)
        if self.flopped:                               # (pets without a lying-down pose) melt a bit more
            squash += 0.06
        if "eyeless" in self.poses:
            sprites.draw_pet(cr, self.poses["eyeless"][side], x + self.lw / 2, y + self.lh, tilt, 0, squash,
                             self.draw_mood_eyes)
        else:
            sprites.draw_pet(cr, self.sprites[side], x + self.lw / 2, y + self.lh, tilt, 0, squash)

    # ── vehicles ────────────────────────────────────────────────────────────
    RIDE_SCALE = 0.7    # vehicles (and him on them) are drawn this much smaller than he walks
    RIDE_POP = 0.3      # seconds the vehicle takes to pop in / out
    RIDE_GONE = 0.45    # ...and its puff of smoke

    @property
    def ride_L(self):
        """His height on a vehicle (px): what the vehicles are measured in."""
        return self.lh * self.RIDE_SCALE

    def ride_gap(self):
        return self.cfg["ride"]["every"] * 60 * random.uniform(0.6, 1.4)

    def walk_range(self):
        """Where his left edge can go where he is now (box, terminal, or window top / floor)."""
        if self.mode == "box":
            return 6, self.box_w - self.lw - 6
        if self.room and self.room_rect:
            left, _top, right, _bottom = self.room_rect
            return left, max(right - self.lw, left)
        if self.platform:
            _addr, left, right, _top = self.platform
            return max(left - self.lw / 2, 0), min(right - self.lw / 2, self.W - self.lw)
        return 0, self.W - self.lw

    def ride_margin(self, kind=None):
        """How much further than the pet itself the vehicle sticks out, each side (px)."""
        kind = kind or (self.ride and self.ride["kind"])
        return max(0.0, vehicles.margin(kind) * self.ride_L - self.lw / 2) if kind else 0.0

    def keep_in(self, pos, lo, hi):
        """Turn around at the walls. Riding, the vehicle has to fit too: if it doesn't yet (it just
        appeared by a wall) he drives back in rather than jumping."""
        m = self.ride_margin()
        if m:
            lo2, hi2 = lo + m, hi - m
            if lo2 > hi2:
                lo2 = hi2 = (lo + hi) / 2
            if pos < lo2:
                self.dir = 1
                return max(pos, lo)
            if pos > hi2:
                self.dir = -1
                return min(pos, hi)
            return pos
        if pos <= lo or pos >= hi:
            pos = min(max(pos, lo), hi)
            self.dir = 1 if pos <= lo else -1
        return pos

    def start_ride(self, kind=None):
        if not self.grounded() or self.typist:
            return False
        kind = kind or self.cfg["ride"]["vehicle"]
        if kind not in vehicles.KINDS:
            kind = random.choice(list(vehicles.KINDS))
        lo, hi = self.walk_range()
        if hi - lo < 2 * self.ride_margin(kind) + 8:
            return False                    # a narrow window: no room to drive
        now = time.monotonic()
        self.act, self.watching, self.pause = None, False, 0
        self.ride = {"kind": kind, "start": now, "until": now + random.uniform(14, 28), "end": None,
                     "dist": 0.0, "alt": 0.0, "wheelie": 0.0, "next_wheelie": now + random.uniform(3, 7)}
        self.damage_larry()
        self.wake()
        return True

    def ride_now(self, kind=None):
        """The settings window's "Ride now": wake him up if needed and go."""
        if self.typist:
            self.typist.stop()
            self.typist = None
        if self.act in ("sleep", "sit", "type"):
            self.act = None
        self.reaction = None
        self.stop_ride()
        if self.mode == "box":
            self.peek(8)
        return self.start_ride(kind)

    def end_ride(self):
        """Time's up: a helicopter lands first, then the vehicle pops away."""
        if self.ride and self.ride["end"] is None:
            self.ride["until"] = 0

    def stop_ride(self):
        """Gone at once (he was picked up, or fell off)."""
        if self.ride:
            self.damage_larry()
            self.ride = None
            self.next_ride = time.monotonic() + self.ride_gap()

    def headroom(self):
        """Space above his feet before the box / terminal / screen ends (px)."""
        ground = self.larry_pos()[1] + self.lh
        if self.mode == "box":
            limit = self.box_geom()[1] + 2
        elif self.room and self.room_rect:
            limit = self.room_rect[1] + 2
        else:
            limit = 4
        return ground - limit

    def ride_fit(self, kind):
        """Shrink a vehicle that's too tall for where he is (the helicopter in a short box)."""
        return max(0.5, min(1.0, self.headroom() / (self.ride_top(kind) * self.ride_L)))

    def heli_ceiling(self):
        """How high the helicopter can fly here without its rotor leaving the box / terminal / screen."""
        room = self.headroom() - self.ride_top("helicopter") * self.ride_L
        return max(0.0, min(self.lh * 1.1, room))

    def rider_head(self, kind):
        """How high his head is when he's on it (in pet heights)."""
        if self.riding:
            frames, meta = self.riding
            _x, y = self.frame_point(frames[0][0], *meta["seat"])
            return vehicles.SEAT[kind][1] + y / self.lh
        _dx, lift, scale = vehicles.RIDER[kind]
        return lift + scale

    def halo(self):
        """The vehicles' sticker outline, matching the pet's."""
        return {"halo": self.cfg["outline"], "halo_rgb": tuple(v / 255 for v in sprites.rgb(self.cfg["outline_color"])),
                "halo_px": float(sprites.outline_width(self.cfg))}

    def frame_point(self, sprite, ax, ay):
        """A point given as fractions of one of Larry's drawn frames -> px in the sprite (the frame
        sits PAD in from the edges, more on the left, right and top with a wide outline)."""
        w, h = sprites.logical_size(sprite)
        p, e = sprites.PAD, sprites.grow(self.cfg)
        return p + e + ax * (w - 2 * (p + e)), p + e + ay * (h - 2 * p - e)

    def ride_top(self, kind):
        return vehicles.top(kind, self.rider_head(kind))

    def draw_rider(self, cr, kind, L, s, frame, bob=0.0):
        """The pet on its vehicle (cr at the vehicle's origin, scaled by s while it pops in: the pet
        keeps its size and slides up into the seat). L: the vehicle's pet height in px."""
        k = L / self.lh
        cr.save()
        cr.scale(1 / s, 1 / s)
        if self.riding:              # Larry: sitting in the seat
            frames, meta = self.riding
            sprite = frames[frame % len(frames)][0]
            sx, sy = vehicles.SEAT[kind]
            if kind == "bike":       # his hooves on the pedals
                ax, ay = meta["crank"]
                sx, sy = vehicles.BIKE_BB[0], -vehicles.BIKE_BB[1]
            else:
                ax, ay = meta["seat"]
            cr.translate(sx * L * s, -sy * L * s - bob)
            cr.scale(k, k)
            px, py = self.frame_point(sprite, ax, ay)
            cr.set_source_surface(sprite, -px, -py)
            cr.paint()
        else:                        # anyone else: standing on it
            dx, lift, scale = vehicles.RIDER[kind]
            cr.translate(dx * L * s, -lift * L * s)
            sc = (1 + (scale - 1) * min(s, 1)) * k
            cr.scale(sc, sc)
            sprites.draw_pet(cr, self.sprites[0], 0, 0, 0, bob, 0)
        cr.restore()

    def pedal_length(self):
        """The bike's crank length, to match his pedalling hooves (in pet heights)."""
        if not self.riding:
            return 0.13
        frames, meta = self.riding
        _w, h = sprites.logical_size(frames[0][0])
        return meta.get("pedal", 0.05) * (h - 2 * sprites.PAD - sprites.grow(self.cfg)) / self.lh

    def update_ride(self, dt, now):
        r = self.ride
        if r["end"] is not None:
            if now - r["end"] > self.RIDE_GONE:
                self.damage_larry()
                self.ride = None
                self.next_ride = now + self.ride_gap()
            return
        ending = now > r["until"]
        if r["kind"] == "helicopter":
            target = 0 if ending or now - r["start"] < self.RIDE_POP else self.heli_ceiling()
            r["alt"] += (target - r["alt"]) * min(1.0, dt * 1.8)
            if ending and r["alt"] < 0.6:
                r["alt"], r["end"] = 0.0, now
        elif ending:
            r["end"] = now
        if r["kind"] == "motorcycle" and self.walking and now > r["next_wheelie"]:
            r["wheelie"], r["next_wheelie"] = now, now + random.uniform(5, 10)

    def ride_rect(self):
        """Everything the vehicle covers (where a click grabs him while riding)."""
        x, y = self.larry_pos()
        r = self.ride
        L = self.ride_L
        m = vehicles.margin(r["kind"]) * L
        top = self.ride_top(r["kind"]) * L
        ground = y + L - r["alt"]
        return x + self.lw / 2 - m, ground - top, 2 * m, top

    WHEELIE_TIME = 1.3

    def draw_ride(self, cr, x, y, t):
        r = self.ride
        kind, L = r["kind"], self.ride_L
        cx, ground = x + self.lw / 2, y + self.lh - r["alt"]
        age = t - r["start"]
        if r["end"] is not None:              # popping away
            gone = (t - r["end"]) / self.RIDE_POP
            s = max(0.0, 1 - gone) ** 2
        else:                                 # popping in, with a little overshoot
            p = min(1.0, age / self.RIDE_POP)
            s = 1 + 2.7 * (p - 1) ** 3 + 1.7 * (p - 1) ** 2
        moving = self.walking and not self.reaction
        crank = vehicles.crank(kind, r["dist"], L)
        frame, bob = 0, 0.0
        if kind == "bike":
            frame = int(crank / (2 * math.pi) * 8) % 8 if self.riding else 0   # Larry pedals
            if not self.riding and moving:
                bob = abs(math.sin(crank)) * L * 0.03
        elif kind == "motorcycle" and moving:
            bob = abs(math.sin(t * 19)) * L * 0.012
        if s > 0.02:
            def rider():
                self.draw_rider(cr, kind, L, s, frame, bob)

            cr.save()
            cr.translate(cx, ground)
            fit = self.ride_fit(kind)
            cr.scale(self.dir * fit, fit)     # vehicles face right
            w = t - r["wheelie"]
            if kind == "motorcycle" and r["wheelie"] and w < self.WHEELIE_TIME:
                up = math.sin(math.pi * w / self.WHEELIE_TIME) ** 0.6 * 0.32
                cr.translate(vehicles.WHEELIE_PIVOT * L, 0)   # up on the back wheel
                cr.rotate(-up)
                cr.translate(-vehicles.WHEELIE_PIVOT * L, 0)
            cr.scale(s, s)
            vehicles.draw(cr, kind, L, rider, t, r["dist"], moving,
                          head=self.rider_head(kind), pedal=self.pedal_length(), **self.halo())
            cr.restore()
        else:                                 # all gone but the smoke: he's back on his feet
            sprites.draw_pet(cr, self.sprites[0 if self.dir > 0 else 1], cx, y + self.lh, 0, 0, 0)
        if age < self.RIDE_GONE:
            vehicles.poof(cr, cx, ground - 0.35 * L, L, age / self.RIDE_GONE)
        if r["end"] is not None:
            vehicles.poof(cr, cx, ground - 0.35 * L, L, min(1.0, (t - r["end"]) / self.RIDE_GONE))
        if self.reaction:
            up = (self.rider_head(kind) - 1) * L * min(s, 1)
            self.draw_reaction(cr, x, y - up - r["alt"], t - self.reaction["start"], self.reaction)

    # ── catch game ──────────────────────────────────────────────────────────
    MIN_TOSS = 60   # px he has to go up for a catch to count

    @staticmethod
    def load_best():
        try:
            return int(json.loads(STATE.read_text()).get("best", 0))
        except (OSError, ValueError, AttributeError):
            return 0

    def save_best(self):
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"best": self.best}))
        except OSError:
            pass
        if self.settings:
            self.settings.update_best()

    def reset_best(self):
        self.best = 0
        self.save_best()
        self.damage_box()
        self.wake()

    def try_catch(self):
        """Grabbed in mid-air: on the way down from a real throw, that's a point."""
        t = self.toss
        self.toss = None
        if not t or self.vy <= 0 or (t["from"] - t["peak"] < self.MIN_TOSS and not t["hit"]):
            return                 # not falling yet, or barely thrown: no point, streak carries on
        # +1 for the catch, +1 for every different side of the screen he bounced off on the way
        points = 1 + len(t["hit"])
        self.streak += points
        self.clips.play("catch" if points == 1 else "trick")
        self.popup({1: "+1", 2: "+2 off the wall!", 3: "+3 bank shot!"}.get(points, f"+{points} trick shot!"),
                   big=points > 1)
        if self.streak > self.best:   # keep the record safe even if this ends abruptly
            self.best = self.streak
            self.save_best()
        self.damage_box()

    def end_streak(self):
        self.toss = None
        if not self.streak:
            return
        n, self.streak = self.streak, 0
        if n >= self.best:
            self.clips.play("best")
            self.popup(f"New best: {n}!", big=True)
        else:
            self.clips.play("miss")
            self.popup(f"Streak {n}", big=True)
        self.damage_box()

    def popup(self, text, big):
        x, y = self.larry_pos()
        self.popups.append({"text": text, "x": x + self.lw / 2, "y": y - 6, "start": time.monotonic(), "big": big})
        self.wake()

    POPUP_TIME = 1.1

    def popup_rect(self, p):
        w = len(p["text"]) * (9 if p["big"] else 8) + 30
        return p["x"] - w / 2, p["y"] - 70, w, 90

    def draw_popups(self, cr, now):
        for p in self.popups:
            k = (now - p["start"]) / (self.POPUP_TIME * (1.6 if p["big"] else 1))
            if k >= 1:
                continue
            size = (15 if p["big"] else 14) * (1 + 0.25 * math.sin(min(k * 4, 1) * math.pi))   # pops in
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(size)
            ext = cr.text_extents(p["text"])
            x = min(max(p["x"] - ext.x_advance / 2, 4), self.W - ext.x_advance - 4)
            y = p["y"] - k * 40
            a = 1 - max(0, k - 0.6) / 0.4
            cr.move_to(x, y)
            cr.text_path(p["text"])
            cr.set_source_rgba(0.06, 0.06, 0.08, 0.85 * a)
            cr.set_line_width(3.5)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.stroke_preserve()
            gold = (1, 0.82, 0.3) if p["big"] else (0.55, 1, 0.6)
            cr.set_source_rgba(*gold, a)
            cr.fill()

    def draw_score(self, cr):
        """Best (and the current streak) in the corner of the open box."""
        if not self.cfg["game"] or not (self.best or self.streak):
            return
        x, y, w, h = self.visible_box()
        if w < 60 or h < 30:
            return
        c = self.colors
        text = f"{self.best}" + (f"   now {self.streak}" if self.streak else "")
        cr.save()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        ext = cr.text_extents(text)
        star = 12
        pw, ph = ext.x_advance + 14 + star + 4, 18
        # top-right, up in the sky: he walks along the bottom, so it's never under him
        px, py = x + w - pw - 8, y + 8
        cr.new_path()
        cr.arc(px + ph / 2, py + ph / 2, ph / 2, math.pi / 2, math.pi * 1.5)
        cr.arc(px + pw - ph / 2, py + ph / 2, ph / 2, -math.pi / 2, math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(*c["bg1"], 0.8 * min(1, self.open * 2))
        cr.fill()
        a = min(1, self.open * 2)
        sx, sy = px + 7 + star / 2, py + ph / 2           # a little gold star (fonts may lack one)
        for i in range(10):
            r = star / 2 if i % 2 == 0 else star / 4.6
            ang = -math.pi / 2 + i * math.pi / 5
            (cr.move_to if i == 0 else cr.line_to)(sx + r * math.cos(ang), sy + r * math.sin(ang))
        cr.close_path()
        cr.set_source_rgba(1, 0.82, 0.3, a)
        cr.fill()
        cr.move_to(px + 7 + star + 4 - ext.x_bearing, py + ph / 2 - ext.y_bearing - ext.height / 2)
        cr.set_source_rgba(*c["fg"], a)
        cr.show_text(text)
        cr.restore()

    REACT_TIME = 3.2   # seconds a reaction lasts

    def on_finished(self, kind, ok, text):
        """Something finished downloading (watch.py): cheer, or be sad if it failed."""
        now = time.monotonic()
        self.reaction = {"mood": "happy" if ok else "sad", "start": now, "until": now + self.REACT_TIME,
                         "text": text if self.cfg["reactions"]["bubble"] else None}
        self.act, self.watching, self.poked = None, False, now   # wake up for it
        self.end_ride()
        if self.mode == "box":
            self.peek(self.REACT_TIME + 0.3)   # pop the box open so you can see
        self.wake()

    def check_updates(self, force=False, done=None):
        """Ask GitHub (on a worker thread) whether there's a newer version; the first time we hear
        of one, say so. done(latest or error) for the settings window's "Check now"."""
        if not self.cfg.get("updates", True) and not force:
            GLib.timeout_add_seconds(updates.EVERY, self.check_updates)
            return False

        def work():
            try:
                res = updates.check(force)
            except updates.UpdateError as e:
                res = e
            GLib.idle_add(finished, res)

        def finished(res):
            if not isinstance(res, Exception) and updates.newer(res["version"]) \
                    and updates.should_announce(res["version"]):
                self.on_finished("update", True, f"Update: v{res['version']} is out!")
            if self.settings:
                self.settings.show_update()
            if done:
                done(res)
            return False
        threading.Thread(target=work, daemon=True).start()
        if not force:
            GLib.timeout_add_seconds(updates.EVERY, self.check_updates)
        return False

    def check_season(self):
        """Once per holiday: tell you there's something new to claim in the wardrobe."""
        season = accessories.new_season()
        if season:
            self.on_finished("season", True, f"New {accessories.SEASONS[season][0]} stuff to claim!")
        GLib.timeout_add_seconds(1800, self.check_season)
        return False

    WATCH_R, WAKE_R = 260, 110   # px: cursor this close gets watched / wakes him up

    def poll_cursor(self, now):
        """Where the mouse is, anywhere on the screen (Hyprland knows; our window mostly doesn't)."""
        if now - self.cursor_t < 0.1:
            return
        self.cursor_t = now
        if self.mode == "box" and (self.mon is None or now - self.mon_t > 3):
            mons = hypr("monitors") or []
            mon = next((m for m in mons if m.get("focused")), mons[0] if mons else None)
            if mon:
                self.mon = mon
            self.mon_t = now
        c = hypr("cursorpos")
        if not c or not self.mon:
            return
        p = (c["x"] - self.mon["x"], c["y"] - self.mon["y"])
        if self.cursor is None or abs(p[0] - self.cursor[0]) + abs(p[1] - self.cursor[1]) > 2:
            self.cursor_moved = now
        self.cursor = p

    def behave(self, now):
        """Idle behaviours while he's on his feet: watch the cursor, sit, sleep."""
        b = self.cfg["behavior"]
        self.poll_cursor(now)
        x, y, w, h = self.larry_rect()
        cx, cy = x + w / 2, y + h / 2
        dist = math.hypot(self.cursor[0] - cx, self.cursor[1] - cy) if self.cursor else 1e9
        recent = now - self.cursor_moved < 2.0
        if self.ride or self.being_petted(now):
            return
        if self.act == "type":
            if recent and dist < self.WAKE_R:          # you're back: stop mid-sentence
                self.typist.stop()
                self.typist, self.act, self.pause = None, None, 1.2
            elif not self.typist.step(now):            # done: back to sleep
                self.typist, self.act, self.last_chat = None, "sleep", now
            return
        if self.act == "dance":
            if not self.music.playing or now > self.dance_until:
                self.act, self.pause = None, 0.8
                self.next_dance = now + (random.uniform(8, 20) if self.music.playing else 0)
                self.damage_larry()
                self.notes = []
            else:
                self.dance_turns(now)
            return
        if self.music.playing and now >= self.next_dance and not (self.reaction or self.typist):
            self.start_dance(now)
            return
        if self.act == "sleep":
            if not b["sleep"] or (recent and dist < self.WAKE_R):
                self.act, self.pause = None, 1.2       # wake up, stand there a moment
            elif self.want_to_type(now):
                self.act = "type"
            return
        if self.act == "sit" and (now > self.act_until or not b["sit"]):
            self.act = None
        if b["sleep"] and now - max(self.cursor_moved, self.poked) > b["sleep_after"]:
            self.act, self.watching = "sleep", False
            self.asleep_since = self.last_chat = now
            self.chats = 0
            return
        self.watching = b["watch"] and recent and dist < self.WATCH_R
        if self.watching and abs(self.cursor[0] - cx) > w * 0.3:
            self.dir = 1 if self.cursor[0] > cx else -1
        if (self.cfg["ride"]["enabled"] and now >= self.next_ride and not (self.act or self.watching
                                                                           or self.reaction or self.pause > 0)):
            if not self.start_ride():
                self.next_ride = now + 20      # no room here: try again in a bit

    # ── dancing ─────────────────────────────────────────────────────────────
    DANCE_MOVES = ("bop", "sway", "spin", "kick", "headbang", "bounce")

    def start_dance(self, now):
        self.act, self.watching, self.pause = "dance", False, 0
        self.dance_until = now + random.uniform(25, 60)
        moves = [m for m in self.DANCE_MOVES if m != "kick" or "dangle0" in self.poses]
        random.shuffle(moves)
        self.dance_moves = moves
        self.last_note_beat = int(self.music.now_beats())
        self.damage_larry()

    def dance_move(self, beats):
        """Which move he's doing on this beat (a new one every 8 beats)."""
        return self.dance_moves[int(beats // 8) % len(self.dance_moves)] if self.dance_moves else "bop"

    def dance_turns(self, now):
        """Spinning flips him round every other beat; music notes pop out on the beat."""
        beats = self.music.now_beats(now)
        if self.dance_move(beats) == "spin":
            self.dir = 1 if int(beats // 2) % 2 == 0 else -1
        if self.cfg["dance"]["notes"] and int(beats) > self.last_note_beat:
            self.last_note_beat = int(beats)
            if int(beats) % 2 == 0:
                self.notes.append({"x": random.uniform(0.15, 0.85), "start": now,
                                   "drift": random.uniform(-1, 1), "kind": random.randrange(2)})
        self.notes = [n for n in self.notes if now - n["start"] < self.NOTE_TIME]

    NOTE_TIME = 1.8

    def dance_pose(self, t):
        """(tilt, bob, squash, legs frame or None) for this moment of the dance."""
        beats = self.music.now_beats(t)
        f = beats % 1                       # 0 on the beat
        k = self.music.strength()
        hop = math.sin(math.pi * f)         # up between beats, down on them
        hit = (1 - f) ** 3                  # a squash right on the beat
        move = self.dance_move(beats)
        if move == "bop":
            return 0, self.lh * 0.09 * k * hop, 0.1 * k * hit - 0.04 * k * hop, None
        if move == "sway":
            return 0.2 * k * math.cos(math.pi * beats), self.lh * 0.03 * hop, 0.04 * k * hit, None
        if move == "spin":
            return 0, self.lh * 0.16 * k * abs(math.sin(math.pi * beats / 2)), 0.08 * k * hit, None
        if move == "kick":
            n = sum(1 for p in self.poses if p.startswith("dangle"))
            return 0, self.lh * 0.14 * k * hop, 0.06 * k * hit, int(f * n) % n
        if move == "headbang":
            return self.dir * 0.22 * k * hit, 0, 0.05 * k * hit, None
        # bounce: big hops on every other beat, a little one between
        big = int(beats) % 2 == 0
        return (0.08 * k * hop * (1 if big else -1), self.lh * (0.24 if big else 0.07) * k * hop,
                (0.14 if big else 0.06) * k * hit - 0.05 * k * hop, None)

    def draw_notes(self, cr, x, y, t):
        """Music notes floating up off him."""
        c = self.colors
        for n in self.notes:
            p = (t - n["start"]) / self.NOTE_TIME
            if not 0 <= p < 1:
                continue
            a = min(1, p * 5) * (1 - p) ** 0.7
            nx = x + self.lw * n["x"] + n["drift"] * self.lh * 0.35 * p + math.sin(p * 9 + n["drift"]) * 3
            ny = y - p * self.lh * 0.9
            s = self.lh * 0.2 * (0.7 + 0.5 * min(1, p * 4))
            cr.save()
            cr.translate(nx, ny)
            cr.rotate(math.sin(p * 7 + n["drift"]) * 0.25)
            cr.scale(s, s)
            self.note_path(cr, n["kind"])
            cr.set_source_rgba(0.06, 0.06, 0.07, a)
            cr.set_line_width(0.22)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.stroke_preserve()
            cr.set_source_rgba(*c["accent2"], a)
            cr.fill()
            cr.restore()

    @staticmethod
    def note_path(cr, kind):
        """A ♪ (kind 0) or a ♫ (kind 1) in a 1-unit box, as one fillable shape."""
        def head(cx, cy):
            cr.save()
            cr.translate(cx, cy)
            cr.rotate(-0.4)
            cr.scale(0.2, 0.14)
            cr.new_sub_path()
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
        if kind == 0:
            head(-0.12, 0.38)
            cr.rectangle(0.0, -0.5, 0.07, 0.86)
            cr.move_to(0.0, -0.5)
            cr.curve_to(0.15, -0.38, 0.35, -0.3, 0.3, -0.05)
            cr.curve_to(0.25, -0.22, 0.12, -0.28, 0.0, -0.3)
            cr.close_path()
        else:
            head(-0.3, 0.42)
            head(0.26, 0.34)
            cr.rectangle(-0.18, -0.38, 0.07, 0.78)
            cr.rectangle(0.38, -0.46, 0.07, 0.78)
            cr.move_to(-0.18, -0.38)
            cr.line_to(0.45, -0.46)
            cr.line_to(0.45, -0.3)
            cr.line_to(-0.18, -0.22)
            cr.close_path()

    MAX_CHATS = 3   # messages per nap: then he really sleeps

    def want_to_type(self, now):
        """Napping in a terminal, typing turned on, you've been away long enough: wake up and type
        something, if the terminal's shell is just sitting at its prompt (never over a program)."""
        chat = self.cfg["chat"]
        if not (chat["typing"] and self.room and self.room_shown) or self.chats >= self.MAX_CHATS:
            return False
        if now - self.last_chat < chat["every"] * 60:
            return False
        self.last_chat = now                           # whatever happens, wait another round
        c = self.clients.get(self.room)
        shell = termchat.find_shell(c["pid"]) if c and c.get("pid") else None
        if not shell or not shell[1] or shell[2] < 60:
            return False                               # busy with a program, or you typed recently
        self.typist = termchat.Typist(shell[0], self.cfg["name"], termchat.message(sprites.is_larry(self.cfg)))
        self.chats += 1
        return True

    def grounded(self):
        if self.mode == "box":
            return self.open > 0
        return self.mode == "free" and bool(self.platform) and (not self.room or self.room_shown)

    def wander(self, dt, speed):
        """Shared walking brain: occasional stops and turns. Returns dx for this frame."""
        a = self.anim
        if self.act or self.watching or self.reaction or self.being_petted(time.monotonic()):   # busy: stay put
            self.walking, self.phase = False, 0
            return 0
        if self.ride:
            r = self.ride
            if r["end"] is not None or time.monotonic() - r["start"] < self.RIDE_POP:
                self.walking = False                     # getting on / off
                return 0
            self.walking = True
            dx = self.dir * speed * vehicles.SPEED[r["kind"]] * dt
            r["dist"] += abs(dx)
            return dx
        if self.pause > 0:
            self.pause -= dt
            self.walking, self.phase = False, 0
            return 0
        if a.stop_every and random.random() < dt / a.stop_every:   # stop and look around
            self.pause = random.uniform(a.stop_min, max(a.stop_min, a.stop_max))
            if self.cfg["behavior"]["sit"] and "sit" in self.poses and random.random() < 0.3:
                self.act, self.act_until = "sit", time.monotonic() + random.uniform(6, 16)
            if random.random() < a.turn_chance / 100:
                self.dir *= -1
            return 0
        self.walking = True
        self.phase += speed * dt / a.step_length
        return self.dir * speed * dt

    def walk_box(self, dt):
        self.bx += self.wander(dt, self.anim.walk_speed)
        self.bx = self.keep_in(self.bx, *self.walk_range())

    def step_room(self, dt):
        """Inside a terminal: the window's bottom is the floor, its sides are walls."""
        if not self.room_shown or not self.room_rect:
            return
        left, top, right, bottom = self.room_rect
        floor = bottom - self.lh
        lo, hi = left, max(right - self.lw, left)
        if self.platform:
            self.y = floor
            self.x += self.wander(dt, self.anim.free_speed)
            self.x = self.keep_in(self.x, lo, hi)
            return
        self.walking = False
        self.vy += self.anim.gravity * dt
        self.vx *= 0.995
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < lo or self.x > hi:
            self.x = min(max(self.x, lo), hi)
            self.vx = -self.vx * self.anim.bounce
        if self.y < top and self.vy < 0:
            self.y, self.vy = top, 0
        if self.y >= floor:
            self.y, self.vx, self.vy = floor, 0, 0
            self.platform = ("room", left, right, bottom)
            self.dir = random.choice((-1, 1))

    SIDE_PAD = 6   # px of his picture that can overlap a window edge (it's mostly transparent there)

    def hit_window_edges(self, before):
        """Bounce off the sides and undersides of windows (their tops are for landing on). Only an
        edge he crosses from outside counts, so letting go of him over a window never traps him."""
        px, py = before
        lw, lh, pad = self.lw, self.lh, self.SIDE_PAD
        for addr, x0, y0, x1, y1 in self.walls:
            # was he beside / below it a moment ago, and does he overlap it now?
            v_overlap = self.y + lh - pad > y0 + 4 and self.y + pad < y1
            h_overlap = self.x + lw - pad > x0 and self.x + pad < x1
            side = None
            if v_overlap and px + lw - pad <= x0 < self.x + lw - pad and self.vx > 0:
                self.x, self.vx, side = x0 - lw + pad, -self.vx * self.anim.bounce, "left"
            elif v_overlap and px + pad >= x1 > self.x + pad and self.vx < 0:
                self.x, self.vx, side = x1 - pad, -self.vx * self.anim.bounce, "right"
            elif h_overlap and py + pad >= y1 > self.y + pad and self.vy < 0:
                self.y, self.vy, side = y1 - pad, -self.vy * self.anim.bounce, "bottom"
            if side and self.toss and (abs(self.vx) > 40 or abs(self.vy) > 40):
                self.toss["hit"].add((addr, side))   # catch game: a window's side counts as a side

    def step_free(self, dt):
        if self.room:
            return self.step_room(dt)
        if self.platform:
            addr, left, right, top = self.platform
            if addr != "floor":   # ride the window he's on; fall if it's gone
                p = next((p for p in self.platforms if p[0] == addr), None)
                cx = self.x + self.lw / 2
                if not p or not (p[1] <= cx <= p[2]):
                    self.platform = None
                    return
                self.platform = p
                addr, left, right, top = p
            self.y = top - self.lh + 3
            self.x += self.wander(dt, self.anim.free_speed)
            self.x = self.keep_in(self.x, *self.walk_range())
            return

        # airborne
        self.walking = False
        self.vy += self.anim.gravity * dt
        self.vx *= 0.995
        feet_before = self.y + self.lh - 3
        before = (self.x, self.y)
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.hit_window_edges(before)
        if self.x < 0 or self.x > self.W - self.lw:      # bounce off the screen sides
            if self.toss and abs(self.vx) > 60:
                self.toss["hit"].add("left" if self.x < 0 else "right")
            self.x = min(max(self.x, 0), self.W - self.lw)
            self.vx = -self.vx * self.anim.bounce
        if self.y < 0 and self.vy < 0:                    # and off the top
            if self.toss and self.vy < -60:
                self.toss["hit"].add("top")
            self.y, self.vy = 0, -self.vy * self.anim.bounce
        if self.toss:
            self.toss["peak"] = min(self.toss["peak"], self.y)
        feet = self.y + self.lh - 3
        cx = self.x + self.lw / 2
        if self.vy >= 0:
            landing = [p for p in self.platforms
                       if p[1] <= cx <= p[2] and feet_before <= p[3] + 1 <= feet + 1]
            if landing:
                self.platform = min(landing, key=lambda p: p[3])
            elif feet >= self.H:
                self.platform = ("floor", 0, self.W, self.H)
            if self.platform:
                self.y = self.platform[3] - self.lh + 3
                self.vx = self.vy = 0
                self.dir = random.choice((-1, 1))
                self.end_streak()     # touched down: missed

    # ── drawing ─────────────────────────────────────────────────────────────
    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        c = self.colors
        bx, by, bw, bh, stretch = self.box_geom()
        tx, ty, tw, th = self.tab_rect()
        edge = self.edge

        # the box (slides out from its edge)
        if self.open > 0:
            pet = self.draw_box_inside if (self.mode == "box" or self.weather_effect()) else None
            cr.save()
            if stretch != 1:  # overshoot: stretch the box (and the pet in it) away from the edge
                ax, ay = {"top": (0, 0), "bottom": (0, self.H), "left": (0, 0), "right": (self.W, 0)}[edge]
                cr.translate(ax, ay)
                cr.scale(*((1, stretch) if edge in ("top", "bottom") else (stretch, 1)))
                cr.translate(-ax, -ay)
            self.box_cache.paint(cr, bx, by, bw, bh, c, self.cfg["box"], pet, edge)
            cr.restore()
            self.draw_score(cr)

        if self.peeking is not None and self.mode == "box":
            self.draw_peek(cr)

        # the tab: rounded on the side away from the edge, grip dots along it
        if self.has_box:            # a soft little pill with a grip bar (accent while pinned open)
            cr.save()
            cr.translate(tx, ty)
            scene.box_path(cr, tw, th, 7, edge)
            cr.restore()
            cr.set_source_rgba(*c["bg1"], 0.96)
            cr.fill()
            horiz = edge in ("top", "bottom")
            gl, gw = (16, 3) if horiz else (3, 16)
            gx, gy = tx + tw / 2 - gl / 2, ty + th / 2 - gw / 2
            cr.new_sub_path()
            r_ = 1.5
            cr.arc(gx + gl - r_, gy + r_, r_, -math.pi / 2, 0)
            cr.arc(gx + gl - r_, gy + gw - r_, r_, 0, math.pi / 2)
            cr.arc(gx + r_, gy + gw - r_, r_, math.pi / 2, math.pi)
            cr.arc(gx + r_, gy + r_, r_, math.pi, 3 * math.pi / 2)
            cr.close_path()
            cr.set_source_rgba(*(c["accent2"] if self.pinned else c["fg"]), 0.85 if self.pinned else 0.35)
            cr.fill()

        if self.mode != "box":
            self.draw_larry(cr)
        if self.hearts:
            self.draw_hearts(cr, time.monotonic())
        if self.poofs:
            self.draw_poofs(cr, time.monotonic())
        if self.popups:
            self.draw_popups(cr, time.monotonic())

    def draw_larry(self, cr):
        if self.mode == "free" and self.room:
            if not self.room_shown or not self.room_rect:
                return
            left, top, right, bottom = self.room_rect   # stay inside the window, behind anything over it
            region = cairo.Region(cairo.RectangleInt(round(left), round(top), round(right - left), round(bottom - top)))
            for r in self.room_covers:
                region.subtract(cairo.RectangleInt(*(round(v) for v in r)))
            cr.save()
            for i in range(region.num_rectangles()):
                r = region.get_rectangle(i)
                cr.rectangle(r.x, r.y, r.width, r.height)
            cr.clip()
            self._draw_larry(cr)
            cr.restore()
            return
        self._draw_larry(cr)

    def _draw_larry(self, cr):
        s = self.pop_scale(time.monotonic())
        if s != 1.0:
            x, y = self.larry_pos()
            cr.save()
            cr.translate(x + self.lw / 2, y + self.lh * 0.6)
            cr.scale(max(s, 0.02), max(s, 0.02))
            cr.translate(-(x + self.lw / 2), -(y + self.lh * 0.6))
            try:
                self._draw_larry_now(cr)
            finally:
                cr.restore()
            return
        self._draw_larry_now(cr)

    def _draw_larry_now(self, cr):
        x, y = self.larry_pos()
        airborne = self.mode == "drag" or (self.mode == "free" and not self.platform)
        if airborne and self.fall_sprites:   # arms up, wobbling
            t = time.monotonic()
            side = 0 if self.dir > 0 else 1
            sprite = self.fall_sprites[side]
            if self.mode == "drag":
                tilt = math.sin(t * 7) * 0.14
                if self.held_sprites:     # held: his little legs waddle
                    sprite = self.held_sprites[int(t * 11) % len(self.held_sprites)][side]
            else:
                tilt = max(-0.5, min(0.5, self.vx / 1500)) + math.sin(t * 15) * 0.09
            fh = sprites.logical_size(sprite)[1]   # hooves where his feet are, arms reaching up
            sprites.draw_centered(cr, sprite, x + self.lw / 2, y + self.lh - fh / 2 + 2, tilt)
            return
        if self.ride:
            self.draw_ride(cr, x, y, time.monotonic())
            return
        tilt, bob, squash = self.anim.pose(self.phase, self.walking)
        tilt *= self.dir              # "forward" is whichever way he's facing
        if self.mode == "drag":
            tilt, bob, squash = math.radians(-8 * self.dir), 0, 0
        elif self.mode == "free" and not self.platform:
            tilt, bob, squash = max(-0.5, min(0.5, self.vx / 1500)), 0, 0
        side = 0 if self.dir > 0 else 1
        sprite, extra, t = self.sprites[side], None, time.monotonic()
        if (self.mode == "drag" or (self.mode == "free" and not self.platform)) and "dangle0" in self.poses:
            n = sum(1 for k in self.poses if k.startswith("dangle"))   # held or flying: legs paddle
            sprite = self.poses[f"dangle{int(t * 11) % n}"][side]
        if self.being_petted(t) and self.pettable():
            self.draw_petted(cr, x, y, side, t)
            return
        r = self.reaction
        if r:
            age = t - r["start"]
            if r["mood"] == "happy":   # a few hops, happy eyes
                hop = abs(math.sin(age * math.pi * 2.4)) if age < 1.7 else 0
                tilt, bob, squash = 0.12 * math.sin(age * 9) * hop, hop * self.lh * 0.32, -0.08 * hop
            else:                      # slumps, a little shake of the head
                droop = min(age / 0.5, 1)
                tilt, bob, squash = 0.06 * math.sin(age * 7) * max(0, 1 - age / 1.6), 0, 0.07 * droop
            if "eyeless" in self.poses:
                sprite, extra = self.poses["eyeless"][side], self.draw_mood_eyes
            sprites.draw_pet(cr, sprite, x + self.lw / 2, y + self.lh, tilt, bob, squash, extra)
            self.draw_reaction(cr, x, y - bob, age, r)
            return
        if self.act == "dance":
            tilt, bob, squash, legs = self.dance_pose(t)
            if legs is not None:
                sprite = self.poses[f"dangle{legs}"][side]
            sprites.draw_pet(cr, sprite, x + self.lw / 2, y + self.lh, tilt, bob, squash)
            if self.notes:
                self.draw_notes(cr, x, y - bob * 0.3, t)
            return
        if self.act == "type":
            if self.typing_sprites:      # Larry: on his butt, keyboard on his lap
                sprite = self.typing_sprites[int(t * 9) % len(self.typing_sprites)][side]
                sprites.draw_pet(cr, sprite, x + self.lw / 2, y + self.lh, 0, 0, 0)
            else:                        # anyone else: a little keyboard in front of them
                sprites.draw_pet(cr, sprite, x + self.lw / 2, y + self.lh, 0, abs(math.sin(t * 9)) * 1.5, 0)
                self.draw_keyboard(cr, x + self.lw * (0.75 if self.dir > 0 else 0.25), y + self.lh, t)
            return
        if self.act == "sleep":
            sprite = self.poses.get("sleep", self.sprites)[side]
            tilt, bob, squash = 0, 0, 0.03 * math.sin(t * 2.2)   # slow breathing
        elif self.act == "sit" and "sit" in self.poses:
            sprite = self.poses["sit"][side]
            tilt, bob, squash = 0, 0, 0.012 * math.sin(t * 2.6)
        elif self.watching and "eyeless" in self.poses:
            sprite, extra = self.poses["eyeless"][side], self.draw_pupils
        sprites.draw_pet(cr, sprite, x + self.lw / 2, y + self.lh, tilt, bob, squash, extra)
        if self.act == "sleep":
            self.draw_zzz(cr, x, y, t)

    def draw_pupils(self, cr):
        """Larry's eyes, looking at the cursor (drawn in the eyeless sprite's coordinates)."""
        w = sprites.logical_size(self.poses["eyeless"][0])[0]
        x, y = self.larry_pos()
        sx = x + self.lw / 2 - w / 2          # sprite's left edge on screen (near enough: no tilt while watching)
        sy = y + self.lh - sprites.logical_size(self.poses["eyeless"][0])[1]
        big = max(e[2] for e in self.poses["eyes"])
        reach = max(big * 0.45, 1.1)
        cr.set_source_rgb(0, 0, 0)
        for ex, ey, rx, ry in self.poses["eyes"]:
            if self.dir < 0:
                ex = w - ex
            dx, dy = (self.cursor[0] - (sx + ex), self.cursor[1] - (sy + ey)) if self.cursor else (0, 0)
            d = math.hypot(dx, dy) or 1
            k = reach * rx / big * min(1, d / 40)
            cr.save()
            cr.translate(ex + dx / d * k, ey + dy / d * k)
            cr.scale(max(rx, 0.6), max(ry, 0.6))
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
            cr.fill()

    def draw_mood_eyes(self, cr):
        """Happy ^ ^ eyes, or sad droopy ones, where Larry's eyes are."""
        w = sprites.logical_size(self.poses["eyeless"][0])[0]
        happy = not self.reaction or self.reaction["mood"] == "happy"   # (being petted: happy)
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for ex, ey, rx, ry in self.poses["eyes"]:
            if self.dir < 0:
                ex = w - ex
            r = max(rx, 0.9) * 1.2
            cr.set_line_width(max(0.9, r * 0.55))
            cr.new_path()
            if happy:
                cr.arc(ex, ey + r * 0.5, r, math.pi * 1.15, math.pi * 1.85)    # ∩
            else:
                cr.arc(ex, ey - r * 0.6, r, math.pi * 0.2, math.pi * 0.8)      # ∪, eyes cast down
            cr.stroke()

    def draw_reaction(self, cr, x, y, age, r):
        """Hearts (or a sweat drop) and the speech bubble above him."""
        top = y + self.lh * 0.1
        hx = x + self.lw * (0.7 if self.dir > 0 else 0.3)
        fade = min(1, (r["until"] - time.monotonic()) / 0.4)
        cr.save()
        if r["mood"] == "happy":
            for i in range(4):
                p = (age * 0.7 + i * 0.27) % 1
                if age < i * 0.25:
                    continue
                s = self.lh * (0.09 + 0.05 * math.sin(p * math.pi))
                hxp = hx + (i - 1.5) * self.lh * 0.22 + math.sin(p * 7 + i) * 3
                hyp = top - p * self.lh * 0.9
                self.heart(cr, hxp, hyp, s, (0.95, 0.33, 0.45, math.sin(p * math.pi) * fade))
        else:
            dx, dy = x + self.lw * (0.9 if self.dir > 0 else 0.1), top + self.lh * 0.1 + min(age, 1.5) * 3
            s = self.lh * 0.09
            cr.move_to(dx, dy - s * 1.8)
            cr.curve_to(dx + s * 1.2, dy - s * 0.2, dx + s, dy + s, dx, dy + s)
            cr.curve_to(dx - s, dy + s, dx - s * 1.2, dy - s * 0.2, dx, dy - s * 1.8)
            cr.set_source_rgba(0.45, 0.72, 1, 0.9 * fade)
            cr.fill_preserve()
            cr.set_source_rgba(0.1, 0.15, 0.3, 0.8 * fade)
            cr.set_line_width(1)
            cr.stroke()
        if r["text"]:
            self.bubble(cr, x + self.lw / 2, top - self.lh * 0.55, r["text"], fade * min(1, age / 0.2))
        cr.restore()

    @staticmethod
    def heart(cr, x, y, s, rgba):
        cr.move_to(x, y + s)
        cr.curve_to(x - s * 2, y - s * 0.4, x - s, y - s * 1.8, x, y - s * 0.7)
        cr.curve_to(x + s, y - s * 1.8, x + s * 2, y - s * 0.4, x, y + s)
        cr.set_source_rgba(*rgba)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, rgba[3] * 0.9)
        cr.set_line_width(1)
        cr.stroke()

    def bubble(self, cr, cx, bottom, text, alpha):
        """A rounded speech bubble whose tail points down at him, kept on screen."""
        c = self.colors
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        ext = cr.text_extents(text)
        w, h = ext.x_advance + 16, 20
        x = min(max(cx - w / 2, 4), self.W - w - 4)
        y = max(bottom - h, 4)
        rad = 8
        cr.new_path()
        cr.arc(x + w - rad, y + rad, rad, -math.pi / 2, 0)
        cr.arc(x + w - rad, y + h - rad, rad, 0, math.pi / 2)
        tx = min(max(cx, x + 10), x + w - 10)
        cr.line_to(tx + 5, y + h)
        cr.line_to(tx, y + h + 6)
        cr.line_to(tx - 5, y + h)
        cr.arc(x + rad, y + h - rad, rad, math.pi / 2, math.pi)
        cr.arc(x + rad, y + rad, rad, math.pi, math.pi * 1.5)
        cr.close_path()
        cr.set_source_rgba(*c["bg1"], 0.95 * alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*c["accent"], 0.8 * alpha)
        cr.set_line_width(1.2)
        cr.stroke()
        cr.move_to(x + 8 - ext.x_bearing, y + h / 2 - ext.y_bearing - ext.height / 2)
        cr.set_source_rgba(*c["fg"], alpha)
        cr.show_text(text)

    def draw_keyboard(self, cr, cx, bottom, t):
        """A mini keyboard on the ground, keys lighting up as they're pressed (for non-Larry pets)."""
        w, h = self.lh * 0.6, self.lh * 0.16
        x, y = cx - w / 2, bottom - h
        cr.save()
        cr.rectangle(x, y, w, h)
        cr.set_source_rgb(0.2, 0.21, 0.24)
        cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_width(1)
        cr.stroke()
        hot = int(t * 9) % 8
        for i in range(8):
            cr.rectangle(x + 1.5 + i * (w - 3) / 8, y + 1.5, (w - 3) / 8 - 1, h - 3)
            cr.set_source_rgb(*((1, 0.85, 0.4) if i == hot else (0.82, 0.83, 0.86)))
            cr.fill()
        cr.restore()

    def draw_zzz(self, cr, x, y, t):
        """Little z's drifting up from his head."""
        hx, hy = (0.72, 0.4) if "sleep" in self.poses else (0.7, 0.15)
        if self.dir < 0:
            hx = 1 - hx
        ox, oy = x + self.lw * hx, y + self.lh * hy
        cr.save()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        for i in range(3):
            p = (t * 0.45 + i / 3) % 1
            cr.set_font_size(self.lh * (0.16 + 0.16 * p))
            zx = ox + self.dir * (4 + p * self.lh * 0.35) + math.sin(p * 6 + i) * 2
            zy = oy - p * self.lh * 0.85
            a = math.sin(p * math.pi)
            cr.move_to(zx, zy)
            cr.text_path("z")
            cr.set_source_rgba(0.08, 0.08, 0.1, 0.8 * a)
            cr.set_line_width(2.4)
            cr.stroke_preserve()
            cr.set_source_rgba(1, 1, 1, a)
            cr.fill()
        cr.restore()


def main():
    GLib.set_prgname("larry")  # app id for the settings window (Hyprland floats it)
    want_settings = "--settings" in sys.argv[1:]
    # one pet at a time: the running one owns this socket; a second launch just pokes it
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind("\0larry-the-cow")
    except OSError:
        if want_settings:
            with socket.socket(socket.AF_UNIX) as c:
                c.connect("\0larry-the-cow")
                c.sendall(b"settings")
        sys.exit(0)
    sock.listen(4)
    pet = Larry()

    def on_cmd(*_):
        conn, _addr = sock.accept()
        with conn:
            cmd = conn.recv(64).strip()
            if cmd == b"settings":
                pet.open_settings()
            elif cmd == b"status":          # the Waybar module (waybar.py) asks once a second
                try:
                    conn.sendall(json.dumps(pet.status()).encode())
                except OSError:
                    pass
            elif cmd in (b"pop", b"toggle"):   # its click: pop out of the box (or poof back in)
                pet.pop()
        return True

    GLib.io_add_watch(sock.fileno(), GLib.IO_IN, on_cmd)
    if want_settings:
        pet.open_settings()
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: Gtk.main_quit() or False)
    try:
        Gtk.main()
    finally:
        pet.music.close()
        waybar.blank()                         # the Waybar icon goes away with the pet


if __name__ == "__main__":
    main()
