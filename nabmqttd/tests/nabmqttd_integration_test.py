import json
import unittest
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import async_to_sync

from nabd.tests.utils import close_old_async_connections
from nabmqttd.nabmqttd import NabMqttd


@pytest.mark.django_db(transaction=True)
class TestHandleLedsSet(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service._send_choreo = MagicMock()
        self.service._send_to_nabd = MagicMock()

    def tearDown(self):
        close_old_async_connections()

    def test_preset_name_sends_choreo(self):
        self.service._handle_leds_set('{"preset": "solid_red"}', MagicMock())
        self.service._send_choreo.assert_called_once()

    def test_unknown_preset_does_not_send(self):
        self.service._handle_leds_set('{"preset": "unknown"}', MagicMock())
        self.service._send_choreo.assert_not_called()

    def test_state_off_sends_off_choreo(self):
        self.service._handle_leds_set('{"state": "OFF"}', MagicMock())
        self.service._send_choreo.assert_called_once()

    def test_state_on_without_color_uses_default(self):
        self.service._handle_leds_set('{"state": "ON"}', MagicMock())
        self.service._send_choreo.assert_called_once()
        args = self.service._send_choreo.call_args[0][0]
        self.assertTrue(args["persist"])
        self.assertEqual(args["colors"][0]["left"], "ffffff")

    def test_state_on_with_color(self):
        self.service._handle_leds_set(
            '{"state": "ON", "color": {"r": 255, "g": 0, "b": 0}}',
            MagicMock(),
        )
        self.service._send_choreo.assert_called_once()
        args = self.service._send_choreo.call_args[0][0]
        self.assertEqual(args["colors"][0]["left"], "ff0000")

    def test_plain_string_preset(self):
        self.service._handle_leds_set("solid_red", MagicMock())
        self.service._send_choreo.assert_called_once()

    def test_plain_string_unknown_does_not_send(self):
        self.service._handle_leds_set("unknown", MagicMock())
        self.service._send_choreo.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestSendChoreo(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service._send_to_nabd = MagicMock()

    def tearDown(self):
        close_old_async_connections()

    def test_send_choreo_produces_correct_packet(self):
        loop = MagicMock()
        choreo = {
            "tempo": 10,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "00ff00",
                    "right": "0000ff",
                }
            ],
        }
        with patch("nabmqttd.nabmqttd.asyncio.run_coroutine_threadsafe"):
            self.service._send_choreo(choreo, loop)
        sent_payload = self.service._send_to_nabd.call_args[0][0]
        data = json.loads(sent_payload)
        self.assertEqual(data["type"], "command")
        self.assertIn("sequence", data)
        self.assertIn("choreography", data["sequence"][0])
        self.assertTrue(
            data["sequence"][0]["choreography"].startswith(
                "data:application/x-nabaztag-mtl-choreography;base64,"
            )
        )


@pytest.mark.django_db(transaction=True)
class TestRadioTrigger(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()

    def tearDown(self):
        close_old_async_connections()

    def test_trigger_radio_sets_radio_active(self):
        async def mock_send(payload):
            pass

        self.service._send_to_nabd = mock_send
        async_to_sync(self.service._trigger_radio)(
            "http://example.com/stream"
        )
        self.assertTrue(self.service._radio_active)

    def test_trigger_radio_sends_request_id(self):
        captured = {}

        async def mock_send(payload):
            captured["data"] = json.loads(payload.strip())

        self.service._send_to_nabd = mock_send
        async_to_sync(self.service._trigger_radio)(
            "http://example.com/stream"
        )
        self.assertEqual(captured["data"]["request_id"], "nabradio")

    def test_stop_radio_sends_cancel_request_id(self):
        captured = {}

        async def mock_send(payload):
            captured["data"] = json.loads(payload.strip())

        self.service._send_to_nabd = mock_send
        async_to_sync(self.service._stop_radio)()
        self.assertEqual(captured["data"]["type"], "cancel")
        self.assertEqual(captured["data"]["request_id"], "nabradio")

    def test_stop_radio_clears_radio_active(self):
        self.service._radio_active = True

        async def mock_send(payload):
            pass

        self.service._send_to_nabd = mock_send
        async_to_sync(self.service._stop_radio)()
        self.assertFalse(self.service._radio_active)


@pytest.mark.django_db(transaction=True)
class TestRadioStopHADiscovery(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service._effective_device_id = "nabaztag_test"
        self.service.mqtt_client = MagicMock()
        self.service._discovery_prefix = "homeassistant"
        self.service._topic_prefix = "nabaztag"

    def tearDown(self):
        close_old_async_connections()

    def test_ha_discovery_includes_radio_stop(self):
        self.service._publish_ha_discovery()
        calls = self.service.mqtt_client.publish.call_args_list
        stop_configs = [
            json.loads(call[0][1])
            for call in calls
            if "radio_stop" in call[0][0]
        ]
        self.assertEqual(len(stop_configs), 1)
        self.assertIn(
            "action/radio/stop", stop_configs[0]["command_topic"]
        )

    def test_ha_discovery_includes_radio_play(self):
        self.service._publish_ha_discovery()
        calls = self.service.mqtt_client.publish.call_args_list
        topics = [call[0][0] for call in calls]
        play_topic = [t for t in topics if "/radio/" in t and "stop" not in t]
        self.assertEqual(len(play_topic), 1)


@pytest.mark.django_db(transaction=True)
class TestRadioOnMessage(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service.loop = MagicMock()

    def tearDown(self):
        close_old_async_connections()

    def test_radio_guard_blocks_second_play(self):
        self.service._radio_active = True
        with patch("nabmqttd.nabmqttd.asyncio.run_coroutine_threadsafe") as mock_run:
            msg = MagicMock()
            msg.topic = "nabaztag/test/action/radio"
            msg.payload = b""
            self.service._on_message(None, None, msg)
        mock_run.assert_not_called()

    def test_radio_guard_allows_first_play(self):
        self.service._radio_active = False
        with patch("nabmqttd.nabmqttd.asyncio.run_coroutine_threadsafe") as mock_run:
            msg = MagicMock()
            msg.topic = "nabaztag/test/action/radio"
            msg.payload = b""
            self.service._on_message(None, None, msg)
        mock_run.assert_called_once()

    def test_radio_stop_calls_stop_radio(self):
        with patch("nabmqttd.nabmqttd.asyncio.run_coroutine_threadsafe") as mock_run:
            msg = MagicMock()
            msg.topic = "nabaztag/test/action/radio/stop"
            msg.payload = b""
            self.service._on_message(None, None, msg)
        mock_run.assert_called_once()
