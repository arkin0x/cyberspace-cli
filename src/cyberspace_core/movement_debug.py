from __future__ import annotations

from dataclasses import dataclass
from typing import List

from cyberspace_core.cantor import cantor_pair


@dataclass(frozen=True)
class AxisCantorDebug:
    v1: int
    v2: int
    height: int
    base: int
    leaf_count: int
    leaf_min: int
    leaf_max: int
    levels: List[List[int]]
    root: int


def build_cantor_levels(base: int, height: int, *, max_height: int = 16) -> List[List[int]]:
    """Build the full Cantor tree levels for a subtree.

    Returns levels[0] as leaves (size 2^h), levels[h] as root (size 1).

    This is O(2^h) and intended for debugging/small heights only.
    """
    if height < 0:
        raise ValueError("height must be >= 0")
    if height > max_height:
        raise ValueError(f"height {height} exceeds max_height {max_height}")

    levels: List[List[int]] = []
    cur = list(range(base, base + (1 << height)))
    levels.append(cur)

    for _ in range(height):
        cur = [cantor_pair(cur[i], cur[i + 1]) for i in range(0, len(cur), 2)]
        levels.append(cur)

    return levels


def axis_cantor_debug(v1: int, v2: int, *, max_height: int = 16) -> AxisCantorDebug:
    """Compute LCA subtree root Cantor number and optionally the full tree levels."""
    if v1 < 0 or v2 < 0:
        raise ValueError("axis values must be non-negative")

    # LCA height: bit_length of xor
    if v1 == v2:
        height = 0
    else:
        height = (v1 ^ v2).bit_length()

    base = (v1 >> height) << height
    leaf_count = 1 << height
    leaf_min = base
    leaf_max = base + leaf_count - 1

    levels = build_cantor_levels(base, height, max_height=max_height)
    root = levels[-1][0]

    return AxisCantorDebug(
        v1=v1,
        v2=v2,
        height=height,
        base=base,
        leaf_count=leaf_count,
        leaf_min=leaf_min,
        leaf_max=leaf_max,
        levels=levels,
        root=root,
    )
