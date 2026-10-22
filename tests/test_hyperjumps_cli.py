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

        c0 = xyz_to_coord(start_xyz[0], start_xyz[1], start_xyz[2], plane=1).to_bytes(32, "big").hex()
        genesis = make_spawn_event(pubkey_hex=pubkey_hex, created_at=1700000000, coord_hex=c0)
        chains.create_new_chain(label, genesis, overwrite=False)

        coord_hex = c0
        if in_hyperjump_system:
            hj_xyz = hyperjump_xyz if hyperjump_xyz is not None else start_xyz
            coord_hex = xyz_to_coord(hj_xyz[0], hj_xyz[1], hj_xyz[2], plane=1).to_bytes(32, "big").hex()
            # A ride at the head of the chain, for the commands that read where
            # it left the identity (its B and C). Its proof values are
            # well-formed placeholders, not a proven ride.
            hj_event = make_hyperjump_event(
                pubkey_hex=pubkey_hex,
                created_at=1700000001,
                genesis_event_id=genesis["id"],
                previous_event_id=genesis["id"],
                prev_coord_hex=c0,
                coord_hex=coord_hex,
                from_height=int(hyperjump_height) - 1,
                to_height=int(hyperjump_height),
                proof_hash_hex="ab" * 32,
                ride_openings_hex="cd" * 32,
                nonce_hex="0" * 16,
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

    def _assert_move_hyperjump_refused(self, **dest) -> None:
        """move --hyperjump appends nothing, leaves the position alone and asks no relay anything."""
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, c0, _coord_hex = self._setup_chain(in_hyperjump_system=False, start_xyz=(15, 0, 0))
                with patch("cyberspace_cli.cli.subprocess.run") as run:
                    buf = io.StringIO()
                    with self.assertRaises(typer.Exit) as ex:
                        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                            move(
                                **dest,
                                max_lca_height=4,
                                max_hops=0,
                                hyperjump=True,
                                hyperjump_relay="wss://cyberspace.nostr1.com",
                                hyperjump_query_limit=25,
                                exit_hyperjump=False,
                            )
                self.assertEqual(ex.exception.exit_code, 2)
                self.assertIn("cannot ride hyperspace yet", buf.getvalue())
                run.assert_not_called()
                self.assertEqual(chains.chain_length(label), 1)
                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c0)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_to_hyperjump_refuses_and_appends_nothing(self) -> None:
        # Before 2026-10-22 this appended a ride with no from_height, proof, mp or mn
        # straight after the spawn: invalid under DECK-0001 4.3 and 5.2, so the chain was too.
        c1 = xyz_to_coord(31, 0, 0, plane=1).to_bytes(32, "big").hex()
        self._assert_move_hyperjump_refused(to=f"0x{c1}", by=None, toward=None)

    def test_move_toward_hyperjump_refuses_before_any_hop(self) -> None:
        # Hops then a ride from wherever they ended is not a DECK-0001 ride
        # (a ride follows a boarding or a ride, 4.3), so no hop is spent on one.
        c_target = xyz_to_coord(31, 0, 0, plane=1).to_bytes(32, "big").hex()
        self._assert_move_hyperjump_refused(to=None, by=None, toward=f"0x{c_target}")

    def test_hyperjump_to_requires_hyperjump_system_for_action(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                self._setup_chain(in_hyperjump_system=False)
                c_target = xyz_to_coord(101, 199, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '\"],[\"M\",\"' + c_target + '\"],[\"B\",\"940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
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
                c_target = xyz_to_coord(101, 199, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '\"],[\"M\",\"' + c_target + '\"],[\"B\",\"940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "show", "940158"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("hyperjump_block_height=940158", res.output)
                self.assertIn(f"coord: 0x{c_target}", res.output)
                self.assertIn("plane=1 ideaspace", res.output)
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
                c_target = xyz_to_coord(102, 200, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '\"],[\"M\",\"' + c_target + '\"],[\"B\",\"940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
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

    def test_hyperjump_next_refuses_to_ride(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord = self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")
                c_target = xyz_to_coord(102, 200, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '\"],[\"M\",\"' + c_target + '\"],[\"B\",\"940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch(
                    "cyberspace_cli.cli.subprocess.run",
                    side_effect=[self._mock_proc(out), self._mock_proc(out)],
                ):
                    res = runner.invoke(app, ["hyperjump", "next"])
                self.assertEqual(res.exit_code, 2, msg=res.output)
                self.assertIn("cannot ride hyperspace yet", res.output)
                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, _coord)
                self.assertEqual(chains.chain_length(label), 2)
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
                c_prev = xyz_to_coord(99, 200, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("cd" * 32)
                    + '","created_at":1773171778,"tags":[["C","'
                    + c_prev
                    + '\"],[\"M\",\"' + c_prev + '\"],[\"B\",\"940157"],["X","0"],["Y","0"],["Z","0"]]}\n'
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
                c_target = xyz_to_coord(101, 199, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '\"],[\"M\",\"' + c_target + '\"],[\"B\",\"940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
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

    def test_hyperjump_to_refuses_to_ride(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td
                label, _c0, _coord = self._setup_chain(in_hyperjump_system=True, hyperjump_height="940157")
                c_target = xyz_to_coord(105, 200, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + c_target
                    + '\"],[\"M\",\"' + c_target + '\"],[\"B\",\"940160"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch(
                    "cyberspace_cli.cli.subprocess.run",
                    side_effect=[self._mock_proc(out), self._mock_proc(out)],
                ):
                    res = runner.invoke(app, ["hyperjump", "to", "940160"])
                self.assertEqual(res.exit_code, 2, msg=res.output)
                self.assertIn("cannot ride hyperspace yet", res.output)
                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, _coord)
                self.assertEqual(chains.chain_length(label), 2)
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
                dest = xyz_to_coord(101, 199, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ab" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + dest
                    + '\"],[\"M\",\"' + dest + '\"],[\"B\",\"940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
                )
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(out)):
                    res = runner.invoke(app, ["hyperjump", "nearest", "--radius", "10"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("nearby_hyperjumps: 1", res.output)
                self.assertIn("direction=x+ (1) y- (1) z= (0)", res.output)
                self.assertIn("suggested_move=cyberspace move --to 101,199,300,1", res.output)
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
                override = xyz_to_coord(150, 200, 300, plane=1).to_bytes(32, "big").hex()
                dest = xyz_to_coord(151, 200, 300, plane=1).to_bytes(32, "big").hex()
                out = (
                    '{"kind":321,"id":"'
                    + ("ef" * 32)
                    + '","created_at":1773171779,"tags":[["C","'
                    + dest
                    + '\"],[\"M\",\"' + dest + '\"],[\"B\",\"940158"],["X","0"],["Y","0"],["Z","0"]]}\n'
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
                dest = xyz_to_coord(101, 199, 300, plane=1).to_bytes(32, "big").hex()
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
                expected = xyz_to_coord(101, 200, 300, plane=1).to_bytes(32, "big").hex()
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
