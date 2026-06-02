import datetime

from django.db import models

from nabcommon import singleton_model


# Create your models here.
class Config(singleton_model.SingletonModel):

    streaming_url = models.TextField(null=True, default="")
    next_radio_date = models.DateTimeField(null=True, default=None)
    next_radio_url = models.TextField(null=True, default="")
    json_data_base = models.TextField(null=True, default="")
