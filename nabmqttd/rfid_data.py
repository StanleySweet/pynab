"""
Serialize & unserialize RFID application data
"""
import json

from nabcommon.config_client import ConfigClient


async def read_data_ui(uid):
    client = ConfigClient()
    config = client.get("nabmqttd")
    try:
        uid_data_base = json.loads(config.get("json_data_base", "{}"))
    except Exception:
        uid_data_base = []

    if uid in uid_data_base:
        event_name = uid_data_base[uid]
    else:
        event_name = "NO_EVENT_NAME"

    return event_name


async def write_data_ui(uid, event_name):
    client = ConfigClient()
    config = client.get("nabmqttd")
    try:
        uid_data_base = json.loads(config.get("json_data_base", "{}"))
    except Exception:
        uid_data_base = {}

    uid_data_base[uid] = event_name
    client.set("nabmqttd", {"json_data_base": json.dumps(uid_data_base)})


def read_data_ui_for_views(uid):
    from .models import Config

    config = Config.load()

    try:
        uid_data_base = json.loads(config.json_data_base)
    except Exception:
        uid_data_base = []

    if uid in uid_data_base:
        event_name = uid_data_base[uid]
    else:
        event_name = ""

    return event_name


def write_data_ui_for_views(uid, event_name):
    from .models import Config

    config = Config.load()

    try:
        uid_data_base = json.loads(config.json_data_base)
    except Exception:
        uid_data_base = {}

    uid_data_base[uid] = event_name
    config.json_data_base = json.dumps(uid_data_base)
    config.save()
