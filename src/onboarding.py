"""The welcome, the first time the settings window opens: two panels slide apart as your pet spins
out between them, you name it, and a short tour (four steps, skippable) shows how it all works.
A layer over the settings window (see Settings.welcome)."""
import math
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import sprites  # noqa: E402

INTRO = 1.9          # seconds of the opening animation
STEPS = [            # (title, text, illustration)
    ("The box", "Your pet lives in a little box at the edge of your screen. Hover the tab to open it, "
                "click the tab to keep it open.", "box"),
    ("Pick it up", "Drag your pet out of the box onto your desktop. It walks on your windows. Throw it "
                   "up and catch it on the way down for points.", "drag"),
    ("Pet it", "Hold the scroll wheel down on your pet and stroke it. Keep going and see what happens.",
     "pet"),
    ("Make it yours", "Right-click your pet any time to come back here: colours, hats, themes, weather, "
                      "a Waybar module and more.", "yours"),
]


def ease_out(p):
    return 1 - (1 - p) ** 3


def ease_in_out(p):
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def back_out(p, s=1.6):
    p -= 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class Welcome(Gtk.Overlay):
    def __init__(self, settings, done, tour_only=False):
        """settings: the Settings window; done(name or None) when it's over."""
        super().__init__()
        self.settings, self.pet, self.done = settings, settings.pet, done
        self.start = time.monotonic()
        self.stage = "tour" if tour_only else "intro"    # intro | name | tour | finish
        self.step = 0
        self.stage_t = self.start
        self.fade = None                                  # closing: when it began fading
        self.big = None
        self.held = None
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.add(self.area)
        self.card = self.build_card()
        self.add_overlay(self.card)
        self.timer = GLib.timeout_add(1000 // 60, self.tick)
        if tour_only:
            self.show_step()
        else:
            self.card.set_opacity(0)

    # ── the card: name entry, tour text, buttons ────────────────────────────
    def build_card(self):
        from settings import css_class, label, icon_button   # (shared look)
        card = css_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), "card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.END)
        card.set_margin_bottom(56)
        card.set_size_request(520, -1)
        self.title = label("", "page-title", xalign=0.5)
        self.text = label("", "card-sub", xalign=0.5, wrap=True)
        self.text.set_justify(Gtk.Justification.CENTER)
        self.text.set_max_width_chars(52)
        card.pack_start(self.title, False, False, 0)
        card.pack_start(self.text, False, False, 0)
        self.entry = Gtk.Entry(placeholder_text="Larry", max_length=32, xalign=0.5)
        self.entry.set_text(self.pet.cfg["name"] if self.pet.cfg["name"] != "Larry" else "")
        self.entry.connect("activate", lambda _e: self.on_next(None))
        card.pack_start(self.entry, False, False, 0)
        self.dots = Gtk.DrawingArea()
        self.dots.set_size_request(-1, 12)
        self.dots.connect("draw", self.draw_dots)
        card.pack_start(self.dots, False, False, 0)
        row = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.skip = icon_button("Skip tour", "media-skip-forward-symbolic")
        self.skip.connect("clicked", lambda _b: self.finish())
        self.back = icon_button("Back", "go-previous-symbolic")
        self.back.connect("clicked", self.on_back)
        self.next = Gtk.Button(label="Next")
        self.next.get_style_context().add_class("primary")
        css_class(self.next, "chip")
        self.next.connect("clicked", self.on_next)
        for w in (self.skip, self.back, self.next):
            row.pack_start(w, False, False, 0)
        card.pack_start(row, False, False, 0)
        for w in (self.entry, self.dots, self.skip, self.back):
            w.set_no_show_all(True)
        self.title.set_text("Name your pet")
        self.text.set_text("Give your new little friend a name. You can change it any time.")
        self.entry.show()
        return card

    def show_step(self):
        title, text, _ill = STEPS[self.step]
        self.title.set_text(title)
        self.text.set_text(text)
        self.entry.hide()
        self.dots.show()
        self.skip.show()
        self.back.show()
        self.back.set_sensitive(self.step > 0)      # (always there, so Next never moves under your cursor)
        self.next.set_label("Done" if self.step == len(STEPS) - 1 else "Next")
        self.dots.queue_draw()
        self.stage_t = time.monotonic()
        if STEPS[self.step][2] == "box" and self.pet.has_box and self.pet.mode == "box":
            self.pet.peek(4.0)                 # the real box opens for a moment
        self.settings.sound.play("select")

    def on_next(self, _b):
        if self.stage == "name":
            self.stage, self.step = "tour", 0
            self.show_step()
        elif self.stage == "tour":
            if self.step < len(STEPS) - 1:
                self.step += 1
                self.show_step()
            else:
                self.finish()

    def on_back(self, _b):
        if self.stage == "tour" and self.step > 0:
            self.step -= 1
            self.show_step()

    def finish(self):
        if self.fade is None:
            self.stage = "finish"
            self.title.set_text("All set!")
            self.text.set_text("Have fun. Your pet's waiting for you.")
            for w in (self.entry, self.dots, self.skip, self.back, self.next):
                w.hide()
            self.fade = time.monotonic() + 0.9
            self.settings.sound.play("on")

    def pet_name(self):
        return self.entry.get_text().strip()[:32] or None

    # ── animation ───────────────────────────────────────────────────────────
    def tick(self):
        now = time.monotonic()
        if self.stage == "intro":
            t = now - self.start
            self.card.set_opacity(max(0.0, min(1.0, (t - INTRO + 0.35) / 0.35)))
            if t >= INTRO:
                self.stage, self.stage_t = "name", now
                self.card.set_opacity(1)
                self.entry.grab_focus()
        if self.fade is not None and now > self.fade:
            k = (now - self.fade) / 0.45
            self.set_opacity(max(0.0, 1 - k))
            if k >= 1:
                self.timer = None
                self.done(self.pet_name())
                return False
        self.area.queue_draw()
        return True

    def sprites_big(self):
        if self.big is None:
            cfg = self.pet.dress(self.pet.cfg)
            self.big = sprites.load(cfg, 4)[0]
            try:
                fall = sprites.load_fall(cfg, 3)
                self.held = fall[0] if fall else self.big
            except Exception:
                self.held = self.big
        return self.big, self.held

    def on_draw(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        c = self.pet.colors
        now = time.monotonic()
        cr.set_source_rgba(*c["bg0"], 0.985)
        cr.paint()
        glow = cairo.RadialGradient(W / 2, H * 0.34, 0, W / 2, H * 0.34, max(W, H) * 0.6)
        glow.add_color_stop_rgba(0, *c["accent2"], 0.16)
        glow.add_color_stop_rgba(1, *c["accent2"], 0)
        cr.set_source(glow)
        cr.paint()
        big, held = self.sprites_big()
        if self.stage == "intro":
            self.draw_intro(cr, W, H, now - self.start, big, c)
        elif self.stage in ("name", "finish"):
            t = now - self.stage_t
            self.draw_pet(cr, big, W / 2, H * 0.4, 1.0, bob=abs(math.sin(t * 3)) * 6)
        else:
            self.draw_step(cr, W, H, now - self.stage_t, big, held, c)

    def draw_pet(self, cr, sprite, cx, feet, scale, rot=0.0, bob=0.0):
        sw, sh = sprites.logical_size(sprite)
        k = 150 / sh * scale
        cr.save()
        cr.translate(cx, feet - bob - sh * k / 2)
        cr.rotate(rot)
        cr.scale(k, k)
        cr.set_source_surface(sprite, -sw / 2, -sh / 2)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()

    def draw_intro(self, cr, W, H, t, big, c):
        """The two halves slide apart (top up, bottom down); the pet spins out from the gap, grows,
        and settles where it'll stand for the name page."""
        open_p = ease_in_out(max(0.0, min(1.0, (t - 0.25) / 0.9)))
        spin = max(0.0, min(1.0, (t - 0.15) / 1.25))
        s = back_out(spin, 1.8) if spin > 0 else 0.0
        rot = (1 - ease_out(spin)) * math.pi * 4
        rise = ease_in_out(max(0.0, min(1.0, (t - 1.05) / 0.7)))
        feet = H / 2 + 75 + (H * 0.4 - (H / 2 + 75)) * rise
        if s > 0.01:
            self.draw_pet(cr, big, W / 2, feet, max(s, 0.01), rot)
        gap = open_p * H / 2
        for top in (True, False):              # the two panels, and a light along the seam
            y0 = -gap if top else H / 2 + gap
            cr.rectangle(0, y0, W, H / 2)
            g = cairo.LinearGradient(0, y0, 0, y0 + H / 2)
            a, b = (c["bg1"], c["bg0"]) if top else (c["bg0"], c["bg1"])
            g.add_color_stop_rgb(0, *a)
            g.add_color_stop_rgb(1, *b)
            cr.set_source(g)
            cr.fill()
            edge = y0 + H / 2 if top else y0
            cr.rectangle(0, edge - 1.5, W, 3)
            cr.set_source_rgba(*c["accent2"], 0.85 * (1 - open_p * 0.6))
            cr.fill()
        if open_p < 0.05:                       # before they part: a little glow where they'll split
            g = cairo.RadialGradient(W / 2, H / 2, 0, W / 2, H / 2, 160)
            g.add_color_stop_rgba(0, *c["accent2"], 0.5)
            g.add_color_stop_rgba(1, *c["accent2"], 0)
            cr.set_source(g)
            cr.paint()

    def draw_step(self, cr, W, H, t, big, held, c):
        """A small looping picture of what this step is about, above the card."""
        kind = STEPS[self.step][2]
        fw, fh = min(520, W - 80), 280
        card_top = H - 56 - self.card.get_allocated_height()
        fx, fy = W / 2 - fw / 2, max(24, (card_top - fh) / 2)
        rounded(cr, fx, fy, fw, fh, 22)
        cr.set_source_rgba(*c["bg1"], 1)
        cr.fill_preserve()
        cr.set_source_rgba(*c["fg"], 0.08)
        cr.set_line_width(1)
        cr.stroke()
        cr.save()
        rounded(cr, fx, fy, fw, fh, 22)
        cr.clip()
        getattr(self, "ill_" + kind)(cr, fx, fy, fw, fh, t, big, held, c)
        cr.restore()

    def small(self, cr, sprite, cx, feet, height, rot=0.0, flip=False):
        sw, sh = sprites.logical_size(sprite)
        k = height / sh
        cr.save()
        cr.translate(cx, feet)
        cr.rotate(rot)
        cr.scale(-k if flip else k, k)
        cr.set_source_surface(sprite, -sw / 2, -sh)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()

    def cursor(self, cr, x, y, grab=False):
        cr.save()
        cr.translate(x, y)
        cr.scale(1.3, 1.3)
        if grab:
            rounded(cr, -8, -3, 16, 13, 5)
        else:
            cr.move_to(0, 0)
            for px, py in ((0, 18), (4.5, 14), (8, 21), (10.5, 20), (7.5, 13), (13, 13)):
                cr.line_to(px, py)
            cr.close_path()
        cr.set_source_rgb(1, 1, 1)
        cr.fill_preserve()
        cr.set_source_rgb(0.05, 0.05, 0.07)
        cr.set_line_width(1.4)
        cr.stroke()
        cr.restore()

    def ill_box(self, cr, x, y, w, h, t, big, held, c):
        """A mini screen: the cursor comes to the tab and the box slides down, pet inside."""
        cyc = t % 3.6
        hover = min(1.0, max(0.0, (cyc - 0.6) / 0.25)) if cyc < 2.8 else max(0.0, 1 - (cyc - 2.8) / 0.3)
        o = ease_out(hover)
        bw, bh = 230, 96
        bx, by = x + w / 2 - bw / 2, y - bh + bh * o
        rounded(cr, bx, by - 20, bw, bh + 20, 16)
        cr.set_source_rgba(*c["bg0"], 1)
        cr.fill()
        cr.rectangle(bx + 6, by + bh - 16, bw - 12, 12)
        cr.set_source_rgba(*c["accent2"], 0.55)
        cr.fill()
        if o > 0.05:
            px = bx + 60 + (bw - 120) * (0.5 + 0.5 * math.sin(t * 1.3))
            self.small(cr, big, px, by + bh - 12, 52, flip=math.cos(t * 1.3) < 0)
        tx = x + w / 2 - 22
        rounded(cr, tx, by + bh - 1, 44, 13, 6)
        cr.set_source_rgba(*c["bg0"], 1)
        cr.fill()
        cx = x + w / 2 + 70 - 66 * ease_out(min(1.0, cyc / 0.6)) if cyc < 2.8 else x + w / 2 + 4 + 60 * ease_out((cyc - 2.8) / 0.8)
        self.cursor(cr, cx, by + bh + 4)

    def ill_drag(self, cr, x, y, w, h, t, big, held, c):
        """The cursor lifts the pet out and drops it onto a window."""
        rounded(cr, x + w * 0.52, y + h * 0.62, w * 0.38, h * 0.5, 10)
        cr.set_source_rgba(*c["bg0"], 1)
        cr.fill()
        cyc = t % 3.0
        sx, sy = x + w * 0.24, y + h * 0.84
        ex, ey = x + w * 0.71, y + h * 0.62
        if cyc < 0.5:
            self.small(cr, big, sx, sy, 60)
            self.cursor(cr, sx + 40 - 40 * ease_out(cyc / 0.5), sy - 70)
        elif cyc < 1.7:
            p = ease_in_out((cyc - 0.5) / 1.2)
            hx, hy = sx + (ex - sx) * p, sy - 50 - math.sin(p * math.pi) * 60 + (ey - sy) * p
            self.small(cr, held, hx, hy + 52, 80, rot=math.sin(t * 9) * 0.12)
            self.cursor(cr, hx - 6, hy - 10, grab=True)
        else:
            k = cyc - 1.7
            sq = math.exp(-k * 7) * math.cos(k * 22) * 0.15
            cr.save()
            cr.translate(ex, ey)
            cr.scale(1 + sq / 2, 1 - sq)
            cr.translate(-ex, -ey)
            self.small(cr, big, ex, ey, 60)
            cr.restore()
            self.cursor(cr, ex + 20 + k * 30, ey - 90 - k * 20)

    def ill_pet(self, cr, x, y, w, h, t, big, held, c):
        """The cursor strokes the pet back and forth and hearts float up."""
        px, feet = x + w / 2, y + h * 0.86
        self.small(cr, big, px, feet, 110)
        sx = px - 30 + math.sin(t * 5) * 34
        self.cursor(cr, sx, feet - 92)
        cr.save()                               # a little "scroll wheel held" ring on the cursor
        cr.arc(sx + 8, feet - 96, 9 + 2 * math.sin(t * 8), 0, 2 * math.pi)
        cr.set_source_rgba(*c["accent2"], 0.6)
        cr.set_line_width(2)
        cr.stroke()
        cr.restore()
        for i in range(4):
            p = (t * 0.6 + i / 4) % 1
            hx = px - 50 + i * 34 + math.sin(p * 6 + i) * 6
            hy = feet - 100 - p * 90
            s = 7 + 4 * math.sin(p * math.pi)
            cr.move_to(hx, hy + s)
            cr.curve_to(hx - s * 2, hy - s * 0.4, hx - s, hy - s * 1.8, hx, hy - s * 0.7)
            cr.curve_to(hx + s, hy - s * 1.8, hx + s * 2, hy - s * 0.4, hx, hy + s)
            cr.set_source_rgba(0.95, 0.33, 0.45, math.sin(p * math.pi))
            cr.fill()

    def ill_yours(self, cr, x, y, w, h, t, big, held, c):
        """The pet, with colour swatches circling it."""
        px, feet = x + w / 2, y + h * 0.82
        self.small(cr, big, px, feet, 100, rot=math.sin(t * 2) * 0.05)
        cols = [(0.95, 0.42, 0.55), (0.98, 0.76, 0.3), (0.4, 0.8, 0.6), (0.45, 0.62, 0.98), (0.72, 0.5, 0.96),
                (0.98, 0.56, 0.32)]
        for i, col in enumerate(cols):
            a = t * 0.8 + i * 2 * math.pi / len(cols)
            sx, sy = px + math.cos(a) * 150, y + h * 0.5 + math.sin(a) * 70
            r = 12 + 3 * math.sin(t * 2 + i)
            cr.new_path()
            cr.arc(sx, sy, r, 0, 2 * math.pi)
            cr.set_source_rgb(*col)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.8)
            cr.set_line_width(2)
            cr.stroke()

    def draw_dots(self, w, cr):
        n = len(STEPS)
        W = w.get_allocated_width()
        c = self.pet.colors
        for i in range(n):
            x = W / 2 + (i - (n - 1) / 2) * 18
            on = i == self.step
            rounded(cr, x - (8 if on else 4), 2, 16 if on else 8, 8, 4)
            cr.set_source_rgba(*(c["accent2"] if on else c["fg"]), 1 if on else 0.25)
            cr.fill()

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
