import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from cyberspace_cli.cli import app
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, save_state
from cyberspace_core.coords import xyz_to_coord


def _setup_min_state() -> None:
    coord_hex = xyz_to_coord(0, 0, 0, plane=0).to_bytes(32, "big").hex()
    save_state(
        CyberspaceState(
            version=STATE_VERSION,
            privkey_hex="22" * 32,
            pubkey_hex="11" * 32,
            coord_hex=coord_hex,
            active_chain_label="",
            targets=[],
            active_target_label="",
        )
    )


class Test3DCLI(unittest.TestCase):
    def test_three_d_passes_default_earth_altitude(self) -> None:
        runner = CliRunner()
        calls = []

        fake_visualizer_app = types.ModuleType("cyberspace_cli.visualizer.app")

        def _run_app(**kwargs):
            calls.append(kwargs)
            return 0

        fake_visualizer_app.run_app = _run_app

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()

                with patch.dict(sys.modules, {"cyberspace_cli.visualizer.app": fake_visualizer_app}):
                    res = runner.invoke(app, ["3d"])

                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertEqual(len(calls), 1)
                self.assertAlmostEqual(float(calls[0]["earth_altitude_km"]), 12000.0, places=6)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_three_d_passes_custom_earth_altitude(self) -> None:
        runner = CliRunner()
        calls = []

        fake_visualizer_app = types.ModuleType("cyberspace_cli.visualizer.app")

        def _run_app(**kwargs):
            calls.append(kwargs)
            return 0

        fake_visualizer_app.run_app = _run_app

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()

                with patch.dict(sys.modules, {"cyberspace_cli.visualizer.app": fake_visualizer_app}):
                    res = runner.invoke(app, ["3d", "--earth-altitude-km", "8500"])

                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertEqual(len(calls), 1)
                self.assertAlmostEqual(float(calls[0]["earth_altitude_km"]), 8500.0, places=6)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_three_d_rejects_negative_earth_altitude(self) -> None:
        runner = CliRunner()

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()

                res = runner.invoke(app, ["3d", "--earth-altitude-km", "-1"])

                self.assertEqual(res.exit_code, 2, msg=res.output)
                self.assertIn("--earth-altitude-km must be >= 0.", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
