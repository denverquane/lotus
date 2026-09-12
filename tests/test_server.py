import json

import pytest
from fastapi.testclient import TestClient

import patterns
from server.app import create_app
from server.lotus import Unreachable
from server.presets import PresetStore
from server.timing import TimingStore


class FakeLotus:
    """Stands in for the Pico: records calls, replays canned answers."""

    def __init__(self):
        self.calls = []
        self.current = "off"
        self.reachable = True

    def _check(self):
        if not self.reachable:
            raise Unreachable("fake: down")

    async def close(self):
        pass

    async def status(self):
        self._check()
        return 200, {"pattern": self.current, "params": patterns.get(self.current).values,
                     "timing": {"compute_ms": 65.0, "period_ms": 68.0, "fps": 14.7, "frames": 40}}

    async def patterns(self):
        self._check()
        return 200, {"current": self.current, "order": patterns.ORDER, "patterns": patterns.to_json()}

    async def apply(self, pattern, params=None):
        self._check()
        self.calls.append(("apply", pattern, params))
        if pattern not in patterns.PATTERNS:
            return 404, {"error": "unknown pattern"}
        try:
            patterns.get(pattern).set(params or {})
        except patterns.ParamError as e:
            return 400, {"error": str(e)}
        self.current = pattern
        return 200, {"pattern": pattern, "params": patterns.get(pattern).values}

    async def tune(self, params):
        self._check()
        self.calls.append(("tune", params))
        try:
            patterns.get(self.current).set(params)
        except patterns.ParamError as e:
            return 400, {"error": str(e)}
        return 200, {"pattern": self.current, "params": patterns.get(self.current).values}

    async def any(self):
        self._check()
        self.calls.append(("any",))
        self.current = "sweep"
        return 200, {"pattern": "sweep", "params": {}}


@pytest.fixture
def fake():
    return FakeLotus()


@pytest.fixture
def client(tmp_path, fake):
    for p in patterns.PATTERNS.values():
        p.reset()
    store = PresetStore(str(tmp_path / "presets.json"))
    timing = TimingStore(str(tmp_path / "timing.json"))
    with TestClient(create_app(lotus=fake, store=store, timing=timing)) as c:
        c.timing = timing
        yield c


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_status_proxies_and_marks_reachable(client, fake):
    fake.current = "rain"
    body = client.get("/api/status").json()
    assert body["pattern"] == "rain" and body["reachable"] is True


def test_status_when_unreachable_is_200_with_flag(client, fake):
    fake.reachable = False
    body = client.get("/api/status").json()
    assert body["reachable"] is False


def test_patterns_from_device(client):
    body = client.get("/api/patterns").json()
    assert body["source"] == "device"
    assert body["order"] == patterns.ORDER


def test_patterns_falls_back_to_local_registry(client, fake):
    fake.reachable = False
    body = client.get("/api/patterns").json()
    assert body["source"] == "local"
    assert "rain" in body["patterns"]


def test_apply_forwards_to_device(client, fake):
    r = client.post("/api/apply", json={"pattern": "rain", "params": {"drops": 9}})
    assert r.status_code == 200
    assert fake.calls == [("apply", "rain", {"drops": 9})]
    assert r.json()["params"]["drops"] == 9


def test_apply_passes_device_errors_through(client):
    assert client.post("/api/apply", json={"pattern": "disco"}).status_code == 404
    r = client.post("/api/apply", json={"pattern": "rain", "params": {"drops": "x"}})
    assert r.status_code == 400 and "drops" in r.json()["error"]


def test_apply_without_pattern_is_400(client):
    assert client.post("/api/apply", json={}).status_code == 400


def test_tune_forwards_params(client, fake):
    fake.current = "ripple"
    r = client.post("/api/tune", json={"spread": 0.1})
    assert r.status_code == 200
    assert fake.calls == [("tune", {"spread": 0.1})]


def test_device_down_is_502(client, fake):
    fake.reachable = False
    r = client.post("/api/apply", json={"pattern": "rain"})
    assert r.status_code == 502
    assert r.json()["error"] == "lotus unreachable"


# --- presets ----------------------------------------------------------------


