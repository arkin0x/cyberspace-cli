import unittest

from cyberspace_core.coords import xyz_to_coord
from cyberspace_core.sector import (
    SECTOR_BITS_DEFAULT,
    coords_in_same_sector,
    coord_to_sector_id,
    coord_to_sector_local_centered,
    xyz_to_sector_bounds,
    xyz_to_sector_id,
)


class TestSector(unittest.TestCase):
    def test_xyz_to_sector_id_default_bits(self) -> None:
        b = SECTOR_BITS_DEFAULT
        size = 1 << b

        sid0 = xyz_to_sector_id(x=0, y=0, z=0)
        self.assertEqual((sid0.sx, sid0.sy, sid0.sz), (0, 0, 0))

        sid1 = xyz_to_sector_id(x=size, y=0, z=0)
        self.assertEqual((sid1.sx, sid1.sy, sid1.sz), (1, 0, 0))

        sid2 = xyz_to_sector_id(x=size - 1, y=size - 1, z=size - 1)
        self.assertEqual((sid2.sx, sid2.sy, sid2.sz), (0, 0, 0))

        sid3 = xyz_to_sector_id(x=size + 123, y=2 * size + 7, z=9)
        self.assertEqual((sid3.sx, sid3.sy, sid3.sz), (1, 2, 0))

    def test_xyz_to_sector_bounds(self) -> None:
        b = SECTOR_BITS_DEFAULT
        size = 1 << b

        (xmin, xmax), (ymin, ymax), (zmin, zmax) = xyz_to_sector_bounds(x=size + 1, y=0, z=2 * size)
        self.assertEqual((xmin, xmax), (size, 2 * size - 1))
        self.assertEqual((ymin, ymax), (0, size - 1))
        self.assertEqual((zmin, zmax), (2 * size, 3 * size - 1))

    def test_coord_to_sector_id_and_local(self) -> None:
        b = SECTOR_BITS_DEFAULT
        size = 1 << b

        # Put a point near the start of sector (sx=1, sy=2, sz=3)
        x = (1 << b) + 0
        y = (2 << b) + 17
        z = (3 << b) + (size - 1)

        c = xyz_to_coord(x, y, z, plane=0)

        sid, plane = coord_to_sector_id(coord=c)
        self.assertEqual(plane, 0)
        self.assertEqual((sid.sx, sid.sy, sid.sz), (1, 2, 3))

        sid2, plane2, (lx, ly, lz) = coord_to_sector_local_centered(coord=c)
        self.assertEqual((sid2, plane2), (sid, 0))

        # All locals should lie in [-0.5, 0.5)
        for v in (lx, ly, lz):
            self.assertGreaterEqual(v, -0.5)
            self.assertLess(v, 0.5)

    def test_coords_in_same_sector(self) -> None:
        b = SECTOR_BITS_DEFAULT
        size = 1 << b

        a = xyz_to_coord(size + 1, 2 * size + 2, 0, plane=0)
        b2 = xyz_to_coord(size + 999, 2 * size + 3, 123, plane=1)  # different plane, same sector
        c = xyz_to_coord(0, 0, 0, plane=0)

        self.assertTrue(coords_in_same_sector(a=a, b=b2))
        self.assertFalse(coords_in_same_sector(a=a, b=c))


if __name__ == "__main__":
    unittest.main()
