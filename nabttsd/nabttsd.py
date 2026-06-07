import asyncio
import ctypes
import json
import logging
import os
import sys

import alsaaudio
import websockets

from nabcommon.config_client import ConfigClient
from nabcommon.nabservice import NabService
from nabcommon.typing import NabdPacket

OPUS_SAMPLE_RATE = 24000
OPUS_FRAME_DURATION_MS = 20
OPUS_FRAME_SIZE = OPUS_SAMPLE_RATE * OPUS_FRAME_DURATION_MS // 1000
OPUS_PENDING_FILE = "/tmp/nabttsd_pending.json"


_libopus = None


def _get_libopus():
    global _libopus
    if _libopus is None:
        for name in ["libopus.so.0", "libopus.so"]:
            try:
                _libopus = ctypes.cdll.LoadLibrary(name)
                break
            except OSError:
                continue
        if _libopus is None:
            raise RuntimeError("libopus not found")
        _libopus.opus_decoder_create.argtypes = [
            ctypes.c_int32,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        _libopus.opus_decoder_create.restype = ctypes.c_void_p
        _libopus.opus_decode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int32,
            ctypes.c_int,
        ]
        _libopus.opus_decode.restype = ctypes.c_int
        _libopus.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        _libopus.opus_decoder_destroy.restype = None
        _libopus.opus_strerror.argtypes = [ctypes.c_int]
        _libopus.opus_strerror.restype = ctypes.c_char_p
    return _libopus


class NabTtsd(NabService):
    DAEMON_PIDFILE = "/run/nabttsd.pid"

    def __init__(self):
        super().__init__(configd=True)
        self.client = ConfigClient()
        self._speaking = False

    async def __config(self):
        return await self.client.get_async("nabttsd")

    async def reload_config(self):
        try:
            with open(OPUS_PENDING_FILE) as f:
                data = json.load(f)
            os.unlink(OPUS_PENDING_FILE)
            text = data.get("text", "")
            if text:
                logging.info("nabttsd: pending text: %s", text[:80])
                asyncio.ensure_future(
                    self.speak(
                        text,
                        data.get("engine", "piper"),
                        data.get("voice", "fr_FR-upmc-medium"),
                    )
                )
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.error(f"nabttsd: pending text error: {e}")

    async def process_nabd_packet(self, packet: NabdPacket):
        if "type" in packet:
            processors = {
                "asr_event": self.process_asr_event_packet,
                "rfid_event": self.process_rfid_event_packet,
                "config-update": self.process_config_update_packet,
            }
            if packet["type"] in processors:
                await processors[packet["type"]](packet)

    async def process_config_update_packet(self, packet):
        if packet.get("service") == "nabttsd":
            logging.info("nabttsd: config updated via configd")
            # Next speak() call will pick up the new values from configd

    async def process_asr_event_packet(self, packet):
        intent = packet.get("nlu", {}).get("intent", "")
        if intent == "nabttsd/speak":
            config = await self.__config()
            if config.get("enabled"):
                text = packet.get("nlu", {}).get("text", "")
                if text:
                    asyncio.ensure_future(
                        self.speak(text, config.get("engine"), config.get("voice"))
                    )

    async def process_rfid_event_packet(self, packet):
        if packet.get("app") == "nabttsd" and packet.get("event") == "detected":
            config = await self.__config()
            if config.get("enabled") and "data" in packet:
                text = packet["data"]
                asyncio.ensure_future(
                    self.speak(text, config.get("engine"), config.get("voice"))
                )

    async def _speak(self, text, engine, voice, addr, length_scale=1.5):
        uri = f"ws://{addr}/ws"
        logging.info("nabttsd: connecting to %s", uri)
        try:
            async with websockets.connect(uri) as ws:
                req = json.dumps(
                    {
                        "text": text,
                        "engine": engine,
                        "voice": voice,
                        "length_scale": length_scale,
                    }
                )
                await ws.send(req)
                msg = await ws.recv()
                meta = json.loads(msg)
                if meta.get("type") != "start":
                    logging.error(f"nabttsd: unexpected response: {meta}")
                    return
                logging.info("nabttsd: speech started")
                frames = []
                while True:
                    msg = await ws.recv()
                    if isinstance(msg, bytes):
                        frames.append(msg)
                    else:
                        ctrl = json.loads(msg)
                        if ctrl.get("type") == "done":
                            break
                        if ctrl.get("type") == "error":
                            logging.error(
                                f"nabttsd: tts error: {ctrl.get('message')}"
                            )
                            return
            if frames:
                logging.info("nabttsd: got %d frames, decoding+playing", len(frames))
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, self._decode_and_play, frames
                )
                logging.info("nabttsd: speech finished")
        except Exception as e:
            logging.error(f"nabttsd: websocket error: {e}")

    async def speak(self, text, engine="piper", voice="fr_FR-upmc-medium"):
        if self._speaking:
            logging.info("nabttsd: already speaking, skipping")
            return
        self._speaking = True
        try:
            config = await self.__config()
            addr = config.get("tts_addr")
            length_scale = config.get("length_scale", 1.5)
            await self._speak(text, engine, voice, addr, length_scale)
        except Exception as e:
            logging.error(f"nabttsd: speak error: {e}")
        finally:
            self._speaking = False

    def _decode_and_play(self, frames):
        opus = _get_libopus()
        err = ctypes.c_int()
        decoder = opus.opus_decoder_create(
            OPUS_SAMPLE_RATE, 1, ctypes.byref(err)
        )
        if err.value != 0:
            err_msg = opus.opus_strerror(err.value)
            logging.error(
                f"nabttsd: opus_decoder_create failed: "
                f"{err_msg.decode()}"
            )
            return
        try:
            pcm = alsaaudio.PCM(alsaaudio.PCM_PLAYBACK, device="default")
            pcm.setchannels(1)
            pcm.setrate(OPUS_SAMPLE_RATE)
            pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            pcm.setperiodsize(OPUS_FRAME_SIZE)
            buf = (ctypes.c_int16 * OPUS_FRAME_SIZE)()
            for frame_data in frames:
                cdata = (ctypes.c_uint8 * len(frame_data)).from_buffer_copy(
                    frame_data
                )
                ret = opus.opus_decode(
                    decoder,
                    cdata,
                    len(frame_data),
                    buf,
                    OPUS_FRAME_SIZE,
                    0,
                )
                if ret > 0:
                    pcm.write(ctypes.string_at(buf, ret * 2))
                elif ret < 0:
                    err_msg = opus.opus_strerror(ret)
                    logging.error(
                        f"nabttsd: opus_decode error: {err_msg.decode()}"
                    )
        except Exception as e:
            logging.error(f"nabttsd: playback error: {e}")
        finally:
            opus.opus_decoder_destroy(decoder)

    def run(self):
        super().connect()
        self.loop = asyncio.get_event_loop()
        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.writer.close()
            tasks = asyncio.all_tasks(self.loop)
            for t in [t for t in tasks if not (t.done() or t.cancelled())]:
                self.loop.run_until_complete(t)
            self.loop.close()


if __name__ == "__main__":
    NabTtsd.main(sys.argv[1:])
