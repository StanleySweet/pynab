import datetime
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import async_to_sync

from nabd.tests.mock import MockWriter, NabdMockTestCase
from nabd.tests.utils import close_old_async_connections
from nabweatherd import models, rfid_data
from nabweatherd.nabweatherd import NabWeatherd


def get_nabweatherd_instance(**kwargs):
    object = NabWeatherd()
    object.get_system_tz = lambda: "Europe/Paris"
    return object


class TestNabWeatherd(unittest.TestCase):
    def test_aliases(self):
        service = get_nabweatherd_instance()
        weather_class = service.normalize_weather_class("Pluie forte")
        self.assertEqual(weather_class, "Pluie forte")
        weather_class = service.normalize_weather_class("None")
        self.assertEqual(weather_class, None)


@pytest.mark.django_db(transaction=True)
class TestNabWeatherdDB(unittest.TestCase):
    RENNES_LOCATION = dict(
        insee="35238",
        name="Rennes",
        lat=48.11417,
        lon=-1.68083,
        country="FR",
        admin="Bretagne",
        admin2="35",
        postCode="35000",
    )

    def tearDown(self):
        close_old_async_connections()

    def test_fetch_info_data(self):
        service = get_nabweatherd_instance()

        data = async_to_sync(service.fetch_info_data)(
            (
                TestNabWeatherdDB.RENNES_LOCATION,
                NabWeatherd.UNIT_CELSIUS,
                "weather_and_rain",
                3,
                None,
                False,
            )
        )
        self.assertTrue("current_weather_class" in data)
        self.assertTrue("today_forecast_weather_class" in data)
        self.assertTrue("today_forecast_max_temp" in data)
        self.assertTrue("tomorrow_forecast_weather_class" in data)
        self.assertTrue("tomorrow_forecast_max_temp" in data)
        self.assertTrue("next_rain" in data)
        self.assertTrue("weather_animation_type" in data)

    def test_perform_both(self):
        service = get_nabweatherd_instance()
        writer = MockWriter()
        service.writer = writer
        config_t = (
            TestNabWeatherdDB.RENNES_LOCATION,
            NabWeatherd.UNIT_CELSIUS,
            "weather_and_rain",
            3,
            None,
            False,
        )
        expiration = datetime.datetime(2019, 4, 22, 0, 0, 0)
        async_to_sync(service.perform)(expiration, "today", config_t)
        self.assertEqual(len(writer.written), 3)
        packet = writer.written[0]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd_rain")
        packet = writer.written[1]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd")
        self.assertTrue("animation" in packet_json)
        packet = writer.written[2]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "message")
        self.assertTrue("signature" in packet_json)
        self.assertTrue("body" in packet_json)

    def test_perform_rain(self):
        service = get_nabweatherd_instance()
        writer = MockWriter()
        service.writer = writer
        config_t = (
            TestNabWeatherdDB.RENNES_LOCATION,
            NabWeatherd.UNIT_CELSIUS,
            "rain_only",
            3,
            None,
            False,
        )
        expiration = datetime.datetime(2019, 4, 22, 0, 0, 0)
        async_to_sync(service.perform)(expiration, "today", config_t)
        self.assertEqual(len(writer.written), 3)
        packet = writer.written[0]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd_rain")
        packet = writer.written[1]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd")
        self.assertFalse("animation" in packet_json)
        packet = writer.written[2]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "message")
        self.assertTrue("signature" in packet_json)
        self.assertTrue("body" in packet_json)

    def test_perform(self):
        service = get_nabweatherd_instance()
        writer = MockWriter()
        service.writer = writer
        config_t = (
            TestNabWeatherdDB.RENNES_LOCATION,
            NabWeatherd.UNIT_CELSIUS,
            "weather_only",
            3,
            None,
            False,
        )
        expiration = datetime.datetime(2019, 4, 22, 0, 0, 0)
        async_to_sync(service.perform)(expiration, "today", config_t)
        self.assertEqual(len(writer.written), 3)
        packet = writer.written[0]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd_rain")
        packet = writer.written[1]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd")
        self.assertTrue("animation" in packet_json)
        packet = writer.written[2]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "message")
        self.assertTrue("signature" in packet_json)
        self.assertTrue("body" in packet_json)

    def test_asr(self):
        config = models.Config.load()
        config.location = TestNabWeatherdDB.RENNES_LOCATION
        config.unit = NabWeatherd.UNIT_CELSIUS
        config.weather_animation_type = "weather_only"
        config.save()
        service = get_nabweatherd_instance()
        writer = MockWriter()
        service.writer = writer
        packet = {
            "type": "asr_event",
            "nlu": {"intent": "nabweatherd/forecast"},
        }
        async_to_sync(service.process_nabd_packet)(packet)
        self.assertEqual(len(writer.written), 3)
        packet = writer.written[0]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd_rain")
        packet = writer.written[1]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "info")
        self.assertEqual(packet_json["info_id"], "nabweatherd")
        self.assertTrue("animation" in packet_json)
        packet = writer.written[2]
        packet_json = json.loads(packet.decode("utf8"))
        self.assertEqual(packet_json["type"], "message")
        self.assertTrue("signature" in packet_json)
        self.assertTrue("body" in packet_json)