def test_preset_crud(client, tmp_path):
    r = client.put("/api/presets/Sunset", json={"pattern": "ripple", "params": {"spread": 0.2, "speed": "0.02"}})
    assert r.status_code == 200
    assert r.json()["params"] == {"spread": 0.2, "speed": 0.02}

    assert [p["name"] for p in client.get("/api/presets").json()["presets"]] == ["Sunset"]
    assert client.get("/api/presets/Sunset").json()["pattern"] == "ripple"

    # persisted to disk
    on_disk = json.loads((tmp_path / "presets.json").read_text())
    assert on_disk["Sunset"]["pattern"] == "ripple"

    assert client.delete("/api/presets/Sunset").json() == {"deleted": "Sunset"}
    assert client.get("/api/presets/Sunset").status_code == 404
    assert client.delete("/api/presets/Sunset").status_code == 404


def test_preset_update_keeps_created(client):
    a = client.put("/api/presets/x", json={"pattern": "rain", "params": {}}).json()
    b = client.put("/api/presets/x", json={"pattern": "rain", "params": {"drops": 2}}).json()
    assert b["created"] == a["created"] and b["updated"] >= a["updated"]
    assert b["params"] == {"drops": 2}


@pytest.mark.parametrize(
    "name, body, needle",
    [
        ("ok", {"pattern": "disco", "params": {}}, "unknown pattern"),
        ("ok", {"pattern": "rain", "params": {"wat": 1}}, "unknown param"),
        ("ok", {"pattern": "rain", "params": {"drops": "lots"}}, "drops"),
        ("bad!name", {"pattern": "rain", "params": {}}, "preset name"),
        ("ok", {}, "unknown pattern"),
    ],
)
def test_preset_validation(client, name, body, needle):
    r = client.put("/api/presets/" + name, json=body)
    assert r.status_code == 400, r.text
    assert needle in r.json()["error"]


def test_preset_values_are_clamped_like_the_device(client):
    r = client.put("/api/presets/loud", json={"pattern": "rain", "params": {"drops": 999}})
    assert r.json()["params"]["drops"] == 20


def test_apply_preset_forwards_and_reports_name(client, fake):
    client.put("/api/presets/Sunset", json={"pattern": "ripple", "params": {"spread": 0.2}})
    r = client.post("/api/presets/Sunset/apply")
    assert r.status_code == 200
    assert r.json()["preset"] == "Sunset"
    assert fake.calls[-1] == ("apply", "ripple", {"spread": 0.2})
    assert client.get("/api/status").json()["preset"] == "Sunset"


def test_apply_preset_unknown_is_404(client):
    assert client.post("/api/presets/nope/apply").status_code == 404


def test_apply_plain_pattern_clears_preset_name(client, fake):
    client.put("/api/presets/Sunset", json={"pattern": "ripple", "params": {}})
    client.post("/api/presets/Sunset/apply")
    client.post("/api/apply", json={"pattern": "rain"})
    assert client.get("/api/status").json()["preset"] is None


def test_random_with_no_presets_falls_back_to_device_any(client, fake):
    r = client.post("/api/random")
    assert r.status_code == 200 and fake.calls == [("any",)]


def test_random_picks_a_preset_and_never_repeats_the_last(client, fake):
    client.put("/api/presets/a", json={"pattern": "rain", "params": {}})
    client.put("/api/presets/b", json={"pattern": "ripple", "params": {}})
    seen = []
    for _ in range(10):
        seen.append(client.post("/api/random").json()["preset"])
    assert set(seen) == {"a", "b"}
    assert all(x != y for x, y in zip(seen, seen[1:]))


# --- Lotus client wire format -------------------------------------------------


