import unittest

from nabmqttd.nabmqttd import (
    _build_device_info,
    _choreography_to_mtl,
    _CHOREOGRAPHIES,
    _rgb_to_choreography,
)


class TestBuildDeviceInfo(unittest.TestCase):
    def test_device_name_is_nabaztag(self):
        info = _build_device_info("nabaztag_abc123")
        self.assertEqual(info["name"], "Nabaztag")

    def test_device_info_contains_device_id(self):
        info = _build_device_info("nabaztag_abc123")
        self.assertIn("nabaztag_abc123", info["identifiers"])

    def test_device_info_has_required_keys(self):
        info = _build_device_info("nabaztag_abc123")
        self.assertIn("name", info)
        self.assertIn("model", info)
        self.assertIn("manufacturer", info)
        self.assertIn("sw_version", info)


class TestRgbToChoreography(unittest.TestCase):
    def test_returns_persist_true(self):
        choreo = _rgb_to_choreography(255, 128, 64)
        self.assertTrue(choreo["persist"])

    def test_returns_single_color(self):
        choreo = _rgb_to_choreography(255, 128, 64)
        self.assertEqual(len(choreo["colors"]), 1)

    def test_color_format(self):
        choreo = _rgb_to_choreography(255, 128, 64)
        color = choreo["colors"][0]
        self.assertEqual(color["left"], "ff8040")
        self.assertEqual(color["center"], "ff8040")
        self.assertEqual(color["right"], "ff8040")

    def test_brightness_applied(self):
        choreo = _rgb_to_choreography(255, 255, 255, brightness=128)
        color = choreo["colors"][0]
        self.assertEqual(color["left"], "808080")
        self.assertEqual(color["center"], "808080")
        self.assertEqual(color["right"], "808080")

    def test_zero_brightness_black(self):
        choreo = _rgb_to_choreography(255, 255, 255, brightness=0)
        color = choreo["colors"][0]
        self.assertEqual(color["left"], "000000")


class TestChoreographyOffPreset(unittest.TestCase):
    def test_off_has_persist(self):
        self.assertTrue(_CHOREOGRAPHIES["off"]["persist"])

    def test_off_has_single_color(self):
        self.assertEqual(len(_CHOREOGRAPHIES["off"]["colors"]), 1)

    def test_off_color_is_black(self):
        color = _CHOREOGRAPHIES["off"]["colors"][0]
        self.assertEqual(color["left"], "000000")
        self.assertEqual(color["center"], "000000")
        self.assertEqual(color["right"], "000000")


class TestChoreographyToMtlPersistSingleColor(unittest.TestCase):
    def test_persist_mtl_starts_with_header(self):
        choreo = {
            "persist": True,
            "tempo": 1,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "ff0000",
                    "right": "ff0000",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertEqual(mtl[:3], bytes([0, 1, 1]))

    def test_persist_mtl_ends_with_terminator(self):
        choreo = {
            "persist": True,
            "tempo": 1,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "ff0000",
                    "right": "ff0000",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertEqual(mtl[-2:], bytes([0, 0]))

    def test_persist_mtl_contains_led_opcode(self):
        choreo = {
            "persist": True,
            "tempo": 1,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "00ff00",
                    "right": "0000ff",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertIn(bytes([0, 9]), mtl)

    def test_persist_mtl_uses_first_color_only(self):
        choreo = {
            "persist": True,
            "tempo": 1,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "00ff00",
                    "right": "0000ff",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertIn(bytes([0, 9, 255, 0, 0]), mtl)

    def test_persist_mtl_no_colors_defaults_black(self):
        choreo = {"persist": True, "tempo": 1, "colors": []}
        mtl = _choreography_to_mtl(choreo)
        self.assertIn(bytes([0, 9, 0, 0, 0]), mtl)

    def test_persist_mtl_without_persist_key_is_non_persist(self):
        choreo = {
            "tempo": 10,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "00ff00",
                    "right": "0000ff",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertEqual(mtl[:3], bytes([0, 1, 10]))


class TestNonPersistMtlFormat(unittest.TestCase):
    def test_non_persist_mtl_starts_with_header(self):
        choreo = {
            "tempo": 10,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "00ff00",
                    "right": "0000ff",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertEqual(mtl[:3], bytes([0, 1, 10]))

    def test_non_persist_mtl_ends_with_terminator(self):
        choreo = {
            "tempo": 10,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "00ff00",
                    "right": "0000ff",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertEqual(mtl[-2:], bytes([0, 0]))

    def test_non_persist_mtl_contains_color_frames(self):
        choreo = {
            "tempo": 10,
            "colors": [
                {
                    "left": "ff0000",
                    "center": "00ff00",
                    "right": "0000ff",
                },
                {
                    "left": "00ff00",
                    "center": "0000ff",
                    "right": "ff0000",
                },
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertIn(bytes([0, 9, 255, 0, 0]), mtl)
        self.assertIn(bytes([0, 9, 0, 255, 0]), mtl)

    def test_non_persist_mtl_parts_is_defined_in_non_persist_branch(self):
        choreo = {
            "tempo": 5,
            "colors": [
                {
                    "left": "ffffff",
                    "center": "ffffff",
                    "right": "ffffff",
                }
            ],
        }
        mtl = _choreography_to_mtl(choreo)
        self.assertEqual(mtl[:3], bytes([0, 1, 5]))
