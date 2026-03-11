import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from cyberspace_cli import chains
from cyberspace_cli.cli import app, move
from cyberspace_cli.nostr_event import make_hyperjump_event, make_spawn_event
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, load_state, save_state
from cyberspace_core.coords import xyz_to_coord


class TestHyperjumpCLI(unittest.TestCase):
    def _with_tmp_home(self):
        return tempfile.TemporaryDirectory()

    @staticmethod
    def _mock_proc(stdout: str, returncode: int = 0, stderr: str = ""):
        class _Proc:
            def __init__(self, out: str, rc: int, err: str):
                self.stdout = out
                self.returncode = rc
                self.stderr = err

        return _Proc(stdout, returncode, stderr)

    def _setup_chain(
        self,
        *,
        in_hyperjump_system: bool = False,
        hyperjump_height: str = "940157",
        start_xyz=(100, 200, 300),
        hyperjump_xyz=None,
    ):
        label = "t"
        pubkey_hex = "11" * 32
        privkey_hex = "22" * 32

        c0 = xyz_to_coord(start_xyz[0], start_xyz[1], start_xyz[2], plane=0).to_bytes(32, "big").hex()
        genesis = make_spawn_event(pubkey_hex=pubkey_hex, created_at=1700000000, coord_hex=c0)
        chains.create_new_chain(label, genesis, overwrite=False)

        coord_hex = c0
        if in_hyperjump_system:
            hj_xyz = hyperjump_xyz if hyperjump_xyz is not None else start_xyz
            coord_hex = xyz_to_coord(hj_xyz[0], hj_xyz[1], hj_xyz[2], plane=0).to_bytes(32, "big").hex()
            hj_event = make_hyperjump_event(
                pubkey_hex=pubkey_hex,
                created_at=1700000001,
                genesis_event_id=genesis["id"],
                previous_event_id=genesis["id"],
                prev_coord_hex=c0,
                coord_hex=coord_hex,
                to_height=hyperjump_height,
            )
            chains.append_event(label, hj_event)

        save_state(
            CyberspaceState(
                version=STATE_VERSION,
                privkey_hex=privkey_hex,
                pubkey_hex=pubkey_hex,
                coord_hex=coord_hex,
                active_chain_label=label,
                targets=[],
                active_target_label="",
            )
        )
        return label, c0, coord_hex

    def test_move_hyperjump_publishes_hyperjump_event(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, c0, _coord_hex = self._setup_chain(in_hyperjump_system=False)
                c1 = xyz_to_coord(101, 201, 302, plane=1).to_bytes(32, "big").hex()

                anchor_json = (
                    '{"kind":321,"id":"aa","tags":[["C","'
                    + c1
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(anchor_json)):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        move(
                            to=f"0x{c1}",
                            by=None,
                            toward=None,
                            max_lca_height=20,
                            max_hops=0,
                            hyperjump=True,
                            hyperjump_relay="wss://cyberspace.nostr1.com",
                            hyperjump_query_limit=25,
                            exit_hyperjump=False,
                        )

                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c1)
                self.assertEqual(chains.chain_length(label), 2)
                last = chains.read_events(label)[-1]
                tags = last.get("tags", [])
                self.assertIn(["A", "hyperjump"], tags)
                self.assertIn(["B", "940158"], tags)
                self.assertFalse(any(t[0] == "proof" for t in tags if isinstance(t, list) and t))
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_hyperjump_fails_when_destination_not_anchor(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord_hex = self._setup_chain(in_hyperjump_system=False)
                c1 = xyz_to_coord(101, 201, 302, plane=1).to_bytes(32, "big").hex()

                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc("")):
                    with self.assertRaises(typer.Exit) as ex:
                        move(
                            to=f"0x{c1}",
                            by=None,
                            toward=None,
                            max_lca_height=20,
                            max_hops=0,
                            hyperjump=True,
                            hyperjump_relay="wss://cyberspace.nostr1.com",
                            hyperjump_query_limit=25,
                            exit_hyperjump=False,
                        )
                self.assertEqual(ex.exception.exit_code, 2)
                self.assertEqual(chains.chain_length(label), 1)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_toward_hyperjump_uses_normal_hops_then_final_hyperjump(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord_hex = self._setup_chain(in_hyperjump_system=False, start_xyz=(15, 0, 0))
                c_target = xyz_to_coord(31, 0, 0, plane=0).to_bytes(32, "big").hex()

                anchor_json = (
                    '{"kind":321,"id":"aa","tags":[["C","'
                    + c_target
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(anchor_json)):
                    move(
                        to=None,
                        by=None,
                        toward=f"0x{c_target}",
                        max_lca_height=4,
                        max_hops=0,
                        hyperjump=True,
                        hyperjump_relay="wss://cyberspace.nostr1.com",
                        hyperjump_query_limit=25,
                        exit_hyperjump=False,
                    )

                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c_target)
                self.assertEqual(chains.chain_length(label), 3)
                events = chains.read_events(label)
                action1 = next((t[1] for t in events[1].get("tags", []) if isinstance(t, list) and len(t) >= 2 and t[0] == "A"), "")
                action2 = next((t[1] for t in events[2].get("tags", []) if isinstance(t, list) and len(t) >= 2 and t[0] == "A"), "")
                self.assertEqual(action1, "hop")
                self.assertEqual(action2, "hyperjump")
                self.assertIn(["B", "940158"], events[2].get("tags", []))
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_toward_hyperjump_fails_when_destination_not_anchor(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord_hex = self._setup_chain(in_hyperjump_system=False)
                c_target = xyz_to_coord(101, 200, 300, plane=0).to_bytes(32, "big").hex()

                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc("")):
                    with self.assertRaises(typer.Exit) as ex:
                        move(
                            to=None,
                            by=None,
                            toward=f"0x{c_target}",
                            max_lca_height=20,
                            max_hops=0,
                            hyperjump=True,
                            hyperjump_relay="wss://cyberspace.nostr1.com",
                            hyperjump_query_limit=25,
                            exit_hyperjump=False,
                        )
                self.assertEqual(ex.exception.exit_code, 2)
                self.assertEqual(chains.chain_length(label), 1)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_to_requires_hyperjump_system_for_action(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=False)
                c_target = xyz_to_coord(101, 199, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "to", "940158"])
                self.assertEqual(res.exit_code, 2)
                self.assertIn("not currently on the hyperjump system", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home
    def test_hyperjump_show_prints_anchor_off_hyperjump_system(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=False)
                c_target = xyz_to_coord(101, 199, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "show", "940158"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("hyperjump_block_height=940158", res.output)
                self.assertIn(f"coord: 0x{c_target}", res.output)
                self.assertIn("plane=0 dataspace", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_next_view_does_not_append_event(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord = self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")
                c_target = xyz_to_coord(102, 200, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "next", "--view"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("hyperjump_block_height=940158", res.output)
                self.assertEqual(chains.chain_length(label), 2)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_next_publishes_hyperjump_event(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord = self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")
                c_target = xyz_to_coord(102, 200, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch(
                    "cyberspace_cli.cli.subprocess.run",
                    side_effect=[self._mock_proc(out), self._mock_proc(out)],
                ):
                    res = runner.invoke(app, ["hyperjump", "next"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c_target)
                self.assertEqual(chains.chain_length(label), 3)
                last = chains.read_events(label)[-1]
                self.assertIn(["A", "hyperjump"], last.get("tags", []))
                self.assertIn(["B", "940158"], last.get("tags", []))
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_prev_view(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=True, hyperjump_height="940158")
                c_prev = xyz_to_coord(99, 200, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("cd" * 32)
                    + '","created_at":1773171778,"tags":[["C","'
                    + c_prev
                    + '"],["B","940157"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "prev", "--view"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("hyperjump_block_height=940157", res.output)
                self.assertIn(f"coord: 0x{c_prev}", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_to_view_off_hyperjump_system(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=False)
                c_target = xyz_to_coord(101, 199, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "to", "940158", "--view"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("hyperjump_block_height=940158", res.output)
                self.assertIn(f"coord: 0x{c_target}", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_to_publishes_hyperjump_event(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord = self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")
                c_target = xyz_to_coord(105, 200, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '"],["B","940160"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch(
                    "cyberspace_cli.cli.subprocess.run",
                    side_effect=[self._mock_proc(out), self._mock_proc(out)],
                ):
                    res = runner.invoke(app, ["hyperjump", "to", "940160"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c_target)
                self.assertEqual(chains.chain_length(label), 3)
                last = chains.read_events(label)[-1]
                self.assertIn(["A", "hyperjump"], last.get("tags", []))
                self.assertIn(["B", "940160"], last.get("tags", []))
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_nearest_prints_direction_hints_off_hyperjump_system(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=False)
                dest = xyz_to_coord(101, 199, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + dest
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "nearest", "--radius", "10"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("nearby_hyperjumps: 1", res.output)
                self.assertIn("direction=x+ (1) y- (1) z= (0)", res.output)
                self.assertIn("suggested_move=cyberspace move --to 101,199,300,0", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_nearest_uses_coord_override(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")
                override = xyz_to_coord(150, 200, 300, plane=0).to_bytes(32, "big").hex()
                dest = xyz_to_coord(151, 200, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ef" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + dest
                    + '"],["B","940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "nearest", "--coord", f"0x{override}", "--radius", "10"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn(f"current: 0x{override}", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_hyperjump_nearest_verbose_prints_req_filter_and_nak_output(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")
                dest = xyz_to_coord(101, 199, 300, plane=0).to_bytes(32, "big").hex()
                out = (
                    "debug-line\n"
                    + "{\"kind\":321,\"id\":\""
                    + ("ab" * 32)
                    + "\",\"created_at\":1773171779,\"tags\":[[\"C\",\""
                    + dest
                    + "\"],[\"B\",\"940158\"],[\"X\",\"0\"],[\"Y\",\"0\"],[\"Z\",\"0\"]]}\n"
                )
                with patch(
                    "cyberspace_cli.cli.subprocess.run",
                    return_value=self._mock_proc(out, stderr="warning: relay notice"),
                ):
                    res = runner.invoke(app, ["hyperjump", "nearest", "--radius", "10", "--verbose"])

                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("req_filter:", res.output)
                self.assertIn("\"#X\":[", res.output)
                self.assertIn("\"#Y\":[", res.output)
                self.assertIn("\"#Z\":[", res.output)
                self.assertIn("nak_stdout:", res.output)
                self.assertIn("debug-line", res.output)
                self.assertIn("nak_stderr:", res.output)
                self.assertIn("warning: relay notice", res.output)
                self.assertIn("nearby_hyperjumps: 1", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_blocks_normal_hop_on_hyperjump_system_without_flag(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord_hex = self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")

                buf = io.StringIO()
                with self.assertRaises(typer.Exit) as ex:
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        move(
                            to="101,200,300",
                            by=None,
                            toward=None,
                            max_lca_height=20,
                            max_hops=0,
                            hyperjump=False,
                            hyperjump_relay="wss://cyberspace.nostr1.com",
                            hyperjump_query_limit=25,
                            exit_hyperjump=False,
                        )
                self.assertEqual(ex.exception.exit_code, 2)
                self.assertIn("--exit-hyperjump", buf.getvalue())
                self.assertEqual(chains.chain_length(label), 2)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_allows_normal_hop_on_hyperjump_system_with_exit_flag(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord_hex = self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    move(
                        to="101,200,300",
                        by=None,
                        toward=None,
                        max_lca_height=20,
                        max_hops=0,
                        hyperjump=False,
                        hyperjump_relay="wss://cyberspace.nostr1.com",
                        hyperjump_query_limit=25,
                        exit_hyperjump=True,
                    )

                st = load_state()
                assert st is not None
                expected = xyz_to_coord(101, 200, 300, plane=0).to_bytes(32, "big").hex()
                self.assertEqual(st.coord_hex, expected)
                self.assertEqual(chains.chain_length(label), 3)
                last = chains.read_events(label)[-1]
                self.assertIn(["A", "hop"], last.get("tags", []))
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
