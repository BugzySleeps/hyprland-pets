#!/usr/bin/env bash
# hyprland-pets installer. One line does everything:
#
#   curl -fsSL https://github.com/BugzySleeps/hyprland-pets/releases/latest/download/install.sh | bash
#
# It downloads hyprland-pets (or uses this copy, if you run it from a clone), installs any missing
# packages (Arch, Debian/Ubuntu, Fedora, Gentoo), puts `hyprland-pets` on your PATH, adds it to
# your Hyprland config so it starts with Hyprland, and starts it. It asks before using sudo or
# touching your config. Run it again any time to update; your settings are never touched.
#
#   install.sh --yes         don't ask, answer yes to everything
#   install.sh --no-deps     skip installing packages (just check them)
#   install.sh --no-config   leave your Hyprland config alone
#   install.sh --uninstall   remove it again (keeps your settings in ~/.config/larry)
set -u

VERSION="v1.2.1"
REPO="BugzySleeps/hyprland-pets"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/hyprland-pets"
BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"
HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
MARK="hyprland-pets (added by install.sh)"

yes=0 deps=1 conf=1 uninstall=0
for arg in "$@"; do
    case $arg in
        -y | --yes) yes=1 ;;
        --no-deps) deps=0 ;;
        --no-config) conf=0 ;;
        --uninstall) uninstall=1 ;;
        -h | --help) sed -n '2,16p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)"; exit 2 ;;
    esac
done

bold() { printf '\e[1m%s\e[0m\n' "$*"; }
good() { printf '  \e[32m✓\e[0m %s\n' "$*"; }
bad()  { printf '  \e[31m✗\e[0m %s\n' "$*"; }
meh()  { printf '  \e[33m~\e[0m %s\n' "$*"; }
die()  { printf '\e[31merror:\e[0m %s\n' "$*" >&2; exit 1; }

ask() {  # ask "question" -> 0 for yes. Reads the terminal, so it works under `curl | bash`.
    (( yes )) && return 0
    local reply
    if ! { exec 9</dev/tty; } 2>/dev/null; then
        echo "$1 [y/N] (no terminal to ask on: skipping; pass --yes to allow)"
        return 1
    fi
    printf '%s [Y/n] ' "$1"
    read -r reply <&9
    exec 9<&-
    [[ -z $reply || $reply == [yY]* ]]
}

# ── uninstall ────────────────────────────────────────────────────────────────
strip_config() {  # remove the block we added between the markers
    local f=$1
    [[ -f $f ]] && grep -q "$MARK" "$f" || return 0
    cp "$f" "$f.bak-hyprland-pets"
    awk -v m="$MARK" 'index($0, m) && index($0, "begin") {skip=1} !skip {print} index($0, m) && index($0, "end") {skip=0}' \
        "$f.bak-hyprland-pets" >"$f"
    good "removed the autostart lines from $f (backup: $f.bak-hyprland-pets)"
}

if (( uninstall )); then
    bold "Uninstalling hyprland-pets"
    pkill -f "hyprland-pets/src/larry.py" 2>/dev/null && good "stopped the running pet"
    [[ -L $BIN/hyprland-pets ]] && rm -f "$BIN/hyprland-pets" && good "removed $BIN/hyprland-pets"
    [[ -d $DEST ]] && rm -rf "$DEST" && good "removed $DEST"
    strip_config "$HYPR/hyprland.lua"
    strip_config "$HYPR/hyprland.conf"
    echo
    echo "Your settings and pictures are still in ~/.config/larry (delete it if you don't want them)."
    exit 0
fi

# ── 1. get the files ─────────────────────────────────────────────────────────
here=""
if [[ -n ${BASH_SOURCE[0]:-} && -f ${BASH_SOURCE[0]} ]]; then
    here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
fi
if [[ -n $here && -f $here/src/larry.py ]]; then
    src=$here
    bold "Installing hyprland-pets from $src"
