from django.http import JsonResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from . import rfid_data
from .models import Config


class SettingsView(TemplateView):
    template_name = "nabwebhook/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["config"] = Config.load()
        return context

    def post(self, request, *args, **kwargs):
        config = Config.load()
        if "webhook_url" in request.POST:
            config.webhook_url = request.POST["webhook_url"]
        config.save()
        context = super().get_context_data(**kwargs)
        context["config"] = config
        return render(request, SettingsView.template_name, context=context)


class RFIDDataView(TemplateView):
    template_name = "nabwebhook/rfid-data.html"

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        uid = request.GET.get("uid", None)

        webhook_url = rfid_data.read_data_ui_for_views(uid)

        context["webhook_url"] = webhook_url
        context["webhook_uid"] = uid

        return render(request, RFIDDataView.template_name, context=context)

    def post(self, request, *args, **kwargs):

        data = "DATA_IN_LOCAL_DB"
        uid = ""

        if "webhook_uid" in request.POST:
            uid = request.POST["webhook_uid"]
        if "webhook_url" in request.POST:
            webhook_url = request.POST["webhook_url"]
        else:
            webhook_url = uid

        rfid_data.write_data_ui_for_views(uid, webhook_url)

        return JsonResponse({"data": data})
