from django.test import Client, TestCase

from nabwebhook.models import Config


class TestWebhookSettingsView(TestCase):
    def setUp(self):
        Config.load()

    def test_get_settings(self):
        c = Client()
        response = c.get("/nabwebhook/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.templates[0].name, "nabwebhook/settings.html"
        )
        self.assertTrue("config" in response.context)
        config = Config.load()
        self.assertEqual(response.context["config"], config)

    def test_post_updates_webhook_url(self):
        c = Client()
        response = c.post(
            "/nabwebhook/settings",
            {"webhook_url": "https://example.com/hook"},
        )
        self.assertEqual(response.status_code, 200)
        config = Config.load()
        self.assertEqual(config.webhook_url, "https://example.com/hook")

    def test_post_without_url_leaves_default(self):
        Config.load()
        c = Client()
        response = c.post("/nabwebhook/settings", {})
        self.assertEqual(response.status_code, 200)
        config = Config.load()
        self.assertEqual(config.webhook_url, "")