def test_lotus_client_sends_params_as_query_string_with_no_body():
    import httpx
    from server.lotus import Lotus, encode

    assert encode({"drops": 8, "inward": False, "color": [255, 120, 0], "fade": None, "speed": 0.02}) == {
        "drops": "8", "inward": "false", "color": "255,120,0", "fade": "random", "speed": "0.02"}

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"pattern": "rain", "params": {}})

    lotus = Lotus("http://lotus.test")
    lotus._client = httpx.AsyncClient(base_url="http://lotus.test", transport=httpx.MockTransport(handler))
    import asyncio as _asyncio
    code, body = _asyncio.run(lotus.apply("rain", {"drops": 8, "color": None, "inward": True}))
    assert code == 200
    req = seen[0]
    assert req.method == "POST"
    assert req.url.path == "/rain"
    assert dict(req.url.params) == {"drops": "8", "color": "random", "inward": "true"}
    assert req.content == b""
    _asyncio.run(lotus.apply("rain", {"color": [255, 120, 0], "speed": -0.5}))
    assert "color=255,120,0" in str(seen[-1].url), str(seen[-1].url)  # commas must not be %2C
    assert "speed=-0.5" in str(seen[-1].url)
    _asyncio.run(lotus.tune({"fade": 5}))
    assert seen[-1].url.path == "/params" and dict(seen[-1].url.params) == {"fade": "5"}


# --- simulator ----------------------------------------------------------------


def test_sim_layout_covers_every_pixel_once_in_six_rings(client):
    body = client.get("/api/sim/layout").json()
    cells = body["cells"]
    assert len(cells) == 180
    assert [c["i"] for c in cells] == list(range(180))
    assert {(c["strip"], c["index"]) for c in cells} == {(s, i) for s in ("left", "right", "top") for i in range(60)}
    per_ring = {}
    for c in cells:
        per_ring[c["ring"]] = per_ring.get(c["ring"], 0) + 1
    assert per_ring == {r: 30 for r in range(6)}
    assert all(c["ring"] == 2 * c["radius"] + c["angle"] % 2 for c in cells)


def test_sim_apply_tune_status(client):
    r = client.post("/api/sim/apply", json={"pattern": "rain", "params": {"drops": 3}})
    assert r.status_code == 200 and r.json()["pattern"] == "rain" and r.json()["params"]["drops"] == 3
    r = client.post("/api/sim/tune", json={"drops": 7})
    assert r.status_code == 200 and r.json()["params"]["drops"] == 7
    assert client.get("/api/sim/status").json()["pattern"] == "rain"


def test_sim_errors(client):
    assert client.post("/api/sim/apply", json={"pattern": "disco"}).status_code == 404
    assert client.post("/api/sim/apply", json={}).status_code == 400
    client.post("/api/sim/apply", json={"pattern": "rain"})
    r = client.post("/api/sim/tune", json={"drops": "lots"})
    assert r.status_code == 400 and "drops" in r.json()["error"]


def test_sim_is_independent_of_the_wall(client, fake):
    client.post("/api/sim/apply", json={"pattern": "ripple"})
    assert fake.calls == []


def test_sim_frames_generator_streams_latest_frames():
    """The SSE route wraps this generator; TestClient can't stop an infinite stream,
    so the generator is tested directly and the route is checked live with curl."""
    import asyncio as _asyncio
    from server.sim import Simulator

    async def run():
        sim = Simulator(fps_cap=1000)
        sim.select("ripple")
        sim.start()
        gen = sim.frames()
        events = []
        try:
            for _ in range(3):
                line = await _asyncio.wait_for(gen.__anext__(), timeout=5)
                assert line.startswith("data: ") and line.endswith("\n\n")
                events.append(json.loads(line[6:]))
        finally:
            await gen.aclose()
            await sim.stop()
        assert not sim.subscribers
        return events

    events = _asyncio.run(run())
    assert all(len(e["f"]) == 180 * 6 for e in events)   # 180 pixels x rrggbb
    assert events[-1]["p"] == "ripple"
    assert set(events[-1]["f"]) != {"0"}, "ripple should light pixels"
    assert events[-1]["err"] is None


def test_sim_survives_a_crashing_pattern():
    import asyncio as _asyncio
    from server.sim import Simulator

    async def run():
        sim = Simulator()
        bad = patterns.Pattern("bad", lambda p: None, lambda s, p: 1 / 0, interval=0.001)
        patterns.PATTERNS["bad"] = bad
        try:
            sim.select("bad")
            sim.start()
            await _asyncio.sleep(0.1)
            assert "ZeroDivisionError" in sim.status()["error"]
            sim.select("ripple")
            await _asyncio.sleep(0.8)  # the loop backs off 0.5 s after a crash
            assert sim.status()["error"] is None
        finally:
            await sim.stop()
            del patterns.PATTERNS["bad"]

    _asyncio.run(run())


