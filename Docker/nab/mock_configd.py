#!/opt/venv/bin/python
"""Minimal configd mock for Docker — responds to get/set over a Unix socket."""
import asyncio, json, os

SOCKET_PATH = os.environ.get("PYNAB_CONFIG_SOCK", "/tmp/pynab-config.sock")

DEFAULTS = {
    "nabd": {
        "locale": "fr_FR",
        "bottom_led_color": "#00FFFF",
    },
    "nabclockd": {
        "play_wakeup_sleep_sounds": False,
        "use_tts": False,
        "chime_hour": False,
        "wakeup_hour": 7,
        "wakeup_min": 0,
        "sleep_hour": 22,
        "sleep_min": 0,
        "settings_per_day": False,
        "sleep_wakeup_override": None,
    },
    "nabweatherd": {
        "use_tts": True,
        "location": None,
        "weather_animation_type": 0,
        "weather_frequency": 0,
        "locale": "fr_FR",
    },
    "nabairqualityd": {
        "localisation": None,
    },
    "nabmastodond": {
        "client_id": None,
        "client_secret": None,
        "access_token": None,
        "instance": None,
        "username": None,
    },
    "nabsurprised": {},
    "nabtaichid": {},
    "nab8balld": {},
    "nabmqttd": {
        "host": "localhost",
        "port": 1883,
        "username": None,
        "password": None,
        "topic_prefix": "nabaztag",
        "use_tls": False,
        "tls_ca_cert": None,
    },
}

store = {k: dict(v) for k, v in DEFAULTS.items()}


async def handle_client(reader, writer):
    try:
        data = await reader.readline()
        if not data:
            return
        req = json.loads(data.decode().strip())
        op = req.get("op")
        table = req.get("table", "")
        if op == "get":
            resp = {"ok": True, "data": store.get(table, {})}
        elif op == "set":
            if table not in store:
                store[table] = {}
            store[table].update(req.get("data", {}))
            resp = {"ok": True}
        else:
            resp = {"ok": False, "error": f"unknown op: {op}"}
        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
    except Exception as e:
        writer.write((json.dumps({"ok": False, "error": str(e)}) + "\n").encode())
        await writer.drain()
    finally:
        writer.close()


async def main():
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
    server = await asyncio.start_unix_server(handle_client, path=SOCKET_PATH)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
