"""A graph you shape by dragging points: drag to move, double-click to add, right-click to delete."""
import math

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

import anim  # noqa: E402

PAD = 12
HIT = 9


class CurveEditor(Gtk.DrawingArea):
    def __init__(self, get_points, on_change, colors, playhead=lambda key: None, sound=lambda name, frac=None: None):
        """get_points(key) -> the live [[x, y], ...] list to edit in place; on_change() after edits;
        playhead(key) -> x in 0..1 to mark (or None); sound(name, frac) for feedback."""
        super().__init__()
        self.get_points, self.on_change, self.colors, self.playhead = get_points, on_change, colors, playhead
        self.sound = sound
        self.key = "tilt"
        self.drag = self.hover = None
        self.set_size_request(-1, 170)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("leave-notify-event", self.on_leave)

    def set_key(self, key):
        self.key = key
        self.drag = self.hover = None
        self.queue_draw()

    # ── geometry ────────────────────────────────────────────────────────────
    @property
    def spec(self):
        return anim.CURVES[self.key]

    @property
    def points(self):
        return self.get_points(self.key)

    def to_px(self, x, y):
        lo, hi = self.spec[2]
        w, h = self.get_allocated_width(), self.get_allocated_height()
        return PAD + x * (w - 2 * PAD), PAD + (hi - y) / (hi - lo) * (h - 2 * PAD)

    def from_px(self, px, py):
        lo, hi = self.spec[2]
        w, h = self.get_allocated_width(), self.get_allocated_height()
        x = (px - PAD) / max(w - 2 * PAD, 1)
        y = hi - (py - PAD) / max(h - 2 * PAD, 1) * (hi - lo)
        return min(max(x, 0), 1), min(max(y, lo), hi)

    def hit(self, px, py):
        best = None
        for i, (x, y) in enumerate(self.points):
            qx, qy = self.to_px(x, y)
            d = math.hypot(qx - px, qy - py)
            if d <= HIT and (best is None or d < best[0]):
                best = (d, i)
        return best and best[1]

    def locked(self, i):
        """The open curve's ends are pinned to shut (0,0) and open (1,1)."""
        return self.key == "open" and i in (0, len(self.points) - 1)

    # ── editing ─────────────────────────────────────────────────────────────
    def on_press(self, _w, ev):
        i = self.hit(ev.x, ev.y)
        pts = self.points
        if ev.button == 1 and ev.type == Gdk.EventType._2BUTTON_PRESS and i is None:
            x, y = self.from_px(ev.x, ev.y)
            if 0.01 < x < 0.99:
                pts.append([round(x, 4), round(y, 4)])
                pts.sort()
                self.drag = next(j for j, p in enumerate(pts) if p[0] == round(x, 4))
                self.sound("pop_up")
                self.on_change()
        elif ev.button == 1 and i is not None and not self.locked(i):
            self.drag = i
            self.sound("grab")
        elif ev.button == 3 and i is not None and 0 < i < len(pts) - 1:
            del pts[i]
            self.hover = None
            self.sound("pop_down")
            self.on_change()
        self.queue_draw()

    def on_motion(self, _w, ev):
        if self.drag is None:
            h = self.hit(ev.x, ev.y)
            if h != self.hover:
                self.hover = h
                self.queue_draw()
            return
        pts, i = self.points, self.drag
        x, y = self.from_px(ev.x, ev.y)
        last = len(pts) - 1
        if i in (0, last):
            x = float(i == last)                     # ends stay on the left/right edge
        else:
            x = min(max(x, pts[i - 1][0] + 0.01), pts[i + 1][0] - 0.01)
        pts[i] = [round(x, 4), round(y, 4)]
        if self.spec[1] and i in (0, last):        # looping curve: both ends move together
            pts[last - i] = [float(i != last), round(y, 4)]
        lo, hi = self.spec[2]
        self.sound("tick", (y - lo) / (hi - lo))   # pitch follows the point's height
        self.on_change()
        self.queue_draw()

    def on_release(self, _w, ev):
        if self.drag is not None:
            self.drag = None
            self.on_change()
            self.queue_draw()

    def on_leave(self, *_):
        if self.drag is None and self.hover is not None:
            self.hover = None
            self.queue_draw()

    # ── drawing ─────────────────────────────────────────────────────────────
    def on_draw(self, _w, cr):
        c = self.colors()
        w, h = self.get_allocated_width(), self.get_allocated_height()
        _label, cyclic, (lo, hi), _help, _default = self.spec

        r = 18
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgb(*[a + (b - a) * 0.05 for a, b in zip(c["bg1"], c["fg"])])
        cr.fill()

        # grid: quarter steps across, the zero line (and the "fully open" line)
        cr.set_line_width(1)
        cr.set_source_rgba(*c["fg"], 0.08)
        for q in (0.25, 0.5, 0.75):
            x, _ = self.to_px(q, 0)
            cr.move_to(round(x) + 0.5, PAD)
            cr.line_to(round(x) + 0.5, h - PAD)
        cr.stroke()
        for level, alpha in ((0, 0.3), (1, 0.3 if self.key == "open" else 0)):
            if alpha and lo <= level <= hi:
                _, y = self.to_px(0, level)
                cr.set_source_rgba(*c["fg"], alpha)
                cr.set_dash([3, 3] if level else [])
                cr.move_to(PAD, round(y) + 0.5)
                cr.line_to(w - PAD, round(y) + 0.5)
                cr.stroke()
        cr.set_dash([])

        # the curve, with a soft fill down to zero
        lut = anim.sample(self.points, cyclic, 160)
        pts = [self.to_px(j / 160, v) for j, v in enumerate(lut)]
        _, zero = self.to_px(0, min(max(0, lo), hi))
        cr.move_to(pts[0][0], zero)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], zero)
        cr.close_path()
        cr.set_source_rgba(*c["accent2"], 0.14)
        cr.fill()
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgb(*c["accent2"])
        cr.set_line_width(2)
        cr.stroke()

        # playhead: where the preview is in this curve right now
        ph = self.playhead(self.key)
        if ph is not None:
            curve = anim.Curve(self.points, cyclic)
            x, y = self.to_px(ph, curve(ph))
            cr.set_source_rgba(*c["fg"], 0.25)
            cr.set_line_width(1)
            cr.move_to(round(x) + 0.5, PAD)
            cr.line_to(round(x) + 0.5, h - PAD)
            cr.stroke()
            cr.set_source_rgb(*c["fg"])
            cr.arc(x, y, 3, 0, 2 * math.pi)
            cr.fill()

        # control points
        for i, (px, py) in enumerate(self.points):
            x, y = self.to_px(px, py)
            active = i in (self.drag, self.hover)
            cr.arc(x, y, 6 if active else 4.5, 0, 2 * math.pi)
            if self.locked(i):
                cr.set_source_rgb(*c["bg1"])
                cr.fill_preserve()
                cr.set_source_rgba(*c["fg"], 0.6)
                cr.set_line_width(1.5)
                cr.stroke()
            else:
                cr.set_source_rgb(*(c["accent"] if active else c["fg"]))
                cr.fill_preserve()
                cr.set_source_rgb(*c["bg0"])
                cr.set_line_width(1.5)
                cr.stroke()
