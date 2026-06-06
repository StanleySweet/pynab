import datetime
import logging
import sys

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabService

from . import rfid_data


class NabRadio(NabService):
    def __init__(self):
        super().__init__(configd=True)
        self.client = ConfigClient()

    async def reload_config(self):
        config = await self.client.get_async("nabradio")
        next_radio_date = config.get("next_radio_date")
        if next_radio_date is not None:
            now = datetime.datetime.now(datetime.timezone.utc)
            next_radio_url = config.get("next_radio_url", "")
            if next_radio_url:
                await self._launch_radio(next_radio_url)
            else:
                await self._stop_radio()
            await self.client.set_async(
                "nabradio",
                {"next_radio_date": None, "next_radio_url": ""},
            )

    async def _launch_radio(self, streaming_url):
        logging.info("streaming radio " + streaming_url)
        now = datetime.datetime.now(datetime.timezone.utc)
        expiration = now + datetime.timedelta(minutes=5)
        packet = (
            f'{{"type":"message",'
            f'"request_id":"nabradio",'
            f'"signature":{{"audio":["nabradio/*.mp3"]}},'
            f'"body":[{{"audio":["{streaming_url}"]}}],'
            f'"expiration":"{expiration.isoformat()}"}}\r\n'
        )
        self.writer.write(packet.encode("utf8"))
        await self.writer.drain()

    async def _stop_radio(self):
        packet = '{"type":"cancel","request_id":"nabradio"}\r\n'
        self.writer.write(packet.encode("utf8"))
        await self.writer.drain()

    async def process_nabd_packet(self, packet):
        if (
            packet["type"] == "rfid_event"
            and packet["app"] == "nabradio"
            and packet["event"] == "detected"
        ):
            streaming_url = await rfid_data.read_data_ui(packet["uid"])
            await self._launch_radio(streaming_url)


if __name__ == "__main__":
    NabRadio.main(sys.argv[1:])
