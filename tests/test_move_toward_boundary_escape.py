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


class TestMoveTowardBoundaryEscape(unittest.TestCase):
    def _with_tmp_home(self):
        return tempfile.TemporaryDirectory()

    def test_move_toward_crosses_block_boundary_with_temp_max_lca_bump(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with self._with_tmp_home() as td:
                os.environ["CYBERSPACE_HOME"] = td

                label = "t"
                pubkey_hex = "11" * 32
                privkey_hex = "22" * 32

                # max_lca_height=4 implies blocks of size 16.
                # Start at the end of a block (x=15) and target beyond it (x=31).
                c0 = xyz_to_coord(15, 0, 0, plane=0).to_bytes(32, "big").hex()
                c_target = xyz_to_coord(31, 0, 0, plane=0).to_bytes(32, "big").hex()

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

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    move(to=None, by=None, toward=f"0x{c_target}", max_lca_height=4, max_hops=0)

                st = load_state()
                assert st is not None
                self.assertEqual(st.coord_hex, c_target)
                self.assertEqual(chains.chain_length(label), 3)

                out = buf.getvalue()
                self.assertIn("LCA boundary encountered", out)
                self.assertIn("temporarily increasing max_lca_height", out)
                self.assertIn("hop: 1", out)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
