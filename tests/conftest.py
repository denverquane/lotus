import pytest

import led


@pytest.fixture(autouse=True)
def reset_strips():
    """Every test starts with all three strips black at full brightness."""
    led.clear()
    led.brightness = 1.0
    yield
    led.clear()
    led.brightness = 1.0


def lit_pixels():
    """Return {(strip_name, index): color} for every non-black pixel across all strips."""
    out = {}
    for name, strip in (("left", led.left), ("right", led.right), ("top", led.top)):
        for i in range(led.numPixels):
            if strip[i] != (0, 0, 0):
                out[(name, i)] = strip[i]
    return out
