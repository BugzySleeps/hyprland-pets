"""Your local weather, so the pet can dress for it: Open-Meteo (open-meteo.com), free and with no
account or key. You type your town once in the settings; it's looked up once to get its
coordinates, and from then on only those coordinates are sent, every half hour."""
import json
import urllib.parse
import urllib.request

FORECAST = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
EVERY = 30 * 60          # seconds between checks
COLD = 5.0               # °C and below: scarf weather
UA = {"User-Agent": "hyprland-pets (https://github.com/BugzySleeps/hyprland-pets)"}


class WeatherError(Exception):
    pass


def _get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read(200_000).decode())
    except (OSError, ValueError) as e:
        raise WeatherError(f"couldn't reach Open-Meteo ({e})") from e


def geocode(name):
    """A town/city name -> (label, latitude, longitude)."""
    d = _get(GEOCODE, {"name": name.strip()[:80], "count": 1, "language": "en", "format": "json"})
    res = d.get("results") or []
    if not res:
        raise WeatherError(f"couldn't find a place called “{name.strip()}”")
    r = res[0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
    return label, float(r["latitude"]), float(r["longitude"])


def fetch(lat, lon):
    """The weather right now: {"temp" (°C), "code" (WMO), "day"}."""
    d = _get(FORECAST, {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}",
                        "current": "temperature_2m,weather_code,is_day", "timezone": "auto"})
    cur = d.get("current") or {}
    try:
        return {"temp": float(cur["temperature_2m"]), "code": int(cur["weather_code"]), "day": bool(cur.get("is_day", 1))}
    except (KeyError, TypeError, ValueError) as e:
        raise WeatherError("Open-Meteo sent something unexpected") from e


def kind(code):
    """WMO weather code -> clear | cloudy | fog | drizzle | rain | snow | storm."""
    if code in (0, 1):
        return "clear"
    if code in (2, 3):
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "cloudy"


SAYS = {"clear": "clear skies", "cloudy": "cloudy", "fog": "foggy", "drizzle": "drizzly", "rain": "raining",
        "snow": "snowing", "storm": "a thunderstorm"}


def wear(w):
    """What to put on for this weather: accessory ids (see accessories.WEATHER)."""
    k = kind(w["code"])
    out = {}
    if k in ("drizzle", "rain", "storm"):
        out["umbrella_hat"] = True
    if k == "snow" or round(w["temp"]) <= COLD:      # (the number you see in the settings)
        out["scarf"] = True
    return out


def effect(w):
    """What falls in the box: rain | snow | storm | None."""
    k = kind(w["code"])
    return {"drizzle": "rain", "rain": "rain", "snow": "snow", "storm": "storm"}.get(k)


def describe(w, place=""):
    k = kind(w["code"])
    f = w["temp"] * 9 / 5 + 32
    where = f" in {place.split(',')[0]}" if place else ""
    return f"{SAYS[k].capitalize()}{where}, {w['temp']:.0f}°C / {f:.0f}°F"


# "Try it" in the settings: pretend weather, to see the outfits without waiting for the real thing
SAMPLES = {"rain": {"temp": 11.0, "code": 63, "day": True}, "snow": {"temp": -2.0, "code": 73, "day": True},
           "storm": {"temp": 16.0, "code": 95, "day": True}, "cold": {"temp": 1.0, "code": 3, "day": True}}
