from __future__ import annotations

import sys
from dataclasses import dataclass

from typing import Dict, List, Tuple

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256, sha256_int_hex
from cyberspace_core.coords import AXIS_BITS
from cyberspace_core.terrain import terrain_k

DEFAULT_MAX_COMPUTE_HEIGHT = 20

# Domain separation constant for sidestep Merkle leaf hashes (spec §4.1).
SIDESTEP_DOMAIN = b"CYBERSPACE_SIDESTEP_V1"

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


# ---------------------------------------------------------------------------
# Sidestep proof — Merkle tree over SHA256 leaf hashes (spec §5.9 / formal spec)
# ---------------------------------------------------------------------------


def merkle_leaf(value: int) -> bytes:
    """Compute a Merkle leaf hash with domain separation.

    H_i = SHA256(SIDESTEP_DOMAIN || int_to_bytes_be_min(value))
    """
    return sha256(SIDESTEP_DOMAIN + int_to_bytes_be_min(value))


def merkle_parent(left: bytes, right: bytes) -> bytes:
    """Compute a Merkle internal node: SHA256(left || right)."""
    return sha256(left + right)


def compute_axis_merkle_root_streaming(
    base: int,
    height: int,
) -> Tuple[bytes, List[bytes]]:
    """Compute the Merkle root for an aligned subtree using streaming computation.

    This uses O(h × 32 bytes) working memory instead of O(2^h) by processing
    leaves in ascending order and maintaining a stack of pending hashes.

    Returns (merkle_root, inclusion_proof_siblings) where inclusion_proof_siblings
    is the list of sibling hashes from the *first* leaf (base) to the root.

    Parameters
    ----------
    base : aligned subtree base value
    height : LCA height (tree has 2^height leaves)

    Returns
    -------
    (root: bytes, inclusion_proof: list[bytes])
        root is the 32-byte Merkle root.
        inclusion_proof contains the sibling hashes for the leaf at index 0
        (which is always the source side leaf in a sidestep).
    """
    if height == 0:
        root = merkle_leaf(base)
        return root, []

    leaf_count = 1 << height

    # Stack-based streaming Merkle tree computation.
    # Each entry is (hash, level) where level 0 = leaf.
    stack: List[Tuple[bytes, int]] = []

    # Track sibling hashes for inclusion proof of leaf at index 0.
    # We collect siblings at each level as we build the tree.
    inclusion_siblings: List[bytes] = []

    for i in range(leaf_count):
        current_hash = merkle_leaf(base + i)
        current_level = 0

        while stack and stack[-1][1] == current_level:
            sibling_hash, _ = stack.pop()

            # If we're building the path for leaf 0, track siblings.
            # At level L, the sibling for leaf 0's path is the right child
            # when leaf 0's ancestor at that level is the left child.
            # Leaf 0 is always on the leftmost path, so its ancestor at level L
            # has index 0 — always a left child. The sibling is always right.
            if len(inclusion_siblings) == current_level:
                # sibling_hash was the left child (popped from stack),
                # current_hash is the right child being combined.
                # For leaf 0: at level 0, the first pair is leaf[0] and leaf[1].
                # leaf[0] was pushed to stack, leaf[1] arrives as current_hash.
                # So sibling of leaf[0] at level 0 is current_hash (leaf[1]).
                # Wait — let me reconsider. The stack pops sibling_hash (left)
                # and we combine with current_hash (right).
                # For leaf 0 path: we need the *sibling* at each level.
                # At level 0: leaf 0 is left, its sibling is leaf 1 (= current_hash).
                # At level 1: hash(leaf0,leaf1) is left, sibling is hash(leaf2,leaf3).
                # The sibling is always the one NOT on leaf 0's path.
                # Since leaf 0 is always on the leftmost path:
                # - left child = sibling_hash (from stack) — this IS on leaf 0's path
                # - right child = current_hash — this is the SIBLING
                inclusion_siblings.append(current_hash)

            # Parent = SHA256(left || right). Stack entry was left, current is right.
            current_hash = merkle_parent(sibling_hash, current_hash)
            current_level += 1

        stack.append((current_hash, current_level))

    assert len(stack) == 1, f"Expected single root on stack, got {len(stack)}"
    root = stack[0][0]
    assert len(inclusion_siblings) == height, (
        f"Expected {height} siblings for inclusion proof, got {len(inclusion_siblings)}"
    )
    return root, inclusion_siblings


def compute_axis_merkle_root(v1: int, v2: int) -> Tuple[bytes, List[bytes], int]:
    """Compute the Merkle root for the LCA subtree between two axis values.

    Returns (merkle_root, inclusion_proof_siblings, lca_height).

    For trivial axes where v1 == v2, returns the single leaf hash with empty
    inclusion proof and height 0.

    For heights >= 20, uses the parallel C-accelerated Merkle engine if
    available, which can be 10-30x faster on multi-core systems.
    """
    h = find_lca_height(v1, v2)
    if h == 0:
        root = merkle_leaf(v1)
        return root, [], 0
    base = (v1 >> h) << h

    # Use parallel engine for large trees
    if h >= 20:
        try:
            from cyberspace_core.merkle_engine import parallel_merkle_root_with_proof
            root, siblings = parallel_merkle_root_with_proof(base, h)
            return root, siblings, h
        except ImportError:
            pass

    root, siblings = compute_axis_merkle_root_streaming(base, h)
    return root, siblings, h


