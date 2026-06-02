import asyncio
import datetime
import json
import logging
import socket
import sys
import uuid

import paho.mqtt.client as mqtt

from nabcommon.nabservice import NabService

from . import rfid_data


def _get_mac():
    try:
        mac = uuid.getnode()
        if (mac >> 40) % 2:
            return None
        return "nabaztag_" + hex(mac)[2:].zfill(12)
    except Exception:
        return None


def _build_device_info(device_id):
    return {
        "identifiers": [device_id],
        "name": "Nabaztag",
        "model": "Nabaztag",
        "manufacturer": "Nabaztag",
        "sw_version": "pynab",
    }


_CHOREOGRAPHIES = {
    "solid_red": {
        "tempo": 1,
        "colors": [
            {"left": "ff0000", "center": "ff0000", "right": "ff0000"},
            {"left": "ff0000", "center": "ff0000", "right": "ff0000"},
        ],
    },
    "solid_green": {
        "tempo": 1,
        "colors": [
            {"left": "00ff00", "center": "00ff00", "right": "00ff00"},
            {"left": "00ff00", "center": "00ff00", "right": "00ff00"},
        ],
    },
    "solid_blue": {
        "tempo": 1,
        "colors": [
            {"left": "0000ff", "center": "0000ff", "right": "0000ff"},
            {"left": "0000ff", "center": "0000ff", "right": "0000ff"},
        ],
    },
    "solid_white": {
        "tempo": 1,
        "colors": [
            {"left": "ffffff", "center": "ffffff", "right": "ffffff"},
            {"left": "ffffff", "center": "ffffff", "right": "ffffff"},
        ],
    },
    "rainbow": {
        "tempo": 30,
        "colors": [
            {"left": "ff0000", "center": "00ff00", "right": "0000ff"},
            {"left": "00ff00", "center": "0000ff", "right": "ff0000"},
            {"left": "0000ff", "center": "ff0000", "right": "00ff00"},
        ],
    },
    "breathing_blue": {
        "tempo": 15,
        "colors": [
            {"left": "000000", "center": "000000", "right": "000000"},
            {"left": "0000ff", "center": "0000ff", "right": "0000ff"},
            {"left": "000000", "center": "000000", "right": "000000"},
            {"left": "0000ff", "center": "0000ff", "right": "0000ff"},
        ],
    },
    "off": {
        "persist": True,
        "tempo": 1,
        "colors": [
            {"left": "000000", "center": "000000", "right": "000000"},
        ],
    },
}


def _choreography_to_base64(choreo):
    mtl = _choreography_to_mtl(choreo)
    import base64

    return base64.b64encode(mtl).decode("ascii")


def _choreography_to_mtl(choreo):
    tempo = choreo.get("tempo", 10)
    colors = choreo.get("colors", [])
    parts = []
    parts.extend([0, 1, tempo])
    if choreo.get("persist", False):
        r = int(colors[0].get("left", "000000")[0:2], 16) if colors else 0
        g = int(colors[0].get("left", "000000")[2:4], 16) if colors else 0
        b = int(colors[0].get("left", "000000")[4:6], 16) if colors else 0
        frame_duration = 255
        parts = [0, 1, frame_duration]
        for _ in range(400):
            parts.extend([0, 9, r, g, b, 255, 0])
        parts.extend([0, 0])
    else:
        for c in colors:
            r = int(c.get("left", "000000")[0:2], 16)
            g = int(c.get("left", "000000")[2:4], 16)
            b = int(c.get("left", "000000")[4:6], 16)
            parts.extend([0, 9, r, g, b])
            parts.extend([tempo, 0])
        parts.extend([0, 0])
    return bytes(parts)


def _rgb_to_choreography(r, g, b, brightness=255):
    br = brightness / 255.0
    r2 = int(min(r * br, 255))
    g2 = int(min(g * br, 255))
    b2 = int(min(b * br, 255))
    hex_color = f"{r2:02x}{g2:02x}{b2:02x}"
    return {
        "persist": True,
        "tempo": 1,
        "colors": [
            {"left": hex_color, "center": hex_color, "right": hex_color},
        ],
    }


