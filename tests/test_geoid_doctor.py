import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from cyberspace_cli.cli import app


def _write_test_geoid_pgm(path: Path) -> None:
    width = 4
    height = 3
    vals = [
        0, 10, 20, 30,
        40, 50, 60, 70,
        80, 90, 100, 110,
    ]
    with path.open("wb") as f:
        f.write(b"P5\n")
        f.write(b"# Offset 0\n")
        f.write(b"# Scale 1\n")
        f.write(f"{width} {height}\n".encode("ascii"))
        f.write(b"65535\n")
        for v in vals:
            f.write(int(v).to_bytes(2, "big", signed=False))


class TestGeoidDoctor(unittest.TestCase):
    def test_doctor_reports_missing_model(self) -> None:
        old_path = os.environ.get("CYBERSPACE_GEOID_PATH")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_GEOID_PATH"] = td
                runner = CliRunner()
                res = runner.invoke(app, ["geoid", "doctor", "--model", "egm2008-1", "--effective-only"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("effective_model=egm2008-1", res.output)
                self.assertIn("model=egm2008-1", res.output)
                self.assertIn("status=missing", res.output)
        finally:
            if old_path is None:
                os.environ.pop("CYBERSPACE_GEOID_PATH", None)
            else:
                os.environ["CYBERSPACE_GEOID_PATH"] = old_path

    def test_doctor_reports_available_model(self) -> None:
        old_path = os.environ.get("CYBERSPACE_GEOID_PATH")
        try:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "egm2008-2_5.pgm"
                _write_test_geoid_pgm(p)
                os.environ["CYBERSPACE_GEOID_PATH"] = td

                runner = CliRunner()
                res = runner.invoke(app, ["geoid", "doctor", "--effective-only"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("effective_model=egm2008-2_5", res.output)
                self.assertIn("model=egm2008-2_5", res.output)
                self.assertIn("status=available", res.output)
                self.assertIn(f"path={p}", res.output)
        finally:
            if old_path is None:
                os.environ.pop("CYBERSPACE_GEOID_PATH", None)
            else:
                os.environ["CYBERSPACE_GEOID_PATH"] = old_path


if __name__ == "__main__":
    unittest.main()
