"""Colour themes for the box, the tab and the settings window.

Each palette has the same five colours the rest of the program draws with:
  bg0 (window / deepest background), bg1 (cards, the box), fg (text),
  accent (lines, quiet details) and accent2 (highlights, the selected thing).
"Desktop" isn't a palette: it follows the rice theme switcher if you use it, otherwise your GTK
theme's colours.
"""

THEMES = {   # key: (title, palette, light?)
    "dark": ("Dark", {"bg0": "#111216", "bg1": "#1b1d23", "fg": "#e6e8ee", "accent": "#b8bdca",
                      "accent2": "#8ab4f8"}, False),
    "desktop": ("Desktop", None, False),
    "light": ("Light", {"bg0": "#eef0f4", "bg1": "#ffffff", "fg": "#1d2026", "accent": "#5a6070",
                        "accent2": "#3b82f6"}, True),
    "gruvbox": ("Gruvbox", {"bg0": "#1d2021", "bg1": "#282828", "fg": "#ebdbb2", "accent": "#bdae93",
                            "accent2": "#fabd2f"}, False),
    "evergreen": ("Evergreen", {"bg0": "#232a2e", "bg1": "#2d353b", "fg": "#d3c6aa", "accent": "#9da9a0",
                                "accent2": "#a7c080"}, False),
    "nord": ("Nord", {"bg0": "#2e3440", "bg1": "#3b4252", "fg": "#eceff4", "accent": "#d8dee9",
                      "accent2": "#88c0d0"}, False),
    "catppuccin": ("Catppuccin", {"bg0": "#1e1e2e", "bg1": "#313244", "fg": "#cdd6f4", "accent": "#a6adc8",
                                  "accent2": "#cba6f7"}, False),
    "tokyonight": ("Tokyo Night", {"bg0": "#1a1b26", "bg1": "#24283b", "fg": "#c0caf5", "accent": "#a9b1d6",
                                   "accent2": "#7aa2f7"}, False),
    "dracula": ("Dracula", {"bg0": "#21222c", "bg1": "#282a36", "fg": "#f8f8f2", "accent": "#bfbfcf",
                            "accent2": "#bd93f9"}, False),
    "rosepine": ("Rosé Pine", {"bg0": "#191724", "bg1": "#1f1d2e", "fg": "#e0def4", "accent": "#908caa",
                               "accent2": "#ebbcba"}, False),
    "solarized": ("Solarized Light", {"bg0": "#fdf6e3", "bg1": "#eee8d5", "fg": "#073642", "accent": "#586e75",
                                      "accent2": "#268bd2"}, True),
    "sakura": ("Cherry Blossom", {"bg0": "#fbeff2", "bg1": "#ffffff", "fg": "#4a2b36", "accent": "#8a5a6a",
                                  "accent2": "#e86a92"}, True),
}
DEFAULT = "dark"


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def palette(key):
    """The theme's colours as 0-1 RGB tuples (None for "desktop": that's worked out live)."""
    pal = THEMES.get(key, THEMES[DEFAULT])[1]
    return {k: rgb(v) for k, v in pal.items()} if pal else None


def is_light(colors):
    r, g, b = colors["bg0"]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5
