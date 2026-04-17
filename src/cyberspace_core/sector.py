from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .coords import AXIS_BITS, coord_to_xyz


SECTOR_BITS_DEFAULT = 30


# DECK-0001 §I.2: Sector extraction from interleaved coordinates
# Coordinates are interleaved as XYZXYZXYZ...P pattern (85 bits per axis + 1 plane bit)
# To extract a sector, we must de-interleave to get the 85-bit axis value, then take high 55 bits


def extract_axis_from_coord256(coord256: int, axis: str) -> int:
    """De-interleave coord256 to get 85-bit axis value per DECK-0001 §I.2.
    
    Coordinates use interleaved bit pattern XYZXYZXYZ...P where:
    - X bits are at positions 3, 6, 9, ..., 255 (85 bits total)
    - Y bits are at positions 2, 5, 8, ..., 254 (85 bits total)
    - Z bits are at positions 1, 4, 7, ..., 253 (85 bits total)
    - P (plane) bit is at position 0
    
    Args:
        coord256: The 256-bit coordinate integer
        axis: 'X', 'Y', or 'Z' to extract
        
    Returns:
        The 85-bit axis value
    """
    if axis == 'X':
        shift = 3  # X bits at positions 3, 6, 9, ...
    elif axis == 'Y':
        shift = 2  # Y bits at positions 2, 5, 8, ...
    elif axis == 'Z':
        shift = 1  # Z bits at positions 1, 4, 7, ...
    else:
        raise ValueError(f"axis must be 'X', 'Y', or 'Z', got '{axis}'")
    
    result = 0
    for i in range(AXIS_BITS):  # 85 iterations
        bit_pos = shift + (3 * i)
        if coord256 & (1 << bit_pos):
            result |= (1 << i)
    return result


def sector_from_coord256(coord256: int, axis: str) -> int:
    """Extract 55-bit sector value from an interleaved coord256 per DECK-0001 §I.2.
    
    This is the DECK-0001 compliant sector extraction method. It de-interleaves
    the coordinate to get the 85-bit axis value, then takes the high 55 bits.
    
    Args:
        coord256: The 256-bit coordinate integer (interleaved XYZXYZ...P pattern)
        axis: 'X', 'Y', or 'Z' to extract sector from
        
    Returns:
        The 55-bit sector value (high 55 bits of the 85-bit axis value)
    """
    axis_value = extract_axis_from_coord256(coord256, axis)
    return axis_value >> 30  # High 55 bits of 85-bit axis


def extract_hyperjump_sectors(merkle_root_hex: str) -> Tuple[int, int, int]:
    """Extract X, Y, Z sector values from a Hyperjump's Merkle root.
    
    Args:
        merkle_root_hex: 64-char lowercase hex string (32-byte Merkle root)
        
    Returns:
        Tuple of (sector_x, sector_y, sector_z) as 55-bit integers
    """
    if len(merkle_root_hex) != 64:
        raise ValueError("merkle_root_hex must be exactly 64 hex chars (32 bytes)")
    if merkle_root_hex != merkle_root_hex.lower():
        raise ValueError("merkle_root_hex must be lowercase hex")
    
    merkle_root_int = int(merkle_root_hex, 16)
    sx = sector_from_coord256(merkle_root_int, 'X')
    sy = sector_from_coord256(merkle_root_int, 'Y')
    sz = sector_from_coord256(merkle_root_int, 'Z')
    return (sx, sy, sz)


def coord_matches_hyperjump_plane(
    coord256: int,
    merkle_root_hex: str,
    axis: str
) -> bool:
    """Check if a coordinate's sector matches a Hyperjump's sector on given axis.
    
    This implements the sector-plane entry check per DECK-0001 §I.2.
    
    Args:
        coord256: The 256-bit coordinate to check
        merkle_root_hex: 64-char hex of the Hyperjump's Merkle root
        axis: 'X', 'Y', or 'Z' for which plane to check
        
    Returns:
        True if sector(coord256, axis) == sector(merkle_root, axis)
    """
    coord_sector = sector_from_coord256(coord256, axis)
    hj_sectors = extract_hyperjump_sectors(merkle_root_hex)
    
    if axis == 'X':
        hj_sector = hj_sectors[0]
    elif axis == 'Y':
        hj_sector = hj_sectors[1]
    elif axis == 'Z':
        hj_sector = hj_sectors[2]
    else:
        raise ValueError(f"axis must be 'X', 'Y', or 'Z', got '{axis}'")
    
    return coord_sector == hj_sector


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
