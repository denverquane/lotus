"""Preset store: a named pattern + param dict, persisted as one JSON file.

Writes are atomic (write to a temp file, then rename). Validation uses the
firmware's own registry (patterns.py, imported through the desktop stubs) so
a preset can never carry a param the device would reject.
"""
import json
import os
import random
import re
import time

import patterns

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,63}$")


class PresetError(ValueError):
    pass


def validate(pattern, params):
    """Return coerced params, or raise PresetError."""
    if pattern not in patterns.PATTERNS:
        raise PresetError("unknown pattern '%s'; valid: %s" % (pattern, ", ".join(patterns.ORDER)))
    schema = patterns.get(pattern).params
    out = {}
    for k, v in (params or {}).items():
        if k not in schema:
            raise PresetError("unknown param '%s' for %s; valid: %s"
                              % (k, pattern, ", ".join(sorted(schema))))
        try:
            out[k] = schema[k].coerce(v)
        except patterns.ParamError as e:
            raise PresetError("%s: %s" % (k, e))
    return out


class PresetStore:
    def __init__(self, path):
        self.path = path
        self._presets = {}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        if isinstance(data, dict):
            self._presets = {k: v for k, v in data.items() if isinstance(v, dict)}

    def _save(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._presets, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def list(self):
        return [self._presets[k] for k in sorted(self._presets, key=str.lower)]

    def get(self, name):
        return self._presets.get(name)

    def names(self):
        return sorted(self._presets, key=str.lower)

    def put(self, name, pattern, params):
        name = (name or "").strip()
        if not NAME_RE.match(name):
            raise PresetError("preset name must be 1-64 letters, digits, spaces, '-' or '_'")
        params = validate(pattern, params)
        now = time.time()
        existing = self._presets.get(name)
        self._presets[name] = {
            "name": name,
            "pattern": pattern,
            "params": params,
            "created": existing["created"] if existing else now,
            "updated": now,
        }
        self._save()
        return self._presets[name]

    def delete(self, name):
        if name not in self._presets:
            return False
        del self._presets[name]
        self._save()
        return True

    def random(self, exclude=None):
        """A random preset other than `exclude` (a preset name), or None if empty."""
        choices = [n for n in self._presets if n != exclude]
        if not choices:
            return None
        return self._presets[random.choice(choices)]
