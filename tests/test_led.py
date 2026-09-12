import pytest

import led
from conftest import lit_pixels

ALL_COORDS = [(a, r) for a in range(60) for r in range(3)]


def test_get_region_tiles_every_angle_exactly_once():
    for angle in range(60):
        assert led.get_region(angle) in (led.TOP, led.RIGHT, led.LEFT), angle


def test_get_region_layout():
    assert all(led.get_region(a) == led.TOP for a in list(range(50, 60)) + list(range(0, 10)))
    assert all(led.get_region(a) == led.RIGHT for a in range(10, 30))
    assert all(led.get_region(a) == led.LEFT for a in range(30, 50))


def test_to_value_stays_within_strip():
    for angle, radius in ALL_COORDS:
        assert 0 <= led.to_value(angle, radius) < led.numPixels


def test_every_polar_coord_maps_to_a_unique_pixel():
    """The core wiring invariant: 60 angles x 3 radii must cover all 180 pixels with no collisions."""
    seen = {}
    for angle, radius in ALL_COORDS:
        led.clear()
        led.set_led(angle, radius, (1, 1, 1))
        lit = lit_pixels()
        assert len(lit) == 1, f"({angle}, {radius}) lit {len(lit)} pixels"
        pixel = next(iter(lit))
        assert pixel not in seen, f"({angle}, {radius}) collides with {seen[pixel]} at {pixel}"
        seen[pixel] = (angle, radius)
    assert len(seen) == 3 * led.numPixels


def test_each_strip_gets_exactly_twenty_columns():
    counts = {"left": 0, "right": 0, "top": 0}
    for angle, radius in ALL_COORDS:
        led.clear()
        led.set_led(angle, radius, (1, 1, 1))
        (name, _), = lit_pixels()
        counts[name] += 1
    assert counts == {"left": 60, "right": 60, "top": 60}


@pytest.mark.parametrize("a, b", [(-1, 59), (-60, 0), (60, 0), (61, 1), (119, 59)])
def test_set_led_wraps_angles(a, b):
    led.set_led(a, 1, (5, 5, 5))
    wrapped = lit_pixels()
    led.clear()
    led.set_led(b, 1, (5, 5, 5))
    assert lit_pixels() == wrapped


def test_adjacent_angles_in_same_column_direction_alternate():
    """Zig-zag wiring: radius 0 and 2 swap physical order between neighbouring columns."""
    v = led.to_value
    # Two neighbouring angles inside one region.
    a0, a1 = 12, 13
    order0 = v(a0, 2) - v(a0, 0)
    order1 = v(a1, 2) - v(a1, 0)
    assert abs(order0) == 2 and abs(order1) == 2
    assert order0 == -order1


@pytest.mark.parametrize(
    "color, step, expected",
    [
        ((255, 0, 0), 10, (245, 0, 0)),
        ((5, 5, 5), 10, (0, 0, 0)),
        ((10, 10, 10), 10, (0, 0, 0)),
        ((11, 0, 30), 10, (1, 0, 20)),
    ],
)
def test_fade_color_clamps_at_zero(color, step, expected):
    assert led.fade_color(color, step) == expected


def test_fade_all_eventually_clears():
    led.set_led(0, 0, (255, 255, 255))
    led.set_led(30, 2, (3, 100, 200))
    for _ in range(26):
        led.fade_all(10)
    assert lit_pixels() == {}


def test_clear_zeroes_all_strips():
    for angle, radius in ALL_COORDS:
        led.set_led(angle, radius, (9, 9, 9))
    assert len(lit_pixels()) == 180
    led.clear()
    assert lit_pixels() == {}


def test_write_pushes_all_three_strips():
    before = (led.left.write_count, led.right.write_count, led.top.write_count)
    led.write()
    after = (led.left.write_count, led.right.write_count, led.top.write_count)
    assert all(b - a == 1 for a, b in zip(before, after))


def test_flower_advances_by_two_and_wraps():
    assert led.flower(0, (1, 1, 1), (2, 2, 2)) == 2
    assert led.flower(58, (1, 1, 1), (2, 2, 2)) == 0
    assert led.flower(59, (1, 1, 1), (2, 2, 2)) == 1


def test_sweep_wraps_and_picks_new_color_at_end():
    color = (7, 7, 7)
    assert led.sweep_leds(10, color, 1) == (11, color)
    angle, new_color = led.sweep_leds(59, color, 1)
    assert angle == 0
    assert len(new_color) == 3


# --- visual ring helpers ------------------------------------------------------


def test_ring_of_formula():
    assert led.ring_of(0, 0) == 0
    assert led.ring_of(1, 0) == 1
    assert led.ring_of(0, 1) == 2
    assert led.ring_of(1, 2) == 5
    assert {led.ring_of(a, r) for a, r in ALL_COORDS} == set(range(led.NUM_RINGS))


def test_set_cell_tiles_all_180_pixels_by_ring():
    """6 rings x 30 cells must hit every physical pixel exactly once."""
    seen = {}
    for ring in range(led.NUM_RINGS):
        for i in range(led.CELLS_PER_RING):
            led.clear()
            led.set_cell(ring, i, (1, 1, 1))
            (pixel,) = lit_pixels()
            assert pixel not in seen, f"ring {ring} cell {i} collides with {seen[pixel]}"
            seen[pixel] = (ring, i)
    assert len(seen) == 180


