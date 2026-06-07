import asyncio

from django.shortcuts import render
from django.views.generic import TemplateView

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabService

from .models import Config


class SettingsView(TemplateView):
    template_name = "nabd/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["config"] = Config.load()
        return context

    def post(self, request, *args, **kwargs):
        config = Config.load()
        config.bottom_led_color = request.POST.get(
            "bottom_led_color", "#00FFFF"
        )
        config.save()
        # Sync to configd: merge with existing so locale is not lost
        existing = ConfigClient().get("nabd")
        existing["bottom_led_color"] = config.bottom_led_color
        ConfigClient().set("nabd", dict(existing))
        asyncio.run(self._notify_config_update("nabd"))
        context = super().get_context_data(**kwargs)
        context["config"] = config
        return render(request, SettingsView.template_name, context=context)

    async def _notify_config_update(self, service):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    NabService.HOST, NabService.PORT_NUMBER
                ),
                0.5,
            )
            packet = (
                f'{{"type":"config-update","service":"{service}"}}\r\n'
            )
            writer.write(packet.encode("utf-8"))
            await writer.drain()
            writer.close()
        except Exception:
            pass
