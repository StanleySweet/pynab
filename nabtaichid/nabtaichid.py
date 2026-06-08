import datetime
import logging
import random
import sys

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabRandomService
from nabcommon.typing import NabdPacket


class NabTaichid(NabRandomService):
    DAEMON_PIDFILE = "/run/nabtaichid.pid"

    def __init__(self):
        super().__init__(configd=True)
        self.client = ConfigClient()
        self._nabd_asleep = False
        logging.info("nabtaichid: startup complete")

    async def get_config(self):
        config = await self.client.get_async("nabtaichid")
        return (config.get("next_taichi"), None, config.get("taichi_frequency", 30))

    async def update_next(self, next_date, next_args):
        await self.client.set_async(
            "nabtaichid", {"next_taichi": next_date}
        )

    async def perform(self, expiration, args, config):
        if self._nabd_asleep:
            logging.info("nabtaichid: rabbit asleep, skipping tai chi")
            return
        logging.info("nabtaichid: performing tai chi")
        packet = (
            '{"type":"command",'
            '"sequence":[{"choreography":"nabtaichid/taichi.chor"}],'
            '"expiration":"' + expiration.isoformat() + '"}\r\n'
        )
        self.writer.write(packet.encode("utf8"))
        await self.writer.drain()

    def compute_random_delta(self, frequency):
        return (256 - frequency) * 60 * (random.uniform(0, 255) + 64) / 128

    async def process_nabd_packet(self, packet: NabdPacket):
        if packet["type"] == "state":
            self._nabd_asleep = packet.get("state") == "asleep"
        if (
            packet["type"] == "asr_event"
            and packet["nlu"]["intent"] == "nabtaichid/taichi"
        ):
            if self._nabd_asleep:
                logging.info("nabtaichid: rabbit asleep, skipping ASR trigger")
                return
            logging.info("nabtaichid: ASR trigger")
            now = datetime.datetime.now(datetime.timezone.utc)
            expiration = now + datetime.timedelta(minutes=1)
            await self.perform(expiration, None, None)
        elif (
            packet["type"] == "rfid_event"
            and packet["app"] == "nabtaichid"
            and packet["event"] == "detected"
        ):
            if self._nabd_asleep:
                logging.info("nabtaichid: rabbit asleep, skipping RFID trigger")
                return
            logging.info("nabtaichid: RFID trigger")
            now = datetime.datetime.now(datetime.timezone.utc)
            expiration = now + datetime.timedelta(minutes=1)
            await self.perform(expiration, None, None)


if __name__ == "__main__":
    NabTaichid.main(sys.argv[1:])
