import logging
import sys

import requests

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabService

from . import rfid_data


class NabIftttd(NabService):
    def __init__(self):
        super().__init__(configd=True)
        self.client = ConfigClient()
        self.__email = None

    async def reload_config(self):
        pass

    async def _call_ifttt(self, event_name, uid):
        config = await self.client.get_async("nabiftttd")

        key = config.get("ifttt_key", "")
        ifttt_url = (
            "https://maker.ifttt.com/trigger/"
            + event_name
            + "/with/key/"
            + key
            + "?value1="
            + uid
            + "&value2=❤️&value3=🐇"
        )
        redacted = ifttt_url.replace(key, "***") if key else ifttt_url
        logging.info("Calling IFTTT " + redacted)
        try:
            result = requests.get(ifttt_url, timeout=10)
            logging.info("IFTTT response: %s", result.reason)
        except Exception as e:
            logging.error("IFTTT error: %s", e)

    async def process_nabd_packet(self, packet):
        if (
            packet["type"] == "rfid_event"
            and packet["app"] == "nabiftttd"
            and packet["event"] == "detected"
        ):
            event_name = await rfid_data.read_data_ui(packet["uid"])
            await self._call_ifttt(event_name, packet["uid"])


if __name__ == "__main__":
    NabIftttd.main(sys.argv[1:])
