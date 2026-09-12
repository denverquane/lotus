"""Per-pattern timing learned from the wall, so the simulator can run at the
speed the Pico really achieves rather than the speed the interval asks for.

Learned passively from every status poll and actively by /api/calibrate.
Persisted as one JSON file next to the presets.
"""
import json
import os
import time

MIN_FRAMES = 3       # ignore a reading until the EMA has seen a few frames
SAVE_DELTA = 0.02    # only rewrite the file when a value moves by more than 2%


class TimingStore:
    def __init__(self, path):
        self.path = path
        self._t = {}
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._t = data
        except FileNotFoundError:
            pass

    def _save(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._t, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def learn(self, pattern, timing, force=False):
        """Record the wall's timing for `pattern`. Returns True if stored."""
        if not pattern or not isinstance(timing, dict):
            return False
        c = timing.get("compute_ms")
        if c is None or (timing.get("frames") or 0) < MIN_FRAMES:
            return False
        entry = {"compute_ms": c, "period_ms": timing.get("period_ms"), "fps": timing.get("fps"),
                 "updated": time.time()}
        old = self._t.get(pattern)
        self._t[pattern] = entry
        if force or old is None or abs(old["compute_ms"] - c) > SAVE_DELTA * max(old["compute_ms"], 0.01):
            self._save()
        return True

    def compute_ms(self, pattern):
        e = self._t.get(pattern)
        return None if e is None else e["compute_ms"]

    def all(self):
        return dict(self._t)
