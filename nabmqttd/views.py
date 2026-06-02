from django.http import JsonResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from . import rfid_data
from .models import Config
from .nabmqttd import NabMqttd


class SettingsView(TemplateView):
    template_name = "nabmqttd/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["config"] = Config.load()
        return context

    def post(self, request, *args, **kwargs):
        config = Config.load()
        if "broker_host" in request.POST:
            config.broker_host = request.POST["broker_host"]
        if "broker_port" in request.POST:
            config.broker_port = int(request.POST["broker_port"])
        if "broker_username" in request.POST:
            config.broker_username = request.POST["broker_username"]
        if "broker_password" in request.POST:
            config.broker_password = request.POST["broker_password"]
        if "broker_tls" in request.POST:
            config.broker_tls = request.POST["broker_tls"] == "true"
        if "device_id" in request.POST:
            config.device_id = request.POST["device_id"]
        if "discovery_prefix" in request.POST:
            config.discovery_prefix = request.POST["discovery_prefix"]
        if "topic_prefix" in request.POST:
            config.topic_prefix = request.POST["topic_prefix"]
        if "default_radio_url" in request.POST:
            config.default_radio_url = request.POST["default_radio_url"]
        config.save()
        NabMqttd.signal_daemon()
        context = self.get_context_data(**kwargs)
        return render(request, SettingsView.template_name, context=context)


class RFIDDataView(TemplateView):
    template_name = "nabmqttd/rfid-data.html"

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        uid = request.GET.get("uid", None)

        mqtt_topic = rfid_data.read_data_ui_for_views(uid)

        context["mqtt_topic"] = mqtt_topic
        context["mqtt_uid"] = uid

        return render(request, RFIDDataView.template_name, context=context)

    def post(self, request, *args, **kwargs):
        data = "DATA_IN_LOCAL_DB"
        uid = ""

        if "mqtt_uid" in request.POST:
            uid = request.POST["mqtt_uid"]
        if "mqtt_topic" in request.POST:
            mqtt_topic = request.POST["mqtt_topic"]
        else:
            mqtt_topic = uid

        rfid_data.write_data_ui_for_views(uid, mqtt_topic)

        return JsonResponse({"data": data})
