import datetime
import logging
import random
import sys
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _, override

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabRandomService
from nabcommon.typing import NabdPacket

from . import rfid_data


class NabSurprised(NabRandomService):
    RARELY, SOMETIMES, OFTEN, VERY_OFTEN = 30, 50, 125, 250
    FREQUENCY_SECONDS = {
        RARELY: 10800,
        SOMETIMES: 7200,
        OFTEN: 3600,
        VERY_OFTEN: 1200,
    }

    NLU_INTENTS = [
        "nabsurprised/surprise",
        "nabsurprised/carrot",
        "nabsurprised/autopromo",
        "nabsurprised/birthday",
    ]

    def __init__(self):
        super().__init__(configd=True, translations=True)
        self.client = ConfigClient()
        self._nabd_asleep = False
        logging.info("nabsurprised: startup complete")

    async def get_config(self):
        cfg = await self.client.get_dict_async("nabsurprised")
        return (cfg.next_surprise, None, cfg.surprise_frequency)

    async def update_next(self, next_date, next_args):
        await self.client.set_async("nabsurprised", {"next_surprise": next_date})

    async def perform(self, expiration, args, config, *, force=False, **kwargs):
        if not force and self._nabd_asleep:
            logging.info("nabsurprised: rabbit asleep, skipping scheduled surprise")
            return
        await self._do_perform(expiration, **kwargs)

    def _tts_texts(self, message_type):
        texts = []
        for i in range(100):
            msgid = f"SURPRISE_{message_type}_{i}"
            text = _(msgid)
            if text == msgid:
                break
            texts.append(text)
        if not texts:
            fallback = _("SURPRISE_surprise_0")
            if fallback != "SURPRISE_surprise_0":
                texts = [fallback]
            else:
                texts = ["Surprise!"]
        return texts

    async def _do_perform(self, expiration, lang=None, message_type=None):
        logging.info("nabsurprised: performing surprise, message_type=%s", message_type)
        cfg = await self.client.get_async("nabsurprised")
        if cfg.get("use_tts"):
            if lang is None or lang == "default":
                lang = "fr_FR"
            with override(lang):
                texts = self._tts_texts(message_type)
                text = random.choice(texts)
            path = f"tts:{text}"
        else:
            if lang is None or lang == "default":
                lang_prefix = ""
            else:
                lang_prefix = lang + "/"
            if message_type is None:
                today = datetime.date.today()
                today_with_style = today.strftime("%m-%d")
                today_path = f"{lang_prefix}nabsurprised/{today_with_style}/*.mp3"
                regular_path = f"{lang_prefix}nabsurprised/*.mp3"
                path = today_path + ";" + regular_path
            else:
                if message_type == "surprise":
                    type_subdir = ""
                else:
                    type_subdir = message_type + "/"
                path = f"{lang_prefix}nabsurprised/{type_subdir}*.mp3"
        if expiration is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            expiration = now + datetime.timedelta(minutes=1)
        await self._send_to_nabd({
            "type": "message",
            "signature": {"audio": ["nabsurprised/respirations/*.mp3"]},
            "body": [{"audio": [path]}],
            "expiration": expiration.isoformat(),
        })

    async def _nabd_get_and_clear_force(self):
        try:
            cfg = await self.client.get_dict_async("nabsurprised")
            force = cfg.force_next_performance if hasattr(cfg, 'force_next_performance') else False
            if force:
                await self.client.set_async("nabsurprised", {"force_next_performance": False})
            return force
        except Exception:
            return False

    def compute_random_delta(self, frequency):
        if frequency == NabSurprised.VERY_OFTEN:
            return random.uniform(
                0, NabSurprised.FREQUENCY_SECONDS[NabSurprised.VERY_OFTEN]
            )  # nosec B311
        elif frequency == NabSurprised.OFTEN:
            return random.uniform(
                NabSurprised.FREQUENCY_SECONDS[NabSurprised.VERY_OFTEN],
                NabSurprised.FREQUENCY_SECONDS[NabSurprised.OFTEN],
            )  # nosec B311
        elif frequency == NabSurprised.SOMETIMES:
            return random.uniform(
                NabSurprised.FREQUENCY_SECONDS[NabSurprised.OFTEN],
                NabSurprised.FREQUENCY_SECONDS[NabSurprised.SOMETIMES],
            )  # nosec B311
        else:
            return random.uniform(
                NabSurprised.FREQUENCY_SECONDS[NabSurprised.SOMETIMES],
                NabSurprised.FREQUENCY_SECONDS[NabSurprised.RARELY],
            )  # nosec B311

    def compute_next(self, saved_date, saved_args, frequency, reason):
        next_t = super().compute_next(saved_date, saved_args, frequency, reason)
        if next_t is None:
            return None
        next_date, next_args = next_t
        adjusted = self._adjust_to_waking_hours(next_date)
        return (adjusted, next_args)

    def _adjust_to_waking_hours(self, dt):
        try:
            clock_cfg = self._read_clock_cfg()
            if clock_cfg is None:
                return dt
            if clock_cfg.get("sleep_wakeup_override") is True:
                return dt
            local_tz = ZoneInfo(self._read_system_tz())
            local_dt = dt.astimezone(local_tz)
            sleep_hour, sleep_min, wakeup_hour, wakeup_min = (
                self._get_sleep_schedule(clock_cfg, local_dt)
            )
            if None in (sleep_hour, sleep_min, wakeup_hour, wakeup_min):
                return dt
            current = (local_dt.hour, local_dt.minute)
            wakeup = (wakeup_hour, wakeup_min)
            sleep = (sleep_hour, sleep_min)
            if wakeup < sleep:
                is_sleeping = current < wakeup or current >= sleep
            else:
                is_sleeping = current < wakeup and current >= sleep
            if not is_sleeping:
                return dt
            wakeup_local = local_dt.replace(
                hour=wakeup_hour, minute=wakeup_min, second=0, microsecond=0
            )
            if wakeup_local <= local_dt:
                wakeup_local += datetime.timedelta(days=1)
            wakeup_utc = wakeup_local.astimezone(datetime.timezone.utc)
            return wakeup_utc + datetime.timedelta(
                seconds=random.uniform(1800, 7200)
            )
        except Exception:
            logging.debug("nabsurprised: _adjust_to_waking_hours failed", exc_info=True)
            return dt

    @staticmethod
    def _read_system_tz():
        try:
            with open("/etc/timezone") as f:
                return f.read().strip()
        except Exception:
            return "UTC"

    @staticmethod
    def _get_sleep_schedule(clock_cfg, local_dt):
        if clock_cfg.get("settings_per_day"):
            adjusted = local_dt - datetime.timedelta(hours=3)
            day = adjusted.strftime("%A").lower()
            wakeup_hour = clock_cfg.get(f"wakeup_hour_{day}")
            sleep_hour = clock_cfg.get(f"sleep_hour_{day}")
            wakeup_min = clock_cfg.get(f"wakeup_min_{day}")
            sleep_min = clock_cfg.get(f"sleep_min_{day}")
        else:
            wakeup_hour = clock_cfg.get("wakeup_hour")
            sleep_hour = clock_cfg.get("sleep_hour")
            wakeup_min = clock_cfg.get("wakeup_min")
            sleep_min = clock_cfg.get("sleep_min")
        return (sleep_hour, sleep_min, wakeup_hour, wakeup_min)

    @staticmethod
    def _read_clock_cfg():
        try:
            return ConfigClient().get_dict("nabclockd")
        except Exception:
            return None

    async def process_nabd_packet(self, packet: NabdPacket):
        if packet["type"] == "state":
            self._nabd_asleep = packet.get("state") == "asleep"
        if packet["type"] == "asr_event":
            intent = packet["nlu"]["intent"]
            if intent in NabSurprised.NLU_INTENTS:
                logging.info("nabsurprised: ASR trigger, intent=%s", intent)
                _, message_type = intent.split("/")
                now = datetime.datetime.now(datetime.timezone.utc)
                expiration = now + datetime.timedelta(minutes=1)
                await self.perform(expiration, None, None, message_type=message_type)
        elif (
            packet["type"] == "rfid_event"
            and packet["app"] == "nabsurprised"
            and packet["event"] == "detected"
        ):
            if "data" in packet:
                lang, message_type = rfid_data.unserialize(
                    packet["data"].encode("utf8")
                )
            else:
                lang = "default"
                message_type = "surprise"
            logging.info("nabsurprised: RFID trigger, message_type=%s, lang=%s", message_type, lang)
            now = datetime.datetime.now(datetime.timezone.utc)
            expiration = now + datetime.timedelta(minutes=1)
            await self.perform(expiration, None, None, force=True, lang=lang, message_type=message_type)


if __name__ == "__main__":
    NabSurprised.main(sys.argv[1:])
