import asyncio
import datetime
import json
import logging
import sys
import uuid

import paho.mqtt.client as mqtt

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabService



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
    if choreo.get("persist", False):
        r = int(colors[0].get("left", "000000")[0:2], 16) if colors else 0
        g = int(colors[0].get("left", "000000")[2:4], 16) if colors else 0
        b = int(colors[0].get("left", "000000")[4:6], 16) if colors else 0
        parts = [0, 1, 1]
        parts.extend([0, 9, r, g, b])
        parts.extend([1, 0])
        parts.extend([0, 0])
    else:
        parts = []
        parts.extend([0, 1, tempo])
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
        super().__init__(configd=True)
        self.client = ConfigClient()
        self.mqtt_client = None
        self.mqtt_connected = False
        self.config = None
        self.loop = None
        self._effective_device_id = ""
        self._radio_active = False

    def _set_service_registry(self, registry):
        self._service_registry = registry

    async def reload_config(self):
        logging.info("reloading configuration")
        self.config = await self.client.get_async("nabmqttd")
        await self._disconnect_mqtt()
        self._connect_mqtt()

    def start_service_loop(self, loop):
        self.loop = loop
        self.config = self.client.get("nabmqttd")
        loop.call_soon(self._connect_mqtt)
        return None

    def _get_device_id(self):
        if self.config is None:
            return _get_mac() or "nabaztag_" + uuid.uuid4().hex[:8]
        did = self.config.get("device_id")
        if did:
            return did
        return _get_mac() or "nabaztag_" + uuid.uuid4().hex[:8]

    def _connect_mqtt(self):
        if self.config is None:
            return
        host = self.config.get("broker_host", "localhost")
        port = self.config.get("broker_port", 1883)
        username = self.config.get("broker_username") or None
        password = self.config.get("broker_password") or None
        tls = self.config.get("broker_tls", False)
        device_id = self._get_device_id()
        self._effective_device_id = device_id

        self._discovery_prefix = self.config.get("discovery_prefix", "homeassistant")
        self._topic_prefix = self.config.get("topic_prefix", "nabaztag")

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
        base_topic = self._get_topic("")
        client.publish(f"{base_topic}ears/left/state", "0", retain=True)
        client.publish(f"{base_topic}ears/right/state", "0", retain=True)

    def _on_disconnect(self, client, userdata, rc):
        self.mqtt_connected = False
        logging.info("MQTT disconnected")

    def _publish_lwt_online(self):
        topic = self._get_topic("status")
        self.mqtt_client.publish(topic, "online", retain=True)

    def _subscribe_command_topics(self):
        client = self.mqtt_client
        base = self._get_topic("")
        client.subscribe(f"{base}ears/left/set")
        client.subscribe(f"{base}ears/right/set")
        client.subscribe(f"{base}leds/set")
        client.subscribe(f"{base}action/#")
        client.subscribe(f"{base}mode/set")
        client.subscribe(f"{base}command/#")
        logging.info(f"Subscribed to MQTT topics under {base}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            return
        loop = self.loop
        if loop is None:
            return
        logging.debug(f"MQTT message: {topic} = {payload}")

        if topic.endswith("/ears/left/set"):
            try:
                pos = int(payload.strip())
                if 0 <= pos <= 16:
                    asyncio.run_coroutine_threadsafe(
                        self._send_to_nabd(
                            json.dumps({"type": "ears", "left": pos})
                        ),
                        loop,
                    )
                    base = self._get_topic("")
                    client.publish(
                        f"{base}ears/left/state", str(pos), retain=True
                    )
            except ValueError:
                pass
        elif topic.endswith("/ears/right/set"):
            try:
                pos = int(payload.strip())
                if 0 <= pos <= 16:
                    asyncio.run_coroutine_threadsafe(
                        self._send_to_nabd(
                            json.dumps({"type": "ears", "right": pos})
                        ),
                        loop,
                    )
                    base = self._get_topic("")
                    client.publish(
                        f"{base}ears/right/state", str(pos), retain=True
                    )
            except ValueError:
                pass
        elif topic.endswith("/leds/set"):
            self._handle_leds_set(payload, loop)
        elif topic.endswith("/action/sleep"):
            asyncio.run_coroutine_threadsafe(
                self._send_to_nabd(json.dumps({"type": "sleep"})), loop
            )
        elif topic.endswith("/action/wake"):
            asyncio.run_coroutine_threadsafe(
                self._send_to_nabd(json.dumps({"type": "wakeup"})), loop
            )
        elif topic.endswith("/action/weather"):
            asyncio.run_coroutine_threadsafe(
                self._trigger_service("nabweatherd", "today"), loop
            )
        elif topic.endswith("/action/airquality"):
            asyncio.run_coroutine_threadsafe(
                self._trigger_service("nabairqualityd", "today"), loop
            )
        elif topic.endswith("/action/taichi"):
            asyncio.run_coroutine_threadsafe(self._trigger_taichi(), loop)
        elif topic.endswith("/action/radio/stop"):
            asyncio.run_coroutine_threadsafe(
                self._stop_radio(), loop
            )
        elif topic.endswith("/action/radio"):
            if self._radio_active:
                return
            asyncio.run_coroutine_threadsafe(
                self._trigger_radio(payload), loop
            )
        elif topic.endswith("/mode/set"):
            mode = payload.strip()
            asyncio.run_coroutine_threadsafe(
                self._send_to_nabd(json.dumps({"type": "mode", "mode": mode})),
                loop,
            )
        elif "/command/" in topic:
            asyncio.run_coroutine_threadsafe(
                self._send_to_nabd(payload), loop
            )

    def _handle_leds_set(self, payload, loop):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = payload.strip()

        if isinstance(data, str):
            data = {"preset": data}

        if "preset" in data:
            preset_name = data["preset"]
            choreo = _CHOREOGRAPHIES.get(preset_name)
            if choreo:
                self._send_choreo(choreo, loop)
            return
        elif "state" in data and data.get("state") == "OFF":
            self._send_choreo(_CHOREOGRAPHIES["off"], loop)
        elif "state" in data and data.get("state") == "ON":
            color = data.get("color", {})
            r = color.get("r", 255)
            g = color.get("g", 255)
            b = color.get("b", 255)
            brightness = data.get("brightness", 255)
            self._send_choreo(_rgb_to_choreography(r, g, b, brightness), loop)

    def _send_choreo(self, choreo, loop):
        choreo_b64 = _choreography_to_base64(choreo)
        packet = json.dumps(
            {
                "type": "command",
                "sequence": [
                    {
                        "choreography": "data:application/"
                        "x-nabaztag-mtl-choreography;base64,"
                        + choreo_b64
                    }
                ],
            }
        )
        asyncio.run_coroutine_threadsafe(
            self._send_to_nabd(packet), loop
        )

    async def _send_to_nabd(self, payload: str):
        if self.writer is None:
            return
        try:
            self.writer.write((payload + "\r\n").encode("utf-8"))
            await self.writer.drain()
        except Exception as e:
            logging.error(f"Failed to send to nabd: {e}")

    async def _trigger_service(self, service_name: str, type: str):
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            if service_name == "nabweatherd":
                await self.client.set_async(
                    "nabweatherd",
                    {
                        "next_performance_date": now,
                        "next_performance_type": type,
                        "force_next_performance": True,
                    },
                )
                svc = self._service_registry.get("NabWeatherd")
                if svc:
                    await svc.reload_config()
            elif service_name == "nabairqualityd":
                await self.client.set_async(
                    "nabairqualityd",
                    {
                        "next_performance_date": now,
                        "next_performance_type": type,
                        "force_next_performance": True,
                    },
                )
                svc = self._service_registry.get("NabAirqualityd")
                if svc:
                    await svc.reload_config()
        except Exception as e:
            logging.error(f"Failed to trigger {service_name}: {e}")

    async def _trigger_taichi(self):
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            await self.client.set_async(
                "nabtaichid", {"next_taichi": now, "force_next_performance": True}
            )
            svc = self._service_registry.get("NabTaichid")
            if svc:
                await svc.reload_config()
        except Exception as e:
            logging.error(f"Failed to trigger taichi: {e}")

    async def _trigger_radio(self, url: str = ""):
        if not url:
            cfg = self.client.get("nabmqttd")
            url = cfg.get("default_radio_url", "") or ""
        if url:
            now = datetime.datetime.now(datetime.timezone.utc)
            expiration = now + datetime.timedelta(minutes=5)
            packet = (
                '{"type":"message",'
                '"request_id":"nabradio",'
                '"signature":{"audio":["nabradio/*.mp3"]},'
                '"body":[{"audio":["'
                + url
                + '"]}],'
                '"expiration":"' + expiration.isoformat() + '"}\r\n'
            )
            await self._send_to_nabd(packet)
            self._radio_active = True

    async def _stop_radio(self):
        packet = '{"type":"cancel","request_id":"nabradio"}\r\n'
        await self._send_to_nabd(packet)
        self._radio_active = False

    def _publish_ha_discovery(self):
        client = self.mqtt_client
        if not client:
            return
        device_id = self._effective_device_id
        dp = self._discovery_prefix
        base_topic = self._get_topic("")
        device_info = _build_device_info(device_id)

        def publish_entity(domain, name, config):
            topic = f"{dp}/{domain}/{device_id}/{name}/config"
            config["device"] = device_info
            client.publish(topic, json.dumps(config), retain=True)

        publish_entity(
            "sensor",
            "left_ear",
            {
                "name": "Left Ear",
                "unique_id": f"{device_id}_left_ear",
                "state_topic": f"{base_topic}ears/left/state",
                "icon": "mdi:paw",
            },
        )
        publish_entity(
            "sensor",
            "right_ear",
            {
                "name": "Right Ear",
                "unique_id": f"{device_id}_right_ear",
                "state_topic": f"{base_topic}ears/right/state",
                "icon": "mdi:paw",
            },
        )
        publish_entity(
            "number",
            "ear_left",
            {
                "name": "Left Ear Position",
                "unique_id": f"{device_id}_set_left_ear",
                "state_topic": f"{base_topic}ears/left/state",
                "command_topic": f"{base_topic}ears/left/set",
                "min": 0,
                "max": 16,
                "step": 1,
                "mode": "slider",
                "icon": "mdi:paw",
            },
        )
        publish_entity(
            "number",
            "ear_right",
            {
                "name": "Right Ear Position",
                "unique_id": f"{device_id}_set_right_ear",
                "state_topic": f"{base_topic}ears/right/state",
                "command_topic": f"{base_topic}ears/right/set",
                "min": 0,
                "max": 16,
                "step": 1,
                "mode": "slider",
                "icon": "mdi:paw",
            },
        )
        publish_entity(
            "sensor",
            "button",
            {
                "name": "Button",
                "unique_id": f"{device_id}_button",
                "state_topic": f"{base_topic}events/button",
                "icon": "mdi:gesture-tap",
            },
        )
        publish_entity(
            "sensor",
            "rfid",
            {
                "name": "RFID Tag",
                "unique_id": f"{device_id}_rfid",
                "state_topic": f"{base_topic}events/rfid",
                "icon": "mdi:nfc",
            },
        )
        publish_entity(
            "sensor",
            "asr",
            {
                "name": "Voice Command",
                "unique_id": f"{device_id}_asr",
                "state_topic": f"{base_topic}events/asr",
                "icon": "mdi:microphone",
            },
        )
        publish_entity(
            "binary_sensor",
            "online",
            {
                "name": "Online",
                "unique_id": f"{device_id}_online",
                "state_topic": f"{base_topic}status",
                "payload_on": "online",
                "payload_off": "offline",
                "device_class": "connectivity",
            },
        )
        publish_entity(
            "button",
            "sleep",
            {
                "name": "Sleep",
                "unique_id": f"{device_id}_sleep",
                "command_topic": f"{base_topic}action/sleep",
                "payload_press": "",
                "icon": "mdi:sleep",
            },
        )
        publish_entity(
            "button",
            "wake",
            {
                "name": "Wake",
                "unique_id": f"{device_id}_wake",
                "command_topic": f"{base_topic}action/wake",
                "payload_press": "",
                "icon": "mdi:weather-night",
            },
        )
        publish_entity(
            "button",
            "weather",
            {
                "name": "Weather Forecast",
                "unique_id": f"{device_id}_weather",
                "command_topic": f"{base_topic}action/weather",
                "payload_press": "",
                "icon": "mdi:weather-partly-cloudy",
            },
        )
        publish_entity(
            "button",
            "airquality",
            {
                "name": "Air Quality",
                "unique_id": f"{device_id}_airquality",
                "command_topic": f"{base_topic}action/airquality",
                "payload_press": "",
                "icon": "mdi:air-filter",
            },
        )
        publish_entity(
            "button",
            "taichi",
            {
                "name": "Tai Chi",
                "unique_id": f"{device_id}_taichi",
                "command_topic": f"{base_topic}action/taichi",
                "payload_press": "",
                "icon": "mdi:meditation",
            },
        )
        publish_entity(
            "button",
            "radio",
            {
                "name": "Play Radio",
                "unique_id": f"{device_id}_radio",
                "command_topic": f"{base_topic}action/radio",
                "payload_press": "",
                "icon": "mdi:radio",
            },
        )
        publish_entity(
            "button",
            "radio_stop",
            {
                "name": "Stop Radio",
                "unique_id": f"{device_id}_radio_stop",
                "command_topic": f"{base_topic}action/radio/stop",
                "payload_press": "",
                "icon": "mdi:radio-off",
            },
        )

        logging.info(f"Published HA discovery for device {device_id}")

    async def process_nabd_packet(self, packet):
        if packet.get("type") == "state":
            self._nabd_asleep = packet.get("state") == "asleep"
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
                client.publish(f"{base}state", json.dumps(packet))
        except Exception as e:
            logging.error(f"Failed to publish to MQTT: {e}")


if __name__ == "__main__":
    NabMqttd.main(sys.argv[1:])
