import machine
import time
import network
import socket
import struct
import wifi_secrets
import uasyncio as asyncio
import ujson
import led
import patterns

try:
    from time import ticks_us, ticks_diff
except ImportError:  # CPython (tests / simulator)
    def ticks_us():
        return int(time.perf_counter() * 1000000)

    def ticks_diff(a, b):
        return a - b

# --- app state --------------------------------------------------------------
connected = False   # WiFi up; while False the render loop shows the green spinner
current = "off"     # name of the selected pattern (see patterns.ORDER)
selection = 0       # bumped by select(); the render loop restarts the pattern when it changes
wake = None         # asyncio.Event created by the render loop; select() sets it so a long sleep ends at once

# --- frame timing -----------------------------------------------------------
MIN_SLEEP = 0.002   # always yield at least this long so the web server gets scheduled


class FrameStats:
    """Exponential moving averages of per-frame compute time and loop period (ms).

    Reported in GET / as "timing" so a client can learn how fast the Pico
    really runs each pattern (the sleep is only a lower bound on the period).
    """

    def __init__(self, alpha=0.1):
        self.alpha = alpha
        self.reset()

    def reset(self):
        self.compute_ms = None
        self.period_ms = None
        self.frames = 0

    def update(self, compute_us, period_us=None):
        c = compute_us / 1000
        self.compute_ms = c if self.compute_ms is None else self.compute_ms + (c - self.compute_ms) * self.alpha
        if period_us is not None:
            pm = period_us / 1000
            self.period_ms = pm if self.period_ms is None else self.period_ms + (pm - self.period_ms) * self.alpha
        self.frames += 1

    def to_json(self):
        return {
            "compute_ms": None if self.compute_ms is None else round(self.compute_ms, 2),
            "period_ms": None if self.period_ms is None else round(self.period_ms, 2),
            "fps": None if not self.period_ms else round(1000 / self.period_ms, 1),
            "frames": self.frames,
        }


stats = FrameStats()


def frame_delay(interval, compute_s):
    """Sleep for the rest of the interval after compute, never less than MIN_SLEEP.
    So the real period is max(interval, compute + MIN_SLEEP)."""
    return max(interval - compute_s, MIN_SLEEP)


async def auto_reconnect_network(ssid, password):
    global connected
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(pm = 0xa11140)  # Disable power-save mode
    wlan.connect(ssid, password)
    await asyncio.sleep(1)

    while True:
        if not wlan.isconnected():
            print('waiting for connection...')
            connected = False
            await asyncio.sleep(1)
        else:
            if not connected:
                connected = True
                try:
                    set_time()
                except Exception as e:
                    print('NTP sync failed:', e)
            print('ip = ' + wlan.ifconfig()[0])
            await asyncio.sleep(60)


# the 25_200 offset corresponds to PST
NTP_DELTA = 2208988800 + 25_200
host = "pool.ntp.org"

def set_time():
    NTP_QUERY = bytearray(48)
    NTP_QUERY[0] = 0x1B
    addr = socket.getaddrinfo(host, 123)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(1)
        res = s.sendto(NTP_QUERY, addr)
        msg = s.recv(48)
    finally:
        s.close()
    val = struct.unpack("!I", msg[40:44])[0]
    t = val - NTP_DELTA
    tm = time.gmtime(t)
    machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))


# --- HTTP parsing -----------------------------------------------------------

def unquote(s):
    """Minimal percent-decoding (%2C -> ',', '+' -> ' '); MicroPython has no urllib."""
    if '%' not in s and '+' not in s:
        return s
    out = ''
    i = 0
    while i < len(s):
        c = s[i]
        if c == '%' and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out += ' ' if c == '+' else c
        i += 1
    return out

def parse_query_string(query_string):
    query = {}
    for pair in query_string.split('&'):
        if not pair:
            continue
        if '=' in pair:
            key, value = pair.split('=', 1)
        else:
            key, value = pair, ''
        query[unquote(key)] = unquote(value)
    return query

def parse_http_request(req_buffer):
    req = {}
    req_buffer_lines = req_buffer.decode('utf8').split('\r\n')
    req['method'], target, req['http_version'] = req_buffer_lines[0].split(' ', 2)
    if (not '?' in target):
        req['path'] = target
    else:
        req['path'], query_string = target.split('?', 1)
        req['query'] = parse_query_string(query_string)

    req['headers'] = {}
    for i in range(1, len(req_buffer_lines) - 1):
        if (req_buffer_lines[i] == ''):
            break
        else:
            name, value = req_buffer_lines[i].split(':', 1)
            req['headers'][name.strip()] = value.strip()

    req['body'] = req_buffer_lines[len(req_buffer_lines) - 1]

    return req


# --- pattern selection ------------------------------------------------------

def current_pattern():
    return current if connected else "connecting"

def select(name, updates=None):
    """Switch to pattern `name` ("any" = a random other pattern), optionally
    applying param updates first. Returns the resolved name, or None if the
    name is unknown. Raises patterns.ParamError on a bad param (and does
    not switch)."""
    global current, selection
    if name == "any":
        name = patterns.random_name(exclude=current)
    if name not in patterns.PATTERNS:
        return None
    if updates:
        patterns.get(name).set(updates)
    current = name
    selection += 1
    if wake is not None:
        wake.set()
    return name

