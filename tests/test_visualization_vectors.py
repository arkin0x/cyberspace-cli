import json
import unittest
from decimal import Decimal
from pathlib import Path

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

            # Stored km values are floats, so use a modest tolerance.
            self.assertAlmostEqual(u85_to_km_from_center(x), float(v["x_km_from_center"]), places=3, msg=f"{name}: x_km")
            self.assertAlmostEqual(u85_to_km_from_center(y), float(v["y_km_from_center"]), places=3, msg=f"{name}: y_km")
            self.assertAlmostEqual(u85_to_km_from_center(z), float(v["z_km_from_center"]), places=3, msg=f"{name}: z_km")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
