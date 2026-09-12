import machine, neopixel
import random
import time
import uasyncio as asyncio

RED = (255,0,0)
GREEN = (0,255,0)
BLUE = (0,0,255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)

TOP = 1
RIGHT = 2
LEFT = 3

numPixels = 60
left = neopixel.NeoPixel(machine.Pin(15), numPixels)
right = neopixel.NeoPixel(machine.Pin(16), numPixels)
top = neopixel.NeoPixel(machine.Pin(17), numPixels)

def clear():
    for i in range(numPixels):
        left[i] = (0,0,0)
        right[i] = (0,0,0)
        top[i] = (0,0,0)
        
def fade_color(color, step):
    r, g, b = color
    return (r-step if r > step else 0, g-step if g > step else 0, b-step if b > step else 0)

def fade_all(step):
    for i in range (0, numPixels):
        left[i] = fade_color(left[i], step)
        right[i] = fade_color(right[i], step)
        top[i] = fade_color(top[i], step)

def write():
    top.write()
    left.write()
    right.write()
    
def get_region(angle):
    if (angle > 49 and angle < 60) or (angle > -1 and angle < 10):
        return TOP
    elif angle > 9 and angle < 30:
        return RIGHT
    elif angle > 29 and angle < 50:
        return LEFT
    
def to_value(angle, radius):
    angle = (angle + 10) % 60
    value = (angle * 3) % 60
    inner = (value + radius) % 6
    if inner < 3:
        return value + (2-radius)
    else:
        return value + radius
    
# Global brightness scalar (0..1) applied to every color passed to set_led.
# Set by the render loop from the active pattern's "brightness" param.
brightness = 1.0

def set_led(angle, radius, color):
    if brightness < 1.0:
        color = (int(color[0] * brightness), int(color[1] * brightness), int(color[2] * brightness))
    if angle < 0:
        angle = 60 + angle
    angle = angle % 60
    region = get_region(angle)
    value = to_value(angle, radius)
    if region == LEFT:
        left[value] = color
    elif region == RIGHT:
        right[59-value] = color
    elif region == TOP:
        top[59-value] = color
        
# --- Visual coordinates -------------------------------------------------
# The 60 columns are staggered: even angles sit one ring further in than odd
# angles. So (angle, radius) is the *wiring* coordinate, and what the eye sees
# is 6 concentric rings of 30 cells. These helpers work in that visual space.
NUM_RINGS = 6
CELLS_PER_RING = 30

def ring_of(angle, radius):
    """Visual ring (0 = innermost) for a wiring coordinate."""
    return 2 * radius + (angle % 2)

