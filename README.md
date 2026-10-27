# hyprland-pets

A little pet that lives in a pull-down box on the edge of your Hyprland screen.

Hover the tab and the box slides out with your pet wandering around inside. Drag the pet out and
it drops onto your desktop, lands on top of your windows (and rides along when you move them),
and walks around on top of everything. Drag it back into the box to put it away. It hides itself
while anything is fullscreen.

The default pet is **Larry the Cow**, but any picture works, and almost everything else is
customisable from a settings window: the box's scene, the pet's accessories, and how it moves.

[![Watch the trailer (50 s)](docs/showcase.jpg)](docs/showcase.mp4)

*Click to watch the 50-second trailer (with sound).*

![The Box page: arranging the scene](docs/box.png)

## Features

- **Name it.** Set your pet's name in settings.
- **Any picture as your pet.** PNGs with transparency look best; solid backgrounds can be cut out
  automatically. Size, facing direction and a white sticker outline are adjustable.
- **A scene you arrange yourself.** Ten built-in decorations (sun/moon, clouds, stars, trees,
  fences, bushes, flowers, rocks, mushrooms, hay bales), as many of each as you like. Drag them
  around, resize them, mirror them, put them in front of or behind the ground. Drag the ground's
  edge to raise or lower it. Five grounds and five skies built in, tinted to your theme or in
  natural colours.
- **Your own pictures everywhere.** Use any image as a decoration, as the ground (it repeats
  across) or as the sky (drag to pan, Ctrl+scroll to zoom).
- **Accessories.** 16 built-in ones (top hat, party hat, crown, cowboy hat, beanie, wizard hat,
  chef hat, grad cap, viking helmet, halo, devil horns, sunglasses, nerd glasses, bow tie, bow,
  flower) plus your own pictures. Fit them in the fitting room: drag, resize and rotate until
  they sit right on your pet. They lean, bob and flip with it.
- **My pets and pet packs.** Keep several pets and switch between them on the My pets page; each
  remembers its picture, name, size, accessories and animation, and saves itself as you change it.
  Export one as a single `.larrypet` file to share, and import other people's (pick the file, or drop
  it on the settings window). Imports are checked: only the expected files are read, sizes are
  capped and every picture is re-encoded.
- **Dances to music.** When anything's playing (Spotify, mpv, a browser tab: whatever shows up in
  `playerctl`), your pet dances: bops, sways, spins, kicks, headbangs and bounces, a new move every
  couple of bars, with music notes floating up. With cava installed it listens and dances in time
  with the song; without it, a steady 120 BPM.
- **Seasonal accessories.** Around holidays, limited ones show up to claim: a pumpkin and witch hat
  for Halloween, a Santa hat and antlers for Christmas, star glasses for New Year, heart boppers
  for Valentine's, a lucky hat for St. Patrick's and bunny ears in spring. Your pet tells you when
  there's something new. Claim it while the season's on and it stays in your wardrobe for good.
- **Animation you shape with graphs.** Walk speed, step length, tilt, bob, squash, wandering,
  gravity, throwing and bounciness, plus curves you drag to shape each step and the box opening.
  Five presets built in; save your own and switch between them.
- **It can move into your terminals.** Drag the pet onto a terminal window and let go: it drops
  to the bottom and walks along inside, moves and resizes with the window, hides behind windows
  stacked over it, and disappears with it when you switch workspace. Drop it above a window
  instead and it stands on top, same as always. Grab it to take it back out.
- **Idle behaviours.**
  - Bring the mouse close and it stops and turns to look at it; Larry's eyes follow the cursor.
  - Larry sits down now and then.
  - Leave the mouse alone for a while and it falls asleep, with little z's floating up. Bring the
    mouse close to wake it.
  - Each one can be turned off on the Fun page.
- **Reacts to downloads finishing.** When a package manager finishes, the pet hops with hearts and a
  bubble saying what finished, or slumps if it failed. That includes apt/nala, pacman, AUR helpers
  (yay, paru, pikaur…), emerge, dnf, zypper, xbps, apk, flatpak, snap, nix, brew, pip/pipx and
  cargo, on any distro. It also cheers when a browser, wget or aria2 download lands in your
  Downloads folder.
  - Telling success from failure needs a readable log: pacman's and apt's are; on Gentoo, add
    yourself to the `portage` group. Without one, it assumes success.
- **Goes for rides.** Every few minutes the pet hops on a vehicle and drives around for a bit instead of
  walking: a mini motorcycle (the default, with the odd wheelie), a car, a one-person helicopter that
  takes off and flies around with the pet hanging under the rotor, or a bike. Larry sits on them
  properly, front legs on the handlebars, and pedals the bike, still wearing his accessories. Pick one, or "Surprise me", on the Fun page, and set how often.
  Picking the pet up ends the ride.
- **Catch game.** Throw your pet up and catch it on the way down for +1. Bounce it off a side of the
  screen (or a window) first for +2, or off two sides (a wall, then the top) for +3: every different side adds a
  point. Catches only count in a row: let it land and the streak is over. Your best is kept and shown in the corner of the box,
  with the live streak next to it.
- **Sounds.** Throw Larry and he moos (seven different moos, picked at random).
  Other pets get a muffled, Kenny-style "weee!" (eight of them). There's a blip when you catch it. Off by
  default: turn on **Pet sounds** on the Fun page.
- **A falling pose.** Throw Larry or pick him up and he stands up and throws his front legs in the air, and while you hold him he waddles all four legs. With the falling pose off he stays on all fours and paddles his legs in the air instead. Other
  pets can get one too: pick any picture as the falling pose in settings.
- **Themes.** Dark (the default), Light, Gruvbox, Evergreen, Nord, Catppuccin, Tokyo Night,
  Dracula, Rosé Pine, Solarized Light and Cherry Blossom, or Desktop to follow your GTK theme.
  Themes colour the settings window, the box and the tab, and switch live.
- **Types in your terminal** (off by default). While it naps in a terminal and you're away, it wakes up
  now and then and types something silly there ("u there?", "brb eating grass"...). Larry sits on his
  butt with a mini keyboard on his lap. The text only appears on screen, the way `write` messages
  do: it's never typed into your shell, and only shows up at a prompt, never over a running program.
- **Tab on any screen edge,** anywhere along it.
- **Physics.** Throw the pet and it flies, bounces off the screen edges and the sides and bottoms of
  windows, and lands on whatever window is under it.
- **Stays out of the way.** Clicks go straight through to your windows everywhere except the
  tab, the box and the pet. Hidden in fullscreen. One small Python process.
- **Searchable settings.** Type in the search box (or press Ctrl+F) to find any setting and jump to it.
- **Satisfying settings window,** with a live preview and soft synthesized click and tick sounds
  (they can be turned off).

| Accessories | Animation |
|---|---|
| ![Fitting room](docs/acc.png) | ![Animation curves](docs/anim.png) |
| **Fun** | **Pet** |
| ![Vehicles, games and reactions](docs/fun.png) | ![Picking your pet](docs/pet.png) |

## Requirements

- Hyprland
- Python 3.11+ with PyGObject, pycairo and Pillow
- GTK 3 and **gtk-layer-shell with GObject introspection**
- Optional: GStreamer with `pulsesink` for the settings sounds (it works silently without them)
- Optional: `cava`, so the pet dances in time with your music (otherwise it dances at a steady 120 BPM)

| Distro | Packages |
|---|---|
| Arch | `python-gobject gtk3 gtk-layer-shell python-cairo python-pillow gst-plugins-good` |
| Gentoo | `dev-python/pygobject x11-libs/gtk+:3 gui-libs/gtk-layer-shell[introspection] dev-python/pycairo dev-python/pillow media-plugins/gst-plugins-pulse` |
| Debian / Ubuntu | `python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 python3-pil gir1.2-gstreamer-1.0 gstreamer1.0-pulseaudio` |
| Fedora | `python3-gobject python3-cairo gtk3 gtk-layer-shell python3-pillow gstreamer1-plugins-good` |

