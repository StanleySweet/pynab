import json
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import async_to_sync
from django.test import Client, TestCase

from nabd.tests.utils import close_old_async_connections
from nabmqttd.nabmqttd import _get_mac, NabMqttd

sys.modules["mastodon"] = MagicMock()
sys.modules["meteofrance_api"] = MagicMock()
sys.modules["meteofrance_api.client"] = MagicMock()
sys.modules["requests"] = MagicMock()
import nabairqualityd.nabairqualityd  # noqa: E402,F401
import nabweatherd.nabweatherd  # noqa: E402,F401


class TestGetMac(unittest.TestCase):
    @patch("nabmqttd.nabmqttd.uuid.getnode")
    def test_get_mac_returns_formatted_mac(self, mock_getnode):
        mock_getnode.return_value = 0x001122334455
        result = _get_mac()
        self.assertEqual(result, "nabaztag_001122334455")

    @patch("nabmqttd.nabmqttd.uuid.getnode")
    def test_get_mac_returns_none_for_random_mac(self, mock_getnode):
        mock_getnode.return_value = 0x011122334455
        result = _get_mac()
        self.assertIsNone(result)

    @patch("nabmqttd.nabmqttd.uuid.getnode")
    def test_get_mac_pads_short_mac(self, mock_getnode):
        mock_getnode.return_value = 0xFF
        result = _get_mac()
        self.assertEqual(result, "nabaztag_0000000000ff")

    @patch("nabmqttd.nabmqttd.uuid.getnode", side_effect=Exception)
    def test_get_mac_returns_none_on_exception(self, mock_getnode):
        result = _get_mac()
        self.assertIsNone(result)


