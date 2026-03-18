from __future__ import annotations

import sys
from dataclasses import dataclass

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256, sha256_int_hex
from cyberspace_core.coords import AXIS_BITS
from cyberspace_core.terrain import terrain_k

DEFAULT_MAX_COMPUTE_HEIGHT = 20

# Temporal axis: the maximum terrain-derived K is 16 (popcount of 16 bits).
TEMPORAL_MAX_COMPUTE_HEIGHT = 17


def find_lca_height(v1: int, v2: int) -> int:
    if v1 == v2:
        return 0
    return (v1 ^ v2).bit_length()


def compute_subtree_cantor(base: int, height: int, *, max_compute_height: int = DEFAULT_MAX_COMPUTE_HEIGHT) -> int:
    """Compute the Cantor number for a subtree rooted at (base, height).

    Height h covers 2^h leaves [base, base + 2^h - 1].

    This is an O(2^h) computation.

    We include safety guards to avoid hard crashes on absurd inputs.
    """
    if height < 0:
        raise ValueError("height must be >= 0")
    if height > max_compute_height:
        raise ValueError(f"height {height} exceeds max_compute_height {max_compute_height}")
    if height == 0:
        return base

    leaf_count = 1 << height
    if leaf_count > sys.maxsize:
        # Even constructing a range/list this large will crash (ssize_t overflow).
        raise ValueError(f"leaf_count {leaf_count} exceeds sys.maxsize; height {height} is too large")

    values = list(range(base, base + leaf_count))
    for _ in range(height):
        values = [cantor_pair(values[i], values[i + 1]) for i in range(0, len(values), 2)]
    return values[0]


def compute_axis_cantor(v1: int, v2: int, *, max_compute_height: int = DEFAULT_MAX_COMPUTE_HEIGHT) -> int:
    h = find_lca_height(v1, v2)
    base = (v1 >> h) << h
    return compute_subtree_cantor(base, h, max_compute_height=max_compute_height)


@dataclass(frozen=True)
class MovementProof:
    cantor_x: int
    cantor_y: int
    cantor_z: int
    combined: int
    proof_hash: str


def compute_movement_proof_xyz(
    x1: int,
    y1: int,
    z1: int,
    x2: int,
    y2: int,
    z2: int,
    *,
    max_compute_height: int = DEFAULT_MAX_COMPUTE_HEIGHT,
) -> MovementProof:
    """Compute the spatial-only movement proof (region_n).

    This is still useful for benchmarks, the `cantor` debug command, and
    location-based encryption key derivation (§7).  It does NOT include
    the temporal axis required for hop event proofs — use
    `compute_hop_proof` for that.
    """
    cx = compute_axis_cantor(x1, x2, max_compute_height=max_compute_height)
    cy = compute_axis_cantor(y1, y2, max_compute_height=max_compute_height)
    cz = compute_axis_cantor(z1, z2, max_compute_height=max_compute_height)
    combined = cantor_pair(cantor_pair(cx, cy), cz)
    proof_hash = sha256_int_hex(combined)
    return MovementProof(cx, cy, cz, combined, proof_hash)


@dataclass(frozen=True)
class HopProof:
    """Full 4D hop proof (spatial + temporal) per spec §5.5.3 / §5.7."""
    cantor_x: int
    cantor_y: int
    cantor_z: int
    region_n: int       # π(π(cx, cy), cz)  — stable spatial region integer
    terrain_k: int      # terrain-derived temporal height K  (§5.5.2.1)
    temporal_seed: int  # t = prev_event_id_int % 2^85       (§5.5.2.2)
    cantor_t: int       # temporal axis Cantor root           (§5.5.2.2)
    hop_n: int          # π(region_n, cantor_t)               (§5.5.3)
    proof_hash: str     # sha256(sha256(int_to_bytes_be_min(hop_n))).hex()  (§5.7)


def compute_hop_proof(
    x1: int,
    y1: int,
    z1: int,
    x2: int,
    y2: int,
    z2: int,
    *,
    plane: int,
    previous_event_id_hex: str,
    max_compute_height: int = DEFAULT_MAX_COMPUTE_HEIGHT,
) -> HopProof:
    """Compute the full 4D hop proof (spatial + temporal) per spec §5.5–§5.7.

    Parameters
    ----------
    x1, y1, z1 : origin u85 axis values
    x2, y2, z2 : destination u85 axis values
    plane      : destination plane bit (0 or 1)
    previous_event_id_hex : 64-char lowercase hex string (the NIP-01 id of
                            the previous movement event in the chain)
    max_compute_height : per-axis spatial LCA height cap
    """
    # --- spatial component (§5.5) ---
    cx = compute_axis_cantor(x1, x2, max_compute_height=max_compute_height)
    cy = compute_axis_cantor(y1, y2, max_compute_height=max_compute_height)
    cz = compute_axis_cantor(z1, z2, max_compute_height=max_compute_height)
    region_n = cantor_pair(cantor_pair(cx, cy), cz)

    # --- temporal component (§5.5.2) ---
    # K from terrain at destination (§5.5.2.1)
    terrain_k_val = terrain_k(x=x2, y=y2, z=z2, plane=plane)

    # Seed from previous event id (§5.5.2.2)
    if len(previous_event_id_hex) != 64:
        raise ValueError("previous_event_id_hex must be exactly 64 hex chars (32 bytes)")
    if previous_event_id_hex != previous_event_id_hex.lower():
        raise ValueError("previous_event_id_hex must be lowercase hex")
    try:
        previous_event_id_bytes = bytes.fromhex(previous_event_id_hex)
    except ValueError as e:
        raise ValueError("previous_event_id_hex must be valid lowercase hex") from e
    prev_id_int = int.from_bytes(previous_event_id_bytes, "big")
    t = prev_id_int % (1 << AXIS_BITS)

    # Temporal subtree root
    t_base = (t >> terrain_k_val) << terrain_k_val if terrain_k_val > 0 else t
    cantor_t = compute_subtree_cantor(
        t_base, terrain_k_val, max_compute_height=TEMPORAL_MAX_COMPUTE_HEIGHT,
    )

    # --- 4D combination (§5.5.3) ---
    hop_n = cantor_pair(region_n, cantor_t)

    # --- proof hash (§5.7): double SHA-256 ---
    hop_bytes = int_to_bytes_be_min(hop_n)
    movement_proof_key = sha256(hop_bytes)
    proof_hash = sha256(movement_proof_key).hex()

    return HopProof(
        cantor_x=cx,
        cantor_y=cy,
        cantor_z=cz,
        region_n=region_n,
        terrain_k=terrain_k_val,
        temporal_seed=t,
        cantor_t=cantor_t,
        hop_n=hop_n,
        proof_hash=proof_hash,
    )
