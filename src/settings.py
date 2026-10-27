"""The settings window. Every change applies to the running pet immediately and is saved."""
import copy
import json
import math
import random
import re
import sys
import time
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import accessories  # noqa: E402
import music  # noqa: E402
import packs  # noqa: E402
import anim  # noqa: E402
import config  # noqa: E402
import library  # noqa: E402
import scene  # noqa: E402
import sounds  # noqa: E402
import themes  # noqa: E402
import fonts  # noqa: E402
import sprites  # noqa: E402
import vehicles  # noqa: E402
from curve_editor import CurveEditor  # noqa: E402
from fitting_room import FittingRoom  # noqa: E402
from scene_editor import SceneEditor  # noqa: E402

ZOOM = 1.7  # the big preview's magnification
NAV_GROUPS = [("Your pet", ["pet", "pets", "acc", "anim", "fun"]), ("Around it", ["box", "theme"])]
PAGES = [
    ("pet", "Pet", "face-smile-symbolic", "Who lives in the box, and how they look"),
    ("pets", "My pets", "system-users-symbolic", "Switch between your pets, and share them as pet packs"),
    ("box", "Box", "weather-clear-symbolic", "The little world your pet walks around in"),
    ("anim", "Animation", "media-playback-start-symbolic", "How your pet moves: shape it with the graphs"),
    ("acc", "Accessories", "starred-symbolic", "Dress your pet up, then drag things around until they fit"),
    ("fun", "Fun", "applications-games-symbolic", "Games, sounds and the little things your pet gets up to"),
    ("theme", "Themes", "applications-graphics-symbolic", "Colours for this window, the box and the tab"),
]


def hexc(c):
    return "#%02x%02x%02x" % tuple(round(v * 255) for v in c)


def rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def label(text, cls=None, xalign=0, wrap=False):
    l = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    if cls:
        for c in cls.split():
            l.get_style_context().add_class(c)
    return l


def css_class(widget, *names):
    for n in names:
        widget.get_style_context().add_class(n)
    return widget


class Squiggle(Gtk.DrawingArea):
    """A wavy divider line (after section and card titles)."""

    def __init__(self, colors, alpha=0.32):
        super().__init__(hexpand=True, valign=Gtk.Align.CENTER)
        self.colors, self.alpha = colors, alpha
        self.set_size_request(24, 10)
        self.connect("draw", self.on_draw)

    def on_draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        c = self.colors()
        cr.set_source_rgba(*c["fg"], self.alpha)
        cr.set_line_width(1.6)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        amp, period = 2.4, 11.0
        x = 2.0
        cr.move_to(x, h / 2)
        while x < w - 2:
            x += 1
            cr.line_to(x, h / 2 + amp * math.sin((x - 2) / period * 2 * math.pi))
        cr.stroke()


def icon_button(text, icon, tip=None):
    b = Gtk.Button(label=f"  {text}")
    b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
    b.set_always_show_image(True)
    if tip:
        b.set_tooltip_text(tip)
    return b


