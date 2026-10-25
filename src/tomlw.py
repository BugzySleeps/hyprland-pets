"""Tiny TOML writer for our settings: scalars, arrays (of values or small tables) and nested tables."""
import json


def value(v):
    if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
        # a list of small tables: one inline table per line
        rows = ["{ " + ", ".join(f"{k} = {value(x)}" for k, x in d.items()) + " }," for d in v]
        return "[\n" + "\n".join("  " + r for r in rows) + "\n]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {value(x)}" for k, x in v.items()) + " }"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(round(v, 4))
    if isinstance(v, (str, list)):
        return json.dumps(v)  # strings and (nested) arrays of numbers/strings are valid TOML as JSON
    return str(v)


def dump(d, prefix="", comments=None):
    """Scalars first, then each sub-dict as its own [table] (dotted for nesting)."""
    comments = comments or {}
    lines = []
    for k, v in d.items():
        if not isinstance(v, dict):
            if k in comments:
                lines.append(f"# {comments[k]}")
            lines.append(f"{k} = {value(v)}")
            if k in comments:
                lines.append("")
    for k, v in d.items():
        if isinstance(v, dict):
            name = f"{prefix}{k}"
            lines += ["", f"[{name}]"]
            body = dump(v, f"{name}.", comments)
            lines.append(body.rstrip("\n"))
    return "\n".join(lines).strip("\n") + "\n"
