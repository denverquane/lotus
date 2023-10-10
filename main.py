import machine, neopixel
import time
import network
import socket
import struct
import secrets
import uasyncio as asyncio
import led
import ujson
import random

WIFI = -1
OFF = 0
CLOCK = 1
RANDOM = 2
SWEEP = 3
RADIAL = 4
BOUNCE = 5
SIMPLE_BOUNCE = 6
FLOWER = 7
MAX_MODE = FLOWER
MODE = WIFI

ANY_STR = "any"

PATTERN_STRS = [
    "off",
    "clock",
    "random",
    "sweep",
    "radial",
    "bounce",
    "simple_bounce",
    "flower",
    ]


async def auto_reconnect_network(ssid, password):
    global MODE
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(pm = 0xa11140)  # Disable power-save mode
    wlan.connect(ssid, password)
    await asyncio.sleep(1)
    
    while True:
        if not wlan.isconnected():
            print('waiting for connection...')
            MODE = WIFI
            await asyncio.sleep(1)
        else:
            if MODE == WIFI:
                MODE = OFF
            status = wlan.ifconfig()
            print('ip = ' + status[0])
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

async def respond_and_close(writer, code, data = ""):
    response = b"HTTP/1.1 " + code + b"\r\nContent-Type: application/json\r\n\r\n"
    print('response:', response)
    await writer.awrite(response)

    if len(data) > 0:
        response = data
        print('response:', response)
        await writer.awrite(response)
    
    await writer.drain()
    await writer.wait_closed()
    
def match_pattern(pattern):
    global MODE
    # prioritize the off command
    if pattern == PATTERN_STRS[OFF]:
        MODE = OFF
        return TRUE
    elif pattern == ANY_STR:
        r = random.randint(RANDOM, MAX_MODE)
        while r == MODE:
            r = random.randint(RANDOM, MAX_MODE)
        MODE = r
        return True
    else:
        for i in range(1,len(PATTERN_STRS)):
            if pattern == PATTERN_STRS[i]:
                MODE = i
                return True
    
    return False
    
        
def serve_client(lock):
    async def f(reader, writer):
        # Read the request headers
        headers = {}
        req_buffer = await reader.read(4096)
        req = parse_http_request(req_buffer)
        print(req['headers'])
        # print(req)
        print(req['body'])
    
        if 'method' not in req:
            return
    
        if req['method'] == 'GET':
            await respond_and_close(writer, b"200 OK", b'{"pattern": "' + PATTERN_STRS[MODE] + b'"}')
            return
        
        if req['method'] != 'POST':
            await respond_and_close(writer, b"400 Bad Request")
            return
    
        if 'path' in req:
            async with lock:
                if match_pattern(req['path'].replace('/','')):
                    await respond_and_close(writer, b"200 OK")
                    await asyncio.sleep(0.1)
                    led.clear()
                    led.write()
                    return

        # Parse the JSON data (assuming it's JSON)
        if 'Content-Type' in req['headers'] and req['headers']['Content-Type'] == 'application/json':
            try:
                post_data = ujson.loads(req['body'])
                print("Received POST data:", post_data)
                
                if 'pattern' in post_data:
                    pattern = post_data['pattern']
                    async with lock:
                        if match_pattern(pattern):
                            await respond_and_close(writer, b"200 OK")
                            await asyncio.sleep(0.1)
                            led.clear()
                            led.write()
                            return
                        else:
                            await respond_and_close(writer, b"204 No Content")
                            return
                else:
                    await respond_and_close(writer, b"400 Bad Request")
            except ValueError:
                print("Error parsing JSON data")
                await respond_and_close(writer, b"406 Not Acceptable")
        else:
            await respond_and_close(writer, b"400 Bad Request")
    
    return f

async def main():
    led.clear()
    led.set_led(29, 2, led.GREEN)
    led.write()
    
    print('Connecting to Network...')
    asyncio.create_task(auto_reconnect_network(secrets.SSID, secrets.PASSWORD))

    print('Setting up webserver...')
    lock = asyncio.Lock()
    asyncio.create_task(asyncio.start_server(serve_client(lock), "0.0.0.0", 80))
    
    c = [-2,2]

    prevMode = OFF
    
    while True:
        if MODE == OFF:
            if prevMode != MODE:
                led.clear()
                led.write()
            print('.')
            await asyncio.sleep(1)
            prevMode = OFF
        elif MODE == WIFI:
            if prevMode != MODE:
                angle = 0
            angle = led.wifi(angle)
            prevMode = WIFI
            await asyncio.sleep(0.1)
        elif MODE == CLOCK:
            led.led_time(time.localtime())
            await asyncio.sleep(1)
            prevMode = CLOCK
        elif MODE == RANDOM:
            led.random_led(1)
            await asyncio.sleep(0.01)
            prevMode = RANDOM
        elif MODE == SWEEP:
            if prevMode != MODE:
                color = led.random_color()
                angle = 0
            angle, color = led.sweep_leds(angle, color, 3)
            await asyncio.sleep(0.01)
            prevMode = SWEEP
        elif MODE == RADIAL:
            if prevMode != MODE:
                color = led.random_color()
                radius = 0
            color, radius = led.radial_leds(color, radius, 40)
            await asyncio.sleep(0.05)
            prevMode = RADIAL
        elif MODE == BOUNCE:
            if prevMode != MODE:
                colors = [led.random_color(),led.random_color(),led.random_color(),led.random_color(),led.random_color(),led.random_color()]
                angles = [0,0,0,1,1,1]
                dirs = [random.choice(c),random.choice(c),random.choice(c),random.choice(c),random.choice(c),random.choice(c)]
            angles, dirs = led.bounce_leds(colors, angles, dirs, 10, 15)
            await asyncio.sleep(0.01)
            prevMode = BOUNCE
        elif MODE == SIMPLE_BOUNCE:
            if prevMode != MODE:
                colors = [led.random_color(),led.random_color(),led.random_color()]
                angles = [0,0,0]
                dirs = [random.choice([-1,1]),random.choice([-1,1]),random.choice([-1,1])]
            angles, dirs = led.bounce_leds(colors, angles, dirs, 5, 5)
            await asyncio.sleep(0.01)
            prevMode = SIMPLE_BOUNCE
        elif MODE == FLOWER:
            if prevMode != MODE:
                idx = 59
                color = led.random_color()
                i_color = led.random_color()
            idx = led.flower(idx, color, i_color)
            await asyncio.sleep(0.2)
            prevMode = FLOWER


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()