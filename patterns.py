"""Pattern registry: every pattern, its tunable params, and how to run it.

A pattern is two functions plus a param schema:

    init(params) -> state          called when the pattern (re)starts
    step(state, params) -> state   draws one frame, returns the new state

`params` is a plain dict of the current values. Every pattern gets
"interval" (seconds between frames) and "brightness" (0..1) for free.
Params can change while a pattern runs; step() reads them every frame.
State is whatever the pattern wants to carry between frames; it is
never exposed outside the render loop.

Runs on MicroPython, so: no dataclasses, no typing, no f-strings.
"""
import random
import time

import led


class ParamError(ValueError):
    pass


class Param:
    """Schema for one tunable value. kind is "int", "float", "bool" or "color".

    A color is an (r, g, b) tuple of 0..255, or None meaning "let the
    pattern pick randomly".
    """

    def __init__(self, kind, default, lo=None, hi=None):
        self.kind = kind
        self.default = default
        self.lo = lo
        self.hi = hi

    def to_json(self):
        d = {"type": self.kind, "default": self.default}
        if self.lo is not None:
            d["min"] = self.lo
        if self.hi is not None:
            d["max"] = self.hi
        return d

    def coerce(self, value):
        """Return a valid value for this param, or raise ParamError.

        Accepts JSON-typed values and also strings (from query strings).
        Numbers are clamped into [lo, hi] rather than rejected.
        """
        if self.kind == "int" or self.kind == "float":
            if isinstance(value, bool):
                raise ParamError("expected a number")
            try:
                value = int(value) if self.kind == "int" else float(value)
            except (TypeError, ValueError):
                raise ParamError("expected a number")
            if self.lo is not None and value < self.lo:
                value = self.lo
            if self.hi is not None and value > self.hi:
                value = self.hi
            return value
        if self.kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("1", "true", "yes", "on"):
                    return True
                if v in ("0", "false", "no", "off"):
                    return False
            if value in (0, 1):
                return bool(value)
            raise ParamError("expected true or false")
        if self.kind == "color":
            if value is None:
                return None
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("", "random", "null", "none"):
                    return None
                value = v.split(",")
            try:
                r, g, b = [int(x) for x in value]
            except (TypeError, ValueError):
                raise ParamError("expected a color as [r, g, b] or 'random'")
            for x in (r, g, b):
                if x < 0 or x > 255:
                    raise ParamError("color channels must be 0..255")
            return (r, g, b)
        raise ParamError("unknown param kind " + self.kind)


class Pattern:
    def __init__(self, name, init, step, params=None, interval=0.05, brightness=1.0):
        self.name = name
        self.init = init
        self.step = step
        self.params = {
            "interval": Param("float", interval, 0.005, 5.0),
            "brightness": Param("float", brightness, 0.0, 1.0),
        }
        if params:
            self.params.update(params)
        self.values = {}
        for k in self.params:
            self.values[k] = self.params[k].default

    def set(self, updates):
        """Validate and apply a dict of param updates. All-or-nothing."""
        coerced = {}
        for k in updates:
            if k not in self.params:
                raise ParamError("unknown param '%s' for %s; valid: %s"
                                 % (k, self.name, ", ".join(sorted(self.params))))
            try:
                coerced[k] = self.params[k].coerce(updates[k])
            except ParamError as e:
                raise ParamError("%s: %s" % (k, e))
        self.values.update(coerced)
        return self.values

    def reset(self):
        for k in self.params:
            self.values[k] = self.params[k].default

    def to_json(self):
        out = {}
        for k in self.params:
            d = self.params[k].to_json()
            d["value"] = self.values[k]
            out[k] = d
        return {"name": self.name, "params": out}


PATTERNS = {}
ORDER = []


def register(name, init, step, params=None, interval=0.05, brightness=1.0):
    PATTERNS[name] = Pattern(name, init, step, params, interval, brightness)
    ORDER.append(name)


def get(name):
    return PATTERNS[name]


def random_name(exclude=None):
    """A random animated pattern, never off/clock and never `exclude`."""
    choices = [n for n in ORDER if n not in ("off", "clock", exclude)]
    return random.choice(choices)


def to_json():
    return {n: PATTERNS[n].to_json() for n in ORDER}


def _pick(color):
    return led.random_color() if color is None else color


def _noop(state, p):
    return state


# --- off / clock ------------------------------------------------------------

def _off_init(p):
    led.clear()
    led.write()


def _clock_step(state, p):
    led.led_time(time.localtime())
    return state


# --- legacy patterns (thin wrappers around led.py step functions) -----------

def _random_step(state, p):
    led.random_led(p["fade"])
    return state


def _sweep_init(p):
    return [0, _pick(p["color"])]