class Settings(Gtk.Window):
    def __init__(self, pet):
        super().__init__(title=f"{pet.cfg['name']} settings")
        self.pet = pet
        self.cfg = copy.deepcopy(pet.cfg)
        if not packs.read(self.cfg["pet"]):   # first time: the pet you have becomes your first saved pet
            try:
                _slug, self.cfg = packs.save(self.cfg)
                config.save(self.cfg)
                pet.set_config(copy.deepcopy(self.cfg))
            except Exception as e:
                print(f"larry: can't save the pet: {e}", file=sys.stderr)
        self.pet_thumbs = {}              # slug -> (signature, sprite) for the My pets tiles
        self.syncing = True               # no sounds/saves while building
        self.size_timer = self.saved_timer = self.acc_timer = self.scene_timer = None
        self.choice_pics = {}             # ground/sky tile previews (rebuilt when pictures change)
        self.anchor = None                # where the pet's head is, for placing new accessories
        self.tiles = []                   # mini scene previews to redraw on changes
        self.zoom_sprites = None
        self.px, self.pdir, self.phase = 0.0, 1, 0.0
        self.play_start = None            # box-open test playback (monotonic start time)
        self.set_default_size(1060, 740)
        css_class(self, "larry")
        self.connect("destroy", self.on_destroy)
        self.sound = sounds.Player(lambda: self.cfg["sounds"], lambda: self.cfg["volume"] / 100 * 0.8)
        self.style()
        self.search_index = []    # {"page", "card", "title", "text"}: every settings card, for search
        self.building = None
        self.connect("key-press-event", self.on_window_key)

        self.squiggles = []
        root = Gtk.Box(spacing=10, margin=10)
        self.add(root)
        root.pack_start(self.sidebar(), False, False, 0)
        root.pack_start(css_class(self.main_area(), "main-panel"), True, True, 0)

        self.hook_sounds(self)
        self.show_all()
        self.set_focus(None)          # don't start typing in the search box
        self.on_curve_pick(None)
        self.ticker = GLib.timeout_add(1000 // 30, self.animate)
        self.syncing = False

    # ── layout ──────────────────────────────────────────────────────────────
    def squiggle(self, alpha=0.32):
        sq = Squiggle(lambda: self.pet.colors, alpha)
        self.squiggles.append(sq)
        return sq

    def section(self, title, extra=None):
        """A small heading with a wavy line after it, like "Your pet ~~~~~"."""
        row = css_class(Gtk.Box(spacing=10), "section")
        row.pack_start(label(title, "section-label"), False, False, 0)
        row.pack_start(self.squiggle(0.28), True, True, 0)
        if extra:
            row.pack_start(extra, False, False, 0)
        return row

    def sidebar(self):
        side = css_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4), "side-panel")
        side.set_size_request(232, -1)
        side.set_hexpand(False)     # (the wavy lines inside want to stretch; the sidebar doesn't)

        brand = css_class(Gtk.Box(spacing=12, margin_bottom=14), "brand")
        self.avatar = Gtk.DrawingArea()
        self.avatar.set_size_request(44, 44)
        self.avatar.connect("draw", self.draw_avatar)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.brand = label(self.pet.cfg["name"], "brand-title")
        names.pack_start(self.brand, False, False, 0)
        names.pack_start(label("settings", "brand-sub"), False, False, 0)
        brand.pack_start(self.avatar, False, False, 0)
        brand.pack_start(names, False, False, 0)
        side.pack_start(brand, False, False, 0)

        self.search = Gtk.SearchEntry(placeholder_text="Search")
        css_class(self.search, "search")
        self.search.connect("search-changed", self.on_search)
        self.search.connect("activate", self.on_search_enter)
        self.search.connect("stop-search", lambda e: e.set_text(""))
        side.pack_start(self.search, False, False, 0)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, no_show_all=True)
        css_class(self.results, "results")
        self.results.connect("row-activated", lambda _l, row: self.go_to(row.hit))
        side.pack_start(self.results, False, False, 0)
        self.no_results = label("Nothing found", "row-sub", xalign=0.5)
        self.no_results.set_no_show_all(True)
        side.pack_start(self.no_results, False, False, 8)

        self.nav = {}
        group = None
        pages = {p[0]: p for p in PAGES}
        for heading, keys in NAV_GROUPS:
            side.pack_start(self.section(heading), False, False, 0)
            for key in keys:
                _k, title, icon, _sub = pages[key]
                b = Gtk.RadioButton(group=group)
                group = group or b
                b.set_mode(False)
                css_class(b, "nav")
                row = Gtk.Box(spacing=12)
                dot = css_class(Gtk.Box(), "nav-icon")
                img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
                img.set_halign(Gtk.Align.CENTER)
                img.set_valign(Gtk.Align.CENTER)
                dot.pack_start(img, True, True, 0)
                row.pack_start(dot, False, False, 0)
                row.pack_start(label(title, "nav-label"), False, False, 0)
                if key == "acc":       # a dot while there's a seasonal accessory to claim
                    self.claim_dot = css_class(Gtk.Box(valign=Gtk.Align.CENTER), "claim-dot")
                    self.claim_dot.set_no_show_all(True)
                    row.pack_start(self.claim_dot, False, False, 0)
                b.add(row)
                b.snd = "whoosh"
                b.connect("toggled", self.on_nav, key)
                side.pack_start(b, False, False, 0)
                self.nav[key] = b

        side.pack_start(Gtk.Box(), True, True, 0)  # spacer

        foot = css_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "side-card")
        row = Gtk.Box(spacing=12)
        dot = css_class(Gtk.Box(), "nav-icon")
        img = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic", Gtk.IconSize.MENU)
        img.set_halign(Gtk.Align.CENTER)
        dot.pack_start(img, True, True, 0)
        row.pack_start(dot, False, False, 0)
        row.pack_start(label("Sounds", "nav-label"), True, True, 0)
        snd = Gtk.Switch(active=self.cfg["sounds"], valign=Gtk.Align.CENTER)
        snd.connect("notify::active", self.on_sounds)
        row.pack_start(snd, False, False, 0)
        foot.pack_start(row, False, False, 0)
        vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        vol.set_draw_value(False)
        vol.set_value(self.cfg["volume"])
        vol.connect("value-changed", self.on_volume)
        foot.pack_start(vol, False, False, 0)
        side.pack_start(foot, False, False, 0)
        return side

    def main_area(self):
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        head = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.page_title = label("", "page-title")
        sub = Gtk.Box(spacing=10)
        self.page_icon = Gtk.Image()
        dot = css_class(Gtk.Box(valign=Gtk.Align.CENTER), "sub-icon")
        self.page_icon.set_halign(Gtk.Align.CENTER)
        dot.pack_start(self.page_icon, True, True, 0)
        self.page_sub = label("", "page-sub")
        sub.pack_start(dot, False, False, 0)
        sub.pack_start(self.page_sub, False, False, 0)
        titles.pack_start(self.page_title, False, False, 0)
        titles.pack_start(sub, False, False, 0)
        head.pack_start(titles, True, True, 0)
        self.saved = label("✓  Saved", "saved")
        self.saved.set_valign(Gtk.Align.START)
        head.pack_end(self.saved, False, False, 0)
        main.pack_start(head, False, False, 0)

        self.preview = css_class(Gtk.DrawingArea(), "hero")
        self.preview.connect("draw", self.draw_preview)
        self.preview_cache = scene.BoxCache(ZOOM)
        main.pack_start(self.preview, False, False, 0)
        self.fit_preview()

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.pages = {}
        for key, build in (("pet", self.pet_page), ("pets", self.pets_page), ("box", self.box_page), ("anim", self.anim_page),
                           ("acc", self.acc_page), ("fun", self.fun_page), ("theme", self.theme_page)):
            self.building = key      # cards made now belong to this page (for search)
            page = build()
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            scroll.add(page)
            self.stack.add_named(scroll, key)
            self.pages[key] = (scroll, page)
        main.pack_start(self.stack, True, True, 0)
        self.show_page("pet")
        return main

    def card(self, title, sub=None, extra=None):
        box = css_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), "card")
        self.search_index.append({"page": self.building, "card": box, "title": title, "text": None})
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head = Gtk.Box(spacing=14)
        head.pack_start(label(title, "card-title"), False, False, 0)
        head.pack_start(self.squiggle(), True, True, 0)
        if extra:
            head.pack_start(extra, False, False, 0)
        titles.pack_start(head, False, False, 0)
        if sub:
            titles.pack_start(label(sub, "card-sub", wrap=True), False, False, 0)
        box.pack_start(titles, False, False, 0)
        return box

    def setting_row(self, title, widget, sub=None):
        row = Gtk.Box(spacing=16)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        text.pack_start(label(title, "row-title"), False, False, 0)
        if sub:
            text.pack_start(label(sub, "row-sub", wrap=True), False, False, 0)
        text.set_size_request(220, -1)
        row.pack_start(text, False, False, 0)
        row.pack_start(widget, True, True, 0)
        return row

    @staticmethod
    def slider(lo, hi, step, digits, value, unit, on_change):
        s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        s.set_digits(digits)
        s.set_value(value)
        s.set_hexpand(True)
        s.set_value_pos(Gtk.PositionType.RIGHT)
        s.connect("format-value", lambda _s, v: f"{v:.{digits}f}{unit}")
        s.connect("value-changed", on_change)
        return s

    def tiles_row(self, options, current, on_pick, draw):
        """Picture tiles that act like radio buttons; draw(cr, w, h, key) paints each preview."""
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=3, max_children_per_line=6,
                           column_spacing=10, row_spacing=10)
        group, buttons = None, {}
        for key, title in options:
            b = Gtk.RadioButton(group=group)
            group = group or b
            b.set_mode(False)
            css_class(b, "tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = Gtk.DrawingArea()
            pic.set_size_request(110, 58)
            pic.connect("draw", lambda w, cr, k=key: draw(cr, w.get_allocated_width(), w.get_allocated_height(), k))
            self.tiles.append(pic)
            inner.pack_start(pic, False, False, 0)
            inner.pack_start(label(title, "tile-label", xalign=0.5), False, False, 0)
            b.add(inner)
            b.snd = "select"
            flow.add(b)
            buttons[key] = b
        buttons[current].set_active(True)
        for key, b in buttons.items():
            b.connect("toggled", lambda btn, k=key: btn.get_active() and on_pick(k))
        return flow, buttons

    # ── pages ───────────────────────────────────────────────────────────────
    def pet_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_end=12)

        c = self.card("Character", "Any picture works: PNGs with transparency look best")
        row = Gtk.Box(spacing=18)
        self.thumb = Gtk.DrawingArea()
        self.thumb.set_size_request(120, 120)
        self.thumb.connect("draw", self.draw_thumb)
        row.pack_start(self.thumb, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
        self.chooser = Gtk.FileChooserButton(title="Choose an image", action=Gtk.FileChooserAction.OPEN)
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        filt.add_pixbuf_formats()
        self.chooser.add_filter(filt)
        pictures = Path.home() / "Pictures"
        if pictures.is_dir():
            self.chooser.set_current_folder(str(pictures))
        self.chooser.set_filename(self.cfg["image"])
        self.chooser.connect("file-set", self.on_image)
        right.pack_start(self.chooser, False, False, 0)
        self.name_entry = Gtk.Entry(text=self.cfg["name"], placeholder_text="Name", max_length=32)
        self.name_entry.set_tooltip_text("Your pet's name")
        self.name_entry.connect("changed", self.on_name)
        right.pack_start(self.name_entry, False, False, 0)
        reset = icon_button("Bring back Larry", "view-refresh-symbolic")
        reset.set_halign(Gtk.Align.START)
        reset.connect("clicked", self.on_reset)
        right.pack_start(reset, False, False, 0)
        row.pack_start(right, True, True, 0)
        c.pack_start(row, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Look")
        self.size = self.slider(config.SIZE_MIN, config.SIZE_MAX, 1, 0, self.cfg["size"], " px", self.on_size)
        c.pack_start(self.setting_row("Size", self.size, "Height on screen"), False, False, 0)
        self.switches = {}
        for key, text, sub in (
            ("faces_left", "Looks left", "Turn on if the character in your image faces left"),
            ("remove_bg", "Remove background", "Cut out a solid background (for images without transparency)"),
            ("outline", "Outline", "White sticker edge so it shows on dark windows"),
        ):
            sw = Gtk.Switch(active=self.cfg[key], halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
            sw.connect("notify::active", self.on_switch, key)
            c.pack_start(self.setting_row(text, sw, sub), False, False, 0)
            self.switches[key] = sw
        page.pack_start(c, False, False, 0)

        return page

    # ── my pets / pet packs ─────────────────────────────────────────────────
    def pets_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_end=12)

        new = icon_button("New pet", "list-add-symbolic", "Start a new pet (as Larry; change it on the Pet page)")
        new.connect("clicked", self.on_new_pet)
        c = self.card("My pets", "Click one to switch. Each remembers its picture, name, size, accessories and "
                                 "animation, and the one you're using saves itself as you change it", new)
        self.pets_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                     min_children_per_line=3, max_children_per_line=6,
                                     column_spacing=10, row_spacing=10)
        c.pack_start(self.pets_flow, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Share", f"Export this pet as one {packs.EXT} file anyone can import: its picture, "
                               "accessories (your own pictures too), size and animation. Seasonal accessories "
                               "only come along for people who've claimed them")
        self.pack_author = Gtk.Entry(placeholder_text="Your name (optional)", max_length=40)
        self.pack_author.connect("changed", lambda e: self.on_pack_info("author", e.get_text()))
        c.pack_start(self.setting_row("Made by", self.pack_author), False, False, 0)
        self.pack_desc = Gtk.Entry(placeholder_text="A line about it (optional)", max_length=120)
        self.pack_desc.connect("changed", lambda e: self.on_pack_info("description", e.get_text()))
        c.pack_start(self.setting_row("About", self.pack_desc), False, False, 0)
        row = Gtk.Box(spacing=10)
        exp = icon_button("Export this pet…", "document-save-symbolic")
        exp.connect("clicked", self.on_export_pet)
        row.pack_start(exp, False, False, 0)
        imp = icon_button("Import a pet pack…", "document-open-symbolic", f"Add a {packs.EXT} file to your pets")
        imp.connect("clicked", self.on_import_pet)
        row.pack_start(imp, False, False, 0)
        c.pack_start(row, False, False, 0)
        self.pack_status = label("", "row-sub", xalign=0, wrap=True)
        c.pack_start(self.pack_status, False, False, 0)
        c.pack_start(label(f"Tip: you can also drop a {packs.EXT} file onto this window", "card-sub", xalign=0),
                     False, False, 0)
        page.pack_start(c, False, False, 0)

        # drop a pack anywhere on the window
        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.connect("drag-data-received", self.on_pack_drop)
        self.fill_pets()
        self.pets_built = True
        return page

    def fill_pets(self):
        for child in self.pets_flow.get_children():
            self.pets_flow.remove(child)
        self.pet_tiles = {}
        group = None
        was, self.syncing = self.syncing, True
        for slug, info in packs.saved():
            b = Gtk.RadioButton(group=group)
            group = group or b
            b.set_mode(False)
            css_class(b, "tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            pic = Gtk.DrawingArea()
            pic.set_size_request(110, 84)
            pic.connect("draw", lambda w, cr, sl=slug: self.draw_pet_tile(cr, w.get_allocated_width(),
                                                                         w.get_allocated_height(), sl))
            inner.pack_start(pic, False, False, 0)
            name = label(info.get("name") or slug, "tile-label", xalign=0.5)
            name.set_ellipsize(3)
            name.set_max_width_chars(14)
            inner.pack_start(name, False, False, 0)
            by = info.get("author")
            sub = label(f"by {by}" if by else ("Using now" if slug == self.cfg["pet"] else " "), "season-status",
                        xalign=0.5)
            sub.set_ellipsize(3)
            sub.set_max_width_chars(16)
            inner.pack_start(sub, False, False, 0)
            b.add(inner)
            b.set_active(slug == self.cfg["pet"])
            b.connect("toggled", lambda btn, sl=slug: btn.get_active() and self.switch_pet(sl))
            b.pic = pic
            over = Gtk.Overlay()
            over.add(b)
            if slug != self.cfg["pet"]:
                x = css_class(Gtk.Button(halign=Gtk.Align.END, valign=Gtk.Align.START), "tile-x")
                x.set_image(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU))
                x.set_tooltip_text("Delete this pet")
                x.connect("clicked", lambda _b, sl=slug: self.on_delete_pet(sl))
                over.add_overlay(x)
            if getattr(self, "pets_built", False):   # the first lot get theirs with everything else
                self.hook_sounds(over)
            self.pets_flow.add(over)
            self.pet_tiles[slug] = b
        self.syncing = was
        self.pets_flow.show_all()
        info = packs.read(self.cfg["pet"]) or {}
        was, self.syncing = self.syncing, True
        self.pack_author.set_text(info.get("author", ""))
        self.pack_desc.set_text(info.get("description", ""))
        self.syncing = was

    def draw_pet_tile(self, cr, w, h, slug):
        c = self.pet.colors
        rounded(cr, 0, 0, w, h, 14)
        cr.clip()
        cr.set_source_rgba(*c["fg"], 0.05)
        cr.paint()
        if slug == self.cfg["pet"]:
            pcfg = self.cfg
        else:
            info = packs.read(slug)
            if not info:
                return
            pcfg = packs.pet_cfg(self.cfg, slug, info)
        sig = json.dumps({k: pcfg[k] for k in (*packs.PET_KEYS, "image")}, sort_keys=True, default=str)
        hit = self.pet_thumbs.get(slug)
        if not hit or hit[0] != sig:
            try:
                hit = (sig, sprites.load({**pcfg, "size": 72})[0])
            except Exception:
                hit = (sig, None)
            self.pet_thumbs[slug] = hit
        sprite = hit[1]
        if not sprite:
            return
        sw, sh = sprite.get_width(), sprite.get_height()
        k = min((w - 16) / sw, (h - 12) / sh, 1.2)
        cr.translate((w - sw * k) / 2, h - 6 - sh * k)
        cr.scale(k, k)
        cr.set_source_surface(sprite, 0, 0)
        cr.paint()

    def switch_pet(self, slug):
        if self.syncing or slug == self.cfg["pet"]:
            return
        info = packs.read(slug)
        if not info:
            self.fill_pets()
            return
        new = packs.pet_cfg(self.cfg, slug, info)
        self.fill_custom()
        self.sync(new)            # move every control over without saving...
        self.apply()              # ...then save once, as this pet
        self.fill_pets()
        self.pack_status.set_text("")

    def on_new_pet(self, _b):
        fresh = copy.deepcopy(self.cfg)
        for k in packs.PET_KEYS:
            fresh[k] = copy.deepcopy(config.DEFAULTS[k])
        fresh["image"], fresh["fall_image"] = config.DEFAULTS["image"], config.DEFAULTS["fall_image"]
        fresh["name"] = "New pet"
        slug, _c = packs.save(fresh)
        self.switch_pet(slug)
        self.nav["pet"].set_active(True)

    def on_delete_pet(self, slug):
        info = packs.read(slug) or {}
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text=f"Delete {info.get('name') or slug}?")
        d.format_secondary_text("It's gone for good, unless you exported it as a pet pack.")
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.ACCEPT)
        if d.run() == Gtk.ResponseType.ACCEPT:
            packs.delete(slug)
            self.pet_thumbs.pop(slug, None)
            self.sound.play("pop_down")
            self.fill_pets()
        d.destroy()

    def on_pack_info(self, key, value):
        if not self.syncing:
            packs.update_info(self.cfg["pet"], **{key: value.strip()})

    def on_export_pet(self, _b):
        d = Gtk.FileChooserDialog(title="Export pet pack", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Export", Gtk.ResponseType.ACCEPT)
        d.set_do_overwrite_confirmation(True)
        d.set_current_name(re.sub(r"[^\w-]+", "-", self.cfg["name"]).strip("-").lower() + packs.EXT)
        folder_ = Path.home() / "Downloads"
        d.set_current_folder(str(folder_ if folder_.is_dir() else Path.home()))
        if d.run() == Gtk.ResponseType.ACCEPT:
            try:
                self.apply()
                out = packs.export(self.cfg["pet"], d.get_filename())
                self.pack_status.set_text(f"Saved {out.name} in {out.parent}")
                self.sound.play("on")
            except Exception as e:
                self.pack_status.set_text(f"Couldn't export: {e}")
        d.destroy()

    def on_import_pet(self, _b):
        d = Gtk.FileChooserDialog(title="Import pet pack", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Import", Gtk.ResponseType.ACCEPT)
        f = Gtk.FileFilter()
        f.set_name("Pet packs")
        f.add_pattern("*" + packs.EXT)
        d.add_filter(f)
        folder_ = Path.home() / "Downloads"
        if folder_.is_dir():
            d.set_current_folder(str(folder_))
        path = d.get_filename() if d.run() == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if path:
            self.import_pack(path)

    def on_pack_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        for uri in data.get_uris() or []:
            path = GLib.filename_from_uri(uri)[0] if uri.startswith("file://") else None
            if path and path.endswith(packs.EXT):
                self.nav["pets"].set_active(True)
                self.import_pack(path)

    def import_pack(self, path):
        try:
            slug = packs.install(path)
        except packs.PackError as e:
            self.pack_status.set_text(f"Couldn't import {Path(path).name}: {e}")
            self.sound.play("grab")
            return
        except Exception as e:
            self.pack_status.set_text(f"Couldn't import {Path(path).name}: {e}")
            return
        info = packs.read(slug) or {}
        self.switch_pet(slug)
        by = f" by {info['author']}" if info.get("author") else ""
        self.pack_status.set_text(f"Added {info.get('name', slug)}{by} to your pets")
        self.sound.play("on")

    def box_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_end=12)

        c = self.card("Scene", "Arrange everything: drag decorations around, drag the ground's edge to "
                               "raise or lower it, drag a sky picture to frame it")
        self.scene_ed = SceneEditor(self.pet, lambda: self.cfg, self.on_scene_change, self.on_scene_select,
                                    self.curve_sound)
        c.pack_start(self.scene_ed, False, False, 0)
        self.deco_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        bar = Gtk.Box(spacing=8)
        self.deco_name = label("", "acc-name")
        bar.pack_start(self.deco_name, True, True, 0)
        self.deco_buttons = {}
        for key, text, icon, tip, cb in (
            ("fwd", "Forward", "go-up-symbolic", "Draw it over the other decorations", lambda b: self.deco_layer(1)),
            ("back", "Back", "go-down-symbolic", "Draw it under the other decorations", lambda b: self.deco_layer(-1)),
            ("dup", "Duplicate", "edit-copy-symbolic", "Add another one just like it", self.deco_duplicate),
            ("del", "Remove", "edit-delete-symbolic", "Take it out of the box", self.deco_remove),
        ):
            btn = icon_button(text, icon, tip)
            btn.connect("clicked", cb)
            bar.pack_start(btn, False, False, 0)
            self.deco_buttons[key] = btn
        self.deco_controls.pack_start(bar, False, False, 0)
        row = Gtk.Box(spacing=28)
        self.deco_scale = self.slider(scene.SCALE_MIN * 100, scene.SCALE_MAX * 100, 1, 0, 100, "%",
                                      lambda sc: self.deco_set("scale", round(sc.get_value() / 100, 3)))
        size = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        size.pack_start(label("Size", "row-title"), False, False, 0)
        size.pack_start(self.deco_scale, False, False, 0)
        row.pack_start(size, True, True, 0)
        self.deco_flags = {}
        for key, text in (("flip", "Mirror"), ("front", "Over the ground")):
            sw = Gtk.Switch(valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda w, _p, k=key: self.deco_set(k, w.get_active()))
            box = Gtk.Box(spacing=10)
            box.pack_start(sw, False, False, 0)
            box.pack_start(label(text, "row-title"), False, False, 0)
            row.pack_start(box, False, False, 0)
            self.deco_flags[key] = sw
        self.deco_controls.pack_start(row, False, False, 0)
        self.deco_controls.set_no_show_all(True)
        c.pack_start(self.deco_controls, False, False, 0)
        page.pack_start(c, False, False, 0)

        shuffle = icon_button("Shuffle", "media-playlist-shuffle-symbolic", "Scatter the decorations")
        shuffle.connect("clicked", self.on_shuffle)
        clear = icon_button("Clear", "edit-clear-all-symbolic", "Take every decoration out")
        clear.connect("clicked", self.deco_clear)
        add = icon_button("Add picture…", "list-add-symbolic", "Use any image as a decoration")
        add.connect("clicked", lambda b: self.add_picture("decorations"))
        extra = Gtk.Box(spacing=8)
        for w in (add, shuffle, clear):
            extra.pack_start(w, False, False, 0)
        c = self.card("Decorations", "Click one to drop it in the box; add as many as you like", extra)
        self.deco_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                     min_children_per_line=4, max_children_per_line=8,
                                     column_spacing=10, row_spacing=10)
        c.pack_start(self.deco_flow, False, False, 0)
        page.pack_start(c, False, False, 0)

        self.choice_flows, self.choice_buttons = {}, {}
        add = icon_button("Add picture…", "list-add-symbolic", "Use any image as the ground (it repeats across)")
        add.connect("clicked", lambda b: self.add_picture("grounds"))
        c = self.card("Ground", "What your pet walks on", add)
        self.choice_flows["ground"] = self.choice_flow()
        c.pack_start(self.choice_flows["ground"], False, False, 0)
        self.ground_h = self.slider(scene.GROUND_MIN, scene.GROUND_MAX, 1, 0, self.cfg["box"]["ground_height"], " px",
                                    lambda sc: self.set_box("ground_height", int(sc.get_value()), soon=True))
        c.pack_start(self.setting_row("Height", self.ground_h, "Or drag the ground's top edge in the scene"),
                     False, False, 0)
        page.pack_start(c, False, False, 0)

        add = icon_button("Add picture…", "list-add-symbolic", "Use any image as the sky")
        add.connect("clicked", lambda b: self.add_picture("skies"))
        c = self.card("Sky", "The background behind everything", add)
        self.choice_flows["sky"] = self.choice_flow()
        c.pack_start(self.choice_flows["sky"], False, False, 0)
        self.sky_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sky_zoom = self.slider(100, scene.SKY_ZOOM_MAX * 100, 1, 0, self.cfg["box"]["sky_zoom"] * 100, "%",
                                    lambda sc: self.set_box("sky_zoom", round(sc.get_value() / 100, 3), soon=True))
        reset = icon_button("Reset framing", "view-refresh-symbolic", "Centre the picture and zoom back out")
        reset.connect("clicked", self.on_sky_reset)
        row = Gtk.Box(spacing=12)
        row.pack_start(self.sky_zoom, True, True, 0)
        row.pack_start(reset, False, False, 0)
        self.sky_controls.pack_start(self.setting_row("Zoom", row, "Drag the sky in the scene to pan it"),
                                     False, False, 0)
        self.sky_controls.set_no_show_all(True)
        c.pack_start(self.sky_controls, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Colours", "Tint decorations to your rice theme, or keep their real colours")
        flow, self.color_tiles = self.tiles_row(scene.COLOR_MODES, self.cfg["box"]["colors"],
                                                lambda k: self.set_box("colors", k),
                                                lambda cr, w, h, k: self.draw_tile(cr, w, h, colors=k))
        c.pack_start(flow, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Tab placement", "Which screen edge the tab hangs on, and where along it")
        flow, self.edge_tiles = self.tiles_row(scene.EDGES, self.cfg["tab"]["edge"],
                                               lambda k: self.set_tab("edge", k), self.draw_edge_tile)
        c.pack_start(flow, False, False, 0)
        self.tab_pos = self.slider(0, 100, 1, 0, self.cfg["tab"]["position"], "%",
                                   lambda sc: self.set_tab("position", int(sc.get_value())))
        c.pack_start(self.setting_row("Position", self.tab_pos, "Left → right, or top → bottom"), False, False, 0)
        page.pack_start(c, False, False, 0)

        self.fill_choice("ground")
        self.fill_choice("sky")
        self.fill_decos()
        return page

    @staticmethod
    def choice_flow():
        return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=3,
                           max_children_per_line=6, column_spacing=10, row_spacing=10)

    def deletable(self, widget, kind, item_id):
        """Wrap a tile with a little ✕ that deletes your picture."""
        x = css_class(Gtk.Button(halign=Gtk.Align.END, valign=Gtk.Align.START), "tile-x")
        x.set_image(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU))
        x.set_tooltip_text("Delete this picture")
        x.connect("clicked", lambda b: self.delete_picture(kind, item_id))
        over = Gtk.Overlay()
        over.add(widget)
        over.add_overlay(x)
        return over

    def fill_choice(self, which):
        """(Re)build the ground or sky tiles: the built-in ones, then your pictures."""
        flow = self.choice_flows[which]
        for child in flow.get_children():
            flow.remove(child)
        key, lib, builtin = (("ground", "grounds", scene.GROUNDS) if which == "ground"
                             else ("background", "skies", scene.BACKGROUNDS))
        group, buttons, pics = None, {}, []
        was, self.syncing = self.syncing, True
        for item_id, title in builtin + library.items(lib):
            b = Gtk.RadioButton(group=group)
            group = group or b
            b.set_mode(False)
            css_class(b, "tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = Gtk.DrawingArea()
            pic.set_size_request(110, 58)
            arg = {key: item_id}
            pic.connect("draw", lambda w, cr, a=arg: self.draw_tile(cr, w.get_allocated_width(),
                                                                   w.get_allocated_height(), **a))
            pics.append(pic)
            inner.pack_start(pic, False, False, 0)
            name = label(title, "tile-label", xalign=0.5)
            name.set_ellipsize(3)
            name.set_max_width_chars(14)
            inner.pack_start(name, False, False, 0)
            b.add(inner)
            b.snd = "select"
            b.connect("toggled", lambda btn, k=item_id: btn.get_active() and self.set_box(key, k))
            buttons[item_id] = b
            tile = self.deletable(b, lib, item_id) if library.is_custom(item_id) else b
            self.hook_sounds(tile)
            flow.add(tile)
        if self.cfg["box"][key] in buttons:
            buttons[self.cfg["box"][key]].set_active(True)
        self.syncing = was
        self.choice_buttons[which], self.choice_pics[which] = buttons, pics
        flow.show_all()
        if which == "sky":
            self.update_sky_controls()

    def fill_decos(self):
        for child in self.deco_flow.get_children():
            self.deco_flow.remove(child)
        for kind, title in scene.DECORATIONS + library.items("decorations"):
            b = css_class(Gtk.Button(), "tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = Gtk.DrawingArea()
            pic.set_size_request(84, 56)
            pic.connect("draw", lambda w, cr, k=kind: self.draw_deco_tile(cr, w.get_allocated_width(),
                                                                         w.get_allocated_height(), k))
            inner.pack_start(pic, False, False, 0)
            name = label(title, "tile-label", xalign=0.5)
            name.set_ellipsize(3)
            name.set_max_width_chars(12)
            inner.pack_start(name, False, False, 0)
            b.add(inner)
            b.set_tooltip_text(f"Add {title.lower()}")
            b.connect("clicked", lambda btn, k=kind: self.deco_add(k))
            tile = self.deletable(b, "decorations", kind) if library.is_custom(kind) else b
            self.deco_flow.add(tile)
        self.deco_flow.show_all()

    # ── scene ───────────────────────────────────────────────────────────────
    def on_scene_change(self):
        self.update_deco_controls()
        self.sync_box_sliders()
        self.scene_apply_soon()

    def on_scene_select(self, _i):
        self.update_deco_controls()

    def scene_apply_soon(self):
        if self.scene_timer:
            GLib.source_remove(self.scene_timer)
        self.scene_timer = GLib.timeout_add(120, self._scene_done)

    def _scene_done(self):
        self.scene_timer = None
        self.apply()
        return False

    def sync_box_sliders(self):
        was, self.syncing = self.syncing, True
        self.ground_h.set_value(self.cfg["box"]["ground_height"])
        self.sky_zoom.set_value(self.cfg["box"]["sky_zoom"] * 100)
        self.syncing = was

    def update_deco_controls(self):
        it = self.scene_ed.selected()
        if it is None:
            self.deco_controls.hide()
            return
        self.deco_controls.show_all()
        was, self.syncing = self.syncing, True
        self.deco_name.set_text(scene.deco_title(it["kind"]))
        self.deco_scale.set_value(it["scale"] * 100)
        for key, sw in self.deco_flags.items():
            sw.set_active(it[key])
        i, n = self.scene_ed.sel, len(self.cfg["box"]["items"])
        self.deco_buttons["fwd"].set_sensitive(i < n - 1)
        self.deco_buttons["back"].set_sensitive(i > 0)
        self.syncing = was

    def update_sky_controls(self):
        if library.is_custom(self.cfg["box"]["background"]):
            self.sky_controls.show_all()
        else:
            self.sky_controls.hide()

    def deco_set(self, key, value):
        it = self.scene_ed.selected()
        if self.syncing or it is None:
            return
        it[key] = value
        self.scene_ed.queue_draw()
        self.scene_apply_soon()

    def deco_add(self, kind):
        items = self.cfg["box"]["items"]
        items.append(scene.new_item(kind))
        self.sound.play("pop_up")
        self.scene_ed.select(len(items) - 1)
        self.apply()

    def deco_duplicate(self, _b):
        it = self.scene_ed.selected()
        if it is None:
            return
        twin = dict(it, x=round(min(it["x"] + 0.08, 1.0), 3), seed=random.randint(1, 99999))
        self.cfg["box"]["items"].insert(self.scene_ed.sel + 1, twin)
        self.sound.play("pop_up")
        self.scene_ed.select(self.scene_ed.sel + 1)
        self.apply()

    def deco_remove(self, _b=None):
        i = self.scene_ed.sel
        if self.scene_ed.selected() is None:
            return
        del self.cfg["box"]["items"][i]
        self.sound.play("pop_down")
        self.scene_ed.select(None)
        self.apply()

    def deco_layer(self, d):
        i, items = self.scene_ed.sel, self.cfg["box"]["items"]
        if self.scene_ed.selected() is None:
            return
        j = min(max(i + d, 0), len(items) - 1)
        items.insert(j, items.pop(i))
        self.scene_ed.select(j)
        self.apply()

    def deco_clear(self, _b):
        self.cfg["box"]["items"] = []
        self.scene_ed.select(None)
        self.apply()

    def on_shuffle(self, _b):
        for it in self.cfg["box"]["items"]:
            it["x"] = round(random.uniform(0.08, 0.92), 3)
            it["seed"] = random.randint(1, 99999)
        self.apply()

    def on_sky_reset(self, _b):
        self.cfg["box"].update(sky_x=0.5, sky_y=0.5, sky_zoom=1.0)
        self.sync_box_sliders()
        self.apply()

    def add_picture(self, kind, path=None):
        if path is None:
            dialog = Gtk.FileChooserDialog(title="Pick a picture", transient_for=self,
                                           action=Gtk.FileChooserAction.OPEN)
            dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
            filt = Gtk.FileFilter()
            filt.set_name("Images")
            filt.add_pixbuf_formats()
            dialog.add_filter(filt)
            pictures = Path.home() / "Pictures"
            if pictures.is_dir():
                dialog.set_current_folder(str(pictures))
            path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
            dialog.destroy()
        if not path:
            return None
        try:
            item_id = library.import_image(kind, path)
        except Exception as e:
            err = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                    buttons=Gtk.ButtonsType.OK, text="Couldn't use that picture")
            err.format_secondary_text(str(e))
            err.run()
            err.destroy()
            return None
        self.sound.play("pop_up")
        if kind == "accessories":
            self.fill_custom()
            self.custom_tiles[item_id].set_active(True)   # puts it on (and picks it)
        elif kind == "decorations":
            self.fill_decos()
            self.deco_add(item_id)
        else:
            which = "ground" if kind == "grounds" else "sky"
            if kind == "skies":
                self.cfg["box"].update(sky_x=0.5, sky_y=0.5, sky_zoom=1.0)
                self.sync_box_sliders()
            self.fill_choice(which)
            self.choice_buttons[which][item_id].set_active(True)
        return item_id

    def delete_picture(self, kind, item_id):
        library.delete(kind, item_id)
        self.sound.play("pop_down")
        box = self.cfg["box"]
        if kind == "accessories":
            if item_id in self.cfg["accessories"]:
                del self.cfg["accessories"][item_id]
                if self.room.sel == item_id:
                    self.room.select(None)
            self.fill_custom()
        elif kind == "decorations":
            box["items"] = [it for it in box["items"] if it["kind"] != item_id]
            self.scene_ed.select(None)
            self.fill_decos()
        elif kind == "grounds":
            if box["ground"] == item_id:
                box["ground"] = config.DEFAULTS["box"]["ground"]
            self.fill_choice("ground")
        else:
            if box["background"] == item_id:
                box["background"] = config.DEFAULTS["box"]["background"]
            self.fill_choice("sky")
        self.apply()

    def anim_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_end=12)

        # presets
        c = self.card("Preset", "Pick a built-in feel or one you saved")
        row = Gtk.Box(spacing=8)
        self.preset_combo = Gtk.ComboBoxText(hexpand=True)
        self.preset_combo.connect("changed", self.on_preset)
        row.pack_start(self.preset_combo, True, True, 0)
        for text, icon, cb, tip, attr in (
            ("Save", "document-save-symbolic", self.on_save, "Save changes to this preset", None),
            ("Save as…", "document-save-as-symbolic", self.on_save_as, "Save as a new preset", None),
            ("Delete", "edit-delete-symbolic", self.on_delete, "Delete this saved preset", "delete_btn"),
            ("Reset to default", "view-refresh-symbolic", self.on_reset_anim, "Back to the Default animation", None),
        ):
            btn = icon_button(text, icon, tip)
            btn.connect("clicked", cb)
            row.pack_start(btn, False, False, 0)
            if attr:
                setattr(self, attr, btn)
        c.pack_start(row, False, False, 0)
        self.modified = label("", "modified")
        self.modified.set_no_show_all(True)
        c.pack_start(self.modified, False, False, 0)
        page.pack_start(c, False, False, 0)

        # curves
        self.play_btn = icon_button("Play", "media-playback-start-symbolic", "Play the box opening in the preview")
        self.play_btn.connect("clicked", self.on_play)
        self.play_btn.set_no_show_all(True)
        c = self.card("Curves", "Drag points · double-click to add one · right-click to delete", self.play_btn)
        seg = css_class(Gtk.Box(), "segmented")
        self.curve_btns, group = {}, None
        for key, (title, *_rest) in anim.CURVES.items():
            b = Gtk.RadioButton(group=group, label=title)
            group = group or b
            b.set_mode(False)
            b.snd = "select"
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self.on_curve_pick(k))
            seg.pack_start(b, True, True, 0)
            self.curve_btns[key] = b
        c.pack_start(seg, False, False, 0)
        self.editor = CurveEditor(lambda key: self.cfg["animation"]["curves"][key], self.on_curve_edit,
                                  lambda: self.pet.colors, self.playhead, self.curve_sound)
        self.editor.set_size_request(-1, 230)
        c.pack_start(self.editor, False, False, 0)
        self.curve_help = label("", "card-sub", wrap=True)
        c.pack_start(self.curve_help, False, False, 0)
        page.pack_start(c, False, False, 0)

        # the numbers, two cards per row
        grid = Gtk.Grid(column_spacing=16, row_spacing=16, column_homogeneous=True)
        self.params = {}
        for i, (group_name, keys) in enumerate(anim.GROUPS):
            c = self.card(group_name)
            for key in keys:
                title, lo, hi, step, digits, _default, unit = anim.PARAMS[key]
                s = self.slider(lo, hi, step, digits, self.cfg["animation"][key], unit,
                                lambda sc, k=key: self.on_param(sc, k))
                self.params[key] = s
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                hint = f"  ·  {anim.HINTS[key]}" if key in anim.HINTS else ""
                box.pack_start(label(title + hint, "row-title"), False, False, 0)
                box.pack_start(s, False, False, 0)
                c.pack_start(box, False, False, 0)
            grid.attach(c, i % 2, i // 2, 1, 1)
        page.pack_start(grid, False, False, 0)

        self.fill_presets()
        self.update_modified()
        return page

    def fun_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_end=12)
        filt = Gtk.FileFilter()          # for the falling-picture chooser
        filt.set_name("Images")
        filt.add_pixbuf_formats()
        pictures = Path.home() / "Pictures"

        c = self.card("Catch game", "Throw your pet up and catch it on the way down: +1, or +2 off a wall, +3 off "
                                    "two sides. Catches count in a row; let it land and the streak's over. "
                                    "Your best shows in the box")
        self.game_switch = Gtk.Switch(active=self.cfg["game"], halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        self.game_switch.connect("notify::active", self.on_switch, "game")
        c.pack_start(self.setting_row("Catch game", self.game_switch), False, False, 0)
        self.pet_sound_switch = Gtk.Switch(active=self.cfg["pet_sounds"], halign=Gtk.Align.END,
                                           valign=Gtk.Align.CENTER)
        self.pet_sound_switch.connect("notify::active", self.on_switch, "pet_sounds")
        c.pack_start(self.setting_row("Pet sounds", self.pet_sound_switch, "A moo (or “weee!” for other pets) when thrown, a blip when caught"),
                     False, False, 0)
        row = Gtk.Box(spacing=12)
        self.best_label = label(f"Best: {self.pet.best}", "row-title")
        row.pack_start(self.best_label, False, False, 0)
        reset = icon_button("Reset best", "edit-clear-symbolic")
        reset.connect("clicked", self.on_reset_best)
        row.pack_end(reset, False, False, 0)
        c.pack_start(row, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Music", "When something's playing (Spotify, mpv, a browser tab... anything playerctl "
                               "sees), your pet dances. A new move every few bars, with breathers in between")
        self.dance_switches = {}
        for key, title, sub in (
            ("enabled", "Dances to music", None),
            ("beat", "Dance in time", "Listens with cava to find the beat" if music.have_cava()
             else "Install cava to dance in time with the song; without it, a steady 120 BPM"),
            ("notes", "Music notes", "Little notes float up off it on the beat"),
        ):
            sw = Gtk.Switch(active=self.cfg["dance"][key], halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
            sw.connect("notify::active", self.on_dance, key)
            if key == "beat" and not music.have_cava():
                sw.set_sensitive(False)
            c.pack_start(self.setting_row(title, sw, sub), False, False, 0)
            self.dance_switches[key] = sw
        page.pack_start(c, False, False, 0)

        c = self.card("Vehicles", "Now and then your pet hops on something and goes for a ride instead of "
                                  "walking. Picking it up ends the ride")
        self.ride_switch = Gtk.Switch(active=self.cfg["ride"]["enabled"], halign=Gtk.Align.END,
                                      valign=Gtk.Align.CENTER)
        self.ride_switch.connect("notify::active", self.on_ride_switch)
        c.pack_start(self.setting_row("Goes for rides", self.ride_switch), False, False, 0)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=2, max_children_per_line=5, column_spacing=10, row_spacing=10)
        group, self.ride_buttons, self.ride_tiles, self.ride_hover = None, {}, {}, None
        for key, title in (*vehicles.KINDS.items(), ("random", "Surprise me")):
            b = Gtk.RadioButton(group=group)
            group = group or b
            b.set_mode(False)
            css_class(b, "tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = Gtk.DrawingArea()
            pic.set_size_request(118, 70)
            pic.connect("draw", self.draw_ride_tile, key)
            self.ride_tiles[key] = pic
            inner.pack_start(pic, False, False, 0)
            inner.pack_start(label(title, "tile-label", xalign=0.5), False, False, 0)
            b.add(inner)
            b.snd = "select"
            b.connect("enter-notify-event", self.on_ride_hover, key)
            b.connect("leave-notify-event", self.on_ride_hover, None)
            flow.add(b)
            self.ride_buttons[key] = b
        self.ride_buttons[self.cfg["ride"]["vehicle"]].set_active(True)
        for key, b in self.ride_buttons.items():
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self.on_ride_vehicle(k))
        c.pack_start(flow, False, False, 0)
        self.ride_every = self.slider(config.RIDE_MIN, config.RIDE_MAX, 1, 0, self.cfg["ride"]["every"], " min",
                                      self.on_ride_every)
        c.pack_start(self.setting_row("How often", self.ride_every, "Minutes between rides, roughly"),
                     False, False, 0)
        go = icon_button("Ride now", "media-playback-start-symbolic", "Hop on now")
        go.set_halign(Gtk.Align.START)
        go.connect("clicked", lambda _b: self.pet.ride_now())
        c.pack_start(go, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Reactions", "Your pet cheers when something finishes downloading")
        self.react_switches = {}
        for key, text, sub in (
            ("packages", "Package installs",
             "apt, pacman, AUR helpers, emerge, dnf, zypper, flatpak… finishing (sad if it failed)"),
            ("downloads", "Downloads", "A file finishing in your Downloads folder"),
            ("bubble", "Speech bubble", "Says what finished"),
        ):
            sw = Gtk.Switch(active=self.cfg["reactions"][key], halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
            sw.connect("notify::active", self.on_reaction, key)
            c.pack_start(self.setting_row(text, sw, sub), False, False, 0)
            self.react_switches[key] = sw
        test = icon_button("Try it", "media-playback-start-symbolic", "Make your pet react now")
        test.set_halign(Gtk.Align.START)
        test.connect("clicked", lambda _b: self.pet.on_finished("download", True, "test done"))
        c.pack_start(test, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Idle behaviour", "What your pet gets up to when it isn't walking")
        self.beh_switches = {}
        for key, text, sub in (
            ("watch", "Watch the cursor", "Stops and turns to look when the mouse comes close (Larry's eyes follow it)"),
            ("sit", "Sit down", "Takes a seat now and then (Larry; other pets just stand)"),
            ("sleep", "Fall asleep", "Dozes off when you leave the mouse alone; bring it close to wake it"),
        ):
            sw = Gtk.Switch(active=self.cfg["behavior"][key], halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
            sw.connect("notify::active", self.on_behavior, key)
            c.pack_start(self.setting_row(text, sw, sub), False, False, 0)
            self.beh_switches[key] = sw
        self.sleep_after = self.slider(config.SLEEP_MIN, config.SLEEP_MAX, 5, 0, self.cfg["behavior"]["sleep_after"],
                                       " s", self.on_sleep_after)
        c.pack_start(self.setting_row("Falls asleep after", self.sleep_after, "Seconds of a still mouse"), False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Falling", "A different picture while it's thrown, falling or held")
        self.fall_switch = Gtk.Switch(active=self.cfg["fall_image"] != "none", halign=Gtk.Align.END,
                                      valign=Gtk.Align.CENTER)
        self.fall_switch.connect("notify::active", self.on_fall_switch)
        c.pack_start(self.setting_row("Falling pose", self.fall_switch,
                                      "Larry stands up with his arms in the air (other pets need a picture below)"), False, False, 0)
        row = Gtk.Box(spacing=8)
        self.fall_chooser = Gtk.FileChooserButton(title="Choose a falling picture", action=Gtk.FileChooserAction.OPEN)
        self.fall_chooser.add_filter(filt)
        if pictures.is_dir():
            self.fall_chooser.set_current_folder(str(pictures))
        self.fall_chooser.connect("file-set", self.on_fall_image)
        row.pack_start(self.fall_chooser, True, True, 0)
        back = icon_button("Larry's", "view-refresh-symbolic", "Back to Larry's arms-up pose")
        back.connect("clicked", self.on_fall_reset)
        row.pack_start(back, False, False, 0)
        c.pack_start(self.setting_row("Falling picture", row, "Drawn centred on the pet, no accessories"),
                     False, False, 0)
        self.show_fall_image()
        page.pack_start(c, False, False, 0)

        c = self.card("Typing in your terminal", "Napping in a terminal while you're away, your pet wakes up now and "
                                                "then and types something silly there. It only shows on screen (never "
                                                "typed into your shell) and only at a prompt, never over a program")
        self.chat_switch = Gtk.Switch(active=self.cfg["chat"]["typing"], halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        self.chat_switch.connect("notify::active", self.on_chat_switch)
        c.pack_start(self.setting_row("Types messages", self.chat_switch, "Off by default; needs Fall asleep on"),
                     False, False, 0)
        self.chat_every = self.slider(config.CHAT_MIN, config.CHAT_MAX, 1, 0, self.cfg["chat"]["every"], " min",
                                      self.on_chat_every)
        c.pack_start(self.setting_row("How often", self.chat_every, "Minutes between messages (3 per nap at most)"),
                     False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("Terminals", "Drag your pet onto a terminal and let go: it moves in and walks along the "
                                   "bottom. Drop it above a window instead to stand on top")
        self.term_switch = Gtk.Switch(active=self.cfg["terminals"]["enabled"], halign=Gtk.Align.END,
                                      valign=Gtk.Align.CENTER)
        self.term_switch.connect("notify::active", self.on_term_switch)
        c.pack_start(self.setting_row("Live in terminals", self.term_switch, "Grab it again to take it back out"),
                     False, False, 0)
        self.term_classes = Gtk.Entry(text=", ".join(self.cfg["terminals"]["classes"]), hexpand=True)
        self.term_classes.connect("changed", self.on_term_classes)
        c.pack_start(self.setting_row("Terminal apps", self.term_classes,
                                      "Window classes, comma separated (hyprctl clients shows them)"), False, False, 0)
        page.pack_start(c, False, False, 0)

        return page

    def theme_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_end=12)
        c = self.card("Theme", "Desktop follows your rice theme if you use it, otherwise your GTK theme")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=2, max_children_per_line=4, column_spacing=12, row_spacing=12)
        group, self.theme_buttons, self.theme_tiles = None, {}, []
        for key, (title, _pal, _light) in themes.THEMES.items():
            b = Gtk.RadioButton(group=group)
            group = group or b
            b.set_mode(False)
            css_class(b, "tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = Gtk.DrawingArea()
            pic.set_size_request(150, 88)
            pic.connect("draw", self.draw_theme_tile, key)
            self.theme_tiles.append(pic)
            inner.pack_start(pic, False, False, 0)
            inner.pack_start(label(title, "tile-label", xalign=0.5), False, False, 0)
            b.add(inner)
            b.snd = "select"
            flow.add(b)
            self.theme_buttons[key] = b
        self.theme_buttons[self.cfg["theme"]].set_active(True)
        for key, b in self.theme_buttons.items():
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self.on_theme(k))
        c.pack_start(flow, False, False, 0)
        page.pack_start(c, False, False, 0)

        c = self.card("The box")
        self.match_switch = Gtk.Switch(active=self.cfg["box"]["match_theme"], halign=Gtk.Align.END,
                                       valign=Gtk.Align.CENTER)
        self.match_switch.connect("notify::active", self.on_match_theme)
        c.pack_start(self.setting_row("Box matches the theme", self.match_switch,
                                      "The built-in skies (day, sunset, night) take on the theme's colours; "
                                      "your own sky pictures stay as they are"), False, False, 0)
        page.pack_start(c, False, False, 0)
        return page

    def on_match_theme(self, sw, _p):
        if not self.syncing and self.cfg["box"]["match_theme"] != sw.get_active():
            self.cfg["box"]["match_theme"] = sw.get_active()
            self.apply()

    def draw_theme_tile(self, area, cr, key):
        """A tiny settings window in the theme's colours."""
        w, h = area.get_allocated_width(), area.get_allocated_height()
        c = self.pet.theme_preview(key)
        rounded(cr, 0, 0, w, h, 14)
        cr.set_source_rgb(*c["bg0"])
        cr.fill_preserve()
        cr.set_source_rgba(*c["accent"], 0.35)
        cr.set_line_width(1)
        cr.stroke()
        rounded(cr, 6, 6, w * 0.26, h - 12, 7)               # sidebar
        cr.set_source_rgb(*c["bg1"])
        cr.fill()
        rounded(cr, 10, 14, w * 0.26 - 8, 9, 4)                # selected nav item
        cr.set_source_rgba(*c["accent2"], 0.7)
        cr.fill()
        for i in range(3):
            rounded(cr, 12, 30 + i * 12, w * 0.26 - 16, 5, 2.5)
            cr.set_source_rgba(*c["fg"], 0.35)
            cr.fill()
        x0 = w * 0.26 + 14
        rounded(cr, x0, 10, w - x0 - 8, h - 20, 8)             # a card
        cr.set_source_rgb(*c["bg1"])
        cr.fill()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(15)
        cr.move_to(x0 + 9, 34)
        cr.set_source_rgb(*c["fg"])
        cr.show_text("Aa")
        rounded(cr, x0 + 9, 46, (w - x0 - 26) * 0.75, 6, 3)    # a slider
        cr.set_source_rgba(*c["fg"], 0.15)
        cr.fill()
        rounded(cr, x0 + 9, 46, (w - x0 - 26) * 0.45, 6, 3)
        cr.set_source_rgb(*c["accent2"])
        cr.fill()
        rounded(cr, w - 40, h - 30, 24, 13, 6.5)               # a switch, on
        cr.set_source_rgb(*c["accent2"])
        cr.fill()
        cr.arc(w - 22.5, h - 23.5, 4.5, 0, 2 * math.pi)
        cr.set_source_rgb(*((1, 1, 1) if themes.is_light(c) else c["fg"]))
        cr.fill()

    def on_theme(self, key):
        if self.syncing or self.cfg["theme"] == key:
            return
        self.cfg["theme"] = key
        self.apply()            # the pet recolours, then calls restyle() on this window

    def acc_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_end=12)

        c = self.card("Fitting room", "Click an accessory to pick it, then drag, resize and rotate it to fit your pet")
        self.room = FittingRoom(lambda: self.cfg, lambda: self.pet.colors, self.on_room_change,
                                self.on_room_select, self.curve_sound)
        c.pack_start(self.room, False, False, 0)

        self.acc_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        bar = Gtk.Box(spacing=8)
        self.acc_name = label("Nothing picked", "acc-name")
        bar.pack_start(self.acc_name, True, True, 0)
        self.acc_buttons = []
        for text, icon, tip, cb in (
            ("Forward", "go-up-symbolic", "Draw it over the other accessories", lambda b: self.acc_layer(1)),
            ("Back", "go-down-symbolic", "Draw it under the other accessories", lambda b: self.acc_layer(-1)),
            ("Reset spot", "view-refresh-symbolic", "Put it back where it started", self.acc_reset),
            ("Take off", "edit-delete-symbolic", "Remove it from your pet", self.acc_remove),
        ):
            btn = icon_button(text, icon, tip)
            btn.connect("clicked", cb)
            bar.pack_start(btn, False, False, 0)
            self.acc_buttons.append(btn)
        self.acc_controls.pack_start(bar, False, False, 0)
        grid = Gtk.Grid(column_spacing=24, row_spacing=4, column_homogeneous=True)
        self.acc_scale = self.slider(accessories.SCALE_MIN * 100, accessories.SCALE_MAX * 100, 1, 0, 30, "%",
                                     lambda sc: self.acc_set("scale", round(sc.get_value() / 100, 4)))
        self.acc_rot = self.slider(-180, 180, 1, 0, 0, "°", lambda sc: self.acc_set("rotate", round(sc.get_value(), 1)))
        for i, (title, widget) in enumerate((("Size  ·  compared to your pet's height", self.acc_scale),
                                             ("Rotation", self.acc_rot))):
            grid.attach(label(title, "row-title"), i, 0, 1, 1)
            grid.attach(widget, i, 1, 1, 1)
        self.acc_controls.pack_start(grid, False, False, 0)
        flags = Gtk.Box(spacing=28)
        self.acc_flags = {}
        for key, text in (("flip", "Mirror"), ("behind", "Behind pet")):
            sw = Gtk.Switch(valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda w, _p, k=key: self.acc_set(k, w.get_active()))
            row = Gtk.Box(spacing=10)
            row.pack_start(sw, False, False, 0)
            row.pack_start(label(text, "row-title"), False, False, 0)
            flags.pack_start(row, False, False, 0)
            self.acc_flags[key] = sw
        self.acc_controls.pack_start(flags, False, False, 0)
        c.pack_start(self.acc_controls, False, False, 0)
        page.pack_start(c, False, False, 0)

        page.pack_start(self.seasonal_card(), False, False, 0)

        bare = icon_button("Take everything off", "edit-clear-all-symbolic")
        bare.connect("clicked", self.acc_clear)
        c = self.card("Wardrobe", "Click to put on or take off", bare)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=4, max_children_per_line=8, column_spacing=10, row_spacing=10)
        self.wardrobe = {}
        self.wardrobe_flow = flow
        for acc_id, (title, *_rest) in accessories.PREMADE.items():
            t = self.acc_tile(acc_id, title)
            flow.add(t)
            self.wardrobe[acc_id] = t
        for acc_id in accessories.owned_seasonal():
            self.add_to_wardrobe(acc_id)
        c.pack_start(flow, False, False, 0)
        page.pack_start(c, False, False, 0)

        add = icon_button("Add picture…", "list-add-symbolic", "Use any image as an accessory")
        add.connect("clicked", self.acc_add_picture)
        c = self.card("Your pictures", "Any image works; solid backgrounds get cut out automatically", add)
        self.custom_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                       min_children_per_line=4, max_children_per_line=8,
                                       column_spacing=10, row_spacing=10)
        c.pack_start(self.custom_flow, False, False, 0)
        self.custom_empty = label("Nothing here yet: add a picture and it shows up as something to wear",
                                  "card-sub", xalign=0.5)
        self.custom_empty.set_no_show_all(True)
        c.pack_start(self.custom_empty, False, False, 6)
        page.pack_start(c, False, False, 0)
        self.fill_custom()
        self.update_acc_controls()
        return page

    def acc_tile(self, acc_id, title):
        t = css_class(Gtk.ToggleButton(active=acc_id in self.cfg["accessories"]), "tile")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pic = Gtk.DrawingArea()
        pic.set_size_request(84, 62)
        pic.connect("draw", lambda w, cr: self.draw_acc_tile(cr, w.get_allocated_width(),
                                                             w.get_allocated_height(), acc_id))
        inner.pack_start(pic, False, False, 0)
        name = label(title, "tile-label", xalign=0.5)
        name.set_ellipsize(3)  # Pango.EllipsizeMode.END
        name.set_max_width_chars(12)
        inner.pack_start(name, False, False, 0)
        t.add(inner)
        t.connect("toggled", lambda b: self.acc_wear(acc_id, b.get_active()))
        return t

    def add_to_wardrobe(self, acc_id, hook=False):
        t = self.acc_tile(acc_id, accessories.title(acc_id))
        if hook:
            self.hook_sounds(t)
        self.wardrobe_flow.add(t)
        self.wardrobe[acc_id] = t
        t.show_all()

    # ── seasonal ────────────────────────────────────────────────────────────
    def seasonal_card(self):
        c = self.card("Seasonal", " ")
        self.season_sub = c.get_children()[0].get_children()[-1]
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=4, max_children_per_line=8, column_spacing=10, row_spacing=10)
        self.season_tiles = {}
        self.claim_fx = {}                 # acc_id -> when it was claimed (the sparkle burst)
        for acc_id in accessories.SEASONAL:
            t = css_class(Gtk.Button(), "tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = Gtk.DrawingArea()
            pic.set_size_request(84, 62)
            pic.connect("draw", lambda w, cr, a=acc_id: self.draw_season_tile(cr, w.get_allocated_width(),
                                                                              w.get_allocated_height(), a))
            inner.pack_start(pic, False, False, 0)
            name = label(accessories.title(acc_id), "tile-label", xalign=0.5)
            name.set_ellipsize(3)
            name.set_max_width_chars(12)
            inner.pack_start(name, False, False, 0)
            status = css_class(label("", "season-status", xalign=0.5), "season-status")
            status.set_halign(Gtk.Align.CENTER)
            inner.pack_start(status, False, False, 0)
            t.add(inner)
            t.pic, t.status, t.no_snd = pic, status, True    # plays its own sounds
            t.connect("clicked", lambda b, a=acc_id: self.on_season_tile(a))
            flow.add(t)
            self.season_tiles[acc_id] = t
        c.pack_start(flow, False, False, 0)
        self.update_seasonal()
        GLib.timeout_add_seconds(600, lambda: self.update_seasonal() or True)   # the date can roll over
        return c

    @staticmethod
    def short_date(d):
        return f"{d:%b} {d.day}"

    def update_seasonal(self):
        A = accessories
        live = [k for k in A.SEASONS if A.in_season(k)]
        open_now = [k for k in A.SEASONAL if A.claimable(k)]
        if open_now:
            season = A.SEASONAL[open_now[0]][4]
            sub = (f"{A.SEASONS[season][0]} is here! Claim these before {self.short_date(A.season_ends(season))} "
                   "and they're yours to keep, even after the season's over")
        else:
            nxt = min(A.SEASONS, key=lambda k: A.season_starts(k))
            when = A.season_starts(nxt)
            sub = ("Holiday accessories show up here around their holiday. Claim them while they're around "
                   f"and they stay in your wardrobe for good. Next up: {A.SEASONS[nxt][0]} on {self.short_date(when)}")
            if live:
                sub = f"You've claimed everything for {A.SEASONS[live[0]][0]}. " + sub.split(". ", 1)[1]
        self.season_sub.set_text(sub)
        for acc_id, t in self.season_tiles.items():
            ctx, st = t.get_style_context(), t.status.get_style_context()
            for cls in ("claim", "owned", "locked"):
                ctx.remove_class(cls)
                st.remove_class(cls)
            if A.claimed(acc_id):
                state, text = "owned", "Yours"
            elif acc_id in open_now:
                state, text = "claim", "Claim"
            else:
                state = "locked"
                text = "Back " + self.short_date(A.season_starts(A.SEASONAL[acc_id][4]))
            ctx.add_class(state)
            st.add_class(state)
            t.status.set_text(text)
            t.state = state
            t.set_tooltip_text({"claim": "Click to keep it forever",
                                "owned": "Click to put it on or take it off",
                                "locked": f"Only claimable around {A.SEASONS[A.SEASONAL[acc_id][4]][0]}"}[state])
            t.pic.queue_draw()
        if hasattr(self, "claim_dot"):
            self.claim_dot.set_visible(bool(open_now))

    def on_season_tile(self, acc_id):
        t = self.season_tiles[acc_id]
        if t.state == "owned":
            self.sound.play("click")
            w = self.wardrobe.get(acc_id)
            if w:
                w.set_active(not w.get_active())
            return
        if t.state != "claim" or not accessories.claim(acc_id):
            self.sound.play("grab")
            return
        self.sound.play("on")
        self.claim_fx[acc_id] = time.monotonic()
        GLib.timeout_add(16, self.tick_claim, acc_id)
        self.add_to_wardrobe(acc_id, hook=True)
        self.update_seasonal()
        self.wardrobe[acc_id].set_active(True)          # try it on straight away

    def tick_claim(self, acc_id):
        self.season_tiles[acc_id].pic.queue_draw()
        if time.monotonic() - self.claim_fx.get(acc_id, 0) > 1.0:
            self.claim_fx.pop(acc_id, None)
            return False
        return True

    def draw_season_tile(self, cr, w, h, acc_id):
        c = self.pet.colors
        state = getattr(self.season_tiles.get(acc_id), "state", "locked")
        rounded(cr, 0, 0, w, h, 14)
        cr.clip()
        cr.set_source_rgba(*c["fg"], 0.05)
        cr.paint()
        a = accessories.aspect(acc_id)
        k = min(w - 18, (h - 14) / a)
        age = time.monotonic() - self.claim_fx[acc_id] if acc_id in self.claim_fx else None
        pop = 1 + 0.25 * math.sin(math.pi * min(1, age / 0.35)) if age is not None else 1
        cr.save()
        cr.translate(w / 2, h / 2)
        cr.scale(k * pop, k * pop)
        if state == "locked":            # a mystery silhouette until its season
            cr.push_group()
            accessories.paint(cr, acc_id)
            pat = cr.pop_group()
            cr.set_source_rgba(*c["fg"], 0.22)
            cr.mask(pat)
        else:
            accessories.paint(cr, acc_id)
        cr.restore()
        if age is not None:              # a burst of little stars
            for i in range(10):
                ang = i * 2 * math.pi / 10 + 0.3
                d = (0.15 + 0.85 * min(1, age / 0.6)) * min(w, h) * 0.5
                r = 5 * (1 - min(1, age))
                x, y = w / 2 + d * math.cos(ang), h / 2 + d * math.sin(ang) * 0.8
                for j in range(10):
                    rr = r if j % 2 == 0 else r * 0.45
                    an = -math.pi / 2 + j * math.pi / 5
                    (cr.move_to if j == 0 else cr.line_to)(x + rr * math.cos(an), y + rr * math.sin(an))
                cr.close_path()
                cr.set_source_rgba(1, 0.8, 0.3, 1 - min(1, age))
                cr.fill()

    def fill_custom(self):
        for child in self.custom_flow.get_children():
            self.custom_flow.remove(child)
        self.custom_tiles = {}
        for acc_id, title in accessories.customs():
            t = self.acc_tile(acc_id, title)
            over = self.deletable(t, "accessories", acc_id)
            self.hook_sounds(over)
            self.custom_flow.add(over)
            self.custom_tiles[acc_id] = t
        self.custom_flow.show_all()
        self.custom_empty.set_visible(not self.custom_tiles)

    # ── accessories ─────────────────────────────────────────────────────────
    def head(self):
        if self.anchor is None:
            self.anchor = sprites.head_anchor(self.cfg)
        return self.anchor

    def acc_wear(self, acc_id, on):
        if self.syncing:
            return
        items = self.cfg["accessories"]
        if on and acc_id not in items:
            items[acc_id] = accessories.default_place(acc_id, self.head())
            self.room.select(acc_id)
        elif not on and acc_id in items:
            del items[acc_id]
            if self.room.sel == acc_id:
                self.room.select(None)
        self.room.queue_draw()
        self.apply()

    def tile_for(self, acc_id):
        return self.wardrobe.get(acc_id) or self.custom_tiles.get(acc_id)

    def set_tile(self, acc_id, on):
        t = self.tile_for(acc_id)
        if t and t.get_active() != on:
            was, self.syncing = self.syncing, True
            t.set_active(on)
            self.syncing = was

    def on_room_select(self, _acc_id):
        self.update_acc_controls()

    def on_room_change(self):
        self.update_acc_controls()
        self.acc_apply_soon()

    def acc_apply_soon(self):
        """Dragging changes things every frame; rebuild the real sprite once it settles."""
        if self.acc_timer:
            GLib.source_remove(self.acc_timer)
        self.acc_timer = GLib.timeout_add(120, self._acc_done)

    def _acc_done(self):
        self.acc_timer = None
        self.apply()
        return False

    def update_acc_controls(self):
        sel = self.room.sel if self.room.sel in self.cfg["accessories"] else None
        self.acc_controls.set_sensitive(bool(sel))
        was, self.syncing = self.syncing, True
        if sel:
            it = self.cfg["accessories"][sel]
            self.acc_name.set_text(accessories.title(sel))
            self.acc_scale.set_value(it["scale"] * 100)
            self.acc_rot.set_value(it["rotate"])
            for key, sw in self.acc_flags.items():
                sw.set_active(it[key])
            names = list(self.cfg["accessories"])
            self.acc_buttons[0].set_sensitive(names.index(sel) < len(names) - 1)
            self.acc_buttons[1].set_sensitive(names.index(sel) > 0)
        else:
            self.acc_name.set_text("Nothing picked" if self.cfg["accessories"] else "Not wearing anything")
        self.syncing = was

    def acc_set(self, key, value):
        sel = self.room.sel
        if self.syncing or sel not in self.cfg["accessories"]:
            return
        self.cfg["accessories"][sel][key] = value
        self.room.queue_draw()
        self.acc_apply_soon()

    def acc_layer(self, d):
        sel = self.room.sel
        names = list(self.cfg["accessories"])
        if sel not in names:
            return
        i = names.index(sel)
        j = min(max(i + d, 0), len(names) - 1)
        names.insert(j, names.pop(i))
        self.cfg["accessories"] = {k: self.cfg["accessories"][k] for k in names}
        self.update_acc_controls()
        self.room.queue_draw()
        self.apply()

    def acc_reset(self, _b):
        sel = self.room.sel
        if sel in self.cfg["accessories"]:
            self.cfg["accessories"][sel] = accessories.default_place(sel, self.head())
            self.update_acc_controls()
            self.room.queue_draw()
            self.apply()

    def acc_remove(self, _b):
        sel = self.room.sel
        if sel in self.cfg["accessories"]:
            self.sound.play("pop_down")
            self.set_tile(sel, False)
            self.acc_wear(sel, False)

    def acc_clear(self, _b):
        for acc_id in list(self.cfg["accessories"]):
            self.set_tile(acc_id, False)
        self.cfg["accessories"] = {}
        self.room.select(None)
        self.apply()

    def acc_add_picture(self, _b):
        self.add_picture("accessories")

    # ── look ────────────────────────────────────────────────────────────────
    def restyle(self):
        """The theme changed: recolour the window and everything drawn in it."""
        self.style()
        self.refresh()
        self.preview.queue_draw()
        self.show_page(self.stack.get_visible_child_name())
        for sq in self.squiggles:
            sq.queue_draw()
        for t in getattr(self, "theme_tiles", []):
            t.queue_draw()

    def style(self):
        c = self.pet.colors
        light = themes.is_light(c)
        mix = lambda x, y, t: hexc(scene.mix(c[x] if isinstance(x, str) else x, c[y] if isinstance(y, str) else y, t))
        bg0, bg1, fg = hexc(c["bg0"]), hexc(c["bg1"]), hexc(c["fg"])
        acc, acc2 = hexc(c["accent"]), hexc(c["accent2"])
        r, g, b = c["accent2"]
        on_acc = "#15121c" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 else "#ffffff"   # text on the accent
        base = mix("bg0", (0, 0, 0), 0.0 if light else 0.18)          # behind the panels
        panel = mix("bg0", "bg1", 0.45)                               # sidebar + main panel
        card = bg1                                                    # cards
        raised = mix("bg1", "fg", 0.06)                               # tiles, fields, tracks
        tonal = mix("bg1", "accent2", 0.16)                           # selected / tonal buttons
        tonal_hi = mix("bg1", "accent2", 0.26)
        muted = mix("fg", "bg1", 0.42)
        font = fonts.FAMILY
        css = f"""
        window.larry, window.larry * {{ font-family: "{font}", sans-serif; }}
        window.larry {{ background-color: {base}; color: {fg}; }}
        window.larry label {{ color: {fg}; }}
        .side-panel, .main-panel {{ background-color: {panel}; border-radius: 26px; }}
        .side-panel {{ padding: 18px 14px 14px 14px; }}
        .main-panel {{ padding: 24px 26px 0 26px; }}

        .brand-title {{ font-size: 20px; font-weight: 900; }}
        .brand-sub {{ font-size: 12px; font-weight: 600; color: {muted}; }}
        .section {{ margin: 14px 6px 4px 8px; }}
        .section-label {{ font-size: 12px; font-weight: 800; color: {muted}; }}

        window.larry .nav {{ background: transparent; border: none; border-radius: 999px;
                padding: 5px 14px 5px 5px; box-shadow: none; transition: background 180ms ease; }}
        window.larry .nav:hover {{ background: alpha({fg}, 0.06); box-shadow: none; }}
        window.larry .nav:checked {{ background: {tonal_hi}; box-shadow: none; }}
        .nav-icon {{ min-width: 32px; min-height: 32px; border-radius: 999px; }}
        .nav-icon image {{ color: {muted}; }}
        .nav:checked .nav-icon {{ background: {acc2}; }}
        .nav:checked .nav-icon image {{ color: {on_acc}; }}
        .nav-label {{ font-weight: 700; font-size: 14px; }}
        .side-card {{ background: {card}; border-radius: 20px; padding: 8px 12px 6px 6px; }}
        .saved {{ opacity: 0; background: {tonal}; color: {acc2}; font-weight: 800; font-size: 12px;
                  border-radius: 999px; padding: 6px 12px; transition: opacity 500ms ease; }}
        .saved.show {{ opacity: 1; transition: opacity 120ms ease; }}

        window.larry entry.search {{ background: {card}; border: none; border-radius: 999px; padding: 8px 14px;
                  box-shadow: none; }}
        window.larry entry.search:focus {{ box-shadow: inset 0 0 0 2px alpha({acc2}, 0.7); }}
        window.larry .results {{ background: transparent; margin-top: 6px; }}
        window.larry .results row {{ border-radius: 14px; }}
        window.larry .results row:hover {{ background: {tonal}; }}

        .page-title {{ font-size: 34px; font-weight: 900; }}
        .page-sub {{ color: {muted}; font-size: 14px; font-weight: 600; }}
        .sub-icon {{ min-width: 26px; min-height: 26px; border-radius: 999px; background: {tonal}; }}
        .sub-icon image {{ color: {acc2}; }}
        .card {{ background-color: {card}; border-radius: 24px; padding: 20px 22px; margin-bottom: 2px; }}
        .card.found {{ box-shadow: inset 0 0 0 2px {acc2}; background-color: {tonal}; }}
        .card-title {{ font-weight: 900; font-size: 18px; }}
        .card-sub, .row-sub {{ color: {muted}; font-size: 12.5px; font-weight: 600; }}
        .row-title {{ font-weight: 700; font-size: 14px; }}
        .modified {{ color: {acc2}; font-size: 12px; font-weight: 800; }}

        window.larry button {{ background: {tonal}; background-image: none; color: {fg}; border: none;
            border-radius: 999px; padding: 8px 16px; box-shadow: none; text-shadow: none; -gtk-icon-shadow: none;
            font-weight: 700; transition: background 150ms ease; }}
        window.larry button:hover {{ background: {tonal_hi}; box-shadow: none; }}
        window.larry button:active {{ background: alpha({acc2}, 0.45); }}
        window.larry button:disabled {{ opacity: 0.35; }}
        window.larry button image {{ color: {acc2}; }}
        window.larry .chip {{ border-radius: 999px; padding: 8px 14px; }}
        window.larry .chip:checked, window.larry .segmented button:checked {{ background: {acc2}; color: {on_acc}; }}
        window.larry .chip:checked label, window.larry .segmented button:checked label,
        window.larry .chip:checked image, window.larry .segmented button:checked image {{ color: {on_acc}; }}
        window.larry .segmented button {{ border-radius: 6px; margin: 0 1px; }}
        window.larry .segmented button:first-child {{ border-radius: 999px 6px 6px 999px; }}
        window.larry .segmented button:last-child {{ border-radius: 6px 999px 999px 6px; }}
        window.larry .tile {{ background: {raised}; padding: 8px; border-radius: 20px; }}
        window.larry .tile:hover {{ background: {tonal}; }}
        window.larry .tile:checked {{ background: {tonal_hi}; box-shadow: inset 0 0 0 2px {acc2}; }}
        .tile-label {{ font-size: 12.5px; font-weight: 700; }}
        .season-status {{ font-size: 11px; font-weight: 800; border-radius: 999px; padding: 1px 10px; }}
        .season-status.claim {{ background: {acc2}; color: {on_acc}; }}
        .season-status.owned {{ color: {acc2}; }}
        .season-status.locked {{ color: {muted}; }}
        window.larry .tile.claim {{ box-shadow: inset 0 0 0 2px {acc2}; }}
        window.larry .claim-dot {{ min-width: 8px; min-height: 8px; border-radius: 999px; background: {acc2}; }}
        window.larry .tile-x {{ padding: 2px; margin: 4px; min-width: 20px; min-height: 20px; border-radius: 999px;
            background: alpha({bg0}, 0.85); opacity: 0.75; }}
        window.larry .tile-x:hover {{ opacity: 1; background: #e0455a; }}
        .acc-name {{ font-weight: 900; font-size: 16px; }}

        window.larry combobox button {{ padding: 7px 14px; }}
        menu, .menu {{ background: {card}; color: {fg}; border: none; border-radius: 16px; padding: 6px; }}
        menuitem {{ padding: 7px 12px; border-radius: 10px; }}
        menuitem:hover {{ background: {tonal_hi}; }}
        window.larry entry {{ background: {raised}; color: {fg}; border: none; border-radius: 14px;
                              padding: 8px 12px; box-shadow: none; }}
        window.larry entry:focus {{ box-shadow: inset 0 0 0 2px alpha({acc2}, 0.7); }}

        window.larry switch {{ background: {raised}; border: 2px solid alpha({fg}, 0.28); border-radius: 999px;
                  min-width: 48px; min-height: 26px; transition: all 180ms ease; }}
        window.larry switch:checked {{ background: {acc2}; border-color: {acc2}; }}
        window.larry switch slider {{ background: alpha({fg}, 0.55); border: 6px solid transparent;
                  background-clip: content-box; border-radius: 999px; box-shadow: none; min-width: 18px;
                  min-height: 18px; }}
        window.larry switch:checked slider {{ background: {on_acc}; border-width: 2px; }}

        window.larry scale {{ padding: 12px 8px; }}
        window.larry scale trough {{ background: {raised}; border: none; border-radius: 999px; min-height: 10px; }}
        window.larry scale highlight {{ background: {acc2}; border: none; border-radius: 999px; }}
        window.larry scale slider {{ background: {acc2}; border: 3px solid {card}; border-radius: 999px;
                  min-width: 6px; min-height: 26px; margin: -10px -3px; box-shadow: none; }}
        window.larry scale slider:hover, window.larry scale slider:active {{ background: {fg}; }}
        window.larry scale value {{ color: {muted}; font-weight: 700; min-width: 64px; }}

        window.larry scrollbar slider {{ background: alpha({fg}, 0.18); border-radius: 999px; min-width: 6px; border: none; }}
        window.larry scrollbar {{ background: transparent; border: none; }}
        window.larry scrolledwindow undershoot.top, window.larry scrolledwindow undershoot.bottom {{ background: none; }}
        """
        if getattr(self, "css", None) is None:
            self.css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(self.get_screen(), self.css,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.css.load_from_data(css.encode())

    # ── sounds ──────────────────────────────────────────────────────────────
    @staticmethod
    def pass_scroll(widget, _ev):
        """Sliders and dropdowns ignore the mouse wheel: it scrolls the page instead, so scrolling
        through the settings never changes one by accident (click or drag them to change them)."""
        widget.stop_emission_by_name("scroll-event")
        return False      # carry on up to the page

    def hook_sounds(self, widget):
        """Give every control its sound (skipped while the window is changing things itself), and
        stop sliders/dropdowns from eating the scroll wheel."""
        if getattr(widget, "no_snd", False):
            return
        if isinstance(widget, (Gtk.Scale, Gtk.ComboBox, Gtk.SpinButton)):
            widget.connect("scroll-event", self.pass_scroll)
        if isinstance(widget, Gtk.Scale):
            widget.connect("value-changed", self.snd_scale)
        elif isinstance(widget, Gtk.Switch):
            widget.connect("notify::active", lambda w, _p: self.snd("on" if w.get_active() else "off"))
        elif isinstance(widget, Gtk.RadioButton):
            widget.connect("toggled", lambda w: w.get_active() and self.snd(getattr(w, "snd", "select")))
        elif isinstance(widget, Gtk.ToggleButton):
            widget.connect("toggled", lambda w: self.snd("on" if w.get_active() else "off"))
        elif isinstance(widget, Gtk.Button):
            widget.connect("clicked", lambda w: self.snd("click"))
        elif isinstance(widget, Gtk.ComboBox):
            widget.connect("changed", lambda w: self.snd("select"))
        if isinstance(widget, Gtk.Container):
            widget.forall(self.hook_sounds)

    def snd(self, name):
        if not self.syncing:
            self.sound.play(name)

    def snd_scale(self, scale):
        if not self.syncing:
            adj = scale.get_adjustment()
            span = adj.get_upper() - adj.get_lower() or 1
            self.sound.tick((adj.get_value() - adj.get_lower()) / span)

    def curve_sound(self, name, frac=None):
        if name == "tick":
            self.sound.tick(frac)
        else:
            self.sound.play(name)

    # ── navigation ──────────────────────────────────────────────────────────
    # ── search ──────────────────────────────────────────────────────────────
    @staticmethod
    def label_text(widget, out):
        """Every bit of text in a card: its title, description, setting names and hints, tile names."""
        if isinstance(widget, Gtk.Label):
            out.append(widget.get_text())
        elif isinstance(widget, Gtk.Entry) and widget.get_placeholder_text():
            out.append(widget.get_placeholder_text())
        if isinstance(widget, Gtk.Container):
            widget.forall(lambda w: Settings.label_text(w, out))
        return out

    def find(self, query):
        words = query.lower().split()
        if not words:
            return []
        hits = []
        for hit in self.search_index:
            if hit["text"] is None:
                hit["text"] = " ".join(self.label_text(hit["card"], [])).lower()
            page_title = next(p[1] for p in PAGES if p[0] == hit["page"]).lower()
            hay = re.findall(r"\w+", hit["text"] + " " + page_title)
            # short words have to start a word in the card ("hat" finds "hats", not "that"); longer
            # ones can be anywhere in one ("sleep" finds "asleep")
            def found(w, tokens):
                return any(t.startswith(w) or (len(w) >= 4 and w in t) for t in tokens)
            if all(found(w, hay) for w in words):
                title = re.findall(r"\w+", hit["title"].lower())
                if all(found(w, title) for w in words):
                    rank = 0                                   # it's the card's name
                elif all(w in hay for w in words):
                    rank = 1                                   # whole words
                else:
                    rank = 2                                   # beginnings of words
                hits.append((rank, hit))
        return [h for _rank, h in sorted(hits, key=lambda x: x[0])]

    def on_search(self, entry):
        for row in self.results.get_children():
            self.results.remove(row)
        query = entry.get_text().strip()
        searching = bool(query)
        for b in self.nav.values():
            b.set_visible(not searching)
        hits = self.find(query)
        for hit in hits[:12]:
            row = Gtk.ListBoxRow()
            row.hit = hit
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, margin=8)
            box.pack_start(label(hit["title"], "row-title"), False, False, 0)
            page = next(p[1] for p in PAGES if p[0] == hit["page"])
            where = label(f"in {page}" + self.snippet(hit, query), "row-sub")
            where.set_ellipsize(3)   # Pango.EllipsizeMode.END
            box.pack_start(where, False, False, 0)
            row.add(box)
            row.show_all()
            self.results.add(row)
        self.results.set_visible(searching and bool(hits))
        self.no_results.set_visible(searching and not hits)

    def snippet(self, hit, query):
        """The setting inside the card that matched, if it wasn't the card's own title."""
        words = query.lower().split()
        if all(w in hit["title"].lower() for w in words):
            return ""
        for text in self.label_text(hit["card"], [])[1:]:
            if any(w in text.lower() for w in words) and len(text) < 60:
                return f"  ·  {text}"
        return ""

    def on_search_enter(self, _entry):
        rows = self.results.get_children()
        if rows:
            self.go_to(rows[0].hit)

    def go_to(self, hit):
        """Open the card's page, scroll it into view and make it glow for a moment."""
        self.nav[hit["page"]].set_active(True)
        self.show_page(hit["page"])

        def scroll():
            sw, page = self.pages[hit["page"]]
            coords = hit["card"].translate_coordinates(page, 0, 0)
            if coords:
                adj = sw.get_vadjustment()
                adj.set_value(min(max(coords[1] - 12, 0), adj.get_upper() - adj.get_page_size()))
            ctx = hit["card"].get_style_context()
            ctx.add_class("found")
            GLib.timeout_add(1400, lambda: (ctx.remove_class("found"), False)[1])
            return False
        GLib.timeout_add(260, scroll)   # after the page slides in

    def on_window_key(self, _w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and Gdk.keyval_name(ev.keyval) in ("f", "F"):
            self.search.grab_focus()
            return True
        if Gdk.keyval_name(ev.keyval) == "Escape" and self.search.get_text():
            self.search.set_text("")
            return True
        return False

    def on_nav(self, button, key):
        if button.get_active():
            self.show_page(key)

    def show_page(self, key):
        _k, title, icon, sub = next(p for p in PAGES if p[0] == key)
        self.stack.set_visible_child_name(key)
        self.page_title.set_markup(f'{GLib.markup_escape_text(title)}<span foreground="{hexc(self.pet.colors["accent2"])}"> •</span>')
        self.page_icon.set_from_icon_name(icon, Gtk.IconSize.MENU)
        self.page_sub.set_text(sub)

    # ── changes ─────────────────────────────────────────────────────────────
    def sync(self, cfg):
        """Config changed elsewhere (hand edit): move the controls to match without re-saving."""
        self.syncing = True
        self.cfg = copy.deepcopy(cfg)
        self.chooser.set_filename(cfg["image"])
        if self.name_entry.get_text().strip() != cfg["name"]:
            self.name_entry.set_text(cfg["name"])
        self.brand.set_text(cfg["name"])
        self.set_title(f"{cfg['name']} settings")
        self.size.set_value(cfg["size"])
        for key, sw in self.switches.items():
            sw.set_active(cfg[key])
        self.term_switch.set_active(cfg["terminals"]["enabled"])
        self.fall_switch.set_active(cfg["fall_image"] != "none")
        for key, sw in self.beh_switches.items():
            sw.set_active(cfg["behavior"][key])
        self.sleep_after.set_value(cfg["behavior"]["sleep_after"])
        for key, sw in self.react_switches.items():
            sw.set_active(cfg["reactions"][key])
        self.game_switch.set_active(cfg["game"])
        self.chat_switch.set_active(cfg["chat"]["typing"])
        self.ride_switch.set_active(cfg["ride"]["enabled"])
        for key, sw in self.dance_switches.items():
            sw.set_active(cfg["dance"][key])
        self.ride_buttons[cfg["ride"]["vehicle"]].set_active(True)
        self.ride_every.set_value(cfg["ride"]["every"])
        self.chat_every.set_value(cfg["chat"]["every"])
        self.theme_buttons[cfg["theme"]].set_active(True)
        self.match_switch.set_active(cfg["box"]["match_theme"])
        self.pet_sound_switch.set_active(cfg["pet_sounds"])
        self.show_fall_image()
        if [c.strip() for c in self.term_classes.get_text().split(",") if c.strip()] != cfg["terminals"]["classes"]:
            self.term_classes.set_text(", ".join(cfg["terminals"]["classes"]))
        for which, key in (("ground", "ground"), ("sky", "background")):
            if cfg["box"][key] not in self.choice_buttons[which]:
                self.fill_choice(which)
            if cfg["box"][key] in self.choice_buttons[which]:
                self.choice_buttons[which][cfg["box"][key]].set_active(True)
        self.color_tiles[cfg["box"]["colors"]].set_active(True)
        self.sync_box_sliders()
        self.update_sky_controls()
        self.edge_tiles[cfg["tab"]["edge"]].set_active(True)
        self.tab_pos.set_value(cfg["tab"]["position"])
        self.load_anim_controls()
        for acc_id, t in {**self.wardrobe, **self.custom_tiles}.items():
            t.set_active(acc_id in cfg["accessories"])
        self.syncing = False
        self.room.select(self.room.sel, notify=False)
        self.update_acc_controls()
        self.scene_ed.select(self.scene_ed.sel, notify=False)
        self.update_deco_controls()
        self.refresh()

    def apply(self):
        if self.syncing:
            return
        try:
            self.cfg, moved = packs.sync(self.cfg)      # the pet you're using saves itself
        except Exception as e:
            print(f"larry: can't save the pet: {e}", file=sys.stderr)
            moved = False
        if moved:
            was, self.syncing = self.syncing, True
            self.chooser.set_filename(self.cfg["image"])
            self.syncing = was
        config.save(self.cfg)
        self.pet.set_config(copy.deepcopy(self.cfg))
        self.refresh()
        self.saved.get_style_context().add_class("show")
        if self.saved_timer:
            GLib.source_remove(self.saved_timer)
        self.saved_timer = GLib.timeout_add(900, self._hide_saved)

    def _hide_saved(self):
        self.saved.get_style_context().remove_class("show")
        self.saved_timer = None
        return False

    def refresh(self):
        self.zoom_sprites = None
        self.anchor = None
        self.room.queue_draw()
        self.scene_ed.queue_draw()
        for pics in self.choice_pics.values():
            for pic in pics:
                pic.queue_draw()
        self.fit_preview()
        self.thumb.queue_draw()
        self.avatar.queue_draw()
        for t in self.tiles:
            t.queue_draw()

    def on_sounds(self, sw, _p):
        self.cfg["sounds"] = sw.get_active()
        self.apply()

    def on_volume(self, scale):
        self.cfg["volume"] = int(scale.get_value())
        self.apply()

    def on_image(self, chooser):
        path = chooser.get_filename()
        if self.syncing or not path:
            return
        self.cfg["image"] = path
        # images without transparency almost always want their background cut out
        self.switches["remove_bg"].set_active(not sprites.has_transparency(path))
        self.apply()

    def on_name(self, entry):
        if self.syncing:
            return
        name = entry.get_text().strip() or config.DEFAULTS["name"]
        self.cfg["name"] = name
        self.brand.set_text(name)
        self.set_title(f"{name} settings")
        self.scene_apply_soon()   # saves once you pause typing

    def on_reset(self, _b):
        self.cfg.update({k: config.DEFAULTS[k] for k in ("image", "faces_left", "remove_bg")})
        self.syncing = True
        self.chooser.set_filename(self.cfg["image"])
        for key, sw in self.switches.items():
            sw.set_active(self.cfg[key])
        self.syncing = False
        self.apply()

    def on_size(self, scale):
        if self.syncing:
            return
        self.cfg["size"] = int(scale.get_value())
        # rebuilding on every pixel of a drag is wasteful; apply once it settles
        if self.size_timer:
            GLib.source_remove(self.size_timer)
        self.size_timer = GLib.timeout_add(120, self._size_done)

    def _size_done(self):
        self.size_timer = None
        self.apply()
        return False

    def show_fall_image(self):
        v = self.cfg["fall_image"]
        if v in ("auto", "none"):
            self.fall_chooser.set_filename(str(sprites.LARRY_FALLING))
        else:
            self.fall_chooser.set_filename(v)

    def on_fall_switch(self, sw, _p):
        if self.syncing:
            return
        if not sw.get_active():
            self.cfg["fall_image"] = "none"
        elif self.cfg["fall_image"] == "none":
            path = self.fall_chooser.get_filename()
            custom = path and Path(path).resolve() != sprites.LARRY_FALLING
            self.cfg["fall_image"] = path if custom else "auto"
        self.apply()

    def on_fall_image(self, chooser):
        path = chooser.get_filename()
        if self.syncing or not path:
            return
        self.cfg["fall_image"] = "auto" if Path(path).resolve() == sprites.LARRY_FALLING else path
        self.syncing = True
        self.fall_switch.set_active(True)
        self.syncing = False
        self.apply()

    def on_fall_reset(self, _b):
        self.cfg["fall_image"] = "auto"
        self.syncing = True
        self.fall_switch.set_active(True)
        self.show_fall_image()
        self.syncing = False
        self.apply()

    def on_behavior(self, sw, _p, key):
        if not self.syncing and self.cfg["behavior"][key] != sw.get_active():
            self.cfg["behavior"][key] = sw.get_active()
            self.apply()

    def on_dance(self, sw, _p, key):
        if not self.syncing and self.cfg["dance"][key] != sw.get_active():
            self.cfg["dance"][key] = sw.get_active()
            self.apply()

    def on_ride_switch(self, sw, _p):
        if not self.syncing and self.cfg["ride"]["enabled"] != sw.get_active():
            self.cfg["ride"]["enabled"] = sw.get_active()
            self.apply()

    def on_ride_vehicle(self, key):
        if self.syncing or self.cfg["ride"]["vehicle"] == key:
            return
        self.cfg["ride"]["vehicle"] = key
        self.apply()

    def on_ride_every(self, scale):
        if self.syncing:
            return
        self.cfg["ride"]["every"] = int(scale.get_value())
        self.scene_apply_soon()

    def on_ride_hover(self, _b, _ev, key):
        """The tile under the mouse drives along on the spot."""
        self.ride_hover = key
        if key and not getattr(self, "ride_timer", None):
            self.ride_timer = GLib.timeout_add(33, self.tick_ride_tile)

    def tick_ride_tile(self):
        for pic in self.ride_tiles.values():
            pic.queue_draw()
        if not self.ride_hover:
            self.ride_timer = None
            return False
        return True

    def draw_ride_tile(self, area, cr, key):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        c = self.pet.colors
        cr.set_source_rgba(*c["fg"], 0.12)                     # a road
        rounded(cr, 10, h - 9, w - 20, 3, 1.5)
        cr.fill()
        if key not in vehicles.KINDS:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(h * 0.55)
            ext = cr.text_extents("?")
            cr.move_to(w / 2 - ext.x_advance / 2, h / 2 + ext.height / 2 - 4)
            cr.set_source_rgba(*c["accent2"], 0.9)
            cr.show_text("?")
            return
        x0, x1, _top = vehicles.EXTENT[key]
        pet = self.pet
        top = pet.ride_top(key)
        L = min((h - 14) / top, (w - 12) / (x1 - x0))
        live = self.ride_hover == key
        t = time.monotonic() if live else 0.4
        dist = t * 90 if live else 30
        crank = vehicles.crank(key, dist, L)
        frame = int(crank / (2 * math.pi) * 8) % 8 if key == "bike" else 0

        cr.save()
        cr.translate(w / 2 - (x0 + x1) / 2 * L, h - 8)
        vehicles.draw(cr, key, L, lambda: pet.draw_rider(cr, key, L, 1, frame), t, dist, live,
                      head=pet.rider_head(key), pedal=pet.pedal_length(), halo=self.cfg["outline"])
        cr.restore()

    def on_reset_best(self, _b):
        self.pet.reset_best()

    def update_best(self):
        """The pet calls this when the record changes."""
        self.best_label.set_text(f"Best: {self.pet.best}")

    def on_chat_switch(self, sw, _p):
        if not self.syncing and self.cfg["chat"]["typing"] != sw.get_active():
            self.cfg["chat"]["typing"] = sw.get_active()
            self.apply()

    def on_chat_every(self, scale):
        if self.syncing:
            return
        self.cfg["chat"]["every"] = int(scale.get_value())
        self.scene_apply_soon()

    def on_reaction(self, sw, _p, key):
        if not self.syncing and self.cfg["reactions"][key] != sw.get_active():
            self.cfg["reactions"][key] = sw.get_active()
            self.apply()

    def on_sleep_after(self, scale):
        if self.syncing:
            return
        self.cfg["behavior"]["sleep_after"] = int(scale.get_value())
        self.scene_apply_soon()   # saves once you stop dragging

    def on_term_switch(self, sw, _p):
        if not self.syncing:
            self.cfg["terminals"]["enabled"] = sw.get_active()
            self.apply()

    def on_term_classes(self, entry):
        if self.syncing:
            return
        self.cfg["terminals"]["classes"] = [c.strip() for c in entry.get_text().split(",") if c.strip()]
        self.scene_apply_soon()   # saves once you pause typing

    def on_switch(self, sw, _param, key):
        if not self.syncing and self.cfg[key] != sw.get_active():
            self.cfg[key] = sw.get_active()
            self.apply()

    def set_tab(self, key, value):
        if not self.syncing and self.cfg["tab"][key] != value:
            self.cfg["tab"][key] = value
            self.apply()
            self.pet.peek()   # show where the box comes out now

    def set_box(self, key, value, soon=False):
        if not self.syncing and self.cfg["box"][key] != value:
            self.cfg["box"][key] = value
            if key == "background":
                self.update_sky_controls()
            self.scene_ed.queue_draw()
            if soon:
                self.scene_apply_soon()
            else:
                self.apply()

    # ── animation ───────────────────────────────────────────────────────────
    def load_anim_controls(self):
        was = self.syncing
        self.syncing = True
        self.fill_presets()
        for key, scale in self.params.items():
            scale.set_value(self.cfg["animation"][key])
        self.syncing = was
        self.editor.queue_draw()
        self.update_modified()

    def fill_presets(self):
        was = self.syncing
        self.syncing = True
        self.preset_combo.remove_all()
        for name in anim.BUILTINS:
            self.preset_combo.append(name, f"{name}  ·  built-in")
        for name in anim.user_names():
            self.preset_combo.append(name, name)
        if not self.preset_combo.set_active_id(self.cfg["animation"]["preset"]):
            self.cfg["animation"]["preset"] = "Default"
            self.preset_combo.set_active_id("Default")
        self.syncing = was

    def update_modified(self):
        name = self.cfg["animation"]["preset"]
        base = anim.get(name)
        changed = base is None or not anim.same(base, self.cfg["animation"])
        self.modified.set_text("●  Modified: save it to keep it as a preset")
        self.modified.set_visible(changed)
        self.delete_btn.set_sensitive(name not in anim.BUILTINS)

    def anim_values(self):
        return {k: v for k, v in self.cfg["animation"].items() if k != "preset"}

    def on_preset(self, combo):
        name = combo.get_active_id()
        if self.syncing or not name:
            return
        d = anim.get(name)
        if d is None:
            return
        self.cfg["animation"] = {"preset": name, **d}
        self.load_anim_controls()
        self.apply()

    def on_param(self, scale, key):
        if self.syncing:
            return
        step, digits = anim.PARAMS[key][3], anim.PARAMS[key][4]
        v = round(round(scale.get_value() / step) * step, digits)
        self.cfg["animation"][key] = int(v) if digits == 0 else v
        self.update_modified()
        self.apply()

    def on_curve_pick(self, key):
        key = key or next(k for k, b in self.curve_btns.items() if b.get_active())
        self.editor.set_key(key)
        self.play_btn.set_visible(key == "open")
        self.curve_help.set_text(anim.CURVES[key][3] + ".")

    def on_curve_edit(self):
        self.update_modified()
        self.apply()

    def playhead(self, key):
        if key == "open":
            if self.play_start is None:
                return None
            return min((time.monotonic() - self.play_start) / self.pet.anim.open_time, 1)
        return self.phase % 1

    def on_play(self, _b):
        self.play_start = time.monotonic()

    def ask_name(self, title, initial):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        css_class(dialog, "larry")
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        area = dialog.get_content_area()
        area.set_spacing(8)
        area.set_border_width(16)
        entry = Gtk.Entry(text=initial, activates_default=True)
        error = label("", "card-sub")
        area.pack_start(label("Preset name", "row-title"), False, False, 0)
        area.pack_start(entry, False, False, 0)
        area.pack_start(error, False, False, 0)
        dialog.show_all()
        name = None
        while dialog.run() == Gtk.ResponseType.OK:
            name = anim.valid_name(entry.get_text())
            if name:
                break
            taken = entry.get_text().strip() in anim.BUILTINS
            error.set_text("That's a built-in name, pick another" if taken else
                           "Use letters, numbers, spaces, . - + ( ) (up to 40)")
        else:
            name = None
        dialog.destroy()
        return name

    def on_save(self, _b):
        name = self.cfg["animation"]["preset"]
        if name in anim.BUILTINS or anim.get(name) is None:
            return self.on_save_as(None)
        anim.save(name, self.anim_values())
        self.update_modified()

    def on_save_as(self, _b):
        current = self.cfg["animation"]["preset"]
        name = self.ask_name("Save animation", "" if current in anim.BUILTINS else current)
        if not name:
            return
        anim.save(name, self.anim_values())
        self.cfg["animation"]["preset"] = name
        self.fill_presets()
        self.update_modified()
        self.apply()

    def on_delete(self, _b):
        name = self.cfg["animation"]["preset"]
        if name in anim.BUILTINS:
            return
        ask = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.OK_CANCEL, text=f"Delete the preset “{name}”?")
        css_class(ask, "larry")
        ask.format_secondary_text("Your pet keeps moving like this until you pick another preset.")
        ok = ask.run() == Gtk.ResponseType.OK
        ask.destroy()
        if not ok:
            return
        anim.delete(name)
        self.cfg["animation"]["preset"] = "Default"
        self.fill_presets()
        self.update_modified()
        self.apply()

    def on_reset_anim(self, _b):
        self.cfg["animation"] = {"preset": "Default", **anim.default()}
        self.load_anim_controls()
        self.apply()

    def on_destroy(self, *_):
        GLib.source_remove(self.ticker)
        for t in (self.size_timer, self.saved_timer, self.acc_timer, self.scene_timer):
            if t:
                GLib.source_remove(t)
        self.sound.close()
        Gtk.StyleContext.remove_provider_for_screen(self.get_screen(), self.css)
        self.pet.settings = None

    # ── drawing ─────────────────────────────────────────────────────────────
    def fit_preview(self):
        self.preview.set_size_request(-1, round(self.pet.box_h * ZOOM) + 44)
        self.preview.queue_draw()

    def animate(self):
        """The preview pet paces back and forth with the current animation."""
        a = self.pet.anim
        sprite = self.pet.sprites[0]
        span = max(self.pet.box_w - sprite.get_width() - 12, 1)
        self.px += self.pdir * a.walk_speed / 30
        if self.px <= 0 or self.px >= span:
            self.px = min(max(self.px, 0), span)
            self.pdir *= -1
        self.phase += a.walk_speed / 30 / a.step_length
        if self.play_start is not None and time.monotonic() - self.play_start > a.open_time + 0.6:
            self.play_start = None   # hold fully open a moment, then end the test
        self.preview.queue_draw()
        self.avatar.queue_draw()
        if self.stack.get_visible_child_name() == "anim":
            self.editor.queue_draw()
        return True

    def pet_sprites(self):
        """Sharper sprites for the zoomed preview (rebuilt when the pet changes)."""
        if self.zoom_sprites is None:
            try:
                self.zoom_sprites = sprites.load(self.pet.cfg, ZOOM)
            except Exception:
                self.zoom_sprites = sprites.load(config.DEFAULTS, ZOOM)
        return self.zoom_sprites

    def draw_preview(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        c, pet = self.pet.colors, self.pet

        # backdrop: a card with a faint dotted grid, like a little desktop
        rounded(cr, 0, 0, w, h, 24)
        cr.clip()
        cr.set_source_rgb(*c["bg1"])
        cr.paint()
        cr.set_source_rgba(*c["fg"], 0.07)
        for x in range(14, w, 20):
            for y in range(14, h, 20):
                cr.arc(x, y, 1, 0, 2 * math.pi)
                cr.fill()
        # live badge: a little pill in the corner
        cr.select_font_face(fonts.FAMILY, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        text = "LIVE PREVIEW"
        tw = cr.text_extents(text).x_advance
        rounded(cr, 14, h - 34, tw + 34, 22, 11)
        cr.set_source_rgb(*scene.mix(c["bg1"], c["accent2"], 0.18))
        cr.fill()
        cr.set_source_rgb(*c["accent2"])
        cr.arc(27, h - 23, 3.5, 0, 2 * math.pi)
        cr.fill()
        cr.move_to(37, h - 19)
        cr.show_text(text)

        bw, bh = pet.box_w, pet.box_h
        bx = (w / ZOOM - bw) / 2
        by, stretch = 0, 1
        if self.play_start is not None:     # test playback of the box-open curve
            t = min((time.monotonic() - self.play_start) / pet.anim.open_time, 1)
            e = pet.anim.open_curve(t)
            if e > 1:
                stretch = e
            else:
                by = (e - 1) * bh
        sprite = self.pet_sprites()[0 if self.pdir > 0 else 1]
        sw, _sh = sprites.logical_size(sprite)

        def pet_in_box(cr):
            tilt, bob, squash = pet.anim.pose(self.phase, True)
            feet = by + bh - pet.ground + (4 if pet.ground else 1)
            sprites.draw_pet(cr, sprite, bx + 6 + self.px + sw / 2, feet, tilt * self.pdir, bob, squash)

        cr.save()
        cr.scale(ZOOM, ZOOM * stretch)
        self.preview_cache.paint(cr, bx, by, bw, bh, c, self.cfg["box"], pet_in_box)
        cr.restore()

    def draw_avatar(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        c = self.pet.colors
        cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 2 * math.pi)
        cr.set_source_rgb(*scene.mix(c["bg1"], c["accent2"], 0.3))
        cr.fill()
        sprite = self.pet_sprites()[0]
        sw, sh = sprites.logical_size(sprite)
        k = min((w - 12) / sw, (h - 12) / sh)
        bob = 2 * abs(math.sin(self.phase * math.pi))
        cr.translate(w / 2, h - 6 - bob)
        cr.scale(k, k)
        cr.set_source_surface(sprite, -sw / 2, -sh)
        cr.paint()

    def draw_thumb(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        c = self.pet.colors
        rounded(cr, 0, 0, w, h, 16)
        cr.clip()
        for y in range(0, h, 12):           # checkerboard: shows what's transparent
            for x in range(0, w, 12):
                cr.set_source_rgba(*c["fg"], 0.09 if (x // 12 + y // 12) % 2 else 0.04)
                cr.rectangle(x, y, 12, 12)
                cr.fill()
        sprite = self.pet_sprites()[0]
        sw, sh = sprites.logical_size(sprite)
        k = min((w - 20) / sw, (h - 20) / sh)
        cr.translate(w / 2, h / 2)
        cr.scale(k, k)
        cr.set_source_surface(sprite, -sw / 2, -sh / 2)
        cr.paint()

    def draw_edge_tile(self, cr, w, h, edge):
        """A mini screen with the tab (and its box, peeking out) on this edge."""
        c = self.pet.colors
        rounded(cr, 0, 0, w, h, 14)
        cr.clip()
        cr.set_source_rgba(*c["fg"], 0.05)
        cr.paint()
        sx, sy, sw, sh = 14, 6, w - 28, h - 12          # the "monitor"
        rounded(cr, sx, sy, sw, sh, 5)
        cr.set_source_rgb(*scene.mix(c["bg0"], (0, 0, 0), 0.2))
        cr.fill_preserve()
        cr.set_source_rgba(*c["fg"], 0.25)
        cr.set_line_width(1)
        cr.stroke()
        f = self.cfg["tab"]["position"] / 100
        bw, bh = (26, 13) if edge in ("top", "bottom") else (16, 18)
        if edge in ("top", "bottom"):
            bx = sx + min(max(sw * f - bw / 2, 1), sw - bw - 1)
            by = sy if edge == "top" else sy + sh - bh
        else:
            by = sy + min(max(sh * f - bh / 2, 1), sh - bh - 1)
            bx = sx if edge == "left" else sx + sw - bw
        cr.save()
        cr.translate(bx, by)
        scene.box_path(cr, bw, bh, 4, edge)
        cr.restore()
        cr.set_source_rgba(*c["accent2"], 0.85)
        cr.fill()

    def draw_acc_tile(self, cr, w, h, acc_id):
        c = self.pet.colors
        rounded(cr, 0, 0, w, h, 14)
        cr.clip()
        cr.set_source_rgba(*c["fg"], 0.05)
        cr.paint()
        a = accessories.aspect(acc_id)
        k = min(w - 18, (h - 14) / a)
        cr.translate(w / 2, h / 2)
        cr.scale(k, k)
        accessories.paint(cr, acc_id)

    def draw_deco_tile(self, cr, w, h, kind):
        c = self.pet.colors
        rounded(cr, 0, 0, w, h, 14)
        cr.clip()
        cr.set_source_rgba(*c["fg"], 0.05)
        cr.paint()
        x0, y0, x1, y1 = scene.bounds(kind)
        k = min((w - 16) / (x1 - x0), (h - 12) / (y1 - y0))
        cr.translate(w / 2 - (x0 + x1) / 2 * k, h / 2 - (y0 + y1) / 2 * k)
        cr.scale(k, k)
        p = scene.palette(c, self.cfg["box"]["colors"])
        scene.paint_deco(cr, {"kind": kind, "seed": 7}, p, self.cfg["box"]["background"] == "night")

    def draw_tile(self, cr, w, h, ground=None, background=None, colors=None):
        """A mini box showing one option, otherwise using the current settings."""
        b = dict(self.cfg["box"])
        b["ground_height"] = min(b["ground_height"], 18)

        def at(kind, x, y=None, seed=3):
            it = scene.new_item(kind, random.Random(seed))
            it["x"] = x
            if y is not None:
                it["y"] = y
            return it
        if ground:
            b.update(ground=ground, items=[])
        if background:
            sky = {"day": [at("sun", 0.85, 32), at("clouds", 0.3, 26)],
                   "sunset": [at("sun", 0.85, 32), at("clouds", 0.3, 26)],
                   "night": [at("sun", 0.85, 32), at("stars", 0.3, 24), at("stars", 0.55, 30, 5)]}
            b.update(background=background, items=sky.get(background, []))
        if colors:
            b.update(colors=colors, ground="grass", ground_height=12,
                     items=[at("tree", 0.2), at("flowers", 0.55), at("mushrooms", 0.8), at("sun", 0.85, 32)])
        rounded(cr, 0, 0, w, h, 14)
        cr.clip()
        cr.set_source_rgba(*self.pet.colors["fg"], 0.05)
        cr.paint()
        k = h / 70
        cr.scale(k, k)
        scene.draw_static(cr, w / k, 70, self.pet.colors, b)
