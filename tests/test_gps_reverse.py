import os
import re
import tempfile
import unittest

from typer.testing import CliRunner

from cyberspace_cli.cli import app
from cyberspace_core.coords import coord_to_xyz, dataspace_coord_to_gps, gps_to_dataspace_coord, xyz_to_coord
from cyberspace_core.geoid import geoid_undulation_m


class TestGpsReverse(unittest.TestCase):
    @staticmethod
    def _write_test_geoid_pgm(path: str) -> None:
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
        with open(path, "wb") as f:
            f.write(b"P5\n")
            f.write(b"# Offset 0\n")
            f.write(b"# Scale 1\n")
            f.write(f"{width} {height}\n".encode("ascii"))
            f.write(b"65535\n")
            for v in vals:
                f.write(int(v).to_bytes(2, "big", signed=False))

    def test_roundtrip_preserves_lat_lon_alt(self) -> None:
        lat = 37.7749
        lon = -122.4194
        alt = 123.45

        coord = gps_to_dataspace_coord(str(lat), str(lon), str(alt), clamp_to_surface=False)
        got_lat, got_lon, got_alt, plane = dataspace_coord_to_gps(coord)

        self.assertEqual(plane, 0)
        self.assertAlmostEqual(got_lat, lat, places=6)
        self.assertAlmostEqual(got_lon, lon, places=6)
        self.assertAlmostEqual(got_alt, alt, places=3)

    def test_ideaspace_coord_still_converts_to_gps(self) -> None:
        lat = 51.5074
        lon = -0.1278

        dataspace_coord = gps_to_dataspace_coord(str(lat), str(lon))
        x, y, z, _plane = coord_to_xyz(dataspace_coord)
        ideaspace_coord = xyz_to_coord(x, y, z, plane=1)

        got_lat, got_lon, got_alt, plane = dataspace_coord_to_gps(ideaspace_coord)

        self.assertEqual(plane, 1)
        self.assertAlmostEqual(got_lat, lat, places=6)
        self.assertAlmostEqual(got_lon, lon, places=6)
        self.assertAlmostEqual(got_alt, 0.0, places=3)

    def test_cli_gps_coord_mode_works_for_ideaspace(self) -> None:
        lat = 40.7128
        lon = -74.0060

        dataspace_coord = gps_to_dataspace_coord(str(lat), str(lon))
        x, y, z, _plane = coord_to_xyz(dataspace_coord)
        ideaspace_coord = xyz_to_coord(x, y, z, plane=1).to_bytes(32, "big").hex()

        runner = CliRunner()
        res = runner.invoke(app, ["gps", "--coord", f"0x{ideaspace_coord}"])

        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn("plane=1 ideaspace", res.output)

        m = re.search(r"gps: lat=([-0-9.]+) lon=([-0-9.]+) alt_m=([-0-9.]+)", res.output)
        self.assertIsNotNone(m, msg=res.output)
        if m is None:
            return

        got_lat = float(m.group(1))
        got_lon = float(m.group(2))
        got_alt = float(m.group(3))

        self.assertAlmostEqual(got_lat, lat, places=6)
        self.assertAlmostEqual(got_lon, lon, places=6)
        self.assertAlmostEqual(got_alt, 0.0, places=3)

    def test_cli_gps_altitude_wgs84_maps_to_same_coord_as_core(self) -> None:
        lat = "37.7749"
        lon = "-122.4194"
        alt_wgs84 = "123.45"
        expected_coord = gps_to_dataspace_coord(lat, lon, alt_wgs84, clamp_to_surface=False).to_bytes(32, "big").hex()

        runner = CliRunner()
        res = runner.invoke(
            app,
            [
                "gps",
                f"{lat},{lon}",
                "--altitude-wgs84",
                alt_wgs84,
            ],
        )
        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn(f"coord: 0x{expected_coord}", res.output)

    def test_cli_gps_altitude_sealevel_converts_using_geoid_offset(self) -> None:
        lat = "37.7749"
        lon = "-122.4194"
        alt_sealevel = 10.0
        geoid_offset = 30.5
        expected_wgs84 = str(alt_sealevel + geoid_offset)
        expected_coord = gps_to_dataspace_coord(lat, lon, expected_wgs84, clamp_to_surface=False).to_bytes(32, "big").hex()

        runner = CliRunner()
        res = runner.invoke(
            app,
            [
                "gps",
                f"{lat},{lon}",
                "--altitude-sealevel",
                str(alt_sealevel),
                "--geoid-offset-m",
                str(geoid_offset),
            ],
        )
        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn(f"coord: 0x{expected_coord}", res.output)

    def test_cli_gps_altitude_sealevel_auto_derives_geoid_offset(self) -> None:
        lat = "0"
        lon = "0"
        alt_sealevel = 10.0
        with tempfile.TemporaryDirectory() as td:
            geoid_file = os.path.join(td, "egm2008-2_5.pgm")
            self._write_test_geoid_pgm(geoid_file)

            old_geoid_path = os.environ.get("CYBERSPACE_GEOID_PATH")
            try:
                os.environ["CYBERSPACE_GEOID_PATH"] = td
                n = geoid_undulation_m(float(lat), float(lon), model="egm2008-2_5")
                expected_wgs84 = str(alt_sealevel + n)
                expected_coord = gps_to_dataspace_coord(
                    lat,
                    lon,
                    expected_wgs84,
                    clamp_to_surface=False,
                ).to_bytes(32, "big").hex()

                runner = CliRunner()
                res = runner.invoke(
                    app,
                    [
                        "gps",
                        f"{lat},{lon}",
                        "--altitude-sealevel",
                        str(alt_sealevel),
                    ],
                )
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn(f"coord: 0x{expected_coord}", res.output)
            finally:
                if old_geoid_path is None:
                    os.environ.pop("CYBERSPACE_GEOID_PATH", None)
                else:
                    os.environ["CYBERSPACE_GEOID_PATH"] = old_geoid_path

    def test_cli_gps_rejects_explicit_clamp_with_altitude(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            app,
            [
                "gps",
                "37.7749,-122.4194",
                "--alt",
                "10",
                "--clamp",
            ],
        )
        self.assertEqual(res.exit_code, 2, msg=res.output)
        self.assertIn("Cannot use --clamp with altitude options", res.output)

    def test_cli_gps_rejects_both_altitude_references(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            app,
            [
                "gps",
                "37.7749,-122.4194",
                "--altitude-wgs84",
                "10",
                "--altitude-sealevel",
                "5",
                "--geoid-offset-m",
                "30",
            ],
        )
        self.assertEqual(res.exit_code, 2, msg=res.output)
        self.assertIn("Use either --altitude-wgs84 OR --altitude-sealevel", res.output)


if __name__ == "__main__":
    unittest.main()
