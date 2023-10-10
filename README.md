# Lotus
Lotus is a 3D-Printed Wall Art installation, for which more details can be found [on Printables](https://www.printables.com/model/588509-lotus-3d-led-wall-art).

This is the code repo for the MicroPython code that the installation runs, which I flashed using [Thonny](https://thonny.org/) to a Raspberry Pi Pico W (for control over WiFi).


## Arrangement/Config
This code assumes the Lotus is wired in 3 segments, corresponding to the left, right, and top 1/3rds of the installation. 
I wired the data lines for these segments to GPIO pins 15, 16, and 17 of the Pico W; see lines ~18-20 of `led.py` for this initialization. 
These assume a certain direction for the data lines depending on the segment; see the `set_led` method in `leds.py` if you wish to change this.

The webserver accepts a few specific HTTP requests for control and reporting (I have my installation hooked up to Home Assistant for automations):

    - `GET /` : Report the current pattern via json: `{"pattern": "pattern_name"}`
    - `POST /pattern_name`: Sets the current pattern to `pattern_name`
    - `POST /`: Same as above, but POST body is json in the form: `{"pattern": "pattern_name"}`

## Patterns:
    - "off"
    - "clock"
    - "random"
    - "sweep"
    - "radial"
    - "bounce"
    - "simple_bounce"
    - "flower"