from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .coords import coord_to_xyz


SECTOR_BITS_DEFAULT = 30


@dataclass(frozen=True)
class SectorId:
    """A sector identifier (per-axis integer sector index).

    Sectoring is defined purely over XYZ (plane is separate), using fixed-size blocks:
      sector_bits = 30  =>  sector_size = 2^30 axis-units per sector.
    """

    sx: int
    sy: int
    sz: int

    def tag(self) -> str:
        return f"{self.sx}-{self.sy}-{self.sz}"


def xyz_to_sector_id(*, x: int, y: int, z: int, sector_bits: int = SECTOR_BITS_DEFAULT) -> SectorId:
    if sector_bits < 0:
        raise ValueError("sector_bits must be >= 0")
    return SectorId(x >> sector_bits, y >> sector_bits, z >> sector_bits)


def coord_to_sector_id(*, coord: int, sector_bits: int = SECTOR_BITS_DEFAULT) -> Tuple[SectorId, int]:
    """Return (SectorId, plane) for an interleaved 256-bit coord int."""

    x, y, z, plane = coord_to_xyz(coord)
    return xyz_to_sector_id(x=x, y=y, z=z, sector_bits=sector_bits), plane


def sector_base(*, s: int, sector_bits: int = SECTOR_BITS_DEFAULT) -> int:
    """Return the axis-unit value at the start of sector index s."""

    if sector_bits < 0:
        raise ValueError("sector_bits must be >= 0")
    return int(s) << sector_bits


def xyz_to_sector_bounds(
    *, x: int, y: int, z: int, sector_bits: int = SECTOR_BITS_DEFAULT
) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
    """Return inclusive (min,max) bounds for the sector containing (x,y,z)."""

    if sector_bits < 0:
        raise ValueError("sector_bits must be >= 0")

    size = 1 << sector_bits

    sx = x >> sector_bits
    sy = y >> sector_bits
    sz = z >> sector_bits

    bx = sx << sector_bits
    by = sy << sector_bits
    bz = sz << sector_bits

    return ((bx, bx + size - 1), (by, by + size - 1), (bz, bz + size - 1))


def xyz_to_sector_local_centered(
    *, x: int, y: int, z: int, sector_bits: int = SECTOR_BITS_DEFAULT
) -> Tuple[SectorId, Tuple[float, float, float]]:
    """Return (SectorId, (lx,ly,lz)) where local coords are centered in [-0.5, +0.5).

    Local coordinates are normalized within the sector cube:
      local = ((v - base) + 0.5) / sector_size - 0.5

    The +0.5 term places the marker at the *center* of the integer cell, which helps
    avoid visually 'sticking' to faces when v is exactly on a boundary.
    """

    if sector_bits < 0:
        raise ValueError("sector_bits must be >= 0")

    size = float(1 << sector_bits)

    sid = xyz_to_sector_id(x=x, y=y, z=z, sector_bits=sector_bits)

    bx = sid.sx << sector_bits
    by = sid.sy << sector_bits
    bz = sid.sz << sector_bits

    lx = ((float(x - bx) + 0.5) / size) - 0.5
    ly = ((float(y - by) + 0.5) / size) - 0.5
    lz = ((float(z - bz) + 0.5) / size) - 0.5

    return sid, (lx, ly, lz)


def coord_to_sector_local_centered(
    *, coord: int, sector_bits: int = SECTOR_BITS_DEFAULT
) -> Tuple[SectorId, int, Tuple[float, float, float]]:
    """Return (SectorId, plane, (lx,ly,lz)) from a 256-bit coord int."""

    x, y, z, plane = coord_to_xyz(coord)
    sid, local = xyz_to_sector_local_centered(x=x, y=y, z=z, sector_bits=sector_bits)
    return sid, plane, local


def coords_in_same_sector(*, a: int, b: int, sector_bits: int = SECTOR_BITS_DEFAULT) -> bool:
    sa, _pa = coord_to_sector_id(coord=a, sector_bits=sector_bits)
    sb, _pb = coord_to_sector_id(coord=b, sector_bits=sector_bits)
    return sa == sb
