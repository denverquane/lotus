"""HTTP client for the Pico's API.

The Pico's server is single-buffer and connection-per-request, so every call
is serialized through one lock, uses short timeouts, and sends
`Connection: close`. Errors reaching the device are raised as Unreachable;
4xx/5xx from the device are returned as (status, body) for the caller to
pass through.
"""
import asyncio

import httpx


class Unreachable(Exception):
    pass


def encode(params):
    """Params as query-string values, in the forms the Pico's Param.coerce accepts.

    Everything goes in the URL rather than a JSON body: the Pico reads one
    buffer per request, so a body that lands in a second TCP segment can be
    truncated. A bodiless request sidesteps that entirely.
    """
    out = {}
    for k, v in (params or {}).items():
        if v is None:
            out[k] = "random"
        elif isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (list, tuple)):
            out[k] = ",".join(str(int(x)) for x in v)
        else:
            out[k] = str(v)
    return out


class Lotus:
    def __init__(self, base_url, timeout=3.0):
        self.base_url = base_url.rstrip("/")
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Connection": "close"},
        )

    async def close(self):
        await self._client.aclose()

    async def _request(self, method, path, params=None):
        # Build the query by hand: the Pico's parser doesn't percent-decode, and
        # httpx would encode the commas in "255,120,0". Values here are digits,
        # dots, minus signs, commas and ASCII words, so nothing needs escaping.
        if params:
            path = path + "?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
        async with self._lock:
            try:
                r = await self._client.request(method, path)
            except httpx.HTTPError as e:
                raise Unreachable("%s: %s" % (self.base_url, e)) from e
        try:
            body = r.json()
        except ValueError:
            body = {"error": "non-JSON response from device", "raw": r.text[:200]}
        return r.status_code, body

    async def status(self):
        return await self._request("GET", "/")

    async def patterns(self):
        return await self._request("GET", "/patterns")

    async def apply(self, pattern, params=None):
        return await self._request("POST", "/" + pattern, params=encode(params))

    async def tune(self, params):
        return await self._request("POST", "/params", params=encode(params))

    async def any(self):
        return await self._request("POST", "/any")
