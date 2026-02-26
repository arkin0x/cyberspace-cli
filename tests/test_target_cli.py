import os
import tempfile
import unittest

from typer.testing import CliRunner

from cyberspace_cli import chains
from cyberspace_cli.cli import app
from cyberspace_cli.nostr_event import make_spawn_event
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, save_state
from cyberspace_core.coords import xyz_to_coord


class TestTargetCLI(unittest.TestCase):
    def test_target_list_does_not_require_coord(self) -> None:
        runner = CliRunner()

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td

                # Minimal state + chain so `target list` can run.
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

                res = runner.invoke(app, ["target", "list"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("(no targets yet)", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_target_set_then_list(self) -> None:
        runner = CliRunner()

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td

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

                r1 = runner.invoke(app, ["target", "set", "0x1", "--label", "foo"])
                self.assertEqual(r1.exit_code, 0, msg=r1.output)
                self.assertIn("(current) foo", r1.output)

                r2 = runner.invoke(app, ["target", "list"])
                self.assertEqual(r2.exit_code, 0, msg=r2.output)
                self.assertIn("(current) foo", r2.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
