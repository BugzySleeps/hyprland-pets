"""The box, big, where you arrange things: drag decorations around (they snap onto the ground),
drag the corner knob or Ctrl+scroll to resize, drag the ground's top edge to make it thicker or thinner,
and drag the sky to frame a sky picture (Ctrl+scroll zooms it)."""
import math

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

import library  # noqa: E402
import scene  # noqa: E402
import sprites  # noqa: E402

KNOB = 6
SNAP = 3          # px (in box units) from the ground where a decoration snaps onto it
HINT_H = 34


class SceneEditor(Gtk.DrawingArea):
    def __init__(self, pet, get_cfg, on_change, on_select, sound):
        """get_cfg() -> live settings (the box is edited in place); on_change() after edits;
        on_select(index or None); sound(name, frac=None)."""
        super().__init__()
        self.pet, self.get_cfg, self.on_change, self.on_select, self.sound = pet, get_cfg, on_change, on_select, sound
        self.sel = self.hover = None      # index into box["items"]
        self.hover_ground = False
        self.drag = None                  # (mode, start pointer, start values)
        self.cache = self.cache_scale = None
        self.pet_key = self.pet_sprite = None
        self.set_can_focus(True)
        self.set_size_request(-1, 330)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        for sig, cb in (("draw", self.on_draw), ("button-press-event", self.on_press),
                        ("button-release-event", self.on_release), ("motion-notify-event", self.on_motion),
                        ("leave-notify-event", self.on_leave), ("scroll-event", self.on_scroll),
                        ("key-press-event", self.on_key)):
            self.connect(sig, cb)

    @property
    def box(self):
        return self.get_cfg()["box"]

    @property
    def items(self):
        return self.box["items"]

    def selected(self):
        return self.items[self.sel] if self.sel is not None and self.sel < len(self.items) else None

    def select(self, i, notify=True):
        self.sel = i if i is not None and 0 <= i < len(self.items) else None
        self.queue_draw()
        if notify:
            self.on_select(self.sel)

    # ── geometry ────────────────────────────────────────────────────────────
    def view(self):
        """(ox, oy, k, bw, bh, gy): box origin in the widget, zoom, box size, ground line (box units)."""
        w, h = self.get_allocated_width(), self.get_allocated_height()
        bw, bh = self.pet.box_size_for(self.box)
        k = max(min((w - 40) / bw, (h - HINT_H - 24) / bh), 0.5)
        return (w - bw * k) / 2, 12 + (h - HINT_H - 12 - bh * k) / 2, k, bw, bh, bh - scene.ground_height(self.box)

    def to_box(self, px, py):
        ox, oy, k, *_ = self.view()
        return (px - ox) / k, (py - oy) / k

    def rect(self, i):
        _ox, _oy, _k, bw, _bh, gy = self.view()
        return scene.item_rect(self.items[i], bw, gy)

    def knob(self, i):
        """The resize knob: top-right corner, in widget pixels."""
        ox, oy, k, *_ = self.view()
        x0, y0, x1, y1 = self.rect(i)
        return ox + x1 * k, oy + y0 * k

    def hit(self, px, py):
        bx, by = self.to_box(px, py)
        _ox, _oy, k, *_ = self.view()
        m = 3 / k
        order = [i for i, it in enumerate(self.items) if it["front"]][::-1] + \
                [i for i, it in enumerate(self.items) if not it["front"]][::-1]
        if self.sel in order:
            order.remove(self.sel)
            order.insert(0, self.sel)
        for i in order:
            x0, y0, x1, y1 = self.rect(i)
            if x0 - m <= bx <= x1 + m and y0 - m <= by <= y1 + m:
                return i
        return None

    def on_knob(self, px, py):
        if self.selected() is None:
            return False
        kx, ky = self.knob(self.sel)
        return math.hypot(px - kx, py - ky) <= KNOB + 4

    def near_ground(self, px, py):
        if self.box["ground"] == "none":
            return False
        ox, oy, k, bw, _bh, gy = self.view()
        return ox <= px <= ox + bw * k and abs(py - (oy + gy * k)) <= 5

    def sky_picture(self):
        bg = self.box["background"]
        return library.surface("skies", bg) if library.is_custom(bg) else None

    def in_box(self, px, py):
        ox, oy, k, bw, bh, _gy = self.view()
        return ox <= px <= ox + bw * k and oy <= py <= oy + bh * k

    # ── editing ─────────────────────────────────────────────────────────────
    def changed(self):
        self.queue_draw()
        self.on_change()

    def on_press(self, _w, ev):
        self.grab_focus()
        if ev.button != 1:
            return
        start = (ev.x, ev.y)
        if self.on_knob(ev.x, ev.y):
            self.drag = ("scale", start, dict(self.selected()))
            self.sound("grab")
            return
        i = self.hit(ev.x, ev.y)
        ground = self.near_ground(ev.x, ev.y) and (i is None or i != self.sel)   # the edge beats things standing on it
        if i is not None and not ground:
            if i != self.sel:
                self.select(i)
            self.drag = ("move", start, dict(self.items[i]))
            self.sound("grab")
        elif ground:
            self.select(None)
            self.drag = ("ground", start, {"h": scene.ground_height(self.box)})
            self.sound("grab")
        elif self.sky_picture() and self.in_box(ev.x, ev.y):
            self.select(None)
            self.drag = ("sky", start, {"x": self.box["sky_x"], "y": self.box["sky_y"]})
            self.set_cursor("grabbing")
        else:
            self.select(None)
        self.queue_draw()

    def set_cursor(self, name):
        win = self.get_window()
        if win:
            win.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), name) if name else None)

    def on_motion(self, _w, ev):
        if not self.drag:
            self.update_hover(ev.x, ev.y)
            return
        mode, (sx, sy), start = self.drag
        ox, oy, k, bw, bh, gy = self.view()
        dx, dy = (ev.x - sx) / k, (ev.y - sy) / k
        if mode == "move":
            it = self.items[self.sel]
            it["x"] = round(min(max(start["x"] + dx / bw, -0.5), 1.5), 3)
            y = start["y"] - dy
            it["y"] = 0 if abs(y) <= SNAP else round(min(max(y, -60), 400), 1)   # snaps onto the ground
            self.sound("tick", min(max(it["y"] / max(gy, 1), 0), 1))
        elif mode == "scale":
            it = self.items[self.sel]
            ax, ay = ox + it["x"] * bw * k, oy + (gy - it["y"]) * k   # it grows from where it stands
            d0 = math.hypot(sx - ax, sy - ay) or 1
            s = start["scale"] * math.hypot(ev.x - ax, ev.y - ay) / d0
            it["scale"] = round(min(max(s, scene.SCALE_MIN), scene.SCALE_MAX), 3)
            self.sound("tick", it["scale"] / 3)
        elif mode == "ground":
            h = round(min(max(start["h"] - dy, scene.GROUND_MIN), scene.GROUND_MAX))
            if h != self.box["ground_height"]:
                self.box["ground_height"] = h
                self.sound("tick", (h - scene.GROUND_MIN) / (scene.GROUND_MAX - scene.GROUND_MIN))
        elif mode == "sky":
            surf = self.sky_picture()
            if surf:
                iw, ih = surf.get_width(), surf.get_height()
                kk = max(bw / iw, bh / ih) * self.box["sky_zoom"]
                over_x, over_y = iw * kk - bw, ih * kk - bh
                if over_x > 0.5:
                    self.box["sky_x"] = round(min(max(start["x"] - dx / over_x, 0), 1), 3)
                if over_y > 0.5:
                    self.box["sky_y"] = round(min(max(start["y"] - dy / over_y, 0), 1), 3)
        self.changed()

    def update_hover(self, px, py):
        knob = self.on_knob(px, py)
        hov = None if knob else self.hit(px, py)
        ground = not knob and self.near_ground(px, py) and (hov is None or hov != self.sel)
        if ground:
            hov = None
        if (hov, ground) != (self.hover, self.hover_ground):
            self.hover, self.hover_ground = hov, ground
            self.queue_draw()
        if knob:
            self.set_cursor("nesw-resize")
        elif hov is not None:
            self.set_cursor("move")
        elif ground:
            self.set_cursor("ns-resize")
        elif self.sky_picture() and self.in_box(px, py):
            self.set_cursor("grab")
        else:
            self.set_cursor(None)

    def on_release(self, _w, ev):
        if self.drag:
            self.drag = None
            self.update_hover(ev.x, ev.y)
            self.changed()

    def on_leave(self, *_):
        if not self.drag and (self.hover is not None or self.hover_ground):
            self.hover, self.hover_ground = None, False
            self.queue_draw()

    def on_scroll(self, _w, ev):
        if not ev.state & Gdk.ModifierType.CONTROL_MASK:
            return False     # plain scrolling scrolls the page; Ctrl+scroll resizes/zooms
        ok, _dx, dy = ev.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction, 0)
        if not dy:
            return True
        it = self.selected()
        if it is not None and (self.hit(ev.x, ev.y) == self.sel or self.on_knob(ev.x, ev.y)):
            it["scale"] = round(min(max(it["scale"] * 1.06 ** -dy, scene.SCALE_MIN), scene.SCALE_MAX), 3)
            self.sound("tick", it["scale"] / 3)
        elif self.sky_picture() and self.in_box(ev.x, ev.y) and self.hit(ev.x, ev.y) is None:
            z = min(max(self.box["sky_zoom"] * 1.06 ** -dy, 1), scene.SKY_ZOOM_MAX)
            self.box["sky_zoom"] = round(z, 3)
            self.sound("tick", (z - 1) / (scene.SKY_ZOOM_MAX - 1))
        else:
            return False     # let the page scroll
        self.changed()
        return True

    def on_key(self, _w, ev):
        it = self.selected()
        if it is None:
            return False
        name = Gdk.keyval_name(ev.keyval)
        big = ev.state & Gdk.ModifierType.SHIFT_MASK
        _ox, _oy, _k, bw, *_ = self.view()
        if name in ("Left", "Right"):
            it["x"] = round(it["x"] + (1 if name == "Right" else -1) * (5 if big else 1) / bw, 3)
        elif name in ("Up", "Down"):
            it["y"] = round(it["y"] + (1 if name == "Up" else -1) * (5 if big else 1), 1)
        elif name in ("plus", "equal", "KP_Add", "minus", "KP_Subtract"):
            f = 1.05 if name in ("plus", "equal", "KP_Add") else 1 / 1.05
            it["scale"] = round(min(max(it["scale"] * f, scene.SCALE_MIN), scene.SCALE_MAX), 3)
        elif name in ("f", "F"):
            it["flip"] = not it["flip"]
        elif name == "Escape":
            self.select(None)
            return True
        else:
            return False
        self.sound("tick", 0.5)
        self.changed()
        return True

    # ── drawing ─────────────────────────────────────────────────────────────
    def sprite(self, k):
        cfg = self.pet.cfg
        key = (round(k, 2), cfg["image"], cfg["size"], cfg["faces_left"], cfg["remove_bg"], cfg["outline"],
               repr(cfg["accessories"]))
        if key != self.pet_key:
            self.pet_key = key
            try:
                self.pet_sprite = sprites.load(cfg, round(k, 2))[0]
            except Exception:
                self.pet_sprite = None
        return self.pet_sprite

    def on_draw(self, _w, cr):
        c = self.pet.colors
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
        cr.set_source_rgba(*c["fg"], 0.05)
        for x in range(10, w, 20):
            for y in range(10, h, 20):
                cr.rectangle(x, y, 1.5, 1.5)
        cr.fill()

        ox, oy, k, bw, bh, gy = self.view()
        if self.cache is None or abs(self.cache_scale - k) > 0.01:
            self.cache, self.cache_scale = scene.BoxCache(k), k
        cr.save()
        cr.translate(ox, oy)
        cr.scale(k, k)
        sprite = self.sprite(k)

        def pet(cr):                 # the pet stands in the middle, for scale
            if sprite:
                sw, _sh = sprites.logical_size(sprite)
                gh = scene.ground_height(self.box)
                sprites.draw_pet(cr, sprite, bw / 2, bh - gh + (4 if gh else 1), 0, 0, 0)
        self.cache.paint(cr, 0, 0, bw, bh, c, self.box, pet, self.get_cfg()["tab"]["edge"])
        cr.restore()

        # overlays
        if self.hover_ground or (self.drag and self.drag[0] == "ground"):
            y = oy + gy * k
            cr.set_source_rgba(*c["accent2"], 0.95)
            cr.set_line_width(2)
            cr.set_dash([6, 4])
            cr.move_to(ox, y)
            cr.line_to(ox + bw * k, y)
            cr.stroke()
            cr.set_dash([])
            self.pill(cr, ox + bw * k / 2, y, f"ground  {scene.ground_height(self.box)} px", c)
        if self.hover is not None and self.hover != self.sel and self.hover < len(self.items):
            self.outline(cr, self.hover, (*c["fg"], 0.4), [4, 4])
        if self.selected() is not None:
            self.outline(cr, self.sel, (*c["accent2"], 0.95), [6, 4])
            kx, ky = self.knob(self.sel)
            cr.arc(kx, ky, KNOB, 0, 2 * math.pi)
            cr.set_source_rgb(*c["fg"])
            cr.fill_preserve()
            cr.set_source_rgb(*c["accent2"])
            cr.set_line_width(2.5)
            cr.stroke()
            it = self.selected()
            if it["y"] == 0:          # standing on the ground: show the little foot mark
                fx, fy = ox + it["x"] * bw * k, oy + gy * k
                cr.set_source_rgba(*c["accent2"], 0.9)
                cr.move_to(fx - 6, fy)
                cr.line_to(fx + 6, fy)
                cr.set_line_width(2)
                cr.stroke()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11.5)
        if self.selected() is not None:
            text = "Drag to move (snaps onto the ground)  ·  corner knob or Ctrl+scroll to resize  ·  arrows nudge  ·  F mirrors"
        else:
            parts = ["Click a decoration to move it"]
            if self.box["ground"] != "none":
                parts.append("drag the ground's top edge to change its height")
            if self.sky_picture():
                parts.append("drag the sky to frame it, Ctrl+scroll to zoom")
            text = "  ·  ".join(parts)
        ext = cr.text_extents(text)
        cr.set_source_rgba(*c["fg"], 0.5)
        cr.move_to((w - ext.width) / 2, h - 14)
        cr.show_text(text)

    def outline(self, cr, i, rgba, dash):
        ox, oy, k, *_ = self.view()
        x0, y0, x1, y1 = self.rect(i)
        cr.rectangle(ox + x0 * k - 2, oy + y0 * k - 2, (x1 - x0) * k + 4, (y1 - y0) * k + 4)
        cr.set_source_rgba(*rgba)
        cr.set_line_width(1.5)
        cr.set_dash(dash)
        cr.stroke()
        cr.set_dash([])

    @staticmethod
    def pill(cr, x, y, text, c):
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.5)
        ext = cr.text_extents(text)
        w, h = ext.width + 16, 18
        x0, y0 = x - w / 2, y - h - 6
        r = h / 2
        cr.new_sub_path()
        cr.arc(x0 + w - r, y0 + r, r, -math.pi / 2, math.pi / 2)
        cr.arc(x0 + r, y0 + r, r, math.pi / 2, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(*c["bg0"], 0.85)
        cr.fill()
        cr.set_source_rgb(*c["fg"])
        cr.move_to(x0 + 8, y0 + 12.5)
        cr.show_text(text)
