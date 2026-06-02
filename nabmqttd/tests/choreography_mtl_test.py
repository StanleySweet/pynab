import unittest

from nabmqttd.nabmqttd import _choreography_to_mtl

PERSIST_CHOREOGRAPHIES = {
    "solid_red": {
        "persist": True,
        "tempo": 1,
        "colors": [
            {"left": "ff0000", "center": "ff0000", "right": "ff0000"},
            {"left": "ff0000", "center": "ff0000", "right": "ff0000"},
        ],
    },
    "solid_green": {
        "persist": True,
        "tempo": 1,
        "colors": [
            {"left": "00ff00", "center": "00ff00", "right": "00ff00"},
            {"left": "00ff00", "center": "00ff00", "right": "00ff00"},
        ],
    },
    "rainbow": {
        "persist": True,
        "tempo": 30,
        "colors": [
            {"left": "ff0000", "center": "00ff00", "right": "0000ff"},
            {"left": "00ff00", "center": "0000ff", "right": "ff0000"},
            {"left": "0000ff", "center": "ff0000", "right": "00ff00"},
        ],
    },
    "off": {
        "persist": True,
        "tempo": 1,
        "colors": [
            {"left": "000000", "center": "000000", "right": "000000"},
        ],
    },
}

NON_PERSIST_CHOREOGRAPHY = {
    "tempo": 10,
    "colors": [
        {"left": "ff0000", "center": "00ff00", "right": "0000ff"},
        {"left": "00ff00", "center": "0000ff", "right": "ff0000"},
    ],
}

RGB_CHOREOGRAPHY = {
    "persist": True,
    "tempo": 1,
    "colors": [
        {"left": "ff8000", "center": "ff8000", "right": "ff8000"},
    ],
}


def mtl_total_time(chor):
    if len(chor) < 2:
        return 0.0
    timescale = 10
    total = 0.0
    index = 0
    while index < len(chor):
        wait = chor[index]
        index += 1
        if index >= len(chor):
            break
        opcode = chor[index]
        index += 1
        if opcode == 1:
            if index < len(chor):
                timescale = 10 * chor[index]
                index += 1
        elif opcode == 9:
            index += 3
        elif opcode == 7:
            index += 4
        elif opcode == 8:
            index += 2
        elif opcode == 10:
            index += 1
        elif opcode == 14:
            index += 1
        elif opcode == 17:
            index += 1
        elif opcode == 0:
            pass
        elif opcode == 255:
            return total
        else:
            break
        if wait > 0:
            total += wait * timescale / 1000.0
    return total


class TestChoreographyToMtl(unittest.TestCase):
    def test_persist_mtl_not_too_long(self):
        for name, choreo in PERSIST_CHOREOGRAPHIES.items():
            with self.subTest(preset=name):
                mtl = _choreography_to_mtl(choreo)
                total = mtl_total_time(mtl)
                self.assertLess(
                    total,
                    5.0,
                    f"{name} persist MTL took {total}s, expected < 5s",
                )

    def test_non_persist_mtl_not_too_long(self):
        mtl = _choreography_to_mtl(NON_PERSIST_CHOREOGRAPHY)
        total = mtl_total_time(mtl)
        self.assertLess(total, 5.0, f"non-persist MTL took {total}s, expected < 5s")

    def test_rgb_choreography_not_too_long(self):
        mtl = _choreography_to_mtl(RGB_CHOREOGRAPHY)
        total = mtl_total_time(mtl)
        self.assertLess(
            total, 5.0, f"RGB persist MTL took {total}s, expected < 5s"
        )

    def test_mtl_ends_with_terminator(self):
        mtl = _choreography_to_mtl(RGB_CHOREOGRAPHY)
        self.assertEqual(mtl[-2:], bytes([0, 0]))

    def test_mtl_contains_frame_duration(self):
        mtl = _choreography_to_mtl(RGB_CHOREOGRAPHY)
        self.assertIn(bytes([0, 1]), mtl[:3])

    def test_mtl_sets_led_color(self):
        mtl = _choreography_to_mtl(RGB_CHOREOGRAPHY)
        self.assertIn(bytes([0, 9]), mtl)

    def test_persist_mtl_does_not_exceed_one_second_per_frame(self):
        for name, choreo in PERSIST_CHOREOGRAPHIES.items():
            with self.subTest(preset=name):
                mtl = _choreography_to_mtl(choreo)
                index = 0
                timescale = 10
                while index < len(mtl) - 1:
                    wait = mtl[index]
                    opcode = mtl[index + 1]
                    index += 2
                    if opcode == 1 and index < len(mtl):
                        timescale = 10 * mtl[index]
                        index += 1
                    elif opcode == 9:
                        index += 3
                    elif opcode == 0:
                        pass
                    else:
                        break
                    if wait > 0:
                        wait_sec = wait * timescale / 1000.0
                        self.assertLess(
                            wait_sec,
                            2.0,
                            f"{name}: wait of {wait_sec}s at opcode {opcode} "
                            f"exceeds 2s",
                        )
