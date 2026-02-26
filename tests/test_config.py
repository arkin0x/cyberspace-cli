import contextlib
import io
import os
import tempfile
import unittest

from cyberspace_cli import chains
from cyberspace_cli.cli import move
from cyberspace_cli.config import CyberspaceConfig, load_config, save_config
from cyberspace_cli.nostr_event import make_spawn_event
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, save_state
from cyberspace_core.coords import xyz_to_coord


class TestConfig(unittest.TestCase):
    def test_load_config_default_when_missing(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                cfg = load_config()
                self.assertIsNotNone(cfg.default_max_lca_height)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_save_and_load_config_roundtrip(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                cfg = CyberspaceConfig.default()
                cfg.default_max_lca_height = 13
                save_config(cfg)

                got = load_config()
                self.assertEqual(got.default_max_lca_height, 13)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_move_uses_config_default_when_option_omitted(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td

                # Set a tiny default max_lca_height so a moderately-large hop is rejected.
                cfg = CyberspaceConfig.default()
                cfg.default_max_lca_height = 1
                save_config(cfg)

                label = "t"
                pubkey_hex = "11" * 32
                privkey_hex = "22" * 32

                c0 = xyz_to_coord(0, 0, 0, plane=0).to_bytes(32, "big").hex()
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
                with self.assertRaises(Exception):
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        # Hop from x=0 -> x=3 has LCA height 2, which exceeds config default 1.
                        move(to="3,0,0", by=None, toward=None, max_lca_height=None, max_hops=0)

                out = buf.getvalue()
                self.assertIn("Move is too large for a single hop", out)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
