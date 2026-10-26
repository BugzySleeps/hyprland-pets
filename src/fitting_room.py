"""The big pet you dress up: click an accessory to pick it, drag it around, drag the corner knob to
resize, the top knob to rotate; Ctrl+scroll resizes, Ctrl+Shift+scroll rotates, arrow keys nudge."""
import math

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

import accessories  # noqa: E402
import sprites  # noqa: E402

RENDER_H = 300    # pet base image resolution (px tall)
KNOB = 7          # handle radius
ROT_ARM = 26      # how far the rotate knob sits above the box
SNAP = 15         # rotation snaps to multiples of this when close (or always with Shift)


class FittingRoom(Gtk.DrawingArea):
    def __init__(self, get_cfg, colors, on_change, on_select, sound):
        """get_cfg() -> the live settings (accessories edited in place); on_change() after any edit;
        on_select(id or None); sound(name, frac=None)."""
        super().__init__()
        self.get_cfg, self.colors, self.on_change, self.on_select, self.sound = get_cfg, colors, on_change, on_select, sound
        self.sel = self.hover = None
        self.drag = None              # (mode, start pointer, start item copy)
        self.base_key = self.base = None
        self.set_can_focus(True)
        self.set_size_request(-1, 340)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        for sig, cb in (("draw", self.on_draw), ("button-press-event", self.on_press),
                        ("button-release-event", self.on_release), ("motion-notify-event", self.on_motion),
                        ("leave-notify-event", self.on_leave), ("scroll-event", self.on_scroll),
                        ("key-press-event", self.on_key)):
            self.connect(sig, cb)

    @property
    def items(self):
        return self.get_cfg()["accessories"]

    def select(self, acc_id, notify=True):
        self.sel = acc_id if acc_id in self.items else None
        self.queue_draw()
        if notify:
            self.on_select(self.sel)

    # ── geometry ────────────────────────────────────────────────────────────
    def pet_surface(self):
        cfg = self.get_cfg()
        key = (cfg["image"], cfg["faces_left"], cfg["remove_bg"])
        if key != self.base_key:
            self.base_key = key
            try:
                self.base = cairo.ImageSurface.create_from_png(str(sprites.base(cfg, RENDER_H)))
            except Exception:
                self.base = None
        return self.base

    def view(self):
        """(ox, oy, pw, ph): where the pet is drawn in the widget."""
        w, h = self.get_allocated_width(), self.get_allocated_height()
        base = self.pet_surface()
        bw, bh = (base.get_width(), base.get_height()) if base else (1, 1)
        ph = h * 0.56
        pw = ph * bw / bh
        if pw > w * 0.6:
            pw = w * 0.6
            ph = pw * bh / bw
        return (w - pw) / 2, h * 0.84 - ph, pw, ph

    def screen_corners(self, acc_id):
        ox, oy, pw, ph = self.view()
        return [(ox + x, oy + y) for x, y in accessories.corners(acc_id, self.items[acc_id], pw, ph)]

    def center(self, acc_id):
        ox, oy, pw, ph = self.view()
        it = self.items[acc_id]
        return ox + it["x"] * pw, oy + it["y"] * ph

    def knobs(self, acc_id):
        """(resize knob, rotate knob) positions."""
        c = self.screen_corners(acc_id)
        cx, cy = self.center(acc_id)
        tx, ty = (c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2
        d = math.hypot(tx - cx, ty - cy) or 1
        return c[2], (tx + (tx - cx) / d * ROT_ARM, ty + (ty - cy) / d * ROT_ARM)

    def hit(self, px, py):
        ox, oy, pw, ph = self.view()
        order = [k for k, it in self.items.items() if not it["behind"]][::-1] + \
                [k for k, it in self.items.items() if it["behind"]][::-1]
        if self.sel in order:          # the picked one wins when they overlap
            order.remove(self.sel)
            order.insert(0, self.sel)
        for acc_id in order:
            it = self.items[acc_id]
            s = it["scale"] * ph
            dx, dy = px - (ox + it["x"] * pw), py - (oy + it["y"] * ph)
            r = -math.radians(it["rotate"])
            u = (dx * math.cos(r) - dy * math.sin(r)) / s
            v = (dx * math.sin(r) + dy * math.cos(r)) / s
            m = 5 / s
            if abs(u) <= 0.5 + m and abs(v) <= accessories.aspect(acc_id) / 2 + m:
                return acc_id
        return None

    def knob_at(self, px, py):
        if self.sel not in self.items:
            return None
        rs, rot = self.knobs(self.sel)
        if math.hypot(px - rot[0], py - rot[1]) <= KNOB + 4:
            return "rotate"
        if math.hypot(px - rs[0], py - rs[1]) <= KNOB + 4:
            return "scale"
        return None

    # ── editing ─────────────────────────────────────────────────────────────
    def changed(self):
        self.queue_draw()
        self.on_change()

    def on_press(self, _w, ev):
        self.grab_focus()
        if ev.button != 1:
            return
        knob = self.knob_at(ev.x, ev.y)
        target = self.sel if knob else self.hit(ev.x, ev.y)
        if target != self.sel:
            self.select(target)
        if target:
            self.drag = (knob or "move", (ev.x, ev.y), dict(self.items[target]))
            self.sound("grab")
        self.queue_draw()

    def on_motion(self, _w, ev):
        if not self.drag or self.sel not in self.items:
            knob = self.knob_at(ev.x, ev.y)
            hov = None if knob else self.hit(ev.x, ev.y)
            if hov != self.hover:
                self.hover = hov
                self.queue_draw()
            win = self.get_window()
            if win:
                name = "grab" if knob == "rotate" else "nwse-resize" if knob else "move" if hov else None
                win.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), name) if name else None)
            return
        mode, (sx, sy), start = self.drag
        it = self.items[self.sel]
        ox, oy, pw, ph = self.view()
        if mode == "move":
            it["x"] = round(start["x"] + (ev.x - sx) / pw, 4)
            it["y"] = round(start["y"] + (ev.y - sy) / ph, 4)
            self.sound("tick", 1 - min(max((ev.y - oy) / ph, 0), 1))
        elif mode == "scale":
            cx, cy = self.center(self.sel)
            unit = math.hypot(0.5, accessories.aspect(self.sel) / 2) * ph
            it["scale"] = round(min(max(math.hypot(ev.x - cx, ev.y - cy) / unit, accessories.SCALE_MIN),
                                    accessories.SCALE_MAX), 4)
            self.sound("tick", it["scale"] / 1.2)
        else:
            cx, cy = self.center(self.sel)
            ang = math.degrees(math.atan2(ev.y - cy, ev.x - cx)) + 90
            ang = (ang + 180) % 360 - 180
            snapped = round(ang / SNAP) * SNAP
            if ev.state & Gdk.ModifierType.SHIFT_MASK or abs(ang - snapped) < 4:
                ang = snapped
            it["rotate"] = round(ang, 1)
            self.sound("tick", (ang + 180) / 360)
        self.changed()

    def on_release(self, _w, _ev):
        if self.drag:
            self.drag = None
            self.changed()

    def on_leave(self, *_):
        if not self.drag and self.hover:
            self.hover = None
            self.queue_draw()

    def on_scroll(self, _w, ev):
        acc_id = self.sel if self.sel in self.items else None
        if not acc_id or not ev.state & Gdk.ModifierType.CONTROL_MASK:
            return False     # plain scrolling scrolls the page; Ctrl+scroll resizes, Ctrl+Shift rotates
        ok, _dx, dy = ev.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction, 0)
        if not dy:
            return True
        it = self.items[acc_id]
        if ev.state & Gdk.ModifierType.SHIFT_MASK:
            it["rotate"] = round((it["rotate"] - 5 * dy + 180) % 360 - 180, 1)
            self.sound("tick", (it["rotate"] + 180) / 360)
        else:
            it["scale"] = round(min(max(it["scale"] * 1.06 ** -dy, accessories.SCALE_MIN), accessories.SCALE_MAX), 4)
            self.sound("tick", it["scale"] / 1.2)
        self.changed()
        return True

    def on_key(self, _w, ev):
        acc_id = self.sel if self.sel in self.items else None
        if not acc_id:
            return False
        it = self.items[acc_id]
        step = 0.02 if ev.state & Gdk.ModifierType.SHIFT_MASK else 0.004
        k = Gdk.keyval_name(ev.keyval)
        moves = {"Left": ("x", -step), "Right": ("x", step), "Up": ("y", -step), "Down": ("y", step)}
        if k in moves:
            key, d = moves[k]
            it[key] = round(it[key] + d, 4)
        elif k in ("plus", "equal", "KP_Add"):
            it["scale"] = round(min(it["scale"] * 1.05, accessories.SCALE_MAX), 4)
        elif k in ("minus", "KP_Subtract"):
            it["scale"] = round(max(it["scale"] / 1.05, accessories.SCALE_MIN), 4)
        elif k in ("bracketleft", "bracketright"):
            it["rotate"] = round((it["rotate"] + (5 if k == "bracketright" else -5) + 180) % 360 - 180, 1)
        elif k == "Escape":
            self.select(None)
            return True
        else:
            return False
        self.sound("tick", 0.5)
        self.changed()
        return True

    # ── drawing ─────────────────────────────────────────────────────────────
    def on_draw(self, _w, cr):
        c = self.colors()
        w, h = self.get_allocated_width(), self.get_allocated_height()
        r = 16
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgb(0, *c["bg1"])
        g.add_color_stop_rgb(1, *[v * 0.75 for v in c["bg0"]])
        cr.set_source(g)
        cr.paint()
        spot = cairo.RadialGradient(w / 2, h * 0.5, 10, w / 2, h * 0.5, w * 0.4)
        spot.add_color_stop_rgba(0, *c["accent2"], 0.2)
        spot.add_color_stop_rgba(1, *c["accent2"], 0)
        cr.set_source(spot)
        cr.paint()

        ox, oy, pw, ph = self.view()
        # a little stage: floor line and a shadow under the feet
        cr.set_source_rgba(*c["fg"], 0.08)
        cr.rectangle(0, oy + ph, w, 1)
        cr.fill()
        cr.save()
        cr.translate(ox + pw / 2, oy + ph)
        cr.scale(pw * 0.55, 8)
        sh = cairo.RadialGradient(0, 0, 0, 0, 0, 1)
        sh.add_color_stop_rgba(0, 0, 0, 0, 0.35)
        sh.add_color_stop_rgba(1, 0, 0, 0, 0)
        cr.set_source(sh)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.fill()
        cr.restore()

        items = self.items
        cr.save()
        cr.translate(ox, oy)
        accessories.draw(cr, items, pw, ph, behind=True)
        base = self.pet_surface()
        if base:
            cr.save()
            cr.scale(pw / base.get_width(), ph / base.get_height())
            cr.set_source_surface(base, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
            cr.restore()
        accessories.draw(cr, items, pw, ph, behind=False)
        cr.restore()

        if self.hover in items and self.hover != self.sel:
            self.outline(cr, self.hover, (*c["fg"], 0.35), [4, 4])
        if self.sel in items:
            self.outline(cr, self.sel, (*c["accent2"], 0.95), [6, 4])
            (rx, ry), (tx, ty) = self.knobs(self.sel)
            corners = self.screen_corners(self.sel)
            mx, my = (corners[0][0] + corners[1][0]) / 2, (corners[0][1] + corners[1][1]) / 2
            cr.set_source_rgba(*c["accent2"], 0.8)
            cr.set_line_width(1.5)
            cr.set_dash([])
            cr.move_to(mx, my)
            cr.line_to(tx, ty)
            cr.stroke()
            for x, y in ((rx, ry), (tx, ty)):
                cr.arc(x, y, KNOB, 0, 2 * math.pi)
                cr.set_source_rgb(*c["fg"])
                cr.fill_preserve()
                cr.set_source_rgb(*c["accent2"])
                cr.set_line_width(2.5)
                cr.stroke()
            # a little rotate arrow inside the top knob
            cr.set_source_rgb(*c["accent2"])
            cr.set_line_width(1.5)
            cr.arc(tx, ty, 3.2, -math.pi * 0.9, math.pi * 0.4)
            cr.stroke()

        # hint along the bottom
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11.5)
        if not items:
            text = "Pick something from the wardrobe below"
        elif self.sel in items:
            text = "Drag to move  ·  corner knob or Ctrl+scroll to resize  ·  top knob or Ctrl+Shift+scroll to rotate  ·  arrows nudge"
        else:
            text = "Click an accessory to adjust it"
        ext = cr.text_extents(text)
        cr.set_source_rgba(*c["fg"], 0.5)
        cr.move_to((w - ext.width) / 2, h - 14)
        cr.show_text(text)

    def outline(self, cr, acc_id, rgba, dash):
        pts = self.screen_corners(acc_id)
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.close_path()
        cr.set_source_rgba(*rgba)
        cr.set_line_width(1.5)
        cr.set_dash(dash)
        cr.stroke()
        cr.set_dash([])
