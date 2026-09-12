"""Render the Lotus layout on the desktop using the real led.py mapping.

    uv run --group render tools/render_layout.py [out.png]

Every pixel's position comes from: angle -> clockwise from 12 o'clock,
visual ring = 2*radius + (angle % 2) -> distance from center.
Pattern colors come from the real led.py functions run against stubs/,
so this doubles as a visual check that the wiring math is right.
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "stubs"), ROOT]
import led  # noqa: E402

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import RegularPolygon  # noqa: E402

STRIPS = {"left": led.left, "right": led.right, "top": led.top}
STRIP_COLOR = {"left": "#4c8be8", "right": "#e8574c", "top": "#4cc86b"}


def ring_of(angle, radius):
    return 2 * radius + (angle % 2)


def xy(angle, radius):
    ring = ring_of(angle, radius)
    d = 1.0 + ring * 0.42
    theta = math.radians(90 - angle * 6)  # clockwise from 12 o'clock
    return d * math.cos(theta), d * math.sin(theta), ring, theta


def cell_size(ring):
    return 0.10 + ring * 0.022


# Build (strip, index) -> (angle, radius) by lighting each coordinate once.
pixel_of = {}
coord_of = {}
for angle in range(60):
    for radius in range(3):
        led.clear()
        led.set_led(angle, radius, (1, 1, 1))
        for name, strip in STRIPS.items():
            for i in range(led.numPixels):
                if strip[i] != (0, 0, 0):
                    pixel_of[(angle, radius)] = (name, i)
                    coord_of[(name, i)] = (angle, radius)
assert len(pixel_of) == 180 and len(coord_of) == 180


def draw_cells(ax, color_fn, title):
    ax.set_facecolor("#111")
    for (angle, radius), (name, i) in pixel_of.items():
        x, y, ring, theta = xy(angle, radius)
        ax.add_patch(RegularPolygon((x, y), 6, radius=cell_size(ring),
                                    orientation=theta, facecolor=color_fn(angle, radius, name, i),
                                    edgecolor="#333", linewidth=0.5))
    ax.set_xlim(-3.5, 3.5)
    ax.set_ylim(-3.5, 3.5)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, color="white", fontsize=11)
    # compass labels
    for a, lbl in [(0, "angle 0\n(12 o'clock)"), (15, "15\n(3)"), (30, "30\n(6)"), (45, "45\n(9)")]:
        th = math.radians(90 - a * 6)
        ax.text(3.35 * math.cos(th), 3.35 * math.sin(th), lbl, color="#aaa", ha="center", va="center", fontsize=7)


import patterns  # noqa: E402

# Panel list: layout + clock + every animated pattern from the registry, with defaults.
names = [n for n in patterns.ORDER if n not in ("off", "clock")]
cols = 4
rows = (2 + len(names) + cols - 1) // cols
fig, axes = plt.subplots(rows, cols, figsize=(6 * cols, 6.3 * rows))
axes = axes.flatten()
fig.patch.set_facecolor("#111")

# Panel 1: strips + wiring order
ax = axes[0]
draw_cells(ax, lambda a, r, name, i: STRIP_COLOR[name], "Strips & wiring order (line = data path, dot = index 0)")
for name, strip in STRIPS.items():
    pts = [xy(*coord_of[(name, i)])[:2] for i in range(led.numPixels)]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], color="white", linewidth=0.7, alpha=0.8)
    ax.plot(*pts[0], "o", color="white", markersize=5)
for a in range(0, 60, 5):
    th = math.radians(90 - a * 6)
    ax.text(3.15 * math.cos(th), 3.15 * math.sin(th), str(a), color="#777", ha="center", va="center", fontsize=6)
for ring in range(6):
    th = math.radians(90 - 20 * 6 + 3)
    d = 1.0 + ring * 0.42
    ax.text(d * math.cos(th), d * math.sin(th), "ring %d" % ring, color="#ddd", ha="center", va="center", fontsize=6,
            bbox=dict(facecolor="#000", edgecolor="none", alpha=0.6, pad=1))


def snapshot_color(a, r, name, i):
    c = STRIPS[name][i]
    return "#222" if c == (0, 0, 0) else tuple(v / 255 for v in c)


# Panel 2: real clock pattern at 10:08:37
led.clear()
led.brightness = 1.0
led.led_time((2026, 9, 11, 10, 8, 37, 0, 0))
draw_cells(axes[1], snapshot_color, "led_time() at 10:08:37\nblue=hour  yellow=minute  red=second")

# One panel per registered pattern, run for a few frames with default params.
FRAMES = {"sweep": 40, "radial": 3, "bounce": 30, "simple_bounce": 30, "random": 80}
for ax, name in zip(axes[2:], names):
    pat = patterns.get(name)
    pat.reset()
    led.clear()
    led.brightness = pat.values["brightness"]
    state = pat.init(pat.values)
    for _ in range(FRAMES.get(name, 6)):
        state = pat.step(state, pat.values)
    tunables = ", ".join(k for k in pat.params if k not in ("interval", "brightness")) or "(none)"
    draw_cells(ax, snapshot_color, "%s\nparams: %s" % (name, tunables))

for ax in axes[2 + len(names):]:
    ax.set_visible(False)

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "lotus_layout.png")
fig.tight_layout()
fig.savefig(out, dpi=100, facecolor=fig.get_facecolor())
print("wrote", out)
