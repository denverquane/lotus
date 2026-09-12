"""Desktop stand-in for MicroPython's `network` module. Only for tests; never flash this."""

STA_IF = 0
AP_IF = 1


class WLAN:
    def __init__(self, interface):
        self.interface = interface
        self._active = False
        self._connected = False

    def active(self, value=None):
        if value is not None:
            self._active = value
        return self._active

    def config(self, **kwargs):
        pass

    def connect(self, ssid, password):
        self._connected = True

    def isconnected(self):
        return self._connected

    def ifconfig(self):
        return ("127.0.0.1", "255.255.255.0", "127.0.0.1", "127.0.0.1")