## Install

One line, run in a terminal inside Hyprland:

```sh
curl -fsSL https://github.com/BugzySleeps/hyprland-pets/releases/latest/download/install.sh | bash
```

The installer:

- downloads hyprland-pets to `~/.local/share/hyprland-pets`
- installs any missing packages on Arch, Debian/Ubuntu, Fedora and Gentoo
- puts `hyprland-pets` on your PATH
- adds it to your Hyprland config so it starts with Hyprland
- starts it

It asks before using sudo or changing your config, and backs the config up first. Run the same
line again to update; your settings are never touched.

Options go after `bash -s --`, for example `curl -fsSL … | bash -s -- --yes`:

| | |
|---|---|
| `--yes` | don't ask, answer yes to everything |
| `--no-deps` | only check the packages, don't install them |
| `--no-config` | leave your Hyprland config alone |
| `--uninstall` | remove it again |

**From a clone instead:** `git clone https://github.com/BugzySleeps/hyprland-pets.git && cd hyprland-pets && ./install.sh`
runs it from the clone, so `git pull` updates it.

**Doing it by hand:** install the packages above, link `hyprland-pets` onto your PATH, and add
it to your config:

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
| Settings → **Fun** | catch game, sounds, reactions, idle behaviours, falling pose, terminals |
| Drag the pet out of the box | it's free on your desktop |
| Drag it onto a terminal and let go | it moves in and walks along the bottom |
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
| `~/.config/larry/claimed.json` | seasonal accessories you've claimed |
| `~/.config/larry/pets/` | your saved pets, one folder each |
| `~/.local/state/larry/game.json` | your catch-game best |
| `~/.cache/larry/` | rendered sprites and sounds (safe to delete) |

**Theme colours:** pick one under Settings → Themes. With **Desktop**, the box and settings follow
the `rice` theme switcher from [bugzysdotfiles](https://github.com/BugzySleeps/bugzysdotfiles) if you
use it (switching rices recolours them live), otherwise your GTK theme.

## Uninstall

```sh
curl -fsSL https://github.com/BugzySleeps/hyprland-pets/releases/latest/download/install.sh | bash -s -- --uninstall
```

This removes the program and the lines it added to your Hyprland config. Your settings stay in
`~/.config/larry`; delete that folder and `~/.cache/larry` too if you don't want them.

## Project layout

```
hyprland-pets        launcher
install.sh           one-step installer / updater / uninstaller
src/larry.py         the pet: overlay window, physics, Hyprland IPC
src/settings.py      the settings window
src/scene.py         the box: sky, ground, decorations
src/scene_editor.py  drag-and-drop scene editor
src/accessories.py   built-in + seasonal accessories, placement, claims
src/music.py         is music playing (MPRIS) + beat tracking (cava)
src/packs.py         saved pets + .larrypet import/export
src/fitting_room.py  drag-and-drop accessory editor
src/anim.py          animation parameters, curves and presets
src/curve_editor.py  the graph editor
src/sprites.py       turns a picture into the walking sprite
src/library.py       your own pictures
src/sounds.py        synthesized UI sounds
src/watch.py         notices package managers and downloads finishing
src/termchat.py      the pet's messages in your terminal
src/themes.py        colour themes
src/fonts/           the settings window's font (Nunito, OFL)
src/vehicles.py      the motorcycle, car, helicopter and bike
src/config.py        settings file
tools/make_falling_larry.py  draws Larry's falling, held (waddling), typing and riding poses
```

## License

MIT: use it, change it, share it, build on it. Contributions welcome. See [LICENSE](LICENSE).

The settings window uses the [Nunito](https://github.com/googlefonts/nunito) font, bundled in `src/fonts/`
under the SIL Open Font License (`src/fonts/OFL.txt`). It's loaded for the app only, nothing is installed.
