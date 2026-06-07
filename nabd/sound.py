import abc
import asyncio
import ctypes
import json
import logging
import wave

import websockets

from .resources import Resources

OPUS_SAMPLE_RATE = 24000
OPUS_FRAME_SIZE = 480


def _get_libopus():
    libopus = ctypes.cdll.LoadLibrary("libopus.so.0")
    libopus.opus_decoder_create.argtypes = [
        ctypes.c_int32,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
    ]
    libopus.opus_decoder_create.restype = ctypes.c_void_p
    libopus.opus_decode.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int16),
        ctypes.c_int32,
        ctypes.c_int,
    ]
    libopus.opus_decode.restype = ctypes.c_int
    libopus.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
    libopus.opus_decoder_destroy.restype = None
    return libopus


class Sound(object, metaclass=abc.ABCMeta):
    """Interface for sound"""

    async def _tts_config(self):
        from nabcommon.config_client import ConfigClient
        client = ConfigClient()
        cfg = await client.get_async("nabttsd")
        return (
            cfg.get("tts_addr", "pi4.local:8765"),
            cfg.get("length_scale", 1.5),
        )

    async def preload(self, audio_resource):
        if audio_resource.startswith("tts:"):
            text = audio_resource[4:]
            logging.info("TTS preload: text='%s'", text[:80])
            if not text:
                logging.warning("TTS preload: empty text")
                return None
            addr, length_scale = await self._tts_config()
            uri = f"ws://{addr}/ws"
            logging.info("TTS preload: connecting to %s", uri)
            try:
                async with websockets.connect(uri) as ws:
                    req = json.dumps(
                        {
                            "text": text,
                            "engine": "piper",
                            "voice": "default",
                            "length_scale": length_scale,
                        }
                    )
                    await ws.send(req)
                    msg = await ws.recv()
                    meta = json.loads(msg)
                    if meta.get("type") != "start":
                        logging.warning(
                            "TTS preload: unexpected response %s", meta
                        )
                        return None
                    logging.info("TTS speech started, sample_rate=%s", meta.get("sample_rate"))
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
                                    "TTS error: %s",
                                    ctrl.get("message"),
                                )
                                return None
            except Exception as e:
                logging.error("TTS WebSocket error: %s", e)
                return None
            if not frames:
                logging.warning("TTS preload: no frames received")
                return None
            logging.info(
                "TTS preload: got %d frames, decoding to WAV", len(frames)
            )
            loop = asyncio.get_event_loop()
            tts_path = await loop.run_in_executor(
                None, self._decode_opus_to_wav, frames
            )
            logging.info("TTS speech finished, WAV at %s", tts_path)
            return tts_path
        logging.debug("preload: %s", audio_resource)
        if audio_resource.startswith("https://") or audio_resource.startswith(
            "http://"
        ):
            return audio_resource
        file = await Resources.find("sounds", audio_resource)
        if file is not None:
            return file.as_posix()
        logging.warning("could not find resource %s", audio_resource)
        return None

    def _decode_opus_to_wav(self, frames):
        libopus = _get_libopus()
        err = ctypes.c_int()
        decoder = libopus.opus_decoder_create(
            OPUS_SAMPLE_RATE, 1, ctypes.byref(err)
        )
        if err.value != 0:
            logging.error("Opus decoder create failed: %s", err.value)
            return None
        tts_path = "/tmp/nabttsd_tts.wav"
        total_samples = 0
        try:
            with wave.open(tts_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(OPUS_SAMPLE_RATE)
                buf = (ctypes.c_int16 * OPUS_FRAME_SIZE)()
                for i, frame_data in enumerate(frames):
                    cdata = (
                        ctypes.c_uint8 * len(frame_data)
                    ).from_buffer_copy(frame_data)
                    ret = libopus.opus_decode(
                        decoder, cdata, len(frame_data), buf, OPUS_FRAME_SIZE, 0
                    )
                    if ret > 0:
                        wf.writeframes(ctypes.string_at(buf, ret * 2))
                        total_samples += ret
        except Exception as e:
            logging.error("Opus decode error: %s", e)
            return None
        finally:
            libopus.opus_decoder_destroy(decoder)
        duration = total_samples / OPUS_SAMPLE_RATE
        logging.info("TTS decode: %d frames, %d samples, %.1f sec", len(frames), total_samples, duration)
        return tts_path

    async def play_list(self, filenames, preloaded, event=None):
        preloaded_list = []
        if preloaded:
            preloaded_list = filenames
        else:
            for filename in filenames:
                preloaded_file = await self.preload(filename)
                if preloaded_file is not None:
                    preloaded_list.append(preloaded_file)
        await self.stop_playing()
        for filename in preloaded_list:
            await self.start_playing_preloaded(filename)
            await self.wait_until_done(event)

    async def start_playing(self, audio_resource):
        preloaded = await self.preload(audio_resource)
        if preloaded is not None:
            await self.start_playing_preloaded(preloaded)

    @abc.abstractmethod
    async def start_playing_preloaded(self, filename):
        """
        Start to play a given sound.
        Stop currently playing sound if any.
        """
        raise NotImplementedError("Should have implemented")

    @abc.abstractmethod
    async def wait_until_done(self, event=None):
        """
        Wait until sound has been played or event is fired.
        """
        raise NotImplementedError("Should have implemented")

    @abc.abstractmethod
    async def stop_playing(self):
        """
        Stop currently playing sound.
        """
        raise NotImplementedError("Should have implemented")

    @abc.abstractmethod
    async def start_recording(self, stream_cb):
        """
        Start recording sound.
        Invokes stream_cb repeatedly with recorded samples.
        """
        raise NotImplementedError("Should have implemented")

    @abc.abstractmethod
    async def stop_recording(self):
        """
        Stop recording sound.
        Invokes stream_cb with finalize set to true.
        """
        raise NotImplementedError("Should have implemented")
