from .settings import *  # noqa: F403

INSTALLED_APPS = [
    app for app in INSTALLED_APPS  # noqa: F405
    if app != "nabmastodond"
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
