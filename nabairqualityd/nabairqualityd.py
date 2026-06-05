import asyncio
import datetime
import json
import logging
import sys

from django.utils.translation import gettext as _, override, to_language

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabInfoCachedService

from . import aqicn


class NabAirqualityd(NabInfoCachedService):

    MESSAGES = ["bad", "moderate", "good"]
    ANIMATION_GOOD = (
        '{"tempo":42,"colors":['
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"000000","center":"000000","right":"000000"}]}'
    )
    ANIMATION_MODERATE = (
        '{"tempo":14,"colors":['
        '{"left":"000000","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"000000"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"000000","right":"00ffff"},'
        '{"left":"000000","center":"000000","right":"00ffff"},'
        '{"left":"000000","center":"000000","right":"000000"},'
        '{"left":"000000","center":"00ffff","right":"000000"},'
        '{"left":"000000","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"000000"},'
        '{"left":"00ffff","center":"000000","right":"00ffff"},'
        '{"left":"000000","center":"00ffff","right":"00ffff"}]}'
    )
    ANIMATION_BAD = (
        '{"tempo":14,"colors":['
        '{"left":"000000","center":"00ffff","right":"000000"},'
        '{"left":"000000","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"00ffff","center":"000000","right":"000000"},'
        '{"left":"000000","center":"000000","right":"000000"},'
        '{"left":"000000","center":"00ffff","right":"000000"},'
        '{"left":"000000","center":"00ffff","right":"00ffff"},'
        '{"left":"000000","center":"000000","right":"000000"},'
        '{"left":"00ffff","center":"00ffff","right":"000000"},'
        '{"left":"00ffff","center":"00ffff","right":"00ffff"},'
        '{"left":"000000","center":"000000","right":"00ffff"},'
        '{"left":"00ffff","center":"000000","right":"000000"},'
        '{"left":"000000","center":"00ffff","right":"000000"},'
        '{"left":"000000","center":"000000","right":"000000"},'
        '{"left":"00ffff","center":"000000","right":"00ffff"},'
        '{"left":"000000","center":"00ffff","right":"000000"}]}'
    )

    ANIMATIONS = [ANIMATION_BAD, ANIMATION_MODERATE, ANIMATION_GOOD]

    def __init__(self):
        super().__init__(configd=True)
        self.client = ConfigClient()

    async def get_config(self):
        weather_config = await self.client.get_async("nabweatherd")
        location = json.loads(weather_config["location"])
        latitude = str(location["lat"])
        longitude = str(location["lon"])

        cfg = await self.client.get_dict_async("nabairqualityd")
        return (
            cfg.next_performance_date,
            cfg.next_performance_type,
            (
                cfg.index_airquality,
                cfg.visual_airquality,
                latitude,
                longitude,
            ),
        )

    async def update_next(self, next_date, next_args):
        await self.client.set_async(
            "nabairqualityd",
            {
                "next_performance_date": next_date,
                "next_performance_type": next_args,
            },
        )

    async def fetch_info_data(self, config_t):
        if config_t is None:
            return None
        index_airquality, visual_airquality, latitude, longitude = config_t
        client = aqicn.aqicnClient(index_airquality, latitude, longitude)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, client.update)
        except Exception as err:
            logging.error(f"{err}")
            return None

        # Save inferred localization to configuration for display on web
        # interface
        cfg = await self.client.get_dict_async("nabairqualityd")
        city = client.get_city()
        if city != cfg.localisation:
            logging.info(
                f"location changed from: "
                f"{str(cfg.localisation)} to: {str(city)}"
            )
            await self.client.set_async(
                "nabairqualityd", {"localisation": city}
            )

        return {
            "visual_airquality": visual_airquality,
            "data": client.get_data(),
        }

    def get_animation(self, info_data):

        if (
            (info_data is None)
            or (info_data["visual_airquality"] == "nothing")
            or (
                info_data["visual_airquality"] == "alert"
                and info_data["data"] == 2
            )
        ):
            return None
        info_animation = NabAirqualityd.ANIMATIONS[info_data["data"]]
        return info_animation

    async def perform_additional(self, expiration, type, info_data, config_t):
        logging.info(f"perform_additional: type={type}, info_data={'None' if info_data is None else 'loaded'}")
        if info_data is None:
            logging.info("perform_additional: no data available")
            packet = (
                '{"type":"message",'
                '"signature":{"audio":["nabairqualityd/signature.mp3"]},'
                '"body":[{"audio":["nabairqualityd/no-data-error.mp3"]}],'
                '"expiration":"' + expiration.isoformat() + '"}\r\n'
            )
            self.writer.write(packet.encode("utf8"))
            await self.writer.drain()
        elif type == "today":
            cfg = await self.client.get_dict_async("nabairqualityd")
            logging.info(f"perform_additional: use_tts={cfg.use_tts}")
            message = NabAirqualityd.MESSAGES[info_data["data"]]
            if cfg.use_tts:
                locale_cfg = await self.client.get_async("nabd")
                user_locale = locale_cfg.get("locale", "fr_FR")
                with override(to_language(user_locale)):
                    text = _("Air quality: %(quality)s") % {"quality": _(message.capitalize())}
                audio = f"tts:{text}"
            else:
                audio = "nabairqualityd/" + message + ".mp3"
            packet = (
                '{"type":"message",'
                '"signature":{"audio":["nabairqualityd/signature.mp3"]},'
                '"body":[{"audio":["' + audio + '"]}],'
                '"expiration":"' + expiration.isoformat() + '"}\r\n'
            )
            self.writer.write(packet.encode("utf8"))
            await self.writer.drain()

    async def process_nabd_packet(self, packet):
        if (
            packet["type"] == "asr_event"
            and packet["nlu"]["intent"] == "nabairqualityd/forecast"
        ) or (
            packet["type"] == "rfid_event"
            and packet["app"] == "nabairqualityd"
            and packet["event"] == "detected"
        ):
            next_date, next_args, config_t = await self.get_config()
            now = datetime.datetime.now(datetime.timezone.utc)
            expiration = now + datetime.timedelta(minutes=1)
            await self.perform(expiration, "today", config_t)


if __name__ == "__main__":
    NabAirqualityd.main(sys.argv[1:])
