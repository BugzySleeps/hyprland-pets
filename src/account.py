"""Your little local "account": when you and your pet started, and whether you've had the welcome
(the first-run intro and tour in the settings window). Just a file on your computer: nothing is sent
anywhere."""
import datetime
import json
import os
from pathlib import Path

FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "larry" / "profile.json"


def load():
    try:
        d = json.loads(FILE.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(d):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(FILE)


def ensure():
    """The profile, made the first time it's needed (that's when "with you since" starts)."""
    d = load()
    if "since" not in d:
        d["since"] = datetime.date.today().isoformat()
        d.setdefault("welcomed", False)
        save(d)
    return d


def needs_welcome():
    return not ensure().get("welcomed")


def welcomed(name):
    d = ensure()
    d.update(welcomed=True, first_name=name)
    save(d)


def since_text():
    """ "with you since 27 Oct" (or "...since 27 Oct 2025" for an older year)."""
    try:
        day = datetime.date.fromisoformat(ensure()["since"])
    except (KeyError, ValueError):
        return ""
    fmt = "%-d %b" if day.year == datetime.date.today().year else "%-d %b %Y"
    return "with you since " + day.strftime(fmt)