def set_params(updates):
    """Live-update the running pattern's params without restarting it."""
    return patterns.get(current).set(updates)

def status():
    return {"pattern": current_pattern(), "params": patterns.get(current).values,
            "timing": stats.to_json()}


# --- HTTP server ------------------------------------------------------------

async def respond(writer, code, obj):
    body = ujson.dumps(obj)
    head = (b"HTTP/1.1 " + code + b"\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n")
    await writer.awrite(head)
    await writer.awrite(body.encode())
    await writer.drain()
    await writer.wait_closed()

async def read_request(reader):
    """Read one HTTP request. Clients often send headers and body as separate
    TCP segments, so keep reading until Content-Length bytes of body arrived."""
    buf = await reader.read(4096)
    head_end = buf.find(b"\r\n\r\n")
    if head_end < 0:
        return buf
    length = 0
    for line in buf[:head_end].split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError:
                length = 0
    while len(buf) - (head_end + 4) < length:
        more = await reader.read(4096)
        if not more:
            break
        buf += more
    return buf

async def serve_client(reader, writer):
    req_buffer = await read_request(reader)
    try:
        req = parse_http_request(req_buffer)
    except Exception:
        await respond(writer, b"400 Bad Request", {"error": "malformed request"})
        return
    method = req['method']
    path = req['path'].strip('/')
    query = req.get('query', {})
    print(method, req['path'], req['body'])

    if method == 'GET':
        if path == 'patterns':
            await respond(writer, b"200 OK",
                          {"current": current_pattern(), "order": patterns.ORDER,
                           "patterns": patterns.to_json()})
        else:
            await respond(writer, b"200 OK", status())
        return

    if method != 'POST':
        await respond(writer, b"405 Method Not Allowed", {"error": "use GET or POST"})
        return

    body = {}
    if req['body'].strip():
        try:
            body = ujson.loads(req['body'])
        except ValueError:
            await respond(writer, b"400 Bad Request", {"error": "body is not valid JSON"})
            return
        if not isinstance(body, dict):
            await respond(writer, b"400 Bad Request", {"error": "body must be a JSON object"})
            return

    try:
        if path == 'params':
            # POST /params?fade=10  or  {"fade": 10}: tune the running pattern live
            updates = dict(query)
            updates.update(body)
            set_params(updates)
            await respond(writer, b"200 OK", status())
            return

        # POST /<name>?k=v  or  POST / {"pattern": name, "params": {...}}
        name = path or body.get('pattern') or query.get('pattern')
        if not name:
            await respond(writer, b"400 Bad Request", {"error": "no pattern given"})
            return
        updates = {k: v for k, v in query.items() if k != 'pattern'}
        updates.update(body.get('params', {}))
        if select(name, updates) is None:
            await respond(writer, b"404 Not Found",
                          {"error": "unknown pattern '%s'" % name, "patterns": patterns.ORDER})
            return
        await respond(writer, b"200 OK", status())
    except patterns.ParamError as e:
        await respond(writer, b"400 Bad Request", {"error": str(e)})


# --- render loop ------------------------------------------------------------

async def main():
    global wake
    wake = asyncio.Event()
    led.clear()
    led.set_led(29, 2, led.GREEN)
    led.write()

    print('Connecting to Network...')
    asyncio.create_task(auto_reconnect_network(wifi_secrets.SSID, wifi_secrets.PASSWORD))

    print('Setting up webserver...')
    asyncio.create_task(asyncio.start_server(serve_client, "0.0.0.0", 80))

    spinner = 0
    running = -1   # selection number whose state is live; -1 forces init
    state = None
    t_prev = None  # ticks_us at the previous frame start, for the period measurement

    while True:
        if not connected:
            led.brightness = 1.0
            spinner = led.wifi(spinner)
            running = -1
            t_prev = None
            await asyncio.sleep(0.1)
            continue

        p = patterns.get(current)
        t0 = ticks_us()
        if running != selection:
            led.clear()
            led.brightness = p.values["brightness"]
            state = p.init(p.values)
            running = selection
            stats.reset()
            t_prev = None
        led.brightness = p.values["brightness"]
        state = p.step(state, p.values)
        t1 = ticks_us()
        compute_us = ticks_diff(t1, t0)
        stats.update(compute_us, None if t_prev is None else ticks_diff(t0, t_prev))
        t_prev = t0
        await sleep_or_wake(frame_delay(p.values["interval"], compute_us / 1000000))


async def sleep_or_wake(seconds):
    """Sleep, but return early if select() fires so pattern switches feel instant."""
    if wake is None:
        await asyncio.sleep(seconds)
        return
    if wake.is_set():
        wake.clear()
        return
    try:
        await asyncio.wait_for(wake.wait(), seconds)
    except asyncio.TimeoutError:
        return
    wake.clear()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        asyncio.new_event_loop()
