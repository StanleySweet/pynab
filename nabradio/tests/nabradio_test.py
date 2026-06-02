import datetime
import json
import unittest
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync

from nabd.tests.mock import MockWriter
from nabd.tests.utils import close_old_async_connections
from nabradio.nabradio import NabRadio


@pytest.mark.django_db(transaction=True)
class TestNabRadioReloadConfig(unittest.TestCase):
    def setUp(self):
        from nabradio.models import Config

        self.config = Config.load()
        self.config.next_radio_date = None
        self.config.next_radio_url = ""
        self.config.save()
        self.service = NabRadio()
        self.service.writer = MockWriter()

    def tearDown(self):
        close_old_async_connections()
        self.config.next_radio_date = None
        self.config.next_radio_url = ""
        self.config.save()

    def test_reload_config_no_scheduled_action(self):
        self.config.next_radio_date = None
        self.config.next_radio_url = ""
        self.config.save()
        async_to_sync(self.service.reload_config)()
        self.assertEqual(len(self.service.writer.written), 0)

    def test_reload_config_launches_radio_when_url_set(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.config.next_radio_date = now
        self.config.next_radio_url = "http://example.com/stream"
        self.config.save()
        async_to_sync(self.service.reload_config)()
        self.assertEqual(len(self.service.writer.written), 1)
        packet = self.service.writer.written[0].decode("utf8")
        data = json.loads(packet)
        self.assertEqual(data["type"], "message")
        self.assertEqual(data["request_id"], "nabradio")
        self.assertIn("http://example.com/stream", packet)

    def test_reload_config_stops_radio_when_url_empty(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.config.next_radio_date = now
        self.config.next_radio_url = ""
        self.config.save()
        async_to_sync(self.service.reload_config)()
        self.assertEqual(len(self.service.writer.written), 1)
        packet = self.service.writer.written[0].decode("utf8")
        data = json.loads(packet)
        self.assertEqual(data["type"], "cancel")
        self.assertEqual(data["request_id"], "nabradio")

    def test_reload_config_clears_scheduled_action(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.config.next_radio_date = now
        self.config.next_radio_url = "http://example.com/stream"
        self.config.save()
        async_to_sync(self.service.reload_config)()
        from nabradio.models import Config

        refreshed = Config.load()
        self.assertIsNone(refreshed.next_radio_date)
        self.assertEqual(refreshed.next_radio_url, "")

    def test_reload_config_uses_async_db(self):
        self.config.next_radio_date = datetime.datetime.now(
            datetime.timezone.utc
        )
        self.config.next_radio_url = "http://example.com/stream"
        self.config.save()
        with patch.object(
            type(self.config), "load_async"
        ) as mock_load_async, patch.object(
            type(self.config), "save_async"
        ) as mock_save_async:
            mock_load_async.return_value = self.config
            async_to_sync(self.service.reload_config)()
            mock_load_async.assert_called_once()
            mock_save_async.assert_called_once()


@pytest.mark.django_db(transaction=True)
class TestNabRadioStop(unittest.TestCase):
    def setUp(self):
        self.service = NabRadio()
        self.service.writer = MockWriter()

    def tearDown(self):
        close_old_async_connections()

    def test_stop_radio_sends_cancel_with_request_id(self):
        async_to_sync(self.service._stop_radio)()
        self.assertEqual(len(self.service.writer.written), 1)
        packet = self.service.writer.written[0].decode("utf8")
        data = json.loads(packet)
        self.assertEqual(data["type"], "cancel")
        self.assertEqual(data["request_id"], "nabradio")


@pytest.mark.django_db(transaction=True)
class TestNabRadioLaunch(unittest.TestCase):
    def setUp(self):
        self.service = NabRadio()
        self.service.writer = MockWriter()

    def tearDown(self):
        close_old_async_connections()

    def test_launch_radio_includes_request_id(self):
        async_to_sync(self.service._launch_radio)(
            "http://example.com/stream"
        )
        self.assertEqual(len(self.service.writer.written), 1)
        packet = self.service.writer.written[0].decode("utf8")
        data = json.loads(packet)
        self.assertEqual(data["type"], "message")
        self.assertEqual(data["request_id"], "nabradio")

    def test_launch_radio_includes_streaming_url(self):
        async_to_sync(self.service._launch_radio)(
            "http://example.com/stream"
        )
        packet = self.service.writer.written[0].decode("utf8")
        self.assertIn("http://example.com/stream", packet)
