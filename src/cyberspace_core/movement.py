from __future__ import annotations

from dataclasses import dataclass

from cyberspace_core.cantor import cantor_pair, sha256_int_hex


def find_lca_height(v1: int, v2: int) -> int:
    if v1 == v2:
        return 0
    return (v1 ^ v2).bit_length()


def compute_subtree_cantor(base: int, height: int) -> int:
    """Compute the Cantor number for a subtree rooted at (base, height).

    Height h covers 2^h leaves [base, base + 2^h - 1].

    This is currently implemented by constructing the full tree bottom-up.
    """
    if height < 0:
        raise ValueError("height must be >= 0")
    if height == 0:
        return base

    values = list(range(base, base + (1 << height)))
    for _ in range(height):
        values = [cantor_pair(values[i], values[i + 1]) for i in range(0, len(values), 2)]
    return values[0]


def compute_axis_cantor(v1: int, v2: int) -> int:
    h = find_lca_height(v1, v2)
    base = (v1 >> h) << h
    return compute_subtree_cantor(base, h)


@dataclass(frozen=True)
class MovementProof:
    cantor_x: int
    cantor_y: int
    cantor_z: int
    combined: int
    proof_hash: str


def compute_movement_proof_xyz(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> MovementProof:
    cx = compute_axis_cantor(x1, x2)
    cy = compute_axis_cantor(y1, y2)
    cz = compute_axis_cantor(z1, z2)
    combined = cantor_pair(cantor_pair(cx, cy), cz)
    proof_hash = sha256_int_hex(combined)
    return MovementProof(cx, cy, cz, combined, proof_hash)
