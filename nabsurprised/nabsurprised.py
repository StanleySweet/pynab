import datetime
import json
import logging
import os
import random
import sys
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _, override, to_language

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabRandomService
from nabcommon.typing import NabdPacket

from . import rfid_data


def _load_answers():
    path = os.path.join(os.path.dirname(__file__), "answers_text.json")
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
            logging.info(
                "nabsurprised: loaded %d locales from answers_text.json", len(data)
            )
            return data
    logging.warning("nabsurprised: answers_text.json not found, MP3 fallback only")
    return {}


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
        self._answers = _load_answers()
        self._nabd_asleep = False
        logging.info("nabsurprised: startup complete")

    async def get_config(self):
        cfg = await self.client.get_dict_async("nabsurprised")
        return (cfg.next_surprise, None, cfg.surprise_frequency)

    async def update_next(self, next_date, next_args):
        await self.client.set_async("nabsurprised", {"next_surprise": next_date})

    async def perform(self, expiration, args, config):
        if self._nabd_asleep:
            logging.info("nabsurprised: rabbit asleep, skipping scheduled surprise")
            return
        await self._do_perform(expiration, None, None)

    async def _do_perform(self, expiration, lang, type):
        logging.info("nabsurprised: performing surprise, type=%s", type)
        cfg = await self.client.get_async("nabsurprised")
        if cfg.get("use_tts"):
            if lang is None or lang == "default":
                lang = "fr_FR"
            locale_answers = self._answers.get(lang, {})
            texts = locale_answers.get(type) or locale_answers.get(
                "surprise", ["Surprise!"]
            )
            text = random.choice(texts)
            path = f"tts:{text}"
        else:
            if lang is None or lang == "default":
                lang_prefix = ""
            else:
                lang_prefix = lang + "/"
            if type is None:
                today = datetime.date.today()
                today_with_style = today.strftime("%m-%d")
                today_path = f"{lang_prefix}nabsurprised/{today_with_style}/*.mp3"
                regular_path = f"{lang_prefix}nabsurprised/*.mp3"
                path = today_path + ";" + regular_path
            else:
                if type == "surprise":
                    type_subdir = ""
                else:
                    type_subdir = type + "/"
                path = f"{lang_prefix}nabsurprised/{type_subdir}*.mp3"
        if expiration is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            expiration = now + datetime.timedelta(minutes=1)
        packet = (
            f'{{"type":"message",'
            f'"signature":{{"audio":["nabsurprised/respirations/*.mp3"]}},'
            f'"body":[{{"audio":["{path}"]}}],'
            f'"expiration":"{expiration.isoformat()}"}}\r\n'
        )
        self.writer.write(packet.encode("utf8"))
        await self.writer.drain()

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
                _, type = intent.split("/")
                await self._do_perform(None, None, type)
        elif (
            packet["type"] == "rfid_event"
            and packet["app"] == "nabsurprised"
            and packet["event"] == "detected"
        ):
            if "data" in packet:
                lang, type = rfid_data.unserialize(
                    packet["data"].encode("utf8")
                )
            else:
                lang = "default"
                type = "surprise"
            logging.info("nabsurprised: RFID trigger, type=%s, lang=%s", type, lang)
            await self._do_perform(None, lang, type)


if __name__ == "__main__":
    NabSurprised.main(sys.argv[1:])