def verify_merkle_inclusion(
    leaf_value: int,
    siblings: List[bytes],
    expected_root: bytes,
    height: int,
    base: int,
) -> bool:
    """Verify a Merkle inclusion proof for a given leaf value.

    Parameters
    ----------
    leaf_value : the coordinate value of the leaf to verify
    siblings : sibling hashes from leaf level to root
    expected_root : the claimed Merkle root
    height : LCA height of the subtree
    base : aligned subtree base value

    Returns True if the inclusion proof is valid.
    """
    if height == 0:
        return merkle_leaf(leaf_value) == expected_root and len(siblings) == 0

    if len(siblings) != height:
        return False

    # Determine leaf index within the subtree
    leaf_index = leaf_value - base
    current = merkle_leaf(leaf_value)

    for level in range(height):
        sibling = siblings[level]
        # At each level, determine if current node is left or right child
        # based on the bit at this level of the leaf index.
        if (leaf_index >> level) & 1 == 0:
            # Current is left child, sibling is right
            current = merkle_parent(current, sibling)
        else:
            # Current is right child, sibling is left
            current = merkle_parent(sibling, current)

    return current == expected_root


@dataclass(frozen=True)
class SidestepProof:
    """Full sidestep proof (spatial Merkle + temporal Cantor) per formal spec."""
    merkle_x: bytes          # 32-byte Merkle root for X axis
    merkle_y: bytes          # 32-byte Merkle root for Y axis
    merkle_z: bytes          # 32-byte Merkle root for Z axis
    region_m: int            # π(π(mx, my), mz) — spatial region integer
    terrain_k: int           # terrain-derived temporal height K
    temporal_seed: int       # t = prev_event_id_int % 2^85
    cantor_t: int            # temporal axis Cantor root
    sidestep_n: int          # π(region_m, cantor_t)
    proof_hash: str          # double_SHA256(sidestep_n).hex()
    lca_heights: Tuple[int, int, int]    # (hx, hy, hz)
    inclusion_proofs: Dict[str, List[bytes]]  # {"x": [...], "y": [...], "z": [...]}


def compute_sidestep_proof(
    x1: int,
    y1: int,
    z1: int,
    x2: int,
    y2: int,
    z2: int,
    *,
    plane: int,
    previous_event_id_hex: str,
) -> SidestepProof:
    """Compute a full sidestep proof (Merkle spatial + Cantor temporal).

    Parameters
    ----------
    x1, y1, z1 : origin u85 axis values
    x2, y2, z2 : destination u85 axis values
    plane       : destination plane bit (0 or 1)
    previous_event_id_hex : 64-char lowercase hex string
    """
    # --- spatial component: per-axis Merkle roots ---
    mx, siblings_x, hx = compute_axis_merkle_root(x1, x2)
    my, siblings_y, hy = compute_axis_merkle_root(y1, y2)
    mz, siblings_z, hz = compute_axis_merkle_root(z1, z2)

    # Combine via Cantor pairing (same structure as hop)
    mx_int = int.from_bytes(mx, "big")
    my_int = int.from_bytes(my, "big")
    mz_int = int.from_bytes(mz, "big")
    region_m = cantor_pair(cantor_pair(mx_int, my_int), mz_int)

    # --- temporal component (identical to hop proof) ---
    terrain_k_val = terrain_k(x=x2, y=y2, z=z2, plane=plane)

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

    t_base = (t >> terrain_k_val) << terrain_k_val if terrain_k_val > 0 else t
    cantor_t_val = compute_subtree_cantor(
        t_base, terrain_k_val, max_compute_height=TEMPORAL_MAX_COMPUTE_HEIGHT,
    )

    # --- 4D combination ---
    sidestep_n = cantor_pair(region_m, cantor_t_val)

    # --- proof hash: double SHA256 ---
    sidestep_bytes = int_to_bytes_be_min(sidestep_n)
    proof_key = sha256(sidestep_bytes)
    proof_hash = sha256(proof_key).hex()

    return SidestepProof(
        merkle_x=mx,
        merkle_y=my,
        merkle_z=mz,
        region_m=region_m,
        terrain_k=terrain_k_val,
        temporal_seed=t,
        cantor_t=cantor_t_val,
        sidestep_n=sidestep_n,
        proof_hash=proof_hash,
        lca_heights=(hx, hy, hz),
        inclusion_proofs={"x": siblings_x, "y": siblings_y, "z": siblings_z},
    )
