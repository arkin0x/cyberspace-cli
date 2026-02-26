import contextlib
import io
import os
import tempfile
import unittest

from cyberspace_cli import chains
from cyberspace_cli.cli import move
from cyberspace_cli.nostr_event import make_spawn_event
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, load_state, save_state
from cyberspace_core.coords import xyz_to_coord


class TestMovePlanes(unittest.TestCase):
    def _with_tmp_home(self):
        return tempfile.TemporaryDirectory()

    def test_move_to_coord_allows_plane_switch(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td

                label = "t"
                pubkey_hex = "11" * 32
                privkey_hex = "22" * 32

                # Start in dataspace plane=0.
                c0 = xyz_to_coord(100, 200, 300, plane=0).to_bytes(32, "big").hex()
                c1 = xyz_to_coord(100, 200, 300, plane=1).to_bytes(32, "big").hex()

                genesis = make_spawn_event(pubkey_hex=pubkey_hex, created_at=1700000000, coord_hex=c0)
                chains.create_new_chain(label, genesis, overwrite=False)

                save_state(
                    CyberspaceState(
                        version=STATE_VERSION,
                        privkey_hex=privkey_hex,
                        pubkey_hex=pubkey_hex,
                        coord_hex=c0,
                        active_chain_label=label,
                        targets=[],
                        active_target_label="",
                    )
                )

                # Switch to ideaspace plane=1 by specifying a coord hex with plane bit set.
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    move(to=f"0x{c1}", by=None, toward=None, max_lca_height=20, max_hops=0)

                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c1)
                self.assertEqual(chains.chain_length(label), 2)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_by_allows_plane_switch(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td

                label = "t"
                pubkey_hex = "11" * 32
                privkey_hex = "22" * 32

                c0 = xyz_to_coord(100, 200, 300, plane=0).to_bytes(32, "big").hex()
                c1 = xyz_to_coord(100, 200, 300, plane=1).to_bytes(32, "big").hex()

                genesis = make_spawn_event(pubkey_hex=pubkey_hex, created_at=1700000000, coord_hex=c0)
                chains.create_new_chain(label, genesis, overwrite=False)

                save_state(
                    CyberspaceState(
                        version=STATE_VERSION,
                        privkey_hex=privkey_hex,
                        pubkey_hex=pubkey_hex,
                        coord_hex=c0,
                        active_chain_label=label,
                        targets=[],
                        active_target_label="",
                    )
                )

                # Switch planes via 0,0,0,plane
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    move(to=None, by="0,0,0,1", toward=None, max_lca_height=20, max_hops=0)

                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c1)
                self.assertEqual(chains.chain_length(label), 2)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
