import json

import pytest

import led
import patterns
from conftest import lit_pixels
from patterns import Param, ParamError


@pytest.fixture(autouse=True)
def reset_params():
    for p in patterns.PATTERNS.values():
        p.reset()
    yield
    for p in patterns.PATTERNS.values():
        p.reset()


# --- Param.coerce -------------------------------------------------------------


@pytest.mark.parametrize(
    "param, value, expected",
    [
        (Param("int", 5, 1, 10), 7, 7),
        (Param("int", 5, 1, 10), "7", 7),
        (Param("int", 5, 1, 10), 7.9, 7),
        (Param("int", 5, 1, 10), 99, 10),      # clamped
        (Param("int", 5, 1, 10), -3, 1),       # clamped
        (Param("float", 0.5, 0, 1), "0.25", 0.25),
        (Param("float", 0.5, 0, 1), 2, 1.0),
        (Param("bool", True), False, False),
        (Param("bool", True), "false", False),
        (Param("bool", True), "on", True),
        (Param("bool", True), 0, False),
        (Param("color", None), None, None),
        (Param("color", None), "random", None),
        (Param("color", None), [255, 0, 10], (255, 0, 10)),
        (Param("color", None), "255,0,10", (255, 0, 10)),
    ],
)
def test_coerce_accepts(param, value, expected):
    assert param.coerce(value) == expected


@pytest.mark.parametrize(
    "param, value",
    [
        (Param("int", 5, 1, 10), "seven"),
        (Param("int", 5, 1, 10), True),
        (Param("float", 0.5), None),
        (Param("bool", True), "maybe"),
        (Param("bool", True), 2),
        (Param("color", None), [255, 0]),
        (Param("color", None), [256, 0, 0]),
        (Param("color", None), "red"),
    ],
)
def test_coerce_rejects(param, value):
    with pytest.raises(ParamError):
        param.coerce(value)


# --- Pattern.set / to_json --------------------------------------------------


def test_every_pattern_has_universal_params_with_defaults_in_range():
    for name in patterns.ORDER:
        p = patterns.get(name)
        assert "interval" in p.params and "brightness" in p.params
        for k, schema in p.params.items():
            v = p.values[k]
            assert schema.coerce(v) == v, (name, k, v)


def test_set_merges_and_returns_values():
    p = patterns.get("rain")
    out = p.set({"drops": "9", "inward": "false"})
    assert out["drops"] == 9 and out["inward"] is False
    assert out["fade"] == 30  # untouched


def test_set_unknown_param_is_all_or_nothing():
    p = patterns.get("rain")
    with pytest.raises(ParamError, match="unknown param 'wat'"):
        p.set({"drops": 2, "wat": 1})
    assert p.values["drops"] == 4


def test_set_bad_value_names_the_param():
    with pytest.raises(ParamError, match="drops"):
        patterns.get("rain").set({"drops": "lots"})


def test_to_json_is_serializable_and_carries_values():
    patterns.get("ripple").set({"spread": 0.25})
    blob = json.loads(json.dumps(patterns.to_json()))
    assert blob["ripple"]["params"]["spread"] == {
        "type": "float", "default": 0.5, "min": 0.0, "max": 1.0, "value": 0.25}
    assert blob["rain"]["params"]["color"]["default"] is None
    assert set(blob) == set(patterns.ORDER)


def test_random_name_excludes_off_clock_and_current():
    for _ in range(50):
        n = patterns.random_name(exclude="ripple")
        assert n not in ("off", "clock", "ripple")
        assert n in patterns.PATTERNS


# --- every pattern runs -----------------------------------------------------


@pytest.mark.parametrize("name", patterns.ORDER)
def test_every_pattern_runs_fifty_frames_with_defaults(name):
    p = patterns.get(name)
    led.brightness = p.values["brightness"]
    state = p.init(p.values)
    for _ in range(50):
        state = p.step(state, p.values)
    if name == "off":
        assert lit_pixels() == {}
    else:
        assert lit_pixels(), "%s drew nothing" % name


@pytest.mark.parametrize("name", [n for n in patterns.ORDER if "color" in patterns.get(n).params])
def test_fixed_color_params_are_honoured(name):
    p = patterns.get(name)
    p.set({"color": [0, 0, 200]})
    if "inner_color" in p.params:
        p.set({"inner_color": [0, 0, 200]})
    state = p.init(p.values)
    for _ in range(20):
        state = p.step(state, p.values)
    for color in lit_pixels().values():
        assert color[0] == 0 and color[1] == 0 and color[2] > 0, (name, color)


def test_brightness_scales_colors_at_set_led():
    led.brightness = 0.5
    led.set_led(0, 0, (200, 100, 0))
    assert list(lit_pixels().values()) == [(100, 50, 0)]


# --- rain -------------------------------------------------------------------


def test_rain_shows_one_cell_per_drop_when_trail_fades_instantly():
    p = patterns.get("rain")
    p.set({"drops": 6, "fade": 255, "color": [200, 200, 200]})
    state = p.init(p.values)
    for _ in range(10):
        positions = {(d[0], d[1]) for d in state}  # drops may share a cell
        state = p.step(state, p.values)
        assert len(lit_pixels()) == len(positions)


def test_rain_falls_inward_and_respawns_on_outer_ring():
    p = patterns.get("rain")
    p.set({"drops": 1, "fade": 255})
    drops = [[3, 7, (1, 2, 3)]]
    drops = p.step(drops, p.values)
    assert drops[0][:2] == [2, 7]
    drops = p.step(drops, p.values)
    drops = p.step(drops, p.values)
    assert drops[0][0] == 0
    drops = p.step(drops, p.values)  # drew ring 0, then fell off the inside
    assert drops[0][0] == led.NUM_RINGS - 1


def test_rain_outward_respawns_on_inner_ring():
    p = patterns.get("rain")
    p.set({"drops": 1, "inward": False})
    drops = [[led.NUM_RINGS - 1, 0, (9, 9, 9)]]
    drops = p.step(drops, p.values)
    assert drops[0][0] == 0


def test_rain_drop_count_changes_live():
    p = patterns.get("rain")
    state = p.init(p.values)
    p.set({"drops": 10})
    state = p.step(state, p.values)
    assert len(state) == 10
    p.set({"drops": 2})
    state = p.step(state, p.values)
    assert len(state) == 2
