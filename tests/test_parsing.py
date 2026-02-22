import unittest

from cyberspace_cli.parsing import normalize_hex_32


class TestParsing(unittest.TestCase):
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
