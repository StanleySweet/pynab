"""Lightweight config client — replaces Django ORM in sub-daemons.

Usage:
    from nabcommon.config_client import ConfigClient

    client = ConfigClient()

    # Sync (for scripts, non-async code)
    cfg = client.get("nabweatherd")

    # Async (for daemon event loops)
    cfg = await client.get_async("nabweatherd")
    cfg = await client.get_dict_async("nabweatherd")
    await client.set_async("nabweatherd", {"use_tts": True})
"""

import asyncio
import datetime
import json
import logging
import os
import socket
import time


class ConfigError(Exception):
    pass


class ConfigTimeoutError(ConfigError):
    """Raised when configd is unreachable or times out after retries."""
    pass


# Known JSON fields per table — configd returns these as strings,
# AttrDict parses them back to dicts.
_JSON_FIELDS = {
    "nabweatherd": {"location"},
    "nabairqualityd": {"localisation"},
}

# Known datetime fields — configd returns these as ISO strings,
# AttrDict converts them back to datetime objects.
_DATETIME_FIELDS = {
    "nabweatherd": {
        "next_performance_date",
        "next_performance_weather_vocal_date",
    },
    "nabairqualityd": {"next_performance_date"},
    "nabclockd": set(),
    "nabsurprised": {"next_surprise"},
    "nabmastodond": {
        "last_processed_status_date",
        "spouse_pairing_date",
    },
    "nab8balld": set(),
    "nabttsd": set(),
    "nabd": set(),
    "nabtaichid": {"next_taichi"},
    "nabradio": {"next_radio_date"},
    "nabmqttd": set(),
}


def _parse_iso_datetime(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "." in s:
        before, after_tz = s.split(".", 1)
        frac = ""
        tz = ""
        for i, ch in enumerate(after_tz):
            if ch in ("+", "-"):
                tz = after_tz[i:]
                break
            frac += ch
        frac = frac.ljust(6, "0")[:6]
        s = f"{before}.{frac}{tz}"
    return datetime.datetime.fromisoformat(s)


class AttrDict(dict):
    """Dict with attribute access + automatic type conversion.

    Converts datetime ISO strings → datetime.datetime
    Converts JSON strings → dict
    """

    def __init__(self, table, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._table = table
        self._json_fields = _JSON_FIELDS.get(table, set())
        self._dt_fields = _DATETIME_FIELDS.get(table, set())

    def __getitem__(self, key):
        return self._convert(key, super().__getitem__(key))

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self[name] = value

    def _convert(self, key, value):
        if value is None:
            return None
        if key in self._dt_fields and isinstance(value, str):
            try:
                return _parse_iso_datetime(value)
            except ValueError:
                return value
        if key in self._json_fields and isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value


class ConfigClient:
    def __init__(self, socket_path=None):
        if socket_path is None:
            socket_path = os.environ.get(
                "PYNAB_CONFIG_SOCK", "/tmp/pynab-config.sock"
            )
        self.socket_path = socket_path
        self._id = 0

    def _call(self, op, table, data=None, fields=None, _retries=3):
        self._id += 1
        req = {"id": self._id, "op": op, "table": table}
        if data is not None:
            req["data"] = _prepare_data(data)
        if fields is not None:
            req["fields"] = fields

        last_err = None
        for attempt in range(_retries):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect(self.socket_path)
                s.sendall(json.dumps(req).encode() + b"\n")

                resp = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                    if b"\n" in chunk:
                        break
                s.close()

                parsed = json.loads(resp.decode().strip())
                if not parsed.get("ok"):
                    raise ConfigError(parsed.get("error", "unknown error"))
                return parsed.get("data")
            except (ConnectionRefusedError, FileNotFoundError) as e:
                raise ConfigError(
                    f"configd unreachable ({self.socket_path}): {e}"
                )
            except (socket.timeout, BrokenPipeError) as e:
                last_err = e
                if attempt < _retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise ConfigTimeoutError(
                    f"configd communication error after {_retries} retries: "
                    f"{e}"
                ) from e
            except json.JSONDecodeError as e:
                raise ConfigError(f"configd bad response: {e}")

    def get(self, table, fields=None, required=True):
        try:
            data = self._call("get", table, fields=fields)
        except ConfigError as e:
            if required:
                raise
            logger = logging.getLogger(__name__)
            logger.warning("Config %s unavailable, using defaults: %s", table, e)
            return {}
        return data

    def get_dict(self, table, fields=None):
        """Get config as AttrDict with automatic type conversion."""
        return AttrDict(table, self._call("get", table, fields=fields))

    def set(self, table, data):
        return self._call("set", table, data=data)

    async def get_async(self, table, fields=None):
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self.get, table, fields)
        return AttrDict(table, data)

    async def get_dict_async(self, table, fields=None):
        return await self.get_async(table, fields=fields)

    async def set_async(self, table, data):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.set, table, data)


def _prepare_data(data):
    """Convert Python types to JSON-safe types for SQLite."""
    out = {}
    for k, v in data.items():
        if v is None:
            out[k] = None
        elif isinstance(v, bool):
            out[k] = 1 if v else 0
        elif isinstance(v, (int, float, str)):
            out[k] = v
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, (list, dict)):
            out[k] = json.dumps(v)
        else:
            out[k] = str(v)
    return out
