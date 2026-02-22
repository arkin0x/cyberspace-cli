import unittest

from cyberspace_cli.parsing import normalize_hex_32, parse_destination_xyz_or_coord


class TestParsing(unittest.TestCase):
    def test_parse_destination_xyz(self) -> None:
        d = parse_destination_xyz_or_coord("1,2,3", default_plane=0)
        self.assertEqual((d.x, d.y, d.z, d.plane, d.kind), (1, 2, 3, 0, "xyz"))

        d2 = parse_destination_xyz_or_coord("1,2,3,1", default_plane=0)
        self.assertEqual((d2.x, d2.y, d2.z, d2.plane, d2.kind), (1, 2, 3, 1, "xyz"))

    def test_parse_destination_coord_hex(self) -> None:
        # Coordinate corresponds to xyz=(100,200,300, plane=0)
        d = parse_destination_xyz_or_coord("0x2b50e80", default_plane=1)
        self.assertEqual((d.x, d.y, d.z, d.plane, d.kind), (100, 200, 300, 0, "coord"))
    def test_normalize_hex_32_accepts_short(self) -> None:
        self.assertEqual(normalize_hex_32("0x1"), "0" * 63 + "1")
        self.assertEqual(normalize_hex_32("1"), "0" * 63 + "1")

    def test_normalize_hex_32_accepts_odd_length(self) -> None:
        # Odd-length hex should be accepted and padded to 64.
        self.assertEqual(normalize_hex_32("abc"), "0" * 61 + "abc")

    def test_normalize_hex_32_lowercases(self) -> None:
        self.assertEqual(normalize_hex_32("0xAB"), "0" * 62 + "ab")

    def test_normalize_hex_32_rejects_too_long(self) -> None:
        with self.assertRaises(ValueError):
            normalize_hex_32("0x" + "11" * 33)

    def test_normalize_hex_32_rejects_non_hex(self) -> None:
        with self.assertRaises(ValueError):
            normalize_hex_32("0xzz")


if __name__ == "__main__":
    unittest.main()
