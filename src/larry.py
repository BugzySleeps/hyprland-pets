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
import json
import math
import os
import random
import socket
import sys
import time
import tomllib
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

import config  # noqa: E402
import anim  # noqa: E402
import scene  # noqa: E402
import sprites  # noqa: E402

RICE = Path.home() / ".config/rice"

BOX_W, BOX_H = 250, 92          # the pull-down box (grows to fit a big pet)
TAB_W, TAB_H = 46, 12           # the handle hanging under it
FPS = 30

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


def theme_colors():
    try:
        name = (RICE / "current").read_text().strip()
        with open(RICE / "themes" / name / "theme.toml", "rb") as f:
            c = tomllib.load(f).get("colors", {})
    except (OSError, tomllib.TOMLDecodeError):
        c = {}
    return {
        "bg0": rgb(c.get("bg0"), (0.07, 0.07, 0.09)),
        "bg1": rgb(c.get("bg1"), (0.1, 0.1, 0.12)),
        "accent": rgb(c.get("accent"), (0.8, 0.8, 0.85)),
        "accent2": rgb(c.get("accent2"), (0.5, 0.7, 0.4)),
        "fg": rgb(c.get("fg"), (0.9, 0.9, 0.9)),
    }



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
        self.sprites = sprites.load(self.cfg)
        self.fall_sprites = self.load_fall(self.cfg)
        self.lw, self.lh = self.sprites[0].get_width(), self.sprites[0].get_height()
        self.anim = anim.Compiled(self.cfg["animation"])
        self.walking = False
        self.settings = None
        self.box_cache = scene.BoxCache()
        self.colors = theme_colors()
        self.theme_mtime = self._theme_mtime()
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
        self.clients = {}         # address -> Hyprland client, from the last refresh
        self.mon = None           # the monitor we're drawn on
        self.room = None          # address of the terminal he lives in (dragged into it), or None
        self.room_rect = None     # its inside: (left, top, right, bottom) on screen
        self.room_shown = True    # False while that terminal is on a workspace you're not looking at
        self.room_covers = []     # windows stacked above his terminal: he's hidden behind them
        self.poller = None
        self.drag_off = (0, 0)
        self.drag_hist = []

        self.last = time.monotonic()
        self.dirty = []
        self.ticking = None
        self.input_key = None

        self.listen_events()
        GLib.timeout_add_seconds(2, self.check_theme)
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

    @staticmethod
    def inside(p, r, pad=0):
        return p and r[0] - pad <= p[0] <= r[0] + r[2] + pad and r[1] - pad <= p[1] <= r[1] + r[3] + pad

    def hovering(self):
        if self.inside(self.pointer, self.to_edge(self.tab_rect(), 2)):
            return True
        return self.open > 0.05 and self.inside(self.pointer, self.to_edge(self.visible_box()))

    # ── input region: only the tab/box and Larry catch the mouse ───────────
    def update_input(self):
        if self.mode == "drag":
            rects = [(0, 0, self.W, self.H)]  # keep getting motion wherever he's dragged
        else:
            rects = [self.to_edge(self.tab_rect(), 5)]
            if self.open > 0.05:
                rects.append(self.visible_box())
            if self.mode == "free" and (not self.room or self.room_shown):
                rects.append(tuple(round(v) for v in self.larry_rect()))
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
        if ev.button != 1:
            return
        lx, ly = self.larry_pos()
        on_larry = self.inside(p, self.larry_rect()) and (self.mode == "free" or self.open > 0.6)
        if on_larry:
            self.x, self.y = lx, ly
            self.drag_off = (ev.x - lx, ev.y - ly)
            self.drag_hist = [(ev.time, ev.x, ev.y)]
            self.mode, self.platform = "drag", None
            self.leave_room()
        elif self.inside(p, self.tab_rect(), 4):
            self.pinned = not self.pinned
        self.update_input()
        self.wake()

    def on_release(self, _w, ev):
        if ev.button != 1 or self.mode != "drag":
            return
        self.pointer = (ev.x, ev.y)
        bx, by, _, _, _ = self.box_geom()
        if self.open > 0.5 and self.inside(self.pointer, self.visible_box()):
            self.damage_larry()
            self.mode = "box"
            self.bx = min(max(self.x - bx, 6), self.box_w - self.lw - 6)
        elif (term := self.terminal_at(self.pointer)):
            self.mode, self.platform = "free", None
            self.room, self.room_rect = term, None
            self.vx = self.vy = 0          # set down gently, then he drops to the bottom
            self.update_room()
            self.restart_poller()
        else:
            # throw: velocity from the last few motion samples
            (t0, x0, y0), (t1, x1, y1) = self.drag_hist[0], self.drag_hist[-1]
            dt = max((t1 - t0) / 1000, 1e-3)
            cap = 1400 * max(self.anim.throw, 0.01)
            k = self.anim.throw
            self.vx = max(-cap, min(cap, k * (x1 - x0) / dt)) if t1 > t0 else 0
            self.vy = max(-cap, min(cap, k * (y1 - y0) / dt)) if t1 > t0 else 0
            self.mode = "free"
            self.refresh_platforms()
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
        plats = []
        clients = hypr("clients") or []
        self.clients = {c["address"]: c for c in clients}
        if self.room:
            self.update_room()
        for c in clients:
            if c["workspace"]["id"] != ws or not c.get("mapped", True) or c.get("hidden"):
                continue
            x, y = c["at"][0] - mon["x"], c["at"][1] - mon["y"]
            w, _h = c["size"]
            if x + w <= 0 or x >= self.W or y <= 0 or y >= self.H:
                continue  # off screen (infinite desktop) or touching the top edge
            plats.append((c["address"], max(x, 0), min(x + w, self.W), y))
        self.platforms = plats

    def poll_platforms(self):
        if self.mode != "free":
            self.poller = None
            return False
        self.refresh_platforms()
        return True

    def restart_poller(self):
        """Poll faster while he lives in a terminal, so he keeps up when you move it."""
        if self.poller:
            GLib.source_remove(self.poller)
            self.poller = None
        self.wake()

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

    def open_settings(self):
        if self.settings:
            self.settings.present()
            return
        import settings
        self.settings = settings.Settings(self)

    def set_config(self, cfg):
        """Swap in new settings live (called by the settings window)."""
        self.anim = anim.Compiled(cfg["animation"])
        sprite_keys = ("image", "size", "faces_left", "remove_bg", "outline", "accessories")
        if any(cfg[k] != self.cfg[k] for k in ("image", "size", "outline", "fall_image")):
            self.fall_sprites = self.load_fall(cfg)
        if all(cfg[k] == self.cfg[k] for k in sprite_keys):
            new = self.sprites
        else:
            try:
                new = sprites.load(cfg)
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
        if self.settings and self.settings.cfg != cfg:
            self.settings.sync(cfg)

    # ── theme ───────────────────────────────────────────────────────────────
    def _theme_mtime(self):
        try:
            return (RICE / "current").stat().st_mtime
        except OSError:
            return 0

    def check_theme(self):
        """Every 2 s: pick up a rice theme switch, or a hand edit of the config file."""
        m = self._theme_mtime()
        if m != self.theme_mtime:
            self.theme_mtime = m
            self.colors = theme_colors()
            self.queue_draw()
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
            self.poller = GLib.timeout_add(120 if self.room else 300, self.poll_platforms)

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
        self.damage(*self.larry_rect(), pad=pad)

    def tick(self):
        now = time.monotonic()
        dt = min(now - self.last, 0.1)
        self.last = now

        # box open/close
        if self.hovering() or self.mode == "drag":
            self.hover_until = now + 0.45
        want = 1.0 if (self.pinned or now < self.hover_until) else 0.0
        if self.open != want:
            self.damage_box()
            if self.mode == "box":
                self.damage_larry()
            step = dt / self.anim.open_time
            self.open = min(want, self.open + step) if want > self.open else max(want, self.open - step)
            self.damage_box()

        if self.mode == "box" and self.open > 0:
            self.damage_larry()
            self.walk_box(dt)
            self.damage_larry()
        elif self.mode == "free":
            self.damage_larry()
            self.step_free(dt)
            self.damage_larry()
        elif self.mode == "drag" and self.fall_sprites:
            self.damage_larry()   # he flails while you hold him

        for r in self.dirty:
            self.queue_draw_area(*r)
        self.dirty.clear()
        self.update_input()

        busy = self.open != want or self.open > 0 or self.mode in ("free", "drag")
        if not busy:
            self.ticking = None
            return False
        return True

    def wander(self, dt, speed):
        """Shared walking brain: occasional stops and turns. Returns dx for this frame."""
        a = self.anim
        if self.pause > 0:
            self.pause -= dt
            self.walking, self.phase = False, 0
            return 0
        if a.stop_every and random.random() < dt / a.stop_every:   # stop and look around
            self.pause = random.uniform(a.stop_min, max(a.stop_min, a.stop_max))
            if random.random() < a.turn_chance / 100:
                self.dir *= -1
            return 0
        self.walking = True
        self.phase += speed * dt / a.step_length
        return self.dir * speed * dt

    def walk_box(self, dt):
        self.bx += self.wander(dt, self.anim.walk_speed)
        lo, hi = 6, self.box_w - self.lw - 6
        if self.bx <= lo or self.bx >= hi:
            self.bx = min(max(self.bx, lo), hi)
            self.dir = 1 if self.bx <= lo else -1

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
            if self.x <= lo or self.x >= hi:
                self.x = min(max(self.x, lo), hi)
                self.dir = 1 if self.x <= lo else -1
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
            lo, hi = max(left - self.lw / 2, 0), min(right - self.lw / 2, self.W - self.lw)
            if self.x <= lo or self.x >= hi:
                self.x = min(max(self.x, lo), hi)
                self.dir = 1 if self.x <= lo else -1
            return

        # airborne
        self.walking = False
        self.vy += self.anim.gravity * dt
        self.vx *= 0.995
        feet_before = self.y + self.lh - 3
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < 0 or self.x > self.W - self.lw:      # bounce off the screen sides
            self.x = min(max(self.x, 0), self.W - self.lw)
            self.vx = -self.vx * self.anim.bounce
        if self.y < 0 and self.vy < 0:
            self.y, self.vy = 0, 0
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
            pet = self.draw_larry if self.mode == "box" else None
            cr.save()
            if stretch != 1:  # overshoot: stretch the box (and the pet in it) away from the edge
                ax, ay = {"top": (0, 0), "bottom": (0, self.H), "left": (0, 0), "right": (self.W, 0)}[edge]
                cr.translate(ax, ay)
                cr.scale(*((1, stretch) if edge in ("top", "bottom") else (stretch, 1)))
                cr.translate(-ax, -ay)
            self.box_cache.paint(cr, bx, by, bw, bh, c, self.cfg["box"], pet, edge)
            cr.restore()

        # the tab: rounded on the side away from the edge, grip dots along it
        cr.save()
        cr.translate(tx, ty)
        scene.box_path(cr, tw, th, 6, edge)
        cr.restore()
        cr.set_source_rgba(*c["bg1"], 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(*c["accent"], 0.55)
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgba(*c["accent"], 0.9 if self.pinned else 0.6)
        for i in (-6, 0, 6):
            dx, dy = (i, 0) if edge in ("top", "bottom") else (0, i)
            cr.arc(tx + tw / 2 + dx, ty + th / 2 + dy, 1.4, 0, 2 * math.pi)
            cr.fill()

        if self.mode != "box":
            self.draw_larry(cr)

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
        x, y = self.larry_pos()
        airborne = self.mode == "drag" or (self.mode == "free" and not self.platform)
        if airborne and self.fall_sprites:   # arms up, wobbling
            t = time.monotonic()
            if self.mode == "drag":
                tilt = math.sin(t * 7) * 0.14
            else:
                tilt = max(-0.5, min(0.5, self.vx / 1500)) + math.sin(t * 15) * 0.09
            sprite = self.fall_sprites[0 if self.dir > 0 else 1]
            fh = sprites.logical_size(sprite)[1]   # hooves where his feet are, arms reaching up
            sprites.draw_centered(cr, sprite, x + self.lw / 2, y + self.lh - fh / 2 + 2, tilt)
            return
        tilt, bob, squash = self.anim.pose(self.phase, self.walking)
        tilt *= self.dir              # "forward" is whichever way he's facing
        if self.mode == "drag":
            tilt, bob, squash = math.radians(-8 * self.dir), 0, 0
        elif self.mode == "free" and not self.platform:
            tilt, bob, squash = max(-0.5, min(0.5, self.vx / 1500)), 0, 0
        sprites.draw_pet(cr, self.sprites[0 if self.dir > 0 else 1], x + self.lw / 2, y + self.lh, tilt, bob, squash)


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
            if conn.recv(64).strip() == b"settings":
                pet.open_settings()
        return True

    GLib.io_add_watch(sock.fileno(), GLib.IO_IN, on_cmd)
    if want_settings:
        pet.open_settings()
    Gtk.main()


if __name__ == "__main__":
    main()
