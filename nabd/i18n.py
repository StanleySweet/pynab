from nabcommon.config_client import ConfigClient


async def get_locale():
    config = ConfigClient().get("nabd")
    return config.get("locale", "fr_FR")
