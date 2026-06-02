from django.test import Client, TestCase

from nabradio.models import Config


class TestRadioSettingsView(TestCase):
    def setUp(self):
        Config.load()

    def test_get_settings(self):
        c = Client()
        response = c.get("/nabradio/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.templates[0].name, "nabradio/settings.html"
        )
        self.assertTrue("config" in response.context)
        config = Config.load()
        self.assertEqual(response.context["config"], config)

    def test_post_updates_streaming_url(self):
        c = Client()
        response = c.post(
            "/nabradio/settings",
            {"streaming_url": "http://example.com/stream"},
        )
        self.assertEqual(response.status_code, 200)
        config = Config.load()
        self.assertEqual(config.streaming_url, "http://example.com/stream")

    def test_post_without_url_leaves_default(self):
        Config.load()
        c = Client()
        response = c.post("/nabradio/settings", {})
        self.assertEqual(response.status_code, 200)
        config = Config.load()
        self.assertEqual(config.streaming_url, "")
