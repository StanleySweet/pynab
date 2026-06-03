from django.db import models

from nabcommon import singleton_model


class Config(singleton_model.SingletonModel):
    enabled = models.BooleanField(default=True)
    engine = models.CharField(default="piper", max_length=32)
    voice = models.CharField(default="fr_FR-upmc-medium", max_length=128)
    tts_addr = models.CharField(default="pi4.local:8765", max_length=256)

    class Meta:
        app_label = "nabttsd"
