"""Desktop stand-in for MicroPython's `machine` module. Only for tests; never flash this."""


class Pin:
    def __init__(self, id, *args, **kwargs):
        self.id = id

    def __repr__(self):
        return f"Pin({self.id})"


class RTC:
    def __init__(self):
        self._datetime = None

    def datetime(self, value=None):
        if value is not None:
            self._datetime = value
        return self._datetime