class NabMqttd(NabService):
    def __init__(self):
        super().__init__()
        self.mqtt_client = None
        self.mqtt_connected = False
        self.config = None
        self.loop = None
        self._effective_device_id = ""

    async def reload_config(self):
        logging.info("reloading configuration")
        from . import models

        self.config = await models.Config.load_async()
        await self._disconnect_mqtt()
        self._connect_mqtt()

    def start_service_loop(self, loop):
        self.loop = loop
        from . import models

        self.config = models.Config.load()
        loop.call_soon(self._connect_mqtt)
        return None

    def _get_device_id(self):
        if self.config is None:
            return _get_mac() or "nabaztag_" + uuid.uuid4().hex[:8]
        did = self.config.device_id
        if did:
            return did
        return _get_mac() or "nabaztag_" + uuid.uuid4().hex[:8]

    def _connect_mqtt(self):
        if self.config is None:
            return
        host = self.config.broker_host
        port = self.config.broker_port
        username = self.config.broker_username or None
        password = self.config.broker_password or None
        tls = self.config.broker_tls
        device_id = self._get_device_id()
        self._effective_device_id = device_id
        self._discovery_prefix = self.config.discovery_prefix or "homeassistant"
        self._topic_prefix = self.config.topic_prefix or "nabaztag"

        client_id = f"{device_id}_mqtt"
        self.mqtt_client = mqtt.Client(client_id=client_id)
        if username:
            self.mqtt_client.username_pw_set(username, password)
        if tls:
            self.mqtt_client.tls_set()
        self.mqtt_client.will_set(
            f"{self._topic_prefix}/{device_id}/status",
            "offline",
            retain=True,
        )
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect
        try:
            self.mqtt_client.connect_async(host, port)
            self.mqtt_client.loop_start()
            logging.info(f"Connecting to MQTT broker at {host}:{port}")
        except Exception as e:
            logging.error(f"MQTT connection failed: {e}")

    async def _disconnect_mqtt(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client = None
        self.mqtt_connected = False

    async def stop_service_loop(self):
        await self._disconnect_mqtt()

    def _get_topic(self, suffix):
        return f"{self._topic_prefix}/{self._effective_device_id}/{suffix}"

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logging.error(f"MQTT connection failed with code {rc}")
            return
        logging.info("MQTT connected")
        self.mqtt_connected = True
        self._publish_lwt_online()
        self._subscribe_command_topics()
        self._publish_ha_discovery()

    def _on_disconnect(self, client, userdata, rc):
        self.mqtt_connected = False
        logging.info("MQTT disconnected")

    def _publish_lwt_online(self):
        topic = self._get_topic("status")
        self.mqtt_client.publish(topic, "online", retain=True)

    def _subscribe_command_topics(self):
        client = self.mqtt_client
        client.publish(f"{base_topic}ears/left/state", "0", retain=True)
        client.publish(f"{base_topic}ears/right/state", "0", retain=True)
        logging.info(f"Published HA discovery for device {device_id}")

    async def process_nabd_packet(self, packet):
        if not self.mqtt_connected or self.mqtt_client is None:
            return
        ptype = packet.get("type")
        client = self.mqtt_client
        base = self._get_topic("")
        try:
            if ptype == "rfid_event":
                client.publish(f"{base}events/rfid", json.dumps(packet))
            elif ptype == "asr_event":
                client.publish(f"{base}events/asr", json.dumps(packet))
            elif ptype == "ears_event":
                left = packet.get("left")
                if left is not None:
                    client.publish(f"{base}ears/left/state", str(left))
                right = packet.get("right")
                if right is not None:
                    client.publish(f"{base}ears/right/state", str(right))
                ear = packet.get("ear")
                if ear is not None:
                    pos = packet.get("pos")
                    if pos is not None:
                        client.publish(f"{base}ears/{ear}/state", str(pos))
            elif ptype == "state":
                client.publish(f"{base}state", packet.get("state", ""))
        except Exception as e:
            logging.error(f"Failed to publish to MQTT: {e}")


if __name__ == "__main__":
    NabMqttd.main(sys.argv[1:])