# --- timing / calibration ---------------------------------------------------


def test_timing_store_learns_and_persists(tmp_path):
    path = str(tmp_path / "timing.json")
    ts = TimingStore(path)
    assert ts.compute_ms("rain") is None
    assert ts.learn("rain", {"compute_ms": 60.0, "frames": 1}) is False      # too few frames
    assert ts.learn("rain", {"compute_ms": 60.0, "fps": 15.0, "frames": 40}) is True
    assert ts.compute_ms("rain") == 60.0
    assert TimingStore(path).compute_ms("rain") == 60.0                       # reloaded from disk
    assert ts.learn(None, {"compute_ms": 1, "frames": 9}) is False
    assert ts.learn("rain", None) is False


def test_status_poll_learns_wall_timing(client):
    assert client.timing.compute_ms("off") is None
    body = client.get("/api/status").json()
    assert body["timing"]["compute_ms"] == 65.0
    assert client.timing.compute_ms("off") == 65.0
    assert client.get("/api/timing").json()["timing"]["off"]["fps"] == 14.7


def test_sim_paces_frames_to_wall_timing(client):
    sim = client.app.state.sim
    assert sim.frame_period("ripple", 0.05) == 0.05                 # nothing learned yet
    client.timing.learn("ripple", {"compute_ms": 65.0, "frames": 40})
    assert sim.frame_period("ripple", 0.05) == pytest.approx(0.067)  # compute + MIN_SLEEP wins
    assert sim.frame_period("ripple", 0.5) == 0.5                    # a long interval still wins
    client.post("/api/sim/apply", json={"pattern": "ripple"})
    import time as _t
    _t.sleep(0.3)
    st = client.get("/api/sim/status").json()
    assert st["wall_compute_ms"] == 65.0
    assert st["fps"] == pytest.approx(14.9, abs=0.2)


def test_calibrate_cycles_patterns_and_restores(client, fake):
    fake.current = "flower"
    r = client.post("/api/calibrate?seconds=0.01")
    assert r.status_code == 200 and r.json()["running"] is True
    import time as _t
    for _ in range(100):
        c = client.get("/api/calibrate").json()
        if not c["running"]:
            break
        _t.sleep(0.05)
    assert not c["running"]
    expected = [n for n in patterns.ORDER if n != "off"]
    assert c["done"] == c["total"] == len(expected)
    assert set(c["results"]) == set(expected)
    applied = [call[1] for call in fake.calls if call[0] == "apply"]
    assert applied == expected + ["flower"]              # every pattern, then back to what was on
    assert client.timing.compute_ms("pinwheel") == 65.0
    assert client.get("/api/timing").json()["timing"]["rain"]["compute_ms"] == 65.0


def test_calibrate_rejects_concurrent_runs(client):
    assert client.post("/api/calibrate?seconds=0.2").status_code == 200
    r = client.post("/api/calibrate?seconds=0.2")
    assert r.status_code == 409
    import time as _t
    for _ in range(100):
        if not client.get("/api/calibrate").json()["running"]:
            break
        _t.sleep(0.05)


def test_calibrate_reports_unreachable(client, fake):
    fake.reachable = False
    client.post("/api/calibrate?seconds=0.01")
    import time as _t
    for _ in range(50):
        c = client.get("/api/calibrate").json()
        if not c["running"]:
            break
        _t.sleep(0.05)
    assert "unreachable" in c.get("error", "").lower() or "down" in c.get("error", "")


def test_sim_switches_immediately_out_of_a_slow_pattern(client):
    import time as _t
    client.post("/api/sim/apply", json={"pattern": "off"})     # 1 s interval
    _t.sleep(0.2)
    client.post("/api/sim/apply", json={"pattern": "ripple"})
    _t.sleep(0.3)
    st = client.get("/api/sim/status").json()
    assert st["pattern"] == "ripple"
    assert st["period"] < 0.5, st                               # not stuck in the 1 s sleep
