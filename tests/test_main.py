import asyncio
import json

import pytest

import main
import patterns


@pytest.fixture(autouse=True)
def reset_app():
    main.current = "off"
    main.connected = True
    main.selection = 0
    for p in patterns.PATTERNS.values():
        p.reset()
    yield
    main.current = "off"
    main.connected = False


# --- parse_http_request -----------------------------------------------------


def test_parse_get_request():
    req = main.parse_http_request(b"GET / HTTP/1.1\r\nHost: lotus\r\n\r\n")
    assert req["method"] == "GET"
    assert req["path"] == "/"
    assert req["http_version"] == "HTTP/1.1"
    assert req["headers"] == {"Host": "lotus"}
    assert req["body"] == ""


def test_parse_post_with_json_body():
    raw = (
        b"POST / HTTP/1.1\r\n"
        b"Host: lotus\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 21\r\n"
        b"\r\n"
        b'{"pattern": "flower"}'
    )
    req = main.parse_http_request(raw)
    assert req["method"] == "POST"
    assert req["headers"]["Content-Type"] == "application/json"
    assert req["body"] == '{"pattern": "flower"}'


def test_parse_query_string_is_split_off_path():
    req = main.parse_http_request(b"GET /x?a=1&b=two&flag HTTP/1.1\r\n\r\n")
    assert req["path"] == "/x"
    assert req["query"] == {"a": "1", "b": "two", "flag": ""}


@pytest.mark.parametrize("raw, expected", [
    ("255%2C120%2C0", "255,120,0"),
    ("a+b", "a b"),
    ("%zz", "%zz"),          # malformed escapes pass through
    ("50%", "50%"),          # trailing percent passes through
    ("plain", "plain"),
])
def test_unquote(raw, expected):
    assert main.unquote(raw) == expected


def test_query_string_is_percent_decoded():
    req = main.parse_http_request(b"POST /rain?color=255%2C120%2C0&drops=3 HTTP/1.1\r\n\r\n")
    assert req["query"] == {"color": "255,120,0", "drops": "3"}


def test_post_path_with_encoded_color_query():
    status, body = http("POST", "/rain?color=255%2C120%2C0")
    assert status == 200 and body["params"]["color"] == [255, 120, 0]


def test_header_values_may_contain_colons():
    req = main.parse_http_request(b"GET / HTTP/1.1\r\nHost: 10.0.0.5:80\r\n\r\n")
    assert req["headers"]["Host"] == "10.0.0.5:80"


# --- select / current_pattern -----------------------------------------------


@pytest.mark.parametrize("name", patterns.ORDER)
def test_select_every_registered_name(name):
    assert main.select(name) == name
    assert main.current == name


def test_select_bumps_selection_so_the_loop_restarts_the_pattern():
    before = main.selection
    main.select("ripple")
    main.select("ripple")
    assert main.selection == before + 2


def test_select_unknown_returns_none_and_keeps_current():
    main.select("sweep")
    assert main.select("disco") is None
    assert main.current == "sweep"


def test_select_any_never_picks_current_off_or_clock():
    for start in patterns.ORDER:
        for _ in range(10):
            main.current = start
            picked = main.select("any")
            assert picked not in (start, "off", "clock")


def test_select_with_bad_params_does_not_switch():
    with pytest.raises(patterns.ParamError):
        main.select("rain", {"drops": "many"})
    assert main.current == "off"


def test_current_pattern_reports_connecting_while_wifi_down():
    main.connected = False
    assert main.current_pattern() == "connecting"
    main.connected = True
    main.select("pinwheel")
    assert main.current_pattern() == "pinwheel"


# --- HTTP handler end-to-end ------------------------------------------------


class FakeReader:
    """Yields `raw` in the given chunks, then b"" (connection closed)."""

    def __init__(self, raw, chunks=None):
        self.chunks = list(chunks) if chunks else [raw]

    async def read(self, n):
        return self.chunks.pop(0) if self.chunks else b""


class FakeWriter:
    def __init__(self):
        self.out = b""
        self.closed = False

    async def awrite(self, data):
        self.out += data

    async def drain(self):
        pass

    async def wait_closed(self):
        self.closed = True


def http(method, target, body=None):
    raw = ("%s %s HTTP/1.1\r\nHost: lotus\r\n" % (method, target)).encode()
    payload = json.dumps(body).encode() if body is not None else b""
    raw += b"Content-Type: application/json\r\nContent-Length: %d\r\n" % len(payload)
    raw += b"\r\n" + payload
    w = FakeWriter()
    asyncio.run(main.serve_client(FakeReader(raw), w))
    assert w.closed
    head, _, resp_body = w.out.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    assert b"Content-Length: %d" % len(resp_body) in head
    return status, json.loads(resp_body)


def test_get_root_reports_pattern_and_params():
    main.select("ripple")
    status, body = http("GET", "/")
    assert status == 200
    assert body["pattern"] == "ripple"
    assert body["params"]["spread"] == 0.5


def test_get_root_reports_connecting():
    main.connected = False
    assert http("GET", "/")[1]["pattern"] == "connecting"


def test_get_patterns_lists_schemas():
    status, body = http("GET", "/patterns")
    assert status == 200
    assert body["order"] == patterns.ORDER
    assert body["patterns"]["rain"]["params"]["drops"]["max"] == 20
    assert body["current"] == "off"


def test_post_path_selects_pattern():
    status, body = http("POST", "/flower")
    assert status == 200 and body["pattern"] == "flower"
    assert main.current == "flower"