def _sweep_step(s, p):
    s[0], c = led.sweep_leds(s[0], s[1], p["fade"])
    s[1] = c if p["color"] is None else p["color"]
    return s


def _radial_init(p):
    return [_pick(p["color"]), 0]


def _radial_step(s, p):
    c, s[1] = led.radial_leds(s[0], s[1], p["fade"])
    s[0] = c if p["color"] is None else p["color"]
    return s


def _bounce_init(heads):
    def init(p):
        colors = [_pick(p["color"]) for _ in range(heads)]
        angles = [0, 0, 0, 1, 1, 1][:heads]
        stride = p["stride"]
        dirs = [random.choice([-stride, stride]) for _ in range(heads)]
        return [colors, angles, dirs]
    return init


def _bounce_step(s, p):
    if p["color"] is not None:
        s[0] = [p["color"]] * len(s[0])
    s[1], s[2] = led.bounce_leds(s[0], s[1], s[2], p["prob"], p["fade"])
    return s


def _flower_init(p):
    return [59, _pick(p["color"]), _pick(p["inner_color"])]


def _flower_step(s, p):
    if p["color"] is not None:
        s[1] = p["color"]
    if p["inner_color"] is not None:
        s[2] = p["inner_color"]
    s[0] = led.flower(s[0], s[1], s[2])
    return s


def _ripple_init(p):
    return 0.0


def _ripple_step(phase, p):
    return led.ripple(phase, p["spread"], 1.0, p["speed"])


def _pinwheel_init(p):
    return [0, random.random()]


def _pinwheel_step(s, p):
    s[0], s[1] = led.pinwheel(s[0], s[1], p["arms"], p["twist"], p["fade"], 1.0, p["hue_speed"])
    return s


# --- rain -------------------------------------------------------------------
# Drops spawn on the outer ring and fall into the dark center (or the reverse
# with inward=false), leaving a fading trail. A drop is [ring, cell, color].

def _rain_spawn(p):
    ring = led.NUM_RINGS - 1 if p["inward"] else 0
    return [ring, random.randint(0, led.CELLS_PER_RING - 1), _pick(p["color"])]


def _rain_init(p):
    drops = []
    for _ in range(p["drops"]):
        d = _rain_spawn(p)
        d[0] = random.randint(0, led.NUM_RINGS - 1)  # stagger the first wave
        drops.append(d)
    return drops


def _rain_step(drops, p):
    led.fade_all(p["fade"])
    n = p["drops"]
    while len(drops) < n:
        drops.append(_rain_spawn(p))
    del drops[n:]
    step = -1 if p["inward"] else 1
    for d in drops:
        led.set_cell(d[0], d[1], d[2])
        d[0] += step
        if d[0] < 0 or d[0] >= led.NUM_RINGS:
            d[:] = _rain_spawn(p)
    led.write()
    return drops


# --- registry ---------------------------------------------------------------

register("off", _off_init, _noop, interval=1.0)
register("clock", lambda p: None, _clock_step, interval=1.0)
register("random", lambda p: None, _random_step, interval=0.01,
         params={"fade": Param("int", 1, 0, 255)})
register("sweep", _sweep_init, _sweep_step, interval=0.01,
         params={"fade": Param("int", 3, 0, 255), "color": Param("color", None)})
register("radial", _radial_init, _radial_step, interval=0.05,
         params={"fade": Param("int", 40, 0, 255), "color": Param("color", None)})
register("bounce", _bounce_init(6), _bounce_step, interval=0.01,
         params={"prob": Param("int", 10, 0, 100), "fade": Param("int", 15, 0, 255),
                 "stride": Param("int", 2, 1, 5), "color": Param("color", None)})
register("simple_bounce", _bounce_init(3), _bounce_step, interval=0.01,
         params={"prob": Param("int", 5, 0, 100), "fade": Param("int", 5, 0, 255),
                 "stride": Param("int", 1, 1, 5), "color": Param("color", None)})
register("flower", _flower_init, _flower_step, interval=0.2,
         params={"color": Param("color", None), "inner_color": Param("color", None)})
register("ripple", _ripple_init, _ripple_step, interval=0.05, brightness=0.5,
         params={"spread": Param("float", 0.5, 0.0, 1.0), "speed": Param("float", 0.01, 0.0, 0.2)})
register("pinwheel", _pinwheel_init, _pinwheel_step, interval=0.08, brightness=0.5,
         params={"arms": Param("int", 3, 1, 10), "twist": Param("int", 1, -5, 5),
                 "fade": Param("int", 40, 0, 255), "hue_speed": Param("float", 0.002, 0.0, 0.1)})
register("rain", _rain_init, _rain_step, interval=0.08, brightness=0.6,
         params={"drops": Param("int", 4, 1, 20), "fade": Param("int", 30, 0, 255),
                 "inward": Param("bool", True), "color": Param("color", None)})
