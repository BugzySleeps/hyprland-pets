# hyprland-pets

A little pet that lives in a pull-down box on the edge of your Hyprland screen.

Hover the tab and the box slides out with your pet wandering around inside. Drag the pet out and
it drops onto your desktop, lands on top of your windows (and rides along when you move them),
and walks around on top of everything. Drag it back into the box to put it away. It hides itself
while anything is fullscreen.

The default pet is **Larry the Cow**, but any picture works, and almost everything else is
customisable from a settings window: the box's scene, the pet's accessories, and how it moves.

![The Box page: arranging the scene](docs/box.png)

## Features

- **Any picture as your pet.** PNGs with transparency look best; solid backgrounds can be cut out
  automatically. Size, facing direction and a white sticker outline are adjustable.
- **A scene you arrange yourself.** Ten built-in decorations (sun/moon, clouds, stars, trees,
  fences, bushes, flowers, rocks, mushrooms, hay bales), as many of each as you like. Drag them
  around, resize them, mirror them, put them in front of or behind the ground. Drag the ground's
  edge to raise or lower it. Five grounds and five skies built in, tinted to your theme or in
  natural colours.
- **Your own pictures everywhere.** Use any image as a decoration, as the ground (it repeats
  across) or as the sky (drag to pan, scroll to zoom).
- **Accessories.** 16 built-in ones (top hat, party hat, crown, cowboy hat, beanie, wizard hat,
  chef hat, grad cap, viking helmet, halo, devil horns, sunglasses, nerd glasses, bow tie, bow,
  flower) plus your own pictures. Fit them in the fitting room: drag, resize and rotate until
  they sit right on your pet. They lean, bob and flip with it.
- **Animation you shape with graphs.** Walk speed, step length, tilt, bob, squash, wandering,
  gravity, throwing and bounciness, plus curves you drag to shape each step and the box opening.
  Five presets built in; save your own and switch between them.
- **Tab on any screen edge,** anywhere along it.
- **Physics.** Throw the pet and it flies, bounces and lands on whatever window is under it.
- **Stays out of the way.** Clicks go straight through to your windows everywhere except the
  tab, the box and the pet. Hidden in fullscreen. One small Python process.
- **Satisfying settings window,** with a live preview and soft synthesized click and tick sounds
  (they can be turned off).

| Accessories | Animation |
|---|---|
| ![Fitting room](docs/acc.png) | ![Animation curves](docs/anim.png) |

## Requirements

- Hyprland
- Python 3.11+ with PyGObject, pycairo and Pillow
- GTK 3 and **gtk-layer-shell with GObject introspection**
- Optional: GStreamer with `pulsesink` for the settings sounds (it works silently without them)

| Distro | Packages |
|---|---|
| Arch | `python-gobject gtk3 gtk-layer-shell python-cairo python-pillow gst-plugins-good` |
| Gentoo | `dev-python/pygobject x11-libs/gtk+:3 gui-libs/gtk-layer-shell[introspection] dev-python/pycairo dev-python/pillow media-plugins/gst-plugins-pulse` |
| Debian / Ubuntu | `python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 python3-pil gir1.2-gstreamer-1.0 gstreamer1.0-pulseaudio` |
| Fedora | `python3-gobject python3-cairo gtk3 gtk-layer-shell python3-pillow gstreamer1-plugins-good` |

## Install

```sh
git clone https://github.com/BugzySleeps/hyprland-pets.git
cd hyprland-pets
./install.sh
```

`install.sh` checks the dependencies and links `hyprland-pets` into `~/.local/bin`, pointing
back at the repo, so a `git pull` is all it takes to update.

Then start it with Hyprland, and float the settings window:

**hyprland.lua**
```lua
hl.on("hyprland.start", function()
    hl.exec_cmd("hyprland-pets")
end)
hl.window_rule({ name = "float-pet-settings", match = { class = "^larry$" }, float = true, center = true })
```

**hyprland.conf** (the window rule syntax differs between Hyprland versions, so check the wiki
for yours)
```ini
exec-once = hyprland-pets
windowrule = float, class:^(larry)$
```

## Usage

| | |
|---|---|
| Hover the tab | the box slides out |
| Click the tab | keep the box open |
| Right-click the tab, the box or the pet | settings |
| Drag the pet out of the box | it's free on your desktop |
| Drag it back into the open box | put it away |
| `hyprland-pets --settings` | open settings from a keybind or script |

Running `hyprland-pets` again while it's already running does nothing, so it's safe to put in
autostart.

## Files

| Path | What |
|---|---|
| `~/.config/larry/config.toml` | all settings; the settings window writes it, but it's readable and hand-editable |
| `~/.config/larry/animations/` | your saved animation presets |
| `~/.config/larry/{accessories,decorations,grounds,skies}/` | copies of pictures you added |
| `~/.cache/larry/` | rendered sprites (safe to delete) |

**Theme colours:** if you use the `rice` theme switcher from
[bugzysdotfiles](https://github.com/BugzySleeps/bugzysdotfiles), the box and the settings window
follow your current theme. Otherwise they use a neutral dark palette.

## Uninstall

```sh
rm ~/.local/bin/hyprland-pets
rm -r ~/.config/larry ~/.cache/larry   # settings and pictures, if you don't want them
```

## Project layout

```
hyprland-pets        launcher
install.sh           dependency check + install
src/larry.py         the pet: overlay window, physics, Hyprland IPC
src/settings.py      the settings window
src/scene.py         the box: sky, ground, decorations
src/scene_editor.py  drag-and-drop scene editor
src/accessories.py   built-in accessories + placement
src/fitting_room.py  drag-and-drop accessory editor
src/anim.py          animation parameters, curves and presets
src/curve_editor.py  the graph editor
src/sprites.py       turns a picture into the walking sprite
src/library.py       your own pictures
src/sounds.py        synthesized UI sounds
src/config.py        settings file
```

## License

MIT: use it, change it, share it, build on it. Contributions welcome. See [LICENSE](LICENSE).
