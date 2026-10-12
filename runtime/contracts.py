"""Enforce contracts/*.schema.json at stage boundaries.

A small validator for the JSON Schema keywords these contracts use (type,
required, properties, additionalProperties, enum, const, minLength, minimum,
items, uniqueItems, format: date-time). The schema FILES are the source of
truth: edit the JSON and enforcement changes with it. No dependencies; the
tests cross-check it against the `jsonschema` package when that is installed.
"""
import os, json
from datetime import datetime
from functools import lru_cache

ROOT = os.environ.get("ICM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}

@lru_cache(maxsize=None)
def schema(name):
    with open(os.path.join(ROOT, "contracts", name + ".schema.json"), encoding="utf-8") as f:
        return json.load(f)

def _is_datetime(v):
    try:
        return "T" in v and datetime.fromisoformat(v.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False

def _check(s, v, path, errs):
    t = s.get("type")
    if t and (not isinstance(v, _TYPES[t]) or (t in ("integer", "number") and isinstance(v, bool))):
        errs.append(f"{path}: expected {t}")
        return
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: must be {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: must be one of {s['enum']}")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            errs.append(f"{path}: must not be empty")
        if s.get("format") == "date-time" and not _is_datetime(v):
            errs.append(f"{path}: not a date-time with timezone")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "minimum" in s and v < s["minimum"]:
        errs.append(f"{path}: below minimum {s['minimum']}")
    if isinstance(v, dict):
        props = s.get("properties", {})
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}.{k}: required")
        for k, x in v.items():
            if k in props:
                _check(props[k], x, f"{path}.{k}", errs)
            elif s.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: unexpected field")
    if isinstance(v, list):
        if s.get("uniqueItems") and len(v) != len({json.dumps(x, sort_keys=True) for x in v}):
            errs.append(f"{path}: items must be unique")
        if "items" in s:
            for i, x in enumerate(v):
                _check(s["items"], x, f"{path}[{i}]", errs)

def validate(name, obj):
    """Return a list of violations of contracts/<name>.schema.json (empty = valid)."""
    errs = []
    _check(schema(name), obj, name, errs)
    return errs
