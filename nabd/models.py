from django.db import models

from nabcommon import singleton_model


class Config(singleton_model.SingletonModel):
    locale = models.TextField(default="fr_FR")
    bottom_led_color = models.CharField(default="#00FFFF", max_length=7)

    class Meta:
        app_label = "nabd"
