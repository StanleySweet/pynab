import os

from django.apps import apps
from django.conf import settings


def configure(appname, orm=True):
    if not settings.configured:
        conf = {
            "INSTALLED_APPS": [appname],
            "USE_TZ": True,
        }
        if orm:
            _DB_DIR = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data",
            )
            conf["DATABASES"] = {
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": os.path.join(_DB_DIR, "pynab.db"),
                }
            }
        settings.configure(**conf)
        apps.populate(settings.INSTALLED_APPS)
