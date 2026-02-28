from __future__ import annotations

"""Deterministic per-coordinate "terrain" utilities.

This module is experimental / non-consensus.

Goal:
- Derive a small integer K in [0, 32] from a destination coordinate.
- Have K follow a bell curve centered around 16 (binomial distribution).
- Add spatial correlation so neighboring coordinates tend to have similar K ("hills").

Design (current prototype):
- For each of 4 cell scales (cell_bits), align the destination to that cell.
- Hash the aligned coord256 with domain separation.
- Take 1 byte from each hash (4 bytes total = 32 bits).
- K = popcount(32-bit word) -> Binomial(n=32, p=0.5).

This produces a stable global distribution with mean 16 and max/min at 32/0.
"""

from typing import Iterable, Tuple

from cyberspace_core.cantor import sha256
from cyberspace_core.coords import xyz_to_coord


TERRAIN_DOMAIN_V1 = b"CYBERSPACE_TERRAIN_K_V1"


def _aligned(v: int, cell_bits: int) -> int:
    if cell_bits <= 0:
        return v
    return (v >> cell_bits) << cell_bits


def terrain_k_popcount32(
    *,
    x: int,
    y: int,
    z: int,
    plane: int,
    cell_bits: Tuple[int, int, int, int] = (3, 7, 9, 11),
) -> int:
    """Return a deterministic K in [0, 32] for a destination coordinate.

    `cell_bits` MUST contain exactly 4 integers.

    Notes:
    - K is the popcount of 32 pseudorandom bits => bell curve centered at 16.
    - Spatial correlation comes from aligning coords to cells at multiple scales.
    """

    if len(cell_bits) != 4:
        raise ValueError("cell_bits must have exactly 4 entries (4 bytes => 32 bits)")

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
        digest = sha256(TERRAIN_DOMAIN_V1 + bytes([bits]) + coord_bytes)
        b0 = digest[0]

        word = (word << 8) | b0

    # int.bit_count() counts 1-bits in the binary representation.
    return int(word).bit_count()


def terrain_k_popcount32_from_coord256(
    *,
    coord: int,
    cell_bits: Tuple[int, int, int, int] = (3, 7, 9, 11),
) -> int:
    """Same as terrain_k_popcount32 but takes a coord256 int.

    Note: this treats the provided coord as the destination and aligns it in XYZ space.
    """

    from cyberspace_core.coords import coord_to_xyz

    x, y, z, plane = coord_to_xyz(coord)
    return terrain_k_popcount32(x=x, y=y, z=z, plane=plane, cell_bits=cell_bits)


__all__ = [
    "TERRAIN_DOMAIN_V1",
    "terrain_k_popcount32",
    "terrain_k_popcount32_from_coord256",
]
