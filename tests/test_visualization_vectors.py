import json
import unittest
from decimal import Decimal
from pathlib import Path
from cyberspace_cli.visualizer.viz import (
    black_sun_circle_center_mpl,
    cyberspace_to_mpl,
    coord_to_dataspace_km,
    golden_vector_markers,
)

from cyberspace_core.coords import AXIS_CENTER, AXIS_UNITS, DATASPACE_AXIS_KM, coord_to_xyz


def u85_to_km_from_center(u: int) -> float:
    return float((Decimal(u - AXIS_CENTER) * DATASPACE_AXIS_KM) / Decimal(AXIS_UNITS))


class TestVisualizationVectors(unittest.TestCase):
    def test_vectors_match_decode(self) -> None:
        # repo_root = .../cyberspace
        repo_root = Path(__file__).resolve().parents[2]
        vectors_path = repo_root / "cyberspace-spec" / "visualization_vectors.json"

        with vectors_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        vectors = data.get("vectors", [])
        self.assertTrue(vectors, "expected vectors in visualization_vectors.json")

        for v in vectors:
            name = v.get("name", "(unnamed)")
            coord_hex = v["coord_hex"]
            coord = int(coord_hex, 16)

            x, y, z, plane = coord_to_xyz(coord)

            self.assertEqual(str(x), v["x_u85"], f"{name}: x mismatch")
            self.assertEqual(str(y), v["y_u85"], f"{name}: y mismatch")
            self.assertEqual(str(z), v["z_u85"], f"{name}: z mismatch")
            self.assertEqual(int(plane), int(v["plane"]), f"{name}: plane mismatch")

            x_km_viz, y_km_viz, z_km_viz = coord_to_dataspace_km(coord)
            self.assertAlmostEqual(u85_to_km_from_center(x), x_km_viz, places=6, msg=f"{name}: x_km")
            self.assertAlmostEqual(u85_to_km_from_center(y), y_km_viz, places=6, msg=f"{name}: y_km")
            self.assertAlmostEqual(u85_to_km_from_center(z), z_km_viz, places=6, msg=f"{name}: z_km")

    def test_golden_vector_overlay_markers(self) -> None:
        markers = golden_vector_markers()
        by_label = {m.label: m for m in markers}

        self.assertEqual(
            set(by_label.keys()),
            {"GV center", "GV +X", "GV -X", "GV +Y", "GV -Y", "GV +Z", "GV -Z"},
        )

        self.assertEqual(by_label["GV +X"].shape, "^")
        self.assertEqual(by_label["GV +X"].color, "#FFD700")
        self.assertEqual(by_label["GV +X"].label_color, "#000000")

        self.assertAlmostEqual(by_label["GV center"].position_km[0], 0.0, places=3)
        self.assertAlmostEqual(by_label["GV center"].position_km[1], 0.0, places=3)
        self.assertAlmostEqual(by_label["GV center"].position_km[2], 0.0, places=3)

        expected_delta = u85_to_km_from_center(AXIS_CENTER + (1 << 82))
        self.assertAlmostEqual(by_label["GV +X"].position_km[0], expected_delta, places=3)
        self.assertAlmostEqual(by_label["GV -X"].position_km[0], -expected_delta, places=3)
        self.assertAlmostEqual(by_label["GV +Y"].position_km[1], expected_delta, places=3)
        self.assertAlmostEqual(by_label["GV -Y"].position_km[1], -expected_delta, places=3)
        self.assertAlmostEqual(by_label["GV +Z"].position_km[2], expected_delta, places=3)
        self.assertAlmostEqual(by_label["GV -Z"].position_km[2], -expected_delta, places=3)

    def test_semantic_axis_mapping_and_black_sun_circle_tangent(self) -> None:
        self.assertEqual(cyberspace_to_mpl(1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertEqual(cyberspace_to_mpl(0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(cyberspace_to_mpl(0.0, 0.0, 1.0), (0.0, 1.0, 0.0))

        half_extent = 10.0
        radius = 2.5
        center = black_sun_circle_center_mpl(half_extent=half_extent, radius=radius)
        self.assertEqual(center, (0.0, 12.5, 0.0))
        # Tangency to +Z boundary (mapped to +Y_mpl = half_extent).
        self.assertAlmostEqual(center[1] - radius, half_extent, places=7)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
