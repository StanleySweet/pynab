import abc
import asyncio
import ctypes
import json
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

    async def _tts_addr(self):
        from nabttsd.models import Config as TtsConfig
        cfg = await TtsConfig.load_async()
        return cfg.tts_addr

    async def preload(self, audio_resource):
        if audio_resource.startswith("tts:"):
            text = audio_resource[4:]
            if not text:
                return None
            addr = await self._tts_addr()
            uri = f"ws://{addr}/ws"
            try:
                async with websockets.connect(uri) as ws:
                    req = json.dumps(
                        {
                            "text": text,
                            "engine": "piper",
                            "voice": "default",
                        }
                    )
                    await ws.send(req)
                    msg = await ws.recv()
                    meta = json.loads(msg)
                    if meta.get("type") != "start":
                        return None
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
                                print(
                                    "TTS error: "
                                    f"{ctrl.get('message')}"
                                )
                                return None
            except Exception as e:
                print(f"TTS WebSocket error: {e}")
                return None
            if not frames:
                return None
            loop = asyncio.get_event_loop()
            tts_path = await loop.run_in_executor(
                None, self._decode_opus_to_wav, frames
            )
            return tts_path
        if audio_resource.startswith("https://") or audio_resource.startswith(
            "http://"
        ):
            return audio_resource
        file = await Resources.find("sounds", audio_resource)
        if file is not None:
            return file.as_posix()
        print(f"Warning : could not find resource {audio_resource}")
        return None

    def _decode_opus_to_wav(self, frames):
        libopus = _get_libopus()
        err = ctypes.c_int()
        decoder = libopus.opus_decoder_create(
            OPUS_SAMPLE_RATE, 1, ctypes.byref(err)
        )
        if err.value != 0:
            print(f"Opus decoder create failed: {err.value}")
            return None
        tts_path = "/tmp/nabttsd_tts.wav"
        try:
            with wave.open(tts_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(OPUS_SAMPLE_RATE)
                buf = (ctypes.c_int16 * OPUS_FRAME_SIZE)()
                for frame_data in frames:
                    cdata = (
                        ctypes.c_uint8 * len(frame_data)
                    ).from_buffer_copy(frame_data)
                    ret = libopus.opus_decode(
                        decoder, cdata, len(frame_data), buf, OPUS_FRAME_SIZE, 0
                    )
                    if ret > 0:
                        wf.writeframes(bytes(buf[:ret]))
        except Exception as e:
            print(f"Opus decode error: {e}")
            return None
        finally:
            libopus.opus_decoder_destroy(decoder)
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