else
    bold "Installing hyprland-pets $VERSION"
    if [[ -d $DEST/.git ]] && command -v git >/dev/null; then
        { git -C "$DEST" fetch -q --depth 1 origin tag "$VERSION" && git -C "$DEST" -c advice.detachedHead=false checkout -q "$VERSION"; } \
            2>/dev/null || die "couldn't update $DEST (delete it and run this again)"
        good "updated $DEST to $VERSION"
    else
        tmp="$(mktemp -d)"
        trap 'rm -rf "$tmp"' EXIT
        if command -v git >/dev/null; then
            git -c advice.detachedHead=false clone -q --depth 1 --branch "$VERSION" "https://github.com/$REPO.git" "$tmp/hyprland-pets" \
                2>"$tmp/git.log" || { cat "$tmp/git.log"; die "couldn't download hyprland-pets"; }
        elif command -v curl >/dev/null; then
            curl -fsSL "https://github.com/$REPO/archive/refs/tags/$VERSION.tar.gz" | tar -xz -C "$tmp" \
                || die "couldn't download hyprland-pets"
            mv "$tmp"/hyprland-pets-* "$tmp/hyprland-pets"
        else
            die "need git or curl to download hyprland-pets"
        fi
        mkdir -p "$(dirname "$DEST")"
        rm -rf "$DEST"
        mv "$tmp/hyprland-pets" "$DEST"
        good "downloaded to $DEST"
    fi
    src=$DEST
fi
chmod +x "$src/hyprland-pets"

# ── 2. dependencies ──────────────────────────────────────────────────────────
missing=0
check() {  # check <description> <python snippet>
    if python3 -c "$2" 2>/dev/null; then good "$1"; else bad "$1"; missing=1; fi
}
check_all() {
    missing=0
    if ! command -v python3 >/dev/null; then bad "Python 3"; missing=1; return; fi
    check "Python 3.11+" "import sys; assert sys.version_info >= (3, 11)"
    check "PyGObject + GTK 3" "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk"
    check "gtk-layer-shell (with GObject introspection)" "import gi; gi.require_version('GtkLayerShell', '0.1'); from gi.repository import GtkLayerShell"
    check "pycairo" "import cairo"
    check "Pillow" "import PIL"
    if python3 -c "import gi; gi.require_version('Gst', '1.0'); from gi.repository import Gst; Gst.init(None); assert Gst.ElementFactory.find('pulsesink')" 2>/dev/null; then
        good "GStreamer + pulsesink (settings sounds)"
    else
        meh "GStreamer + pulsesink (optional: without it the settings window is silent)"
    fi
    if command -v cava >/dev/null; then
        good "cava (dancing in time with music)"
    else
        meh "cava (optional: without it the pet dances to music at a steady 120 BPM)"
    fi
}

distro=""
if [[ -r /etc/os-release ]]; then
    distro="$(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}")"
fi
pkg_install() {  # prints and runs the install command for this distro
    local cmd=()
    case " $distro " in
        *" arch "*)
            cmd=(sudo pacman -S --needed python python-gobject gtk3 gtk-layer-shell python-cairo python-pillow gst-plugins-good) ;;
        *" debian "* | *" ubuntu "*)
            cmd=(sudo apt-get install -y python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1
                 python3-pil gir1.2-gstreamer-1.0 gstreamer1.0-pulseaudio) ;;
        *" fedora "*)
            cmd=(sudo dnf install -y python3 python3-gobject python3-cairo gtk3 gtk-layer-shell python3-pillow gstreamer1-plugins-good) ;;
        *" gentoo "*)
            # gtk-layer-shell is only usable from Python with its introspection USE flag
            if ! portageq envvar USE 2>/dev/null | grep -qw introspection \
                && ! grep -rqs "gtk-layer-shell.*introspection" /etc/portage/package.use; then
                echo "  gtk-layer-shell needs USE=introspection; adding /etc/portage/package.use/hyprland-pets"
                echo "gui-libs/gtk-layer-shell introspection" | sudo tee /etc/portage/package.use/hyprland-pets >/dev/null || return 1
            fi
            cmd=(sudo emerge --noreplace --changed-use dev-python/pygobject x11-libs/gtk+:3 gui-libs/gtk-layer-shell
                 dev-python/pycairo dev-python/pillow media-plugins/gst-plugins-pulse) ;;
        *) return 2 ;;
    esac
    echo "  \$ ${cmd[*]}"
    if [[ -e /dev/tty ]]; then "${cmd[@]}" </dev/tty; else "${cmd[@]}"; fi
}