def test_set_cell_round_trips_through_ring_of():
    for ring in range(led.NUM_RINGS):
        for i in range(led.CELLS_PER_RING):
            angle, radius = 2 * i + ring % 2, ring // 2
            assert led.ring_of(angle, radius) == ring


@pytest.mark.parametrize(
    "hsv, rgb",
    [
        ((0.0, 1.0, 1.0), (255, 0, 0)),
        ((1 / 3, 1.0, 1.0), (0, 255, 0)),
        ((2 / 3, 1.0, 1.0), (0, 0, 255)),
        ((0.0, 0.0, 1.0), (255, 255, 255)),
        ((0.5, 1.0, 0.0), (0, 0, 0)),
        ((1.0, 1.0, 1.0), (255, 0, 0)),  # hue wraps
        ((-1 / 3, 1.0, 1.0), (0, 0, 255)),  # negative hue wraps
    ],
)
def test_hsv_to_rgb(hsv, rgb):
    assert led.hsv_to_rgb(*hsv) == rgb


def test_hsv_to_rgb_is_always_in_range():
    for step in range(0, 100):
        r, g, b = led.hsv_to_rgb(step / 100, 1.0, 0.7)
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255


# --- ripple -----------------------------------------------------------------


def ring_colors():
    """Set of colors present on each visual ring, read back from the strips."""
    out = {ring: set() for ring in range(led.NUM_RINGS)}
    for angle, radius in ALL_COORDS:
        led.clear()
        led.set_led(angle, radius, (1, 1, 1))
        (pixel,) = lit_pixels()
        out[led.ring_of(angle, radius)].add(pixel)
    return out


def test_ripple_paints_each_ring_one_solid_color():
    pixels_by_ring = ring_colors()
    led.ripple(0.0)
    lit = lit_pixels()
    assert len(lit) == 180
    colors_by_ring = []
    for ring in range(led.NUM_RINGS):
        colors = {lit[p] for p in pixels_by_ring[ring]}
        assert len(colors) == 1, f"ring {ring} has mixed colors {colors}"
        colors_by_ring.append(colors.pop())
    assert len(set(colors_by_ring)) == led.NUM_RINGS, "adjacent rings should differ"


def test_ripple_advances_and_wraps_phase():
    assert abs(led.ripple(0.0) - 0.01) < 1e-9
    assert led.ripple(0.995) < 0.01


def test_ripple_flows_outward():
    """The hue on ring r at phase p should appear on ring r+1 one 'spread step' later."""
    pixels_by_ring = ring_colors()
    step = 0.5 / led.NUM_RINGS
    led.ripple(0.3)
    inner = {ring: lit_pixels()[next(iter(pixels_by_ring[ring]))] for ring in range(led.NUM_RINGS)}
    led.ripple(0.3 + step)
    later = {ring: lit_pixels()[next(iter(pixels_by_ring[ring]))] for ring in range(led.NUM_RINGS)}
    for ring in range(led.NUM_RINGS - 1):
        # Same hue reached via different float paths can round one step apart.
        assert all(abs(a - b) <= 1 for a, b in zip(later[ring + 1], inner[ring])), (ring, later[ring + 1], inner[ring])


# --- pinwheel ---------------------------------------------------------------


def lit_cells_by_ring():
    """{ring: {cell_index}} for every lit pixel, via the set_cell mapping."""
    lit = lit_pixels()
    out = {ring: set() for ring in range(led.NUM_RINGS)}
    for ring in range(led.NUM_RINGS):
        for i in range(led.CELLS_PER_RING):
            angle, radius = 2 * i + ring % 2, ring // 2
            led.clear()
            led.set_led(angle, radius, (1, 1, 1))
            (pixel,) = lit_pixels()
            if pixel in lit:
                out[ring].add(i)
    return out


def test_pinwheel_draws_one_cell_per_arm_per_ring():
    led.pinwheel(0, 0.0, arms=3)
    cells = lit_cells_by_ring()
    for ring in range(led.NUM_RINGS):
        assert len(cells[ring]) == 3, (ring, cells[ring])


def test_pinwheel_arms_curve_by_twist_per_ring():
    led.pinwheel(5, 0.0, arms=3, twist=1)
    cells = lit_cells_by_ring()
    for ring in range(led.NUM_RINGS - 1):
        shifted = {(c + 1) % led.CELLS_PER_RING for c in cells[ring]}
        assert cells[ring + 1] == shifted, (ring, cells[ring], cells[ring + 1])


def test_pinwheel_arms_are_evenly_spaced():
    led.pinwheel(0, 0.0, arms=3, twist=0)
    cells = lit_cells_by_ring()
    assert cells[0] == {0, 10, 20}


def test_pinwheel_advances_pos_and_wraps():
    pos, hue = led.pinwheel(28, 0.5)
    assert (pos, round(hue, 3)) == (29, 0.502)
    pos, _ = led.pinwheel(29, 0.5)
    assert pos == 0


def test_pinwheel_leaves_fading_trail():
    led.pinwheel(0, 0.0, fade=40)
    led.pinwheel(1, 0.0, fade=40)
    cells = lit_cells_by_ring()
    # Ring 0 now has the current 3 arm cells plus 3 dimmer trail cells.
    assert len(cells[0]) == 6
