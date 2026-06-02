import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class MockedKaldiModel:
    def __init__(self, *args, **kwargs):
        pass


class MockedKaldiDecoder:
    def __init__(self, *args, **kwargs):
        self.decode = MagicMock()
        self.get_decoded_string = MagicMock(return_value=("hello", 0.5))


numpy_module = types.ModuleType("numpy")
numpy_module.array = MagicMock(return_value=MagicMock())
numpy_module.float32 = MagicMock()
sys.modules["numpy"] = numpy_module

kaldiasr_module = types.ModuleType("kaldiasr")
kaldiasr_nnet3_module = types.ModuleType("kaldiasr.nnet3")
kaldiasr_nnet3_module.KaldiNNet3OnlineModel = MockedKaldiModel
kaldiasr_nnet3_module.KaldiNNet3OnlineDecoder = MockedKaldiDecoder
sys.modules["kaldiasr"] = kaldiasr_module
sys.modules["kaldiasr.nnet3"] = kaldiasr_nnet3_module


class TestAsrDecodeChunk(unittest.TestCase):
    def setUp(self):
        from nabd.asr import ASR

        self.asr = ASR("fr_FR")
        self.asr.decoder.decode = MagicMock()
        self.asr.decoder.get_decoded_string = MagicMock(
            return_value=("hello", 0.5)
        )

    def test_decode_chunk_empty_frames_returns_early(self):
        with self.assertLogs(level="WARNING") as logs:
            self.asr._decode_chunk(b"", False)
        self.asr.decoder.decode.assert_not_called()
        self.assertTrue(
            any("No frames to decode" in msg for msg in logs.output)
        )

    def test_decode_chunk_single_byte_returns_early(self):
        with self.assertLogs(level="WARNING"):
            self.asr._decode_chunk(b"a", False)
        self.asr.decoder.decode.assert_not_called()

    def test_decode_chunk_two_bytes_calls_decode(self):
        with patch("nabd.asr.struct.unpack_from", return_value=[0]):
            self.asr._decode_chunk(b"\x00\x01", False)
        self.asr.decoder.decode.assert_called_once()

    def test_decode_chunk_four_bytes_calls_decode(self):
        with patch("nabd.asr.struct.unpack_from", return_value=[0, 0]):
            self.asr._decode_chunk(b"\x00\x01\x02\x03", False)
        self.asr.decoder.decode.assert_called_once()

    def test_decode_chunk_logs_error_on_exception(self):
        self.asr.decoder.decode.side_effect = Exception("test error")
        with self.assertLogs(level="ERROR") as logs:
            self.asr._decode_chunk(b"\x00\x01\x02\x03", False)
        self.assertTrue(
            any("test error" in msg for msg in logs.output)
        )

    def test_get_decoded_string_logs_error(self):
        self.asr.decoder.get_decoded_string.side_effect = Exception(
            "test error"
        )
        with self.assertLogs(level="ERROR") as logs:
            self.asr._get_decoded_string()
        self.assertTrue(
            any("test error" in msg for msg in logs.output)
        )


class TestASR(unittest.TestCase):
    def test_get_locale(self):
        from nabd.asr import ASR

        self.assertEqual("fr_FR", ASR.get_locale("fr_FR"))
        self.assertEqual("en_GB", ASR.get_locale("en_GB"))
        self.assertEqual("en_US", ASR.get_locale("en_US"))
        self.assertEqual("fr_FR", ASR.get_locale("de_DE"))

    def test_load_model_fr(self):
        from nabd.asr import ASR

        asr = ASR("fr_FR")
        self.assertIsNotNone(asr.model)
        self.assertIsNotNone(asr.decoder)