@pytest.mark.django_db(transaction=True)
class TestGetDeviceId(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service.config = MagicMock()
        from nabmqttd.models import Config as MqttConfig

        self.real_config_cls = MqttConfig

    def tearDown(self):
        close_old_async_connections()

    def test_get_device_id_uses_config_device_id(self):
        self.service.config.device_id = "custom_device_id"
        result = self.service._get_device_id()
        self.assertEqual(result, "custom_device_id")

    def test_get_device_id_falls_back_to_mac(self):
        self.service.config.device_id = ""
        with patch(
            "nabmqttd.nabmqttd._get_mac",
            return_value="nabaztag_001122334455",
        ):
            result = self.service._get_device_id()
        self.assertEqual(result, "nabaztag_001122334455")


@pytest.mark.django_db(transaction=True)
class TestSendToNabd(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service.writer = MagicMock()

    def tearDown(self):
        close_old_async_connections()

    def test_send_to_nabd_writes_packet(self):
        async_to_sync(self.service._send_to_nabd)('{"test": true}')
        written = self.service.writer.write.call_args[0][0]
        self.assertEqual(written, b'{"test": true}\r\n')

    def test_send_to_nabd_drains_writer(self):
        async_to_sync(self.service._send_to_nabd)('{"test": true}')
        self.service.writer.drain.assert_called_once()

    def test_send_to_nabd_does_not_write_when_writer_none(self):
        self.service.writer = None
        result = async_to_sync(self.service._send_to_nabd)('{"test": true}')
        self.assertIsNone(result)


@pytest.mark.django_db(transaction=True)
class TestPublishLwtOnline(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service.mqtt_client = MagicMock()
        self.service._effective_device_id = "nabaztag_test"
        self.service._topic_prefix = "nabaztag"

    def tearDown(self):
        close_old_async_connections()

    def test_publishes_online_status(self):
        self.service._publish_lwt_online()
        self.service.mqtt_client.publish.assert_called_with(
            "nabaztag/nabaztag_test/status", "online", retain=True
        )


@pytest.mark.django_db(transaction=True)
class TestProcessNabdPacket(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()
        self.service.mqtt_connected = True
        self.service.mqtt_client = MagicMock()
        self.service._effective_device_id = "nabaztag_test"
        self.service._topic_prefix = "nabaztag"

    def tearDown(self):
        close_old_async_connections()

    def test_rfid_event_publishes(self):
        async_to_sync(self.service.process_nabd_packet)(
            {"type": "rfid_event", "uid": "abc123"}
        )
        self.service.mqtt_client.publish.assert_called_once()

    def test_asr_event_publishes(self):
        async_to_sync(self.service.process_nabd_packet)(
            {"type": "asr_event", "text": "hello"}
        )
        self.service.mqtt_client.publish.assert_called_once()

    def test_ears_event_publishes(self):
        async_to_sync(self.service.process_nabd_packet)(
            {"type": "ears_event", "left": 5, "right": 10}
        )
        calls = self.service.mqtt_client.publish.call_args_list
        topics = [call[0][0] for call in calls]
        self.assertIn("nabaztag/nabaztag_test/ears/left/state", topics)
        self.assertIn("nabaztag/nabaztag_test/ears/right/state", topics)

    def test_ears_event_single_ear(self):
        async_to_sync(self.service.process_nabd_packet)(
            {"type": "ears_event", "ear": "left", "pos": 7}
        )
        self.service.mqtt_client.publish.assert_called_with(
            "nabaztag/nabaztag_test/ears/left/state", "7"
        )

    def test_state_event_publishes(self):
        async_to_sync(self.service.process_nabd_packet)(
            {"type": "state", "state": "idle"}
        )
        self.service.mqtt_client.publish.assert_called_with(
            "nabaztag/nabaztag_test/state", "idle"
        )

    def test_skips_when_mqtt_not_connected(self):
        self.service.mqtt_connected = False
        async_to_sync(self.service.process_nabd_packet)(
            {"type": "rfid_event"}
        )
        self.service.mqtt_client.publish.assert_not_called()

    def test_skips_when_mqtt_client_none(self):
        self.service.mqtt_client = None
        async_to_sync(self.service.process_nabd_packet)(
            {"type": "rfid_event"}
        )


@pytest.mark.django_db(transaction=True)
class TestTriggerService(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()

    def tearDown(self):
        close_old_async_connections()

    @patch("nabweatherd.models.Config.load_async")
    @patch("nabweatherd.nabweatherd.NabWeatherd.signal_daemon")
    def test_trigger_weather(
        self, mock_signal, mock_load
    ):
        cfg = MagicMock()
        cfg.next_performance_date = None
        cfg.next_performance_type = ""
        mock_load.return_value = cfg
        async_to_sync(self.service._trigger_service)("nabweatherd", "today")
        self.assertEqual(cfg.next_performance_type, "today")

    @patch("nabairqualityd.models.Config.load_async")
    @patch("nabairqualityd.nabairqualityd.NabAirqualityd.signal_daemon")
    def test_trigger_airquality(
        self, mock_signal, mock_load
    ):
        cfg = MagicMock()
        mock_load.return_value = cfg
        async_to_sync(self.service._trigger_service)("nabairqualityd", "today")
        self.assertEqual(cfg.next_performance_type, "today")


@pytest.mark.django_db(transaction=True)
class TestTriggerTaichi(unittest.TestCase):
    def setUp(self):
        self.service = NabMqttd()

    def tearDown(self):
        close_old_async_connections()

    @patch("nabtaichid.models.Config.load_async")
    @patch("nabtaichid.nabtaichid.NabTaichid.signal_daemon")
    def test_trigger_taichi_sets_next_taichi(
        self, mock_signal, mock_load
    ):
        cfg = MagicMock()
        cfg.next_taichi = None
        mock_load.return_value = cfg
        async_to_sync(self.service._trigger_taichi)()
        self.assertIsNotNone(cfg.next_taichi)


class TestRfidDataFunctions(unittest.TestCase):
    def test_read_data_ui_for_views_returns_empty_for_unknown_uid(self):
        from nabmqttd import rfid_data

        with patch("nabmqttd.models.Config") as MockConfig:
            config = MagicMock()
            config.json_data_base = "{}"
            MockConfig.load.return_value = config
            result = rfid_data.read_data_ui_for_views("unknown_uid")
        self.assertEqual(result, "")

    def test_read_data_ui_for_views_returns_topic_for_known_uid(self):
        from nabmqttd import rfid_data

        with patch("nabmqttd.models.Config") as MockConfig:
            config = MagicMock()
            config.json_data_base = '{"known_uid": "events/my_topic"}'
            MockConfig.load.return_value = config
            result = rfid_data.read_data_ui_for_views("known_uid")
        self.assertEqual(result, "events/my_topic")

    def test_write_data_ui_for_views_stores_data(self):
        from nabmqttd import rfid_data

        with patch("nabmqttd.models.Config") as MockConfig:
            config = MagicMock()
            config.json_data_base = "{}"
            MockConfig.load.return_value = config
            rfid_data.write_data_ui_for_views("test_uid", "events/test")
            self.assertIn("test_uid", json.loads(config.json_data_base))
            self.assertEqual(
                json.loads(config.json_data_base)["test_uid"], "events/test"
            )
            config.save.assert_called_once()


class TestMqttSettingsView(TestCase):

    def setUp(self):
        from nabmqttd.models import Config as MqttConfig

        MqttConfig.load()

    def test_get_settings(self):
        c = Client()
        response = c.get("/nabmqttd/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.templates[0].name, "nabmqttd/settings.html"
        )
        self.assertTrue("config" in response.context)

    def test_post_updates_broker_host(self):
        from nabmqttd.models import Config as MqttConfig

        c = Client()
        response = c.post(
            "/nabmqttd/settings",
            {"broker_host": "mqtt.example.com"},
        )
        self.assertEqual(response.status_code, 200)
        config = MqttConfig.load()
        self.assertEqual(config.broker_host, "mqtt.example.com")

    def test_post_updates_broker_port(self):
        from nabmqttd.models import Config as MqttConfig

        c = Client()
        response = c.post(
            "/nabmqttd/settings", {"broker_port": "8883"}
        )
        self.assertEqual(response.status_code, 200)
        config = MqttConfig.load()
        self.assertEqual(config.broker_port, 8883)
