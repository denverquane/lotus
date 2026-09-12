"""Desktop simulator: runs the real firmware render loop against the stub strips.

`main.py` and `patterns.py` are imported through the desktop stubs, so the
frames produced here are exactly what the Pico would push to its strips for
the same pattern, params and (random) seed. Pattern selection reuses
main.select / main.set_params, so semantics match the device.

Frames are published to subscribers as raw RGB bytes in strip order
(left[0..59], right[0..59], top[0..59]); /api/sim/layout says where each of
those 180 pixels sits on the wall.
"""
import asyncio
import json
import math
import time
import traceback

import led
import main
import patterns

STRIPS = ("left", "right", "top")


def build_layout():
    """One entry per physical pixel, in frame order, with its wall position.

    x, y are in layout units (y down, for canvas), rings 0..5 from the center.
    """
    saved = led.brightness
    led.brightness = 1.0
    cells = []
    for angle in range(60):
        for radius in range(3):
            led.clear()
            led.set_led(angle, radius, (1, 1, 1))
            for si, name in enumerate(STRIPS):
                strip = getattr(led, name)
                for i in range(led.numPixels):
                    if strip[i] != (0, 0, 0):
                        ring = led.ring_of(angle, radius)
                        d = 1.0 + ring * 0.42
                        th = math.radians(90 - angle * 6)
                        cells.append({
                            "i": si * led.numPixels + i, "strip": name, "index": i,
                            "angle": angle, "radius": radius, "ring": ring,
                            "x": round(d * math.cos(th), 4), "y": round(-d * math.sin(th), 4),
                        })
    led.clear()
    led.brightness = saved
    cells.sort(key=lambda c: c["i"])
    assert len(cells) == 3 * led.numPixels
    return cells


class Simulator:
    def __init__(self, fps_cap=30, timing=None):
        self.fps_cap = fps_cap
        self.timing = timing          # TimingStore or None: learned per-pattern compute on the wall
        self.period = None            # seconds between frames the loop is currently using
        self.layout = build_layout()
        self.subscribers = set()
        self.frame_ms = 0.0
        self.error = None
        self.task = None
        main.connected = True  # the simulator is always "online"

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        main.wake = asyncio.Event()   # owned by this loop; main.select() sets it
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        main.wake = None

    # --- selection (delegates to main.py so semantics match the device) ---

    def select(self, name, updates=None):
        return main.select(name, updates)

    def tune(self, updates):
        return main.set_params(updates)

    def frame_period(self, pattern, interval):
        """What the wall's frame period would be: the firmware sleeps
        max(interval - compute, MIN_SLEEP), so the period is
        max(interval, compute + MIN_SLEEP). Unknown compute -> just the interval."""
        c = self.timing.compute_ms(pattern) if self.timing else None
        if c is None:
            return interval
        return max(interval, c / 1000.0 + main.MIN_SLEEP)

    def status(self):
        s = main.status()
        s["frame_ms"] = round(self.frame_ms, 2)
        s["period"] = self.period
        s["fps"] = None if not self.period else round(1 / self.period, 1)
        s["wall_compute_ms"] = self.timing.compute_ms(main.current) if self.timing else None
        s["error"] = self.error
        return s

    # --- render loop (mirrors main.main()) -------------------------------

    async def _run(self):
        running = -1
        state = None
        while True:
            p = patterns.get(main.current)
            t0 = time.perf_counter()
            try:
                if running != main.selection:
                    led.clear()
                    led.brightness = p.values["brightness"]
                    state = p.init(p.values)
                    running = main.selection
                    self.error = None
                led.brightness = p.values["brightness"]
                state = p.step(state, p.values)
            except Exception as e:  # a buggy pattern must not kill the server
                self.error = "%s: %s" % (type(e).__name__, e)
                traceback.print_exc()
                running = -1
                await asyncio.sleep(0.5)
                continue
            self.frame_ms = (time.perf_counter() - t0) * 1000
            self._publish(self.snapshot())
            self.period = self.frame_period(main.current, p.values["interval"])
            await main.sleep_or_wake(self.period)

    def snapshot(self):
        buf = bytearray()
        for name in STRIPS:
            strip = getattr(led, name)
            for i in range(led.numPixels):
                buf.extend(strip[i])
        return bytes(buf)

    def _publish(self, frame):
        for q in list(self.subscribers):
            if q.full():
                q.get_nowait()
            q.put_nowait(frame)

    # --- SSE ---------------------------------------------------------------

    def _event(self, frame):
        return "data: %s\n\n" % json.dumps({
            "p": main.current, "f": frame.hex(), "ms": round(self.frame_ms, 2), "err": self.error,
            "fps": None if not self.period else round(1 / self.period, 1),
            "wall_ms": self.timing.compute_ms(main.current) if self.timing else None})

    async def frames(self):
        """Async generator of SSE events, throttled to fps_cap; always sends the latest frame."""
        q = asyncio.Queue(maxsize=1)
        self.subscribers.add(q)
        try:
            yield self._event(self.snapshot())
            last = time.monotonic()
            while True:
                frame = await q.get()
                wait = 1.0 / self.fps_cap - (time.monotonic() - last)
                if wait > 0:
                    await asyncio.sleep(wait)
                    while not q.empty():
                        frame = q.get_nowait()
                last = time.monotonic()
                yield self._event(frame)
        finally:
            self.subscribers.discard(q)
