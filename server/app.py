"""Lotus companion server: tuning UI, preset storage, and a proxy to the Pico.

    uv run --group server uvicorn server.app:app --reload

Env:
    LOTUS_URL   base URL of the Pico            (default http://10.0.0.22)
    LOTUS_DATA  directory for presets.json      (default ./data)
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "stubs"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402

import patterns  # noqa: E402  (firmware registry, via stubs)
from server.lotus import Lotus, Unreachable  # noqa: E402
from server.presets import PresetError, PresetStore  # noqa: E402
from server.sim import Simulator  # noqa: E402
from server.timing import TimingStore  # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app(lotus=None, store=None, timing=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.lotus = lotus or Lotus(os.environ.get("LOTUS_URL", "http://10.0.0.22"))
        data_dir = os.environ.get("LOTUS_DATA", os.path.join(ROOT, "data"))
        app.state.store = store or PresetStore(os.path.join(data_dir, "presets.json"))
        app.state.timing = timing or TimingStore(os.path.join(data_dir, "timing.json"))
        app.state.last_preset = None
        app.state.calibration = {"running": False, "done": 0, "total": 0, "pattern": None, "results": {}}
        app.state.sim = Simulator(timing=app.state.timing)
        app.state.sim.start()
        yield
        await app.state.sim.stop()
        await app.state.lotus.close()

    app = FastAPI(title="Lotus", lifespan=lifespan)

    @app.exception_handler(Unreachable)
    async def unreachable(request, exc):
        return JSONResponse({"error": "lotus unreachable", "detail": str(exc)}, status_code=502)

    @app.exception_handler(PresetError)
    async def preset_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(patterns.ParamError)
    async def param_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    def passthrough(status, body):
        return JSONResponse(body, status_code=status)

    async def json_body(request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        return body if isinstance(body, dict) else {}

    # --- UI ---------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(os.path.join(STATIC, "index.html"))

    @app.get("/health")
    async def health():
        return {"ok": True}

    # --- device proxy -----------------------------------------------------

    @app.get("/api/status")
    async def status(request: Request):
        try:
            code, body = await request.app.state.lotus.status()
        except Unreachable as e:
            return {"reachable": False, "detail": str(e)}
        body["reachable"] = code == 200
        body["preset"] = request.app.state.last_preset
        if code == 200:
            request.app.state.timing.learn(body.get("pattern"), body.get("timing"))
        return body

    @app.get("/api/patterns")
    async def get_patterns(request: Request):
        """Schema from the device; falls back to the bundled firmware registry."""
        try:
            code, body = await request.app.state.lotus.patterns()
            if code == 200:
                body["source"] = "device"
                return body
        except Unreachable:
            pass
        return {"current": None, "order": patterns.ORDER, "patterns": patterns.to_json(),
                "source": "local"}

    @app.post("/api/apply")
    async def apply(request: Request):
        body = await json_body(request)
        pattern = body.get("pattern")
        if not pattern:
            return JSONResponse({"error": "no pattern given"}, status_code=400)
        request.app.state.last_preset = None
        return passthrough(*await request.app.state.lotus.apply(pattern, body.get("params") or {}))

    @app.post("/api/tune")
    async def tune(request: Request):
        return passthrough(*await request.app.state.lotus.tune(await json_body(request)))

    @app.post("/api/random")
    async def random_preset(request: Request):
        """Apply a random saved preset; with no presets, fall back to the device's /any."""
        st = request.app.state
        preset = st.store.random(exclude=st.last_preset)
        if preset is None:
            st.last_preset = None
            return passthrough(*await st.lotus.any())
        code, body = await st.lotus.apply(preset["pattern"], preset["params"])
        if code == 200:
            st.last_preset = preset["name"]
            body["preset"] = preset["name"]
        return passthrough(code, body)

    # --- presets ----------------------------------------------------------

    @app.get("/api/presets")
    async def list_presets(request: Request):
        return {"presets": request.app.state.store.list()}

    @app.get("/api/presets/{name}")
    async def get_preset(name: str, request: Request):
        preset = request.app.state.store.get(name)
        if preset is None:
            return JSONResponse({"error": "no preset '%s'" % name}, status_code=404)
        return preset

    @app.put("/api/presets/{name}")
    async def put_preset(name: str, request: Request):
        body = await json_body(request)
        preset = request.app.state.store.put(name, body.get("pattern"), body.get("params") or {})
        return preset

    @app.delete("/api/presets/{name}")
    async def delete_preset(name: str, request: Request):
        if not request.app.state.store.delete(name):
            return JSONResponse({"error": "no preset '%s'" % name}, status_code=404)
        if request.app.state.last_preset == name:
            request.app.state.last_preset = None
        return {"deleted": name}

    @app.post("/api/presets/{name}/apply")
    async def apply_preset(name: str, request: Request):
        st = request.app.state
        preset = st.store.get(name)
        if preset is None:
            return JSONResponse({"error": "no preset '%s'" % name}, status_code=404)
        code, body = await st.lotus.apply(preset["pattern"], preset["params"])
        if code == 200:
            st.last_preset = name
            body["preset"] = name
        return passthrough(code, body)

    # --- timing / calibration -----------------------------------------------

    @app.get("/api/timing")
    async def get_timing(request: Request):
        return {"timing": request.app.state.timing.all()}

    async def run_calibration(st, seconds):
        names = [n for n in patterns.ORDER if n != "off"]
        st.calibration = {"running": True, "done": 0, "total": len(names), "pattern": None, "results": {}}
        prev = None
        try:
            code, before = await st.lotus.status()
            if code == 200 and before.get("pattern") in patterns.PATTERNS:
                prev = before["pattern"]
            for name in names:
                st.calibration["pattern"] = name
                code, _ = await st.lotus.apply(name)   # the wall keeps its own params per pattern
                if code == 200:
                    await asyncio.sleep(seconds)
                    code, body = await st.lotus.status()
                    if code == 200 and body.get("pattern") == name and body.get("timing"):
                        if st.timing.learn(name, body["timing"], force=True):
                            st.calibration["results"][name] = body["timing"]
                st.calibration["done"] += 1
            if prev:
                await st.lotus.apply(prev)
        except Unreachable as e:
            st.calibration["error"] = str(e)
        finally:
            st.calibration["running"] = False
            st.calibration["pattern"] = None

    @app.post("/api/calibrate")
    async def calibrate(request: Request, seconds: float = 3.0):
        """Cycle every pattern on the wall for `seconds` each and record its real frame timing."""
        st = request.app.state
        if st.calibration["running"]:
            return JSONResponse({"error": "calibration already running", **st.calibration}, status_code=409)
        seconds = min(max(seconds, 0.01), 30.0)
        st.calibration_task = asyncio.create_task(run_calibration(st, seconds))
        await asyncio.sleep(0)  # let it set the running flag before we report
        return st.calibration

    @app.get("/api/calibrate")
    async def calibration_status(request: Request):
        return request.app.state.calibration

    # --- simulator (real firmware code, desktop stubs) ---------------------

    @app.get("/api/sim/layout")
    async def sim_layout(request: Request):
        return {"cells": request.app.state.sim.layout, "rings": 6, "cells_per_ring": 30}

    @app.get("/api/sim/status")
    async def sim_status(request: Request):
        return request.app.state.sim.status()

    @app.post("/api/sim/apply")
    async def sim_apply(request: Request):
        body = await json_body(request)
        pattern = body.get("pattern")
        if not pattern:
            return JSONResponse({"error": "no pattern given"}, status_code=400)
        sim = request.app.state.sim
        if sim.select(pattern, body.get("params") or {}) is None:
            return JSONResponse({"error": "unknown pattern '%s'" % pattern, "patterns": patterns.ORDER},
                                status_code=404)
        return sim.status()

    @app.post("/api/sim/tune")
    async def sim_tune(request: Request):
        sim = request.app.state.sim
        sim.tune(await json_body(request))
        return sim.status()

    @app.get("/api/sim/frames")
    async def sim_frames(request: Request):
        return StreamingResponse(request.app.state.sim.frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


app = create_app()
