import re
import unittest

from typer.testing import CliRunner

from cyberspace_cli.cli import app
from cyberspace_core.coords import coord_to_xyz, dataspace_coord_to_gps, gps_to_dataspace_coord, xyz_to_coord


class TestGpsReverse(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
