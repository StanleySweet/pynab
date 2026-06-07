import datetime
import json
import logging
import os
import random
import sys

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
        logging.info("nabsurprised: startup complete")

    async def get_config(self):
        cfg = await self.client.get_dict_async("nabsurprised")
        return (cfg.next_surprise, None, cfg.surprise_frequency)

    async def update_next(self, next_date, next_args):
        await self.client.set_async("nabsurprised", {"next_surprise": next_date})

    async def perform(self, expiration, args, config):
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

    async def process_nabd_packet(self, packet: NabdPacket):
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
