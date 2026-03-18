import tempfile
import unittest
from pathlib import Path

from cyberspace_core.geoid import GeoidModelNotFoundError, geoid_undulation_m, load_geoid_grid, normalize_geoid_model


def _write_test_geoid_pgm(path: Path) -> None:
    # 4x3 grid with a simple ramp for deterministic interpolation:
    # row0: 0,10,20,30
    # row1: 40,50,60,70
    # row2: 80,90,100,110
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


class TestGeoid(unittest.TestCase):
    def test_normalize_model(self) -> None:
        self.assertEqual(normalize_geoid_model("EGM2008-2_5"), "egm2008-2_5")
        self.assertEqual(normalize_geoid_model("egm2008-1"), "egm2008-1")
        with self.assertRaises(ValueError):
            normalize_geoid_model("egm96-15")

    def test_model_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(GeoidModelNotFoundError):
                load_geoid_grid("egm2008-2_5", geoid_dir=Path(td))

    def test_undulation_exact_points_and_interpolation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "egm2008-2_5.pgm"
            _write_test_geoid_pgm(p)

            # Exact grid nodes.
            self.assertAlmostEqual(geoid_undulation_m(90.0, 0.0, model="egm2008-2_5", geoid_dir=Path(td)), 0.0, places=6)
            self.assertAlmostEqual(geoid_undulation_m(0.0, 180.0, model="egm2008-2_5", geoid_dir=Path(td)), 60.0, places=6)
            self.assertAlmostEqual(geoid_undulation_m(-90.0, 270.0, model="egm2008-2_5", geoid_dir=Path(td)), 110.0, places=6)

            # Bilinear interpolation at center between (row0/1, col0/1):
            # (0 + 10 + 40 + 50) / 4 = 25
            self.assertAlmostEqual(geoid_undulation_m(45.0, 45.0, model="egm2008-2_5", geoid_dir=Path(td)), 25.0, places=6)

            # Longitude wrap: -315 == 45
            self.assertAlmostEqual(geoid_undulation_m(45.0, -315.0, model="egm2008-2_5", geoid_dir=Path(td)), 25.0, places=6)


if __name__ == "__main__":
    unittest.main()
