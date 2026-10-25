#!/usr/bin/env bash
# Checks the dependencies and puts `hyprland-pets` on your PATH (a symlink into this repo,
# so `git pull` updates it). Run it again any time; it doesn't touch your settings.
set -u
here="$(dirname "$(readlink -f "$0")")"
bin="${XDG_BIN_HOME:-$HOME/.local/bin}"

ok=1
check() {  # check <description> <python snippet>
    if python3 -c "$2" 2>/dev/null; then
        printf '  \e[32m✓\e[0m %s\n' "$1"
    else
        printf '  \e[31m✗\e[0m %s\n' "$1"
        ok=0
    fi
}
echo "Checking dependencies:"
check "Python 3.11+" "import sys; assert sys.version_info >= (3, 11)"
check "PyGObject + GTK 3" "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk"
check "gtk-layer-shell (with GObject introspection)" "import gi; gi.require_version('GtkLayerShell', '0.1'); from gi.repository import GtkLayerShell"
check "pycairo" "import cairo"
check "Pillow" "import PIL"
if python3 -c "import gi; gi.require_version('Gst', '1.0'); from gi.repository import Gst; Gst.init(None); assert Gst.ElementFactory.find('pulsesink')" 2>/dev/null; then
    printf '  \e[32m✓\e[0m %s\n' "GStreamer + pulsesink (settings sounds)"
else
    printf '  \e[33m~\e[0m %s\n' "GStreamer + pulsesink missing: everything works, the settings window is just silent"
fi
if [ "$ok" = 0 ]; then
    echo
    echo "Install what's missing (see README.md for package names), then run this again."
    exit 1
fi

mkdir -p "$bin"
ln -sf "$here/hyprland-pets" "$bin/hyprland-pets"
echo
echo "Installed: $bin/hyprland-pets -> $here/hyprland-pets"
case ":$PATH:" in *":$bin:"*) ;; *) echo "Note: $bin isn't on your PATH yet." ;; esac
cat <<'MSG'

Start it with Hyprland by adding this to your config:

  hyprland.conf:
    exec-once = hyprland-pets
    windowrule = float, class:^(larry)$

  hyprland.lua:
    hl.on("hyprland.start", function() hl.exec_cmd("hyprland-pets") end)
    hl.window_rule({ name = "float-pet-settings", match = { class = "^larry$" }, float = true, center = true })

Then run `hyprland-pets` now to try it (right-click the tab for settings).
MSG
