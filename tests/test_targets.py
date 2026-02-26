import unittest

from cyberspace_cli.state import CyberspaceState, STATE_VERSION
from cyberspace_cli.targets import format_target_list, get_current_target, set_target


class TestTargets(unittest.TestCase):
    def _state(self) -> CyberspaceState:
        return CyberspaceState(
            version=STATE_VERSION,
            privkey_hex="22" * 32,
            pubkey_hex="11" * 32,
            coord_hex="00" * 32,
            active_chain_label="",
            targets=[],
            active_target_label="",
        )

    def test_set_target_with_label_sets_current(self) -> None:
        st = self._state()
        label, coord = set_target(st, "0x1", label="homebase")
        self.assertEqual(label, "homebase")
        self.assertEqual(coord, "0" * 63 + "1")
        self.assertEqual(st.active_target_label, "homebase")
        self.assertEqual(len(st.targets), 1)

        lines = format_target_list(st)
        self.assertEqual(lines, [f"(current) homebase 0x{coord}"])

    def test_set_target_without_label_generates_unnamed(self) -> None:
        st = self._state()
        _, c1 = set_target(st, "0x1", label="homebase")

        label2, c2 = set_target(st, "0x2", label=None)
        self.assertEqual(label2, "unnamed_1")
        self.assertEqual(c2, "0" * 63 + "2")

        lines = format_target_list(st)
        self.assertEqual(lines, [f"homebase 0x{c1}", f"(current) unnamed_1 0x{c2}"])

    def test_set_target_without_label_selects_existing_coord(self) -> None:
        st = self._state()
        label1, c1 = set_target(st, "0x1", label="homebase")

        label2, c2 = set_target(st, "0x1", label=None)
        self.assertEqual((label2, c2), (label1, c1))
        cur = get_current_target(st)
        assert cur is not None
        self.assertEqual(cur["label"], "homebase")


if __name__ == "__main__":
    unittest.main()
