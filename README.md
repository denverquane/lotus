# Lotus
Lotus is a 3D-Printed Wall Art installation, for which more details can be found [on Printables](https://www.printables.com/model/588509-lotus-3d-led-wall-art).

This is the code repo for the MicroPython code that the installation runs, which I flashed using [Thonny](https://thonny.org/) to a Raspberry Pi Pico W (for control over WiFi).


## Arrangement/Config
This code assumes the Lotus is wired in 3 segments, corresponding to the left, right, and top 1/3rds of the installation. 
I wired the data lines for these segments to GPIO pins 15, 16, and 17 of the Pico W; see lines ~18-20 of `led.py` for this initialization. 
These assume a certain direction for the data lines depending on the segment; see the `set_led` method in `led.py` if you wish to change this.

The columns are staggered radially (even angles inset, odd angles outset), so the 60 columns x 3 LEDs read as 6 visual rings of 30. `tools/render_layout.py` draws the layout and a couple of patterns from the real `led.py` code:

![Lotus layout](docs/lotus_layout.png)

The webserver exposes a small JSON API (I have my installation hooked up to Home Assistant for automations):

    - `GET /`                : Current pattern and its param values: `{"pattern": "rain", "params": {...}}` (`"connecting"` until WiFi is up)
    - `GET /patterns`        : Every pattern with its param schema (type, default, min/max) and current values. Built for UIs.
    - `POST /<name>`         : Switch to pattern `<name>`. Query-string params are applied first: `POST /rain?drops=8&inward=false&color=0,0,255`
    - `POST /`               : Same, JSON body: `{"pattern": "rain", "params": {"drops": 8}}`
    - `POST /params`         : Tune the running pattern live without restarting it: `POST /params?fade=5` or JSON `{"fade": 5}`
    - `POST /any`            : Switch to a random animated pattern (not off/clock, not the current one)

Every pattern has `interval` (seconds per frame) and `brightness` (0..1). Colors are `[r, g, b]` or `null`/`"random"`.
`GET /` also reports `timing` (`compute_ms`, `period_ms`, `fps`): the Pico sleeps only for what's left of `interval` after computing a frame, so the real period is `max(interval, compute + 2ms)`. Currently a frame costs ~65 ms (fade + 3 strip writes), i.e. ~14 fps ceiling; intervals below ~0.07 all run at that speed.
Numbers outside a param's range are clamped; unknown params or patterns return 400/404 with a JSON error.

## Patterns:
    - "off"
    - "clock"
    - "random"
    - "sweep"
    - "radial"
    - "bounce"
    - "simple_bounce"
    - "flower"
    - "ripple"
    - "pinwheel"
    - "rain"

See `patterns.py` for each one's tunable params, or ask the device: `curl http://<pico-ip>/patterns`.

## Development
The code only runs on the Pico W, but the LED coordinate math and HTTP parsing are unit-tested on desktop Python using [uv](https://docs.astral.sh/uv/):

    uv run pytest

To preview the layout or a pattern without flashing:

    uv run --group render tools/render_layout.py

`stubs/` contains desktop stand-ins for the MicroPython-only modules so `led.py` and `main.py` import cleanly. Don't copy `stubs/` to the device.

To flash from the terminal instead of Thonny, install [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) (`uv tool install mpremote`) and run:

    mpremote cp main.py led.py patterns.py wifi_secrets.py :


## Companion server (UI, presets, proxy)
`server/` is a small FastAPI app meant to run on a home server. It serves a tuning UI with a **live simulator** (the real `patterns.py` running on the server, frames streamed to a canvas), stores named presets (a pattern + params), and proxies everything to the Pico, so Home Assistant can keep talking to the Pico directly for the basics and hit the server for presets.

Workflow: pick a pattern, drag sliders and watch the preview; toggle **Live link** to mirror every change to the wall as you go; **Apply to Lotus** to send once; **Save preset** to keep it.

    uv run --group server uvicorn server.app:app --reload     # http://127.0.0.1:8000

Env: `LOTUS_URL` (default `http://10.0.0.22`), `LOTUS_DATA` (directory for `presets.json`, default `./data`).

    - `GET  /api/status`                : wall's current pattern/params plus `reachable` and the last applied `preset`
    - `GET  /api/patterns`              : param schema (from the wall; falls back to the bundled registry if unreachable)
    - `POST /api/apply`                 : `{"pattern": "rain", "params": {...}}` -> wall
    - `POST /api/tune`                  : `{"fade": 5}` -> tune the running pattern live
    - `GET/PUT/DELETE /api/presets/{name}` : presets; PUT body `{"pattern": ..., "params": {...}}` is validated against the registry
    - `POST /api/presets/{name}/apply`  : send a preset to the wall
    - `POST /api/random`                : apply a random preset (never the last one); with no presets, the wall's `/any`
    - `POST /api/calibrate?seconds=3`   : cycle every pattern on the wall and record its real frame timing (`GET /api/calibrate` for progress, `GET /api/timing` for the table). The preview then runs at wall speed.
    - `GET  /api/sim/layout`            : where each of the 180 pixels sits (strip/index/angle/radius/ring/x/y)
    - `GET  /api/sim/frames`            : server-sent events, one per rendered frame (hex RGB in strip order), capped at 30 fps
    - `POST /api/sim/apply`, `POST /api/sim/tune`, `GET /api/sim/status` : drive the simulator like the wall

Docker:

    docker build -t lotus-server .
    docker run -d -p 8000:8000 -e LOTUS_URL=http://10.0.0.22 -v lotus-data:/data lotus-server