echo
bold "Checking dependencies"
check_all
if (( missing )); then
    echo
    if (( ! deps )); then
        die "some dependencies are missing (see the README for package names)"
    fi
    if ask "Install the missing packages now (uses sudo)?"; then
        pkg_install
        case $? in
            0) echo; bold "Checking again"; check_all ;;
            2) die "don't know the package names for this distro; install the ✗ ones above yourself (see the README), then run this again" ;;
            *) die "installing packages failed" ;;
        esac
        (( missing )) && die "still missing something; install the ✗ ones above, then run this again"
    else
        die "install the ✗ ones above (see the README for package names), then run this again"
    fi
fi

# ── 3. put it on the PATH ────────────────────────────────────────────────────
echo
bold "Installing the command"
mkdir -p "$BIN"
ln -sfn "$src/hyprland-pets" "$BIN/hyprland-pets"
good "$BIN/hyprland-pets -> $src/hyprland-pets"
onpath=1
case ":$PATH:" in *":$BIN:"*) ;; *) onpath=0; meh "$BIN isn't on your PATH (the autostart line uses the full path, so it still works)" ;; esac
cmd="hyprland-pets"
(( onpath )) || cmd="$BIN/hyprland-pets"

# ── 4. start with Hyprland ───────────────────────────────────────────────────
echo
bold "Starting with Hyprland"
if (( ! conf )); then
    meh "left your Hyprland config alone (--no-config)"
elif [[ -f $HYPR/hyprland.lua ]]; then
    f=$HYPR/hyprland.lua
    if grep -q "hyprland-pets" "$f"; then
        good "$f already starts it"
    elif ask "Add hyprland-pets to $f?"; then
        cp "$f" "$f.bak-hyprland-pets"
        cat >>"$f" <<EOF

-- $MARK: begin
hl.on("hyprland.start", function()
    hl.exec_cmd("$cmd")
end)
hl.window_rule({ name = "float-pet-settings", match = { class = "^larry$" }, float = true, center = true })
-- $MARK: end
EOF
        good "added to $f (backup: $f.bak-hyprland-pets)"
    else
        meh "skipped: add hl.exec_cmd(\"$cmd\") to your hyprland.start handler yourself"
    fi
elif [[ -f $HYPR/hyprland.conf ]]; then
    f=$HYPR/hyprland.conf
    if grep -q "hyprland-pets" "$f"; then
        good "$f already starts it"
    elif ask "Add hyprland-pets to $f?"; then
        cp "$f" "$f.bak-hyprland-pets"
        cat >>"$f" <<EOF

# $MARK: begin
exec-once = $cmd
# $MARK: end
EOF
        good "added to $f (backup: $f.bak-hyprland-pets)"
        meh "to float the settings window, add a window rule for class ^(larry)\$ (the syntax depends on your Hyprland version)"
    else
        meh "skipped: add 'exec-once = $cmd' to your hyprland.conf yourself"
    fi
else
    meh "no Hyprland config found in $HYPR: add '$cmd' to your autostart yourself"
fi

# ── 5. start it now ──────────────────────────────────────────────────────────
echo
if [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} && -n ${WAYLAND_DISPLAY:-} ]]; then
    pkill -f "hyprland-pets/src/larry.py" 2>/dev/null && sleep 0.5   # restart on the new version
    (setsid "$src/hyprland-pets" >/dev/null 2>&1 </dev/null &)
    bold "Done! Your pet is running: hover the tab at the top of the screen."
else
    bold "Done! It starts with Hyprland next time (or run hyprland-pets inside Hyprland)."
fi
cat <<'MSG'
  Right-click the tab, the box or the pet for settings.
  Run this installer again any time to update. To remove it: install.sh --uninstall
MSG