def set_cell(ring, i, color):
    """Light cell i (0-29, clockwise from 12 o'clock) on visual ring (0-5)."""
    set_led(2 * i + (ring % 2), ring // 2, color)

def hsv_to_rgb(h, s, v):
    """h, s, v in 0..1 (h wraps) -> (r, g, b) ints in 0..255."""
    h = h % 1.0
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    i %= 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return (int(r * 255), int(g * 255), int(b * 255))

def random_color():
    return (random.randint(0,255), random.randint(0,255), random.randint(0,255))
    
def random_led(fade):
    fade_all(fade)
    
    rand_angle = random.randint(0,59)
    rand_val = random.randint(0,2)
    
    set_led(rand_angle, rand_val, random_color())
    
    write()
    
def sweep_leds(angle, color, fade):
    fade_all(fade)
    set_led(angle, 0, color)
    set_led(angle, 1, color)
    set_led(angle, 2, color)
    write()
    angle += 1
    if angle > 59:
        return 0, random_color()
    else:
        return angle, color
            
def radial_leds(color, radius, fade):
    fade_all(fade)
    for angle in range (0, 60, 2):
        set_led(angle, radius, color)
    write()
    time.sleep(0.01)
    fade_all(fade)
    for angle in range(1, 60, 2):
        set_led(angle, radius, color)
    write()
    radius += 1
    if radius > 2:
        return random_color(), 0
    else:
        return color, radius
        
def bounce_leds(colors, angles, dirs, prob, fade): 
    fade_all(fade)
    set_led(angles[0], 0, colors[0])
    set_led(angles[1], 1, colors[1])
    set_led(angles[2], 2, colors[2])
    if len(angles) > 3:
        set_led(angles[3], 0, colors[3])
        set_led(angles[4], 1, colors[4])
        set_led(angles[5], 2, colors[5])
    write()
    for i in range(0,len(angles)):
        roll = random.randint(0,100)
        if roll < prob:
            dirs[i] *= -1
        newVal = angles[i] + dirs[i]
        if newVal > 59:
            newVal = 0 if newVal == 60 else 1
        elif newVal < 0:
            newVal = 59 if newVal == -1 else 58
        angles[i] = newVal
    return angles, dirs
        
        
def wifi(angle):
    fade_all(5)
    set_led(angle, 0, (0,20,0))
    write()
    angle += 2
    if angle > 59:
        return 0
    return angle
        
def hour_to_angle(hr):
    hr = hr % 12
    # this isn't right
    return hr * 5
        
def led_time(t):
    hr_angle = hour_to_angle(t[3])
    min_angle = t[4]
    sec_angle = t[5]
    clear()
    
    set_led(hr_angle, 0, BLUE)
    set_led(hr_angle-1, 0, BLUE)
    set_led(hr_angle+1, 0, BLUE)
    
    
    set_led(min_angle, 0, YELLOW)
    set_led(min_angle, 1, YELLOW)
    
    set_led(min_angle-1, 0, YELLOW)
    set_led(min_angle+1, 0, YELLOW)
    
    if min_angle % 2 == 1:
        set_led(min_angle-1, 1, YELLOW)
        set_led(min_angle+1, 1, YELLOW)
    
    
    set_led(sec_angle, 0, RED)
    set_led(sec_angle, 1, RED)
    set_led(sec_angle, 2, RED)
    
    set_led(sec_angle+1, 0, RED)
    set_led(sec_angle+1, 1, RED)
    
    set_led(sec_angle-1, 0, RED)
    set_led(sec_angle-1, 1, RED)
    
    if sec_angle % 2 == 1:
        set_led(sec_angle+1, 2, RED)
        set_led(sec_angle-1, 2, RED)
    
    write()
    
def petal(idx, color, i_color):
    set_led(idx, 2, color)
    
    set_led(idx - 1, 2, color)
    set_led(idx + 1, 2, color)
    
    set_led(idx - 2, 1, color)
    set_led(idx + 2, 1, color)
    
    set_led(idx - 3, 1, color)
    set_led(idx + 3, 1, color)

    set_led(idx - 2, 0, color)
    set_led(idx + 2, 0, color)
    
    set_led(idx - 1, 0, color)
    set_led(idx + 1, 0, color)
    
    set_led(idx, 1, i_color)
    set_led(idx - 1, 1, i_color)
    set_led(idx + 1, 1, i_color)
    set_led(idx, 0, i_color)
    
    
def flower(idx, color, i_color):
    clear()
    
    petal(idx, color, i_color)
    petal(idx+6, color, i_color)
    petal(idx+12, color, i_color)
    petal(idx+18, color, i_color)
    petal(idx+24, color, i_color)
    petal(idx+30, color, i_color)
    petal(idx+36, color, i_color)
    petal(idx+42, color, i_color)
    petal(idx+48, color, i_color)
    petal(idx+54, color, i_color)
    
    write()
    
    return (idx + 2) % 60


def ripple(phase, spread=0.5, brightness=1.0, speed=0.01):
    """Rainbow flowing outward ring by ring.

    Each visual ring is one solid hue; hue advances with phase so colors
    travel from the center outward. `spread` is how much of the hue wheel
    is visible across the 6 rings at once. Returns the next phase.
    """
    for ring in range(NUM_RINGS):
        color = hsv_to_rgb(phase - ring * spread / NUM_RINGS, 1.0, brightness)
        for i in range(CELLS_PER_RING):
            set_cell(ring, i, color)
    write()
    return (phase + speed) % 1.0


def pinwheel(pos, hue, arms=3, twist=1, fade=40, brightness=1.0, speed=0.002):
    """Spinning spiral arms.

    Each arm is one cell per ring, shifted `twist` cells further around on
    each ring outward, so it curves. Arms are evenly spaced and each has its
    own hue; the whole thing slowly cycles through the hue wheel. fade_all
    leaves a short trail behind each arm. Returns (next pos, next hue).
    """
    fade_all(fade)
    for arm in range(arms):
        color = hsv_to_rgb(hue + arm / arms, 1.0, brightness)
        base = pos + (arm * CELLS_PER_RING) // arms
        for ring in range(NUM_RINGS):
            set_cell(ring, (base + ring * twist) % CELLS_PER_RING, color)
    write()
    return (pos + 1) % CELLS_PER_RING, (hue + speed) % 1.0
