import asyncio
import logging
import random
import sys

from django.utils.translation import gettext as _, override, to_language

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabService
from nabcommon.typing import NabdPacket

from . import rfid_data


ANSWERS = [
    "go for it",
    "but it's so obvious",
    "definitely but have a little fun",
    "be sure not to make any waves",
    "well I wouldn't bet on that",
    "stop wasting time",
    "don't be ridiculous",
    "haste makes waste",
    "think of it as a long-term investment",
    "change your approach",
    "take a step back and see what awaits you",
    "avoid getting all happy",
    "prepare yourself for a few nasty repercussions",
    "not just yet wait a little",
    "yes",
    "no",
    "yes or maybe no",
    "that's for sure",
    "never",
    "indubitably",
]


class Nab8Balld(NabService):
    DAEMON_PIDFILE = "/run/nab8balld.pid"

    def __init__(self):
        super().__init__(configd=True, translations=True)
        self._interactive = False
        self._timeout_task = None
        self.client = ConfigClient()
        logging.info("nab8balld: startup complete")

    async def __config(self):
        return await self.client.get_async("nab8balld")

    async def reload_config(self):
        await self.setup_listener()

    async def setup_listener(self):
        config = await self.__config()
        if config.get("enabled"):
            packet = (
                ""
                '{"type":"mode","mode":"idle",'
                '"events":["button","asr/nab8balld","rfid/nab8balld"],'
                '"request_id":"idle-button"}\r\n'
            )
        else:
            packet = (
                '{"type":"mode","mode":"idle",'
                '"events":["asr/nab8balld","rfid/nab8balld"],'
                '"request_id":"idle-disabled"}\r\n'
            )
        self.writer.write(packet.encode("utf8"))

    async def perform(self, lang):
        logging.info("nab8balld: performing answer, lang=%s", lang)
        config = await self.__config()
        if config.get("use_tts"):
            answer = random.choice(ANSWERS)
            locale = lang if lang and lang != "default" else None
            if locale:
                with override(to_language(locale)):
                    text = _(answer)
            else:
                text = _(answer)
            path = f"tts:{text}"
        else:
            if lang is None or lang == "default":
                lang_prefix = ""
            else:
                lang_prefix = lang + "/"
            path = f"{lang_prefix}nab8balld/answers/*.mp3"
        packet = (
            f'{{"type":"message",'
            f'"body":[{{"audio":["{path}"]}}],'
            f'"request_id":"play-answer"}}\r\n'
        )
        self.writer.write(packet.encode("utf8"))
        await self.writer.drain()

    async def process_nabd_packet(self, packet: NabdPacket):
        if "type" in packet:
            processors = {
                "button_event": self.process_button_event_packet,
                "asr_event": self.process_asr_event_packet,
                "rfid_event": self.process_rfid_event_packet,
                "response": self.process_response_packet,
            }
            if packet["type"] in processors:
                await processors[packet["type"]](packet)

    async def process_button_event_packet(self, packet):
        if not self._interactive:
            if packet["event"] == "click_and_hold":
                logging.info("nab8balld: button click_and_hold, entering interactive")
                await self.enter_interactive()
                self._timeout_task = asyncio.ensure_future(self.timeout_job())
        else:
            if packet["event"] == "up":
                logging.info("nab8balld: button up, exiting interactive")
                if self._timeout_task:
                    self._timeout_task.cancel()
                    self._timeout_task = None
                await self.exit_interactive()

    async def enter_interactive(self):
        logging.info("nab8balld: entering interactive mode")
        packet = (
            '{"type":"mode","mode":"interactive",'
            '"events":["button"],'
            '"request_id":"set-interactive"}\r\n'
        )
        self.writer.write(packet.encode("utf8"))
        await self.writer.drain()

    async def entered_interactive(self):
        logging.info("nab8balld: interactive mode confirmed")
        self._interactive = True
        resp = (
            '{"type":"command",'
            '"sequence":[{"audio":["nab8balld/listen.mp3"],'
            '"choreography":"data:application/x-nabaztag-mtl-choreography;'
            'base64,AAcA/wD/AAAABwEAAAAAAAAHAgAAAAAAAAcDAAAAAAA="'
            "}],"
            '"request_id":"play-listen"}\r\n'
        )
        self.writer.write(resp.encode("utf8"))
        await self.writer.drain()

    async def exit_interactive(self):
        logging.info("nab8balld: exiting interactive mode")
        packet = (
            '{"type":"command",'
            '"sequence":[{"audio":["nab8balld/acquired.mp3"]}],'
            '"request_id":"play-acquired"}\r\n'
        )
        self.writer.write(packet.encode("utf8"))
        await self.perform(None)
        self._interactive = False
        await self.setup_listener()

    async def timeout_job(self):
        logging.info("nab8balld: interactive timeout")
        await asyncio.sleep(10)
        self._timeout_task = None
        self.exit_interactive()

    async def process_response_packet(self, packet):
        if (
            "request_id" in packet
            and packet["request_id"] == "set-interactive"
        ):
            await self.entered_interactive()

    async def process_asr_event_packet(self, packet):
        if packet["nlu"]["intent"] == "nab8balld/8ball":
            logging.info("nab8balld: ASR trigger")
            await self.perform(None)

    async def process_rfid_event_packet(self, packet):
        if packet["app"] == "nab8balld" and packet["event"] == "detected":
            if "data" in packet:
                lang = rfid_data.unserialize(packet["data"].encode("utf8"))
            else:
                lang = "default"
            logging.info("nab8balld: RFID trigger, lang=%s", lang)
            await self.perform(lang)

    def run(self):
        super().connect()
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.setup_listener())
        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False  # signal to exit
            self.writer.close()
            tasks = asyncio.all_tasks(self.loop)
            for t in [t for t in tasks if not (t.done() or t.cancelled())]:
                # give canceled tasks the last chance to run
                self.loop.run_until_complete(t)
            self.loop.close()


if __name__ == "__main__":
    Nab8Balld.main(sys.argv[1:])
