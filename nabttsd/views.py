import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from .models import Config
from .nabttsd import NabTtsd


class SettingsView(TemplateView):
    template_name = "nabttsd/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["config"] = Config.load()
        return context

    def post(self, request, *args, **kwargs):
        config = Config.load()
        config.enabled = request.POST.get("enabled") == "true"
        config.engine = request.POST.get("engine", "piper")
        config.voice = request.POST.get("voice", "fr_FR-upmc-medium")
        config.tts_addr = request.POST.get("tts_addr", "pi4.local:8765")
        length_scale = request.POST.get("length_scale", "1.5")
        try:
            config.length_scale = float(length_scale)
        except ValueError:
            config.length_scale = 1.5
        config.save()
        NabTtsd.signal_daemon()
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context=context)

    def put(self, request, *args, **kwargs):
        data = json.loads(request.body)
        text = data.get("text", "")
        if text:
            config = Config.load()
            with open("/tmp/nabttsd_pending.json", "w") as f:
                json.dump({
                    "text": text,
                    "engine": data.get("engine", "piper"),
                    "voice": data.get("voice", "fr_FR-upmc-medium"),
                    "length_scale": float(data.get("length_scale", config.length_scale)),
                }, f)
            NabTtsd.signal_daemon()
        return JsonResponse({"status": "ok"})
