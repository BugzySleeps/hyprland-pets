"""The settings window's font, Nunito (SIL Open Font License, see OFL.txt), loaded for this program
only: nothing is installed. Call register() before any window is made."""
import ctypes
import ctypes.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAMILY = "Nunito"


def register():
    """True if the bundled font is available (otherwise GTK just uses your normal font)."""
    try:
        fc = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        return bool(fc.FcConfigAppFontAddFile(None, str(HERE / "Nunito.ttf").encode()))
    except (OSError, AttributeError):
        return False