def test_post_path_with_query_params():
    status, body = http("POST", "/rain?drops=8&inward=false&color=0,0,255")
    assert status == 200
    assert body["params"]["drops"] == 8
    assert body["params"]["inward"] is False
    assert body["params"]["color"] == [0, 0, 255]


def test_post_root_json_selects_with_params():
    status, body = http("POST", "/", {"pattern": "pinwheel", "params": {"arms": 5}})
    assert status == 200
    assert main.current == "pinwheel"
    assert patterns.get("pinwheel").values["arms"] == 5


def test_post_root_json_pattern_only_keeps_existing_params():
    patterns.get("rain").set({"drops": 12})
    http("POST", "/", {"pattern": "rain"})
    assert patterns.get("rain").values["drops"] == 12


def test_post_params_tunes_live_without_restart():
    main.select("rain")
    before = main.selection
    status, body = http("POST", "/params", {"fade": 5})
    assert status == 200
    assert body["params"]["fade"] == 5
    assert main.selection == before


def test_post_params_via_query_string():
    main.select("ripple")
    assert http("POST", "/params?speed=0.05")[1]["params"]["speed"] == 0.05


def test_post_unknown_pattern_is_404_with_list():
    status, body = http("POST", "/disco")
    assert status == 404
    assert body["patterns"] == patterns.ORDER


def test_post_bad_param_is_400_and_does_not_switch():
    status, body = http("POST", "/rain?drops=lots")
    assert status == 400 and "drops" in body["error"]
    assert main.current == "off"


def test_post_unknown_param_is_400():
    status, body = http("POST", "/rain?wat=1")
    assert status == 400 and "wat" in body["error"]


def test_post_invalid_json_is_400():
    raw = b"POST / HTTP/1.1\r\n\r\n{not json"
    w = FakeWriter()
    asyncio.run(main.serve_client(FakeReader(raw), w))
    assert w.out.startswith(b"HTTP/1.1 400")


def test_post_root_without_pattern_is_400():
    assert http("POST", "/", {"params": {"fade": 1}})[0] == 400


def test_put_is_405():
    assert http("PUT", "/rain")[0] == 405


def test_body_arriving_in_a_second_segment_is_read_fully():
    payload = json.dumps({"pattern": "rain", "params": {"drops": 7}}).encode()
    head = b"POST / HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(payload)
    w = FakeWriter()
    asyncio.run(main.serve_client(FakeReader(None, chunks=[head, payload]), w))
    assert w.out.startswith(b"HTTP/1.1 200")
    assert patterns.get("rain").values["drops"] == 7


def test_body_split_mid_json_is_read_fully():
    payload = json.dumps({"pattern": "rain", "params": {"drops": 3}}).encode()
    head = b"POST / HTTP/1.1\r\nContent-Length: %d\r\n\r\n" % len(payload)
    chunks = [head + payload[:5], payload[5:12], payload[12:]]
    w = FakeWriter()
    asyncio.run(main.serve_client(FakeReader(None, chunks=chunks), w))
    assert w.out.startswith(b"HTTP/1.1 200")
    assert patterns.get("rain").values["drops"] == 3


def test_short_body_with_closed_connection_does_not_hang():
    head = b"POST / HTTP/1.1\r\nContent-Length: 500\r\n\r\n{"
    w = FakeWriter()
    asyncio.run(main.serve_client(FakeReader(None, chunks=[head]), w))
    assert w.out.startswith(b"HTTP/1.1 400")


# --- frame timing -----------------------------------------------------------


def test_frame_delay_sleeps_the_remainder_with_a_floor():
    assert main.frame_delay(0.05, 0.010) == pytest.approx(0.040)
    assert main.frame_delay(0.01, 0.030) == main.MIN_SLEEP
    assert main.frame_delay(0.002, 0.0) == main.MIN_SLEEP


def test_frame_stats_averages_and_reports():
    st = main.FrameStats(alpha=0.5)
    assert st.to_json() == {"compute_ms": None, "period_ms": None, "fps": None, "frames": 0}
    st.update(10_000)                       # first frame: no period yet
    st.update(20_000, period_us=50_000)
    st.update(20_000, period_us=50_000)
    j = st.to_json()
    assert j["frames"] == 3
    assert j["compute_ms"] == pytest.approx(17.5)
    assert j["period_ms"] == pytest.approx(50.0)
    assert j["fps"] == pytest.approx(20.0)
    st.reset()
    assert st.frames == 0 and st.compute_ms is None


def test_status_includes_timing():
    main.select("ripple")
    body = http("GET", "/")[1]
    assert set(body["timing"]) == {"compute_ms", "period_ms", "fps", "frames"}


def test_select_wakes_a_sleeping_render_loop():
    import time as _t

    async def run():
        main.wake = asyncio.Event()
        t0 = _t.perf_counter()
        task = asyncio.ensure_future(main.sleep_or_wake(2.0))
        await asyncio.sleep(0.05)
        main.select("ripple")          # sets main.wake
        await task
        return _t.perf_counter() - t0

    assert asyncio.run(run()) < 0.5


def test_sleep_or_wake_times_out_normally():
    async def run():
        main.wake = asyncio.Event()
        await asyncio.wait_for(main.sleep_or_wake(0.02), timeout=1)
        assert not main.wake.is_set()
    asyncio.run(run())
    main.wake = None


def test_sleep_or_wake_without_an_event_is_a_plain_sleep():
    main.wake = None
    asyncio.run(asyncio.wait_for(main.sleep_or_wake(0.01), timeout=1))
