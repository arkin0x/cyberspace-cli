"""DECK-0001 v3 stop coordinates: golden vectors, anchor resolution, distances, CLI."""
import os
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from cyberspace_cli.cli import app
from cyberspace_core.coords import coord_to_xyz, gps_to_dataspace_xyz, xyz_to_coord
from cyberspace_core.hyperspace import (
    LANDFALL_GOLDEN_VECTORS,
    StopError,
    geodesic_km,
    landfall_coord_hex,
    resolve_stop,
    stop_distance,
    stop_from_block,
    stop_plane,
)

runner = CliRunner()

# Block 692065 (mainnet): merkle root ends in ...2c, plane bit 0, so it is a landfall.
B692065_HASH = "0000000000000000000a6701d93f0305d8bad4e4b2fabc893910a5f5951db91e"
B692065_MERKLE = "8e81cea8267368294372d3219296db8b9059cd4344e86500c9062fc34219a62c"
B692065_LANDFALL = "c49249249249249249249218f274586be7a6dc6a6f31736d95761f13d129666a"

# DECK example: block 398 is a landfall whose merkle root is given in the anchor example.
B398_MERKLE = "c056d48ae983586d78b51352c7d689db7c33acd286958301a5ec59e3a09ae016"
B398_HASH, B398_LANDFALL = LANDFALL_GOLDEN_VECTORS[0][1], LANDFALL_GOLDEN_VECTORS[0][2]


class TestLandfallGoldenVectors(unittest.TestCase):
    def test_all_eight_vectors(self) -> None:
        for height, block_hash, expected in LANDFALL_GOLDEN_VECTORS:
            with self.subTest(height=height):
                self.assertEqual(landfall_coord_hex(block_hash), expected)

    def test_landfall_is_plane_zero_on_the_surface(self) -> None:
        x, y, z, plane = coord_to_xyz(int(B692065_LANDFALL, 16))
        self.assertEqual(plane, 0)
        stop = stop_from_block(merkle_root_hex=B692065_MERKLE, block_hash_hex=B692065_HASH)
        lat, lon, alt = stop.gps()
        self.assertAlmostEqual(lat, 25.528272, places=5)
        self.assertAlmostEqual(lon, -80.162736, places=5)
        self.assertAlmostEqual(alt, 0.0, places=3)


class TestStopResolution(unittest.TestCase):
    def test_plane_bit(self) -> None:
        self.assertEqual(stop_plane(B692065_MERKLE), 0)
        self.assertEqual(stop_plane(B398_MERKLE), 0)
        self.assertEqual(stop_plane("ff" * 32), 1)

    def test_legacy_anchor_landfall_is_derived_from_hash(self) -> None:
        # Section 2.2: no M tag, C is the merkle root, and C MUST NOT be used as a position.
        stop = resolve_stop(c_hex=B398_MERKLE, m_hex=None, h_hex=B398_HASH)
        self.assertEqual(stop.kind, "landfall")
        self.assertEqual(stop.coord_hex, B398_LANDFALL)
        self.assertTrue(stop.legacy)
        self.assertTrue(stop.derived)
        self.assertEqual(stop.merkle_root_hex, B398_MERKLE)

    def test_legacy_anchor_port_is_the_merkle_root(self) -> None:
        port_root = "ab" * 31 + "01"
        stop = resolve_stop(c_hex=port_root, m_hex=None, h_hex="00" * 32)
        self.assertEqual(stop.kind, "port")
        self.assertEqual(stop.coord_hex, port_root)
        self.assertEqual(stop.plane, 1)
        self.assertFalse(stop.derived)

    def test_legacy_landfall_without_hash_is_unresolvable(self) -> None:
        with self.assertRaises(StopError):
            resolve_stop(c_hex=B398_MERKLE, m_hex=None, h_hex=None)

    def test_v3_anchor_is_verified_against_m_and_h(self) -> None:
        stop = resolve_stop(c_hex=B398_LANDFALL, m_hex=B398_MERKLE, h_hex=B398_HASH)
        self.assertEqual(stop.kind, "landfall")
        self.assertFalse(stop.legacy)
        self.assertFalse(stop.derived)
        with self.assertRaises(StopError):
            resolve_stop(c_hex=B398_MERKLE, m_hex=B398_MERKLE, h_hex=B398_HASH)  # C must be the landfall

    def test_stop_distance_is_max_axis_lca(self) -> None:
        self.assertEqual(stop_distance((0, 0, 0), (0, 0, 0)), 0)
        self.assertEqual(stop_distance((1, 0, 0), (0, 0, 0)), 1)
        self.assertEqual(stop_distance((0, 1 << 10, 0), (0, 0, 7)), 11)

    def test_geodesic_matches_known_distance(self) -> None:
        # Block 692065 landfall to downtown Miami: about 26.0 km.
        d = geodesic_km(25.528271719, -80.162736, 25.7617, -80.1918)
        self.assertAlmostEqual(d, 26.024, places=2)


