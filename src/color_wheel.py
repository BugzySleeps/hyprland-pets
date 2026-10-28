"""A colour wheel: drag round the ring for the hue, inside the square for how strong and how light
it is. Every colour there is, not a palette."""
import colorsys
import math

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402


def to_hex(rgb):
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in rgb)


def from_hex(s):
    s = s.strip().lstrip("#")
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


class ColorWheel(Gtk.DrawingArea):
    RING = 0.17          # ring thickness, as a share of the radius

    def __init__(self, on_change, on_done, size=232):
        """on_change(rgb) while dragging; on_done(rgb) when you let go."""
        super().__init__()
        self.on_change, self.on_done = on_change, on_done
        self.set_size_request(size, size)
        self.h, self.s, self.v = 0.0, 0.0, 1.0
        self.drag = None              # "ring" | "square" while dragging
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-release-event", self.on_release)
        self.ring_cache = None

    # ── value ───────────────────────────────────────────────────────────────
    def set_rgb(self, rgb):
        h, s, v = colorsys.rgb_to_hsv(*rgb)
        if s > 0.001 and v > 0.001:   # greys and black have no hue: keep the one we had
            self.h = h
        if v > 0.001:
            self.s = s
        self.v = v
        self.queue_draw()

    def rgb(self):
        return colorsys.hsv_to_rgb(self.h, self.s, self.v)

    # ── geometry ────────────────────────────────────────────────────────────
    def geom(self):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        r = min(w, h) / 2 - 4
        inner = r * (1 - self.RING)
        half = inner * 0.66              # the square fits inside the ring with a gap
        return w / 2, h / 2, r, inner, half

    def on_draw(self, _w, cr):
        cx, cy, r, inner, half = self.geom()
        # hue ring (cached: it never changes)
        key = (round(r), round(inner))
        if not self.ring_cache or self.ring_cache[0] != key:
            size = int(r * 2 + 8)
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
            c2 = cairo.Context(surf)
            c2.translate(size / 2, size / 2)
            steps = 360
            for i in range(steps):
                a0 = i / steps * 2 * math.pi - math.pi / 2
                a1 = (i + 1.5) / steps * 2 * math.pi - math.pi / 2
                c2.new_path()
                c2.arc(0, 0, r, a0, a1)
                c2.arc_negative(0, 0, inner, a1, a0)
                c2.close_path()
                c2.set_source_rgb(*colorsys.hsv_to_rgb(i / steps, 1, 1))
                c2.fill()
            self.ring_cache = (key, surf, size)
        _k, surf, size = self.ring_cache
        cr.set_source_surface(surf, cx - size / 2, cy - size / 2)
        cr.paint()
        # saturation / value square for this hue
        x0, y0, side = cx - half, cy - half, half * 2
        rr = 10
        cr.new_sub_path()
        cr.arc(x0 + side - rr, y0 + rr, rr, -math.pi / 2, 0)
        cr.arc(x0 + side - rr, y0 + side - rr, rr, 0, math.pi / 2)
        cr.arc(x0 + rr, y0 + side - rr, rr, math.pi / 2, math.pi)
        cr.arc(x0 + rr, y0 + rr, rr, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.save()
        cr.clip()
        g = cairo.LinearGradient(x0, 0, x0 + side, 0)
        g.add_color_stop_rgb(0, 1, 1, 1)
        g.add_color_stop_rgb(1, *colorsys.hsv_to_rgb(self.h, 1, 1))
        cr.set_source(g)
        cr.paint()
        g = cairo.LinearGradient(0, y0, 0, y0 + side)
        g.add_color_stop_rgba(0, 0, 0, 0, 0)
        g.add_color_stop_rgba(1, 0, 0, 0, 1)
        cr.set_source(g)
        cr.paint()
        cr.restore()
        # knobs
        a = self.h * 2 * math.pi - math.pi / 2
        mid = (r + inner) / 2
        self.knob(cr, cx + math.cos(a) * mid, cy + math.sin(a) * mid, (r - inner) * 0.42,
                  colorsys.hsv_to_rgb(self.h, 1, 1))
        self.knob(cr, x0 + self.s * side, y0 + (1 - self.v) * side, 9, self.rgb())

    @staticmethod
    def knob(cr, x, y, rad, fill):
        cr.new_path()
        cr.arc(x, y + 1.5, rad + 3, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.3)
        cr.fill()
        cr.arc(x, y, rad + 2.5, 0, 2 * math.pi)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()
        cr.arc(x, y, rad, 0, 2 * math.pi)
        cr.set_source_rgb(*fill)
        cr.fill()

    # ── input ───────────────────────────────────────────────────────────────
    def pick(self, x, y):
        cx, cy, r, inner, half = self.geom()
        if self.drag == "ring":
            self.h = (math.atan2(y - cy, x - cx) + math.pi / 2) / (2 * math.pi) % 1
        elif self.drag == "square":
            self.s = max(0.0, min(1.0, (x - (cx - half)) / (2 * half)))
            self.v = 1 - max(0.0, min(1.0, (y - (cy - half)) / (2 * half)))
        self.queue_draw()
        self.on_change(self.rgb())

    def on_press(self, _w, ev):
        if ev.button != 1:
            return False
        cx, cy, r, inner, half = self.geom()
        d = math.hypot(ev.x - cx, ev.y - cy)
        if inner - 6 <= d <= r + 6:
            self.drag = "ring"
        elif abs(ev.x - cx) <= half + 8 and abs(ev.y - cy) <= half + 8:
            self.drag = "square"
        else:
            return False
        self.pick(ev.x, ev.y)
        return True

    def on_motion(self, _w, ev):
        if self.drag:
            self.pick(ev.x, ev.y)
        return bool(self.drag)

    def on_release(self, _w, ev):
        if self.drag and ev.button == 1:
            self.drag = None
            self.on_done(self.rgb())
            return True
        return False
