import logging
import os
import sys
from pathlib import Path

from nabcommon.nabservice import NabService
from nabcommon.typing import NabdPacket

from . import rfid_data


class NabBookd(NabService):
    def __init__(self):
        super().__init__(configd=True)
        self.__isbn = None
        self.__voice = None
        self.__current_chapter = None
        self.__state_handler = self.process_nabd_packet_idle

    async def reload_config(self):
        pass

    def has_more_voices(self, isbn):
        nabbookd_root = os.path.dirname(__file__)
        bookdir = Path(f"{nabbookd_root}/sounds/nabbookd/books/{isbn}")
        count_voices = 0
        for voicedir in bookdir.iterdir():
            if not voicedir.is_dir():
                continue
            count_voices = count_voices + 1
        return count_voices > 1

    async def next_chapter(self):
        if self.__current_chapter is None:
            chapter = 1
        else:
            chapter = self.__current_chapter + 1
        self.__current_chapter = chapter
        isbn = self.__isbn
        voice = self.__voice
        nabbookd_root = os.path.dirname(__file__)
        relpath = f"nabbookd/books/{isbn}/{voice}/{chapter}.mp3"
        next_file = f"{nabbookd_root}/sounds/{relpath}"
        if os.path.isfile(next_file):
            await self._send_to_nabd({
                "type": "command",
                "sequence": [{"audio": relpath}],
                "request_id": "reading",
            })
        else:
            if self.has_more_voices(isbn):
                outro = "outro-alt"
            else:
                outro = "outro-noalt"
            self.__state_handler = self.process_nabd_packet_outro
            await self._send_to_nabd({
                "type": "command",
                "sequence": [{"audio": f"nabbookd/{outro}.mp3",
                               "choreography": f"nabbookd/{outro}.chor"}],
                "request_id": "outro",
            })

    async def process_nabd_packet(self, packet: NabdPacket):
        await self.__state_handler(packet)

    async def process_nabd_packet_idle(self, packet):
        type = packet["type"]
        if type == "state" and packet["state"] != "idle":
            self.__state_handler = self.process_nabd_packet_busy
        elif type == "state":
            pass
        elif (
            type == "rfid_event"
            and packet["app"] == "nabbookd"
            and packet["event"] == "detected"
            and "data" in packet
        ):
            self.__state_handler = self.process_nabd_packet_start_interactive
            self.__voice, self.__isbn = rfid_data.unserialize(
                packet["data"].encode()
            )
            self.__current_chapter = None
            await self._send_to_nabd({
                "type": "mode",
                "mode": "interactive",
                "events": ["button", "ears"],
                "request_id": "mode",
            })
        elif type == "response":
            # Ignore responses, as we can transition to idle state with several
            # messages (cancel/abort sound, etc.)
            pass
        else:
            logging.debug(f"[idle] Unknown packet {packet}")

    async def process_nabd_packet_busy(self, packet: NabdPacket):
        if packet["type"] == "state" and packet["state"] == "idle":
            self.__state_handler = self.process_nabd_packet_idle
        elif type == "state":
            pass
        else:
            logging.debug(f"[busy] Unknown packet {packet}")

    async def process_nabd_packet_start_interactive(self, packet: NabdPacket):
        if packet["type"] == "state":
            pass
        elif (
            packet["type"] == "response"
            and packet.get("status") == "ok"
            and packet.get("request_id") == "mode"
        ):
            self.__state_handler = self.process_nabd_packet_intro
            await self._send_to_nabd({
                "type": "command",
                "sequence": [{"audio": "nabbookd/intro.mp3",
                              "choreography": "nabbookd/intro.chor"}],
                "request_id": "intro",
            })
        elif packet["type"] == "button_event" and packet["event"] == "click":
            self.__state_handler = self.process_nabd_packet_idle
            await self.exit_interactive(True)
        elif packet["type"] == "button_event":
            pass
        else:
            logging.debug(f"[start_interactive] Unknown packet {packet}")

    async def process_nabd_packet_intro(self, packet: NabdPacket):
        if packet["type"] == "state":
            pass
        elif (
            packet["type"] == "response"
            and packet.get("status") == "ok"
            and packet.get("request_id") == "intro"
        ):
            # Chapter was selected when reading the tag
            self.__state_handler = self.process_nabd_packet_reading
            await self.next_chapter()
        elif packet["type"] == "button_event" and packet["event"] == "click":
            self.__state_handler = self.process_nabd_packet_idle
            await self.cancel_command("intro")
            await self.exit_interactive(True)
        elif packet["type"] == "button_event":
            pass
        else:
            logging.debug(f"[intro] Unknown packet {packet}")

    async def process_nabd_packet_reading(self, packet: NabdPacket):
        if (
            packet["type"] == "response"
            and packet.get("status") == "ok"
            and packet.get("request_id") == "reading"
        ):
            await self.next_chapter()
        elif packet["type"] == "button_event" and packet["event"] == "click":
            await self.cancel_command("reading")
            self.__state_handler = self.process_nabd_packet_outro
            await self._send_to_nabd({
                "type": "command",
                "sequence": [{"audio": "nabd/abort.wav"},
                             {"audio": "nabbookd/interrupt.mp3",
                              "choreography": "nabbookd/interrupt.chor"}],
                "request_id": "outro",
            })
        elif packet["type"] == "button_event":
            pass
        elif packet["type"] == "ear_event" and packet["ear"] == "left":
            self.__state_handler = self.process_nabd_packet_backward
            await self.cancel_command("reading")
        elif packet["type"] == "ear_event" and packet["ear"] == "right":
            self.__state_handler = self.process_nabd_packet_forward
            await self.cancel_command("reading")
        else:
            logging.debug(f"[reading] Unknown packet {packet}")

    async def process_nabd_packet_backward(self, packet: NabdPacket):
        if (
            packet["type"] == "response"
            and packet.get("request_id") == "reading"
        ):
            await self._send_to_nabd({
                "type": "command",
                "sequence": [{"audio": "nabbookd/previous.mp3"}],
                "request_id": "feedback",
            })
        elif (
            packet["type"] == "response"
            and "request_id" in packet
            and packet["request_id"] == "feedback"
        ):
            self.__current_chapter = self.__current_chapter - 2
            if self.__current_chapter < 0:
                self.__current_chapter = 0
            self.__state_handler = self.process_nabd_packet_reading
            await self.next_chapter()
        elif packet["type"] == "ear_event":
            pass
        else:
            logging.debug(f"[backward] Unknown packet {packet}")

    async def process_nabd_packet_forward(self, packet: NabdPacket):
        if (
            packet["type"] == "response"
            and packet.get("request_id") == "reading"
        ):
            await self._send_to_nabd({
                "type": "command",
                "sequence": [{"audio": "nabbookd/next.mp3"}],
                "request_id": "feedback",
            })
        elif (
            packet["type"] == "response"
            and "request_id" in packet
            and packet["request_id"] == "feedback"
        ):
            self.__state_handler = self.process_nabd_packet_reading
            await self.next_chapter()
        elif packet["type"] == "ear_event":
            pass
        else:
            logging.debug(f"[forward] Unknown packet {packet}")

    async def process_nabd_packet_outro(self, packet: NabdPacket):
        if packet["type"] == "response" and packet.get("status") == "canceled":
            pass
        elif (
            packet["type"] == "response"
            and packet.get("status") == "ok"
            and packet.get("request_id") == "outro"
        ):
            self.__state_handler = self.process_nabd_packet_idle
            await self.exit_interactive(False)
        elif packet["type"] == "button_event" and packet["event"] == "click":
            self.__state_handler = self.process_nabd_packet_idle
            await self.cancel_command("outro")
            await self.exit_interactive(True)
        elif packet["type"] == "button_event":
            pass
        else:
            logging.debug(f"[outro] Unknown packet {packet}")


if __name__ == "__main__":
    NabBookd.main(sys.argv[1:])
