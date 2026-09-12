"""Desktop stand-in for MicroPython's `neopixel` module. Only for tests; never flash this.

A NeoPixel is just a list of (r, g, b) tuples with a no-op write().
"""


class NeoPixel:
    def __init__(self, pin, n, *args, **kwargs):
        self.pin = pin
        self.n = n
        self._buf = [(0, 0, 0)] * n
        self.write_count = 0

    def __getitem__(self, i):
        return self._buf[i]

    def __setitem__(self, i, color):
        self._buf[i] = tuple(color)

    def __len__(self):
        return self.n

    def write(self):
        self.write_count += 1

    def fill(self, color):
        self._buf = [tuple(color)] * self.n
