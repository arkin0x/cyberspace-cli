from __future__ import annotations

"""Deterministic per-coordinate "terrain" utilities.

This module defines the terrain-derived temporal height K used for hop
proof freshness (spec §5.4.2.1).

Goal:
- Derive a small integer K in [0, 16] from a destination coordinate.
- Have K follow a bell curve centered around 8 (binomial distribution).
- Add spatial correlation so neighboring coordinates tend to have similar K ("hills").

Design:
- For each of 4 cell scales (cell_bits), align the destination to that cell.
- Hash the aligned coord256 with domain separation.
- Take the low 4 bits (nibble) of the first byte from each hash (4 nibbles = 16 bits).
- K = popcount(16-bit word) -> Binomial(n=16, p=0.5).

This produces a stable global distribution with mean 8 and max 16.
The worst-case temporal computation is 2^16 = 65,536 Cantor pairs (~100 ms).
"""

from typing import Tuple

from cyberspace_core.cantor import sha256
from cyberspace_core.coords import xyz_to_coord


# Domain string (consensus-critical).  Bumped from V1 → V2 when the
# extraction changed from full byte (32 bits) to low nibble (16 bits).
TERRAIN_DOMAIN_V2 = b"CYBERSPACE_TERRAIN_K_V2"


def _aligned(v: int, cell_bits: int) -> int:
    if cell_bits <= 0:
        return v
    return (v >> cell_bits) << cell_bits


def terrain_k(
    *,
    x: int,
    y: int,
    z: int,
    plane: int,
    cell_bits: Tuple[int, int, int, int] = (3, 7, 9, 11),
) -> int:
    """Return a deterministic K in [0, 16] for a destination coordinate.

    `cell_bits` MUST contain exactly 4 integers.

    For each cell scale the low 4 bits of digest[0] are used (one nibble
    per scale, 16 pseudorandom bits total).  K is the popcount of the
    resulting 16-bit word → Binomial(n=16, p=0.5), mean 8.

    Spatial correlation comes from aligning coords to cells at multiple scales.
    """

    if len(cell_bits) != 4:
        raise ValueError("cell_bits must have exactly 4 entries (4 nibbles => 16 bits)")

    if plane not in (0, 1):
        raise ValueError("plane must be 0 or 1")

    word = 0

    for bits in cell_bits:
        if bits < 0 or bits > 84:
            raise ValueError("cell_bits entries must be within [0, 84]")

        bx = _aligned(x, bits)
        by = _aligned(y, bits)
        bz = _aligned(z, bits)

        coord = xyz_to_coord(bx, by, bz, plane=plane)
        coord_bytes = coord.to_bytes(32, "big")

        # Domain-separate by including the cell_bits byte.
        digest = sha256(TERRAIN_DOMAIN_V2 + bytes([bits]) + coord_bytes)
        nibble = digest[0] & 0x0F  # low 4 bits only

        word = (word << 4) | nibble

    # int.bit_count() counts 1-bits in the binary representation.
    return int(word).bit_count()


def terrain_k_from_coord256(
    *,
    coord: int,
    cell_bits: Tuple[int, int, int, int] = (3, 7, 9, 11),
) -> int:
    """Same as terrain_k but takes a coord256 int."""

    from cyberspace_core.coords import coord_to_xyz

    x, y, z, plane = coord_to_xyz(coord)
    return terrain_k(x=x, y=y, z=z, plane=plane, cell_bits=cell_bits)


# ------------------------------------------------------------------
# Backwards compatibility shims (deprecated; use terrain_k instead)
# ------------------------------------------------------------------
TERRAIN_DOMAIN_V1 = b"CYBERSPACE_TERRAIN_K_V1"

def terrain_k_popcount32(
    *,
    x: int,
    y: int,
    z: int,
    plane: int,
    cell_bits: Tuple[int, int, int, int] = (3, 7, 9, 11),
) -> int:
    """Deprecated: alias for terrain_k."""
    return terrain_k(x=x, y=y, z=z, plane=plane, cell_bits=cell_bits)


def terrain_k_popcount32_from_coord256(
    *,
    coord: int,
    cell_bits: Tuple[int, int, int, int] = (3, 7, 9, 11),
) -> int:
    """Deprecated: alias for terrain_k_from_coord256."""
    return terrain_k_from_coord256(coord=coord, cell_bits=cell_bits)


__all__ = [
    "TERRAIN_DOMAIN_V2",
    "terrain_k",
    "terrain_k_from_coord256",
    # deprecated
    "TERRAIN_DOMAIN_V1",
    "terrain_k_popcount32",
    "terrain_k_popcount32_from_coord256",
]