class TestHyperjumpShowCLI(unittest.TestCase):
    def _legacy_anchor_json(self) -> str:
        return (
            '{"kind":321,"id":"38c03aa310904caa1bb534e9b0c143d9cb6035eed17a67f0bb6e0aa4563d46b6",'
            '"created_at":1772955100,"tags":[["C","' + B692065_MERKLE + '"],["B","692065"],'
            '["H","' + B692065_HASH + '"],["X","0"],["Y","0"],["Z","0"]]}\n'
        )

    @staticmethod
    def _mock_proc(stdout: str):
        class _Proc:
            stdout = ""
            returncode = 0
            stderr = ""

        p = _Proc()
        p.stdout = stdout
        return p

    def test_show_derives_landfall_from_legacy_anchor_and_prints_distance(self) -> None:
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                with patch("cyberspace_cli.cli.subprocess.run", return_value=self._mock_proc(self._legacy_anchor_json())) as run:
                    res = runner.invoke(app, ["hyperjump", "show", "692065", "--from-gps", "25.7617,-80.1918"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("--auth", run.call_args.args[0])
                self.assertIn("stop_kind=landfall", res.output)
                self.assertIn(f"coord: 0x{B692065_LANDFALL}", res.output)
                self.assertIn("lat=25.528272", res.output)
                self.assertIn("lon=-80.162736", res.output)
                self.assertIn("maps=https://www.google.com/maps?q=25.528272,-80.162736", res.output)
                self.assertIn("anchor_format=legacy", res.output)
                self.assertIn("stop_distance_d=51", res.output)
                self.assertIn("geodesic_km=26.024", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_show_offline_from_block_hash_and_merkle_root(self) -> None:
        res = runner.invoke(
            app,
            ["hyperjump", "show", "692065", "--block-hash", B692065_HASH, "--merkle-root", B692065_MERKLE],
        )
        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn(f"coord: 0x{B692065_LANDFALL}", res.output)
        self.assertIn("source=offline", res.output)

    def test_show_offline_requires_merkle_root(self) -> None:
        res = runner.invoke(app, ["hyperjump", "show", "692065", "--block-hash", B692065_HASH])
        self.assertNotEqual(res.exit_code, 0)

    def test_from_coord_distance_uses_axis_values(self) -> None:
        fx, fy, fz = gps_to_dataspace_xyz(25.7617, -80.1918)
        from_hex = format(xyz_to_coord(fx, fy, fz, 0), "064x")
        res = runner.invoke(
            app,
            ["hyperjump", "show", "692065", "--block-hash", B692065_HASH, "--merkle-root", B692065_MERKLE, "--from", f"0x{from_hex}"],
        )
        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn("lca_heights: X=50 Y=51 Z=49", res.output)
        self.assertIn("geodesic_km=26.024", res.output)


if __name__ == "__main__":
    unittest.main()