class TestRFIDData(unittest.TestCase):
    def test_serialize(self):
        self.assertEqual(b"\x01", rfid_data.serialize("today"))
        self.assertEqual(b"\x02", rfid_data.serialize("tomorrow"))
        self.assertEqual(b"\x01", rfid_data.serialize("unknown"))

    def test_unserialize(self):
        self.assertEqual("today", rfid_data.unserialize(b"\x01"))
        self.assertEqual("tomorrow", rfid_data.unserialize(b"\x02"))
        self.assertEqual("today", rfid_data.unserialize(b""))
        self.assertEqual("today", rfid_data.unserialize(b"unknown"))


@pytest.mark.django_db
class TestNabWeatherdRun(NabdMockTestCase):
    def tearDown(self):
        NabdMockTestCase.tearDown(self)
        close_old_async_connections()

    def test_connect(self):
        self.do_test_connect(NabWeatherd)


class TestPerformAdditional(unittest.TestCase):
    def setUp(self):
        self.service = NabWeatherd()
        self.service.writer = MagicMock()
        self.service.writer.drain = AsyncMock()
        self.expiration = datetime.datetime.now()

    def test_today_none_weather_class_does_not_crash(self):
        info_data = {
            "today_forecast_weather_class": None,
            "today_forecast_max_temp": 20,
            "tomorrow_forecast_weather_class": "Eclaircies",
            "tomorrow_forecast_max_temp": 22,
        }
        config = (
            "Paris",
            1,
            "weather_and_rain",
            1,
            None,
            None,
        )
        async_to_sync(self.service.perform_additional)(
            self.expiration, "today", info_data, config
        )
        self.service.writer.write.assert_called_once()

    def test_tomorrow_none_weather_class_does_not_crash(self):
        info_data = {
            "today_forecast_weather_class": "Eclaircies",
            "today_forecast_max_temp": 20,
            "tomorrow_forecast_weather_class": None,
            "tomorrow_forecast_max_temp": 22,
        }
        config = (
            "Paris",
            1,
            "weather_and_rain",
            1,
            None,
            None,
        )
        async_to_sync(self.service.perform_additional)(
            self.expiration, "tomorrow", info_data, config
        )
        self.service.writer.write.assert_called_once()

    def test_valid_weather_class_proceeds_normally(self):
        info_data = {
            "today_forecast_weather_class": "Eclaircies",
            "today_forecast_max_temp": 20,
            "tomorrow_forecast_weather_class": "Pluie",
            "tomorrow_forecast_max_temp": 18,
        }
        config = (
            "Paris",
            1,
            "weather_and_rain",
            1,
            None,
            None,
        )
        async_to_sync(self.service.perform_additional)(
            self.expiration, "today", info_data, config
        )
        self.service.writer.write.assert_called_once()
        written = self.service.writer.write.call_args[0][0]
        self.assertIn("sunny".encode(), written)


class TestGetAnimation(unittest.TestCase):
    def setUp(self):
        self.service = NabWeatherd()
        self.service.writer = MagicMock()

    def test_none_weather_class_returns_none(self):
        info_data = {
            "weather_animation_type": "weather_only",
            "today_forecast_weather_class": None,
            "next_rain": False,
        }
        result = self.service.get_animation(info_data)
        self.assertIsNone(result)

    def test_valid_weather_class_returns_animation(self):
        info_data = {
            "weather_animation_type": "weather_only",
            "today_forecast_weather_class": "Eclaircies",
            "next_rain": False,
        }
        result = self.service.get_animation(info_data)
        self.assertIsNotNone(result)
