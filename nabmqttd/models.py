from django.db import models

from nabcommon import singleton_model


class Config(singleton_model.SingletonModel):
    broker_host = models.TextField(default="localhost")
    broker_port = models.IntegerField(default=1883)
    broker_username = models.TextField(null=True, default="")
    broker_password = models.TextField(null=True, default="")
    broker_tls = models.BooleanField(default=False)
    device_id = models.TextField(null=True, default="")
    discovery_prefix = models.TextField(default="homeassistant")
    topic_prefix = models.TextField(default="nabaztag")
    default_radio_url = models.TextField(null=True, default="")
    json_data_base = models.TextField(null=True, default="")
