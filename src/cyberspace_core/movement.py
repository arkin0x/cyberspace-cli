from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from functools import partial

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256, sha256_int_hex
from cyberspace_core.coords import AXIS_BITS, AXIS_MAX, coord_to_xyz
from cyberspace_core.terrain import terrain_k

DEFAULT_MAX_COMPUTE_HEIGHT = 20

# Domain separation constant for sidestep Merkle leaf hashes (spec §4.1).

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


# ============================================================================
# Sidestep version 3 (CYBERSPACE_V2 section 6, revised 2026-09-28)
#
# The sidestep is a toll. Every leaf is hashed under a 64-byte seed prefix:
# the V2 domain, the mover's previous event id, an axis byte and nine zero
# bytes, so a tree is unique to one chain position and one axis. The prefix
# fills exactly one SHA-256 block, so its state is taken once per axis and
# each leaf costs one compression (6.5). With no canonical root to compare
# against, the prover publishes openings (6.10): the destination leaf's path
# and eight sampled paths, which a verifier recomputes from the seed.
#
# Version 3 puts a price on the samples (6.10, 6.16). They are drawn from G,
# a hash of a nonce, the previous event id and all three axis roots, and the
# prover publishes (in the mn tag) a nonce whose G, read as an integer, times
# A = ceil(leaves / 8) is below 2^256. A fresh set of samples therefore costs
# about one eighth of the tree, which is what makes building part of the tree
# and retrying until the samples miss the rest cost more than building all of
# it (6.11). The tree, its leaves and its roots are unchanged from version 2.
# A prover works in order: every axis root (one streaming pass), then the
# nonce, then the openings at the destination and at the positions drawn from
# G. Checked against the spec's sidestep-reference.py.
# ============================================================================

SIDESTEP_DOMAIN = b"CYBERSPACE_SIDESTEP_V2"
SEED_PAD = b"\x00" * 9
SIDESTEP_GRIND_DOMAIN = b"CYBERSPACE_SIDESTEP_GRIND_V1"
SIDESTEP_SAMPLE_DOMAIN = b"CYBERSPACE_SIDESTEP_SAMPLE_V2"
SIDESTEP_SAMPLES = 8
AXIS_BYTE = {"x": 0, "y": 1, "z": 2}
# Nodes from this many levels below the root are kept from the main pass, so
# the openings can be assembled afterwards by rebuilding only the small
# subtree under each opened leaf: at most 2^17 hashes kept, whatever the height.
KEPT_LEVELS = 16
# A nonce search that expects at least this many attempts runs across
# processes, NONCE_CHUNK nonces per task; below it a pool costs more than it
# saves, since one attempt is a single SHA-256 of 164 bytes.
PARALLEL_NONCE_ATTEMPTS = 1 << 18
NONCE_CHUNK = 1 << 16


def seed_prefix(previous_event_id: bytes, axis_byte: int) -> bytes:
    """The per-axis seed prefix (6.4): exactly one SHA-256 block."""
    if len(previous_event_id) != 32:
        raise ValueError("previous_event_id must be 32 raw bytes")
    if axis_byte not in (0, 1, 2):
        raise ValueError("axis byte must be 0, 1 or 2")
    prefix = SIDESTEP_DOMAIN + previous_event_id + bytes([axis_byte]) + SEED_PAD
    assert len(prefix) == 64
    return prefix


def leaf_hasher(prefix: bytes) -> Callable[[int], bytes]:
    """A leaf hasher for one seed prefix, resuming from the prefix's state (6.5)."""
    if len(prefix) != 64:
        raise ValueError("seed prefix must be exactly one SHA-256 block")
    mid = hashlib.sha256(prefix)

    def leaf(value: int) -> bytes:
        h = mid.copy()
        h.update(int_to_bytes_be_min(value))
        return h.digest()

    return leaf


def merkle_leaf(prefix: bytes, value: int) -> bytes:
    """H = SHA256(seed_prefix || int_to_bytes_be_min(value))."""
    return sha256(prefix + int_to_bytes_be_min(value))


def merkle_parent(left: bytes, right: bytes) -> bytes:
    """Merkle internal node: SHA256(left || right)."""
    return sha256(left + right)


# ---------------------------------------------------------------- the re-roll price (6.10)

def reroll_attempts(heights: Sequence[int]) -> int:
    """A = max(1, ceil(L / SIDESTEP_SAMPLES)), with L the leaves over every axis
    that moves (6.10). An attempt costs one leaf's share of the tree, so A
    attempts, the expected price of one set of samples, are one eighth of it."""
    leaves = sum(1 << h for h in heights if h > 0)
    return max(1, -(-leaves // SIDESTEP_SAMPLES))


def grind_hash(previous_event_id: bytes, roots: Sequence[bytes], nonce: int) -> bytes:
    """G = SHA256(GRIND_DOMAIN || be64(nonce) || previous_event_id || M_x || M_y || M_z)
    (6.10). For a trivial axis M is its single seeded leaf. 164 bytes, three
    SHA-256 blocks with the nonce in the first, so no state carries from one
    attempt to the next."""
    if not 0 <= nonce < 1 << 64:
        raise ValueError("nonce must be an unsigned 64-bit integer")
    if len(previous_event_id) != 32 or len(roots) != 3 or any(len(r) != 32 for r in roots):
        raise ValueError("G takes a 32-byte previous event id and three 32-byte roots")
    return sha256(SIDESTEP_GRIND_DOMAIN + nonce.to_bytes(8, "big") + previous_event_id + b"".join(roots))


def meets_price(G: bytes, attempts: int) -> bool:
    """G, read as a 256-bit big-endian integer, times A is below 2^256: a
    nonce succeeds with probability 1/A."""
    return int.from_bytes(G, "big") * attempts < (1 << 256)


def _nonce_meets_price(previous_event_id: bytes, roots: Tuple[bytes, ...], attempts: int, nonce: int) -> bool:
    return meets_price(grind_hash(previous_event_id, roots, nonce), attempts)


def find_nonce(previous_event_id: bytes, roots: Sequence[bytes], attempts: int, *, workers: Optional[int] = None) -> int:
    """The smallest nonce that meets the price. Any valid nonce verifies; the
    smallest is what the spec's golden vectors publish, and it is the same
    however the search is split. A search that expects many attempts runs
    across processes over consecutive chunks of nonces (workers=1 keeps it in
    this process)."""
    check = partial(_nonce_meets_price, previous_event_id, tuple(roots), attempts)
    if attempts >= PARALLEL_NONCE_ATTEMPTS and workers != 1:
        from cyberspace_core.merkle_engine import parallel_first

        return parallel_first(check, chunk=NONCE_CHUNK, workers=workers)
    nonce = 0
    while not check(nonce):
        nonce += 1
    return nonce


def encode_nonce(nonce: int) -> str:
    """The mn tag value (8.5): exactly 16 lowercase hex characters, big-endian."""
    return nonce.to_bytes(8, "big").hex()


def decode_nonce(value: object) -> Optional[int]:
    """The nonce in an mn value, or None unless it is exactly 16 lowercase hex characters."""
    if not isinstance(value, str) or len(value) != 16 or any(c not in "0123456789abcdef" for c in value):
        return None
    return int(value, 16)


def sample_indices(G: bytes, axis_byte: int, height: int) -> List[int]:
    """The sampled positions for an axis (6.10), within the aligned subtree:
    SHA256(SAMPLE_DOMAIN || G || axis_byte || be32(i)) mod 2^h for i in 0..7.
    Not deduplicated, so the number of openings stays fixed."""
    if height == 0:
        return []
    return [
        int.from_bytes(sha256(SIDESTEP_SAMPLE_DOMAIN + G + bytes([axis_byte]) + i.to_bytes(4, "big")), "big") % (1 << height)
        for i in range(SIDESTEP_SAMPLES)
    ]


# ---------------------------------------------------------------- the tree, root first (6.5)

@dataclass(frozen=True)
class AxisTree:
    """One axis's seeded tree after the root pass: its root, and the paths of
    any leaves once G has said which ones to open. `paths` takes a list of
    indices within the aligned subtree and returns each leaf's siblings, leaf
    level first."""
    root: bytes
    base: int
    height: int
    paths: Callable[[Sequence[int]], List[List[bytes]]] = field(repr=False, compare=False)

    def openings(self, target_index: int, G: bytes, axis_byte: int) -> List[List[bytes]]:
        """The destination's path, then the eight sampled paths (6.10); none at height 0."""
        if self.height == 0:
            return []
        return self.paths([target_index] + sample_indices(G, axis_byte, self.height))


def _fold(leaf: Callable[[int], bytes], base: int, first: int, height: int, keep_from: int, keep: Callable[[int, int, bytes], None]) -> bytes:
    """A streaming fold over the leaves first .. first + 2^height - 1 (6.5), in
    O(height) memory. `keep` receives every node at or above level keep_from,
    by level and by its index within the level (absolute, from the tree's base)."""
    stack: List[Tuple[bytes, int, int]] = []
    for i in range(1 << height):
        at = first + i
        current, level, start = leaf(base + at), 0, at
        if keep_from == 0:
            keep(0, at, current)
        while stack and stack[-1][1] == level:
            left_hash, _, left_start = stack.pop()
            current = merkle_parent(left_hash, current)
            level += 1
            start = left_start
            if level >= keep_from:
                keep(level, start >> level, current)
        stack.append((current, level, start))
    assert len(stack) == 1, f"expected a single root, got {len(stack)}"
    return stack[0][0]


def compute_axis_merkle_root_streaming(prefix: bytes, base: int, height: int) -> AxisTree:
    """The root pass over the aligned subtree at `base` of `height` (6.5), in
    one process. The top KEPT_LEVELS levels of nodes are kept, and a path's
    lower siblings come from rebuilding the small subtree under its leaf, so
    the paths can be fetched after the nonce is found."""
    leaf = leaf_hasher(prefix)
    if height == 0:
        return AxisTree(leaf(base), base, 0, lambda indices: [[] for _ in indices])
    keep_from = max(0, height - KEPT_LEVELS)
    kept: Dict[Tuple[int, int], bytes] = {}
    root = _fold(leaf, base, 0, height, keep_from, lambda lvl, idx, h: kept.__setitem__((lvl, idx), h))

    def path_for(index: int) -> List[bytes]:
        if not 0 <= index < (1 << height):
            raise ValueError(f"index {index} outside subtree of {1 << height} leaves")
        siblings: List[Optional[bytes]] = [None] * height
        if keep_from > 0:
            size = 1 << keep_from
            first = (index // size) * size
            local: Dict[Tuple[int, int], bytes] = {}
            _fold(leaf, base, first, keep_from, 0, lambda lvl, idx, h: local.__setitem__((lvl, idx), h))
            for level in range(keep_from):
                siblings[level] = local[(level, (index >> level) ^ 1)]
        for level in range(keep_from, height):
            siblings[level] = kept[(level, (index >> level) ^ 1)]
        assert all(s is not None for s in siblings)
        return siblings  # type: ignore[return-value]

    return AxisTree(root, base, height, lambda indices: [path_for(i) for i in indices])


def compute_axis_merkle_root(prefix: bytes, v1: int, v2: int) -> AxisTree:
    """The root pass for one axis of a crossing from v1 to v2 (the whole
    aligned subtree of their LCA). From h20 the parallel engine builds the
    tree across cores."""
    h = find_lca_height(v1, v2)
    base = (v1 >> h) << h
    if h >= 20:
        try:
            from cyberspace_core.merkle_engine import parallel_merkle_tree

            return parallel_merkle_tree(prefix, base, h)
        except ImportError:
            pass
    return compute_axis_merkle_root_streaming(prefix, base, h)


# ---------------------------------------------------------------- Level 1 (6.11)

def verify_merkle_inclusion(prefix: bytes, leaf_value: int, siblings: List[bytes], root: bytes, height: int = 0, base: int = 0) -> bool:
    """Whether `siblings` carry the seeded leaf at leaf_value up to `root`."""
    if height == 0:
        return merkle_leaf(prefix, leaf_value) == root and len(siblings) == 0
    if len(siblings) != height:
        return False
    leaf_index = leaf_value - base
    if not 0 <= leaf_index < (1 << height):
        return False
    current = merkle_leaf(prefix, leaf_value)
    for level in range(height):
        if (leaf_index >> level) & 1 == 0:
            current = merkle_parent(current, siblings[level])
        else:
            current = merkle_parent(siblings[level], current)
    return current == root


def verify_axis_openings(prefix: bytes, axis_byte: int, v1: int, v2: int, root: bytes, openings: List[List[bytes]], G: bytes) -> bool:
    """Level 1 for one axis (6.11 steps 5 and 6): the destination's path, then
    each leaf at a position drawn from G recomputed from the seed and carried
    to the root. G must already have been checked against the price."""
    h = find_lca_height(v1, v2)
    if h == 0:
        return not openings and merkle_leaf(prefix, v1) == root
    if len(openings) != SIDESTEP_SAMPLES + 1 or any(len(p) != h for p in openings):
        return False
    base = (v1 >> h) << h
    if not verify_merkle_inclusion(prefix, v2, openings[0], root, h, base):
        return False
    for path, idx in zip(openings[1:], sample_indices(G, axis_byte, h)):
        if not verify_merkle_inclusion(prefix, base + idx, path, root, h, base):
            return False
    return True


def verify_sidestep_openings(
    previous_event_id: bytes,
    src: Sequence[int],
    dst: Sequence[int],
    roots: Sequence[bytes],
    nonce: int,
    openings: Dict[str, List[List[bytes]]],
) -> List[str]:
    """Level 1 over a whole crossing (6.11 steps 4 to 6): G from the nonce,
    the previous event id and the three claimed roots must meet the price,
    then every axis's openings must prove its seeded tree at the positions
    drawn from G. Returns the failed checks; empty means the openings hold.
    A G that misses the price fails the crossing whatever its samples say; the
    axes are still checked so that the report names every fault."""
    heights = [find_lca_height(a, b) for a, b in zip(src, dst)]
    attempts = reroll_attempts(heights)
    G = grind_hash(previous_event_id, roots, nonce)
    failures: List[str] = []
    if not meets_price(G, attempts):
        failures.append(f"mn: nonce {encode_nonce(nonce)} does not meet the re-roll price, A={attempts} (6.10)")
    for axis, v1, v2, root in zip("xyz", src, dst, roots):
        prefix = seed_prefix(previous_event_id, AXIS_BYTE[axis])
        if not verify_axis_openings(prefix, AXIS_BYTE[axis], v1, v2, root, openings.get(axis) or [], G):
            failures.append(f"merkle_{axis}: openings do not prove the seeded tree")
    return failures


def encode_openings(openings: List[List[bytes]]) -> str:
    """The mp segment for one axis (8.5): every opening's siblings, leaf first, as hex."""
    return "".join(s.hex() for path in openings for s in path)


def decode_openings(segment: str, height: int) -> Optional[List[List[bytes]]]:
    """The openings from an mp segment for an axis of LCA height `height`
    (8.5). None when malformed, and None for a v1 segment (one path rather
    than nine), which 6.15 says must be rejected."""
    if height == 0:
        return [] if segment == "" else None
    per = 64 * height
    if len(segment) != per * (SIDESTEP_SAMPLES + 1):
        return None
    try:
        raw = bytes.fromhex(segment)
    except ValueError:
        return None
    if segment != raw.hex():
        return None
    out = []
    for p in range(SIDESTEP_SAMPLES + 1):
        path = [raw[(p * height + level) * 32:(p * height + level + 1) * 32] for level in range(height)]
        out.append(path)
    return out


def sidestep_geometry_ok(v1: int, v2: int) -> bool:
    """6.3 for one axis: no movement, or a crossing whose source touches the
    wall and whose destination is the leaf on the other side. Two values one
    Gibson apart always straddle the wall of their LCA subtree with the source
    touching it, so this is |v2 - v1| <= 1; every longer move is a hop."""
    return abs(v2 - v1) <= 1


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
    openings: Dict[str, List[List[bytes]]]  # per axis: destination path, then 8 sampled paths (6.10)
    nonce: int               # the re-roll nonce (6.10), published as the mn tag via encode_nonce


def _previous_event_id_bytes(previous_event_id_hex: str) -> bytes:
    if not isinstance(previous_event_id_hex, str) or len(previous_event_id_hex) != 64 or previous_event_id_hex != previous_event_id_hex.lower():
        raise ValueError("previous_event_id_hex must be exactly 64 lowercase hex chars (32 bytes)")
    try:
        return bytes.fromhex(previous_event_id_hex)
    except ValueError as e:
        raise ValueError("previous_event_id_hex must be valid lowercase hex") from e


def _sidestep_binding(roots: Sequence[bytes], x2: int, y2: int, z2: int, plane: int, previous_event_id: bytes) -> Tuple[int, int, int, int, int, str]:
    """region_m (6.6), the temporal axis at the destination (6.7), and
    sidestep_n with its proof hash (6.8): (region_m, K, t, cantor_t, sidestep_n, proof_hash)."""
    mx, my, mz = (int.from_bytes(r, "big") for r in roots)
    region_m = cantor_pair(cantor_pair(mx, my), mz)
    k = terrain_k(x=x2, y=y2, z=z2, plane=plane)
    t = int.from_bytes(previous_event_id, "big") % (1 << AXIS_BITS)
    t_base = (t >> k) << k if k > 0 else t
    cantor_t = compute_subtree_cantor(t_base, k, max_compute_height=TEMPORAL_MAX_COMPUTE_HEIGHT)
    sidestep_n = cantor_pair(region_m, cantor_t)
    return region_m, k, t, cantor_t, sidestep_n, sha256(sha256(int_to_bytes_be_min(sidestep_n))).hex()


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
    prev_bytes = _previous_event_id_bytes(previous_event_id_hex)

    # --- every axis root first: the seeded trees (6.4, 6.5) ---
    src, dst = (x1, y1, z1), (x2, y2, z2)
    trees = {axis: compute_axis_merkle_root(seed_prefix(prev_bytes, AXIS_BYTE[axis]), v1, v2) for axis, v1, v2 in zip("xyz", src, dst)}
    roots = [trees[axis].root for axis in "xyz"]
    heights = (trees["x"].height, trees["y"].height, trees["z"].height)

    # --- then the nonce, which prices the samples (6.10) ---
    nonce = find_nonce(prev_bytes, roots, reroll_attempts(heights))
    G = grind_hash(prev_bytes, roots, nonce)

    # --- then the openings at the destination and at the positions drawn from G ---
    openings = {
        axis: trees[axis].openings(v2 - trees[axis].base, G, AXIS_BYTE[axis]) for axis, v2 in zip("xyz", dst)
    }

    # --- region_m, the temporal axis (identical to a hop's) and the proof hash ---
    region_m, k, t, cantor_t_val, sidestep_n, proof_hash = _sidestep_binding(roots, x2, y2, z2, plane, prev_bytes)

    return SidestepProof(
        merkle_x=roots[0],
        merkle_y=roots[1],
        merkle_z=roots[2],
        region_m=region_m,
        terrain_k=k,
        temporal_seed=t,
        cantor_t=cantor_t_val,
        sidestep_n=sidestep_n,
        proof_hash=proof_hash,
        lca_heights=heights,
        openings=openings,
        nonce=nonce,
    )


def _hex_bytes(value: object, size: int) -> Optional[bytes]:
    """`size` bytes from exactly 2 * size lowercase hex characters, else None."""
    if not isinstance(value, str) or len(value) != 2 * size or any(c not in "0123456789abcdef" for c in value):
        return None
    return bytes.fromhex(value)


def verify_sidestep_event(event: Dict[str, Any]) -> List[str]:
    """Level 1 verification of a published sidestep event (8.7.2). Returns the
    failed checks; empty means valid.

    Chain linkage (the c tag is the previous event's C, and e previous names
    that event) needs the chain and stays with the caller, as does the NIP-01
    signature. An event without an mn tag is a version 2 proof and is invalid
    unless its id is listed in grandfathered-v2-sidesteps.txt (6.16). A listed
    event's roots and openings are taken as audited, and its geometry, height
    tags and proof hash are checked exactly as for any other sidestep."""
    from cyberspace_core.grandfathered import GRANDFATHERED_V2_SIDESTEPS, is_grandfathered

    tags = [t for t in (event.get("tags") or []) if isinstance(t, list) and len(t) >= 2]

    def value(name: str) -> Optional[str]:
        return next((t[1] for t in tags if t[0] == name), None)

    if value("A") != "sidestep":
        return ["A: not a sidestep"]
    failures: List[str] = []
    prev = _hex_bytes(next((t[1] for t in tags if t[0] == "e" and len(t) >= 4 and t[3] == "previous"), None), 32)
    if prev is None:
        failures.append("e previous: missing or not 32 bytes of lowercase hex")
    points = []
    for name in ("c", "C"):
        raw = _hex_bytes(value(name), 32)
        if raw is None:
            failures.append(f"{name}: missing or not a 32-byte lowercase hex coordinate")
        else:
            points.append(coord_to_xyz(int.from_bytes(raw, "big")))
    roots = [_hex_bytes(r, 32) for r in (value("mr") or "").split(":")]
    if len(roots) != 3 or any(r is None for r in roots):
        failures.append("mr: not three colon-separated 32-byte lowercase hex roots")
    if failures:
        return failures
    assert prev is not None
    (x1, y1, z1, _), (x2, y2, z2, plane) = points
    src, dst = (x1, y1, z1), (x2, y2, z2)
    heights = [find_lca_height(a, b) for a, b in zip(src, dst)]

    # 6.3: each axis that moves crosses exactly one wall, by exactly one Gibson
    for axis, v1, v2 in zip("xyz", src, dst):
        if not sidestep_geometry_ok(v1, v2):
            failures.append(f"geometry: axis {axis} moves {v2 - v1:+d} gibsons; a sidestep crosses one wall by one gibson (6.3)")
    for axis, h in zip("xyz", heights):
        if value(f"h{axis}") != str(h):
            failures.append(f"h{axis}: tag {value(f'h{axis}')!r} but the coordinates give {h}")

    # 6.10, 6.11: the price and the openings, unless listed under 6.16
    mn = value("mn")
    if mn is None:
        if not is_grandfathered(event, GRANDFATHERED_V2_SIDESTEPS):
            failures.append("mn: missing; a version 2 sidestep not listed in grandfathered-v2-sidesteps.txt (6.16)")
    else:
        nonce = decode_nonce(mn)
        segments = (value("mp") or "").split(":")
        if nonce is None:
            failures.append("mn: not exactly 16 lowercase hex characters")
        elif len(segments) != 3:
            failures.append("mp: not three colon-separated axis segments")
        else:
            openings = {axis: decode_openings(seg, h) for axis, seg, h in zip("xyz", segments, heights)}
            bad = [axis for axis, o in openings.items() if o is None]
            for axis in bad:
                failures.append(f"mp: axis {axis} segment is malformed, or a version 1 single path (8.5, 6.15)")
            if not bad:
                failures += verify_sidestep_openings(prev, src, dst, roots, nonce, openings)  # type: ignore[arg-type]

    # 6.6 to 6.8: the proof hash of the claimed roots at this chain position
    if value("proof") != _sidestep_binding(roots, x2, y2, z2, plane, prev)[5]:  # type: ignore[arg-type]
        failures.append("proof: does not match the proof hash of the claimed roots (6.8)")
    return failures


@dataclass(frozen=True)
class CoordPreview:
    """Preview data for a single coordinate in the movement visualizer."""
    offset: int                # Signed offset from current position (Gibsons)
    axis_value: int            # Actual u85 axis value
    lca_height: int            # LCA height between current and this coord
    terrain_k: int             # Terrain difficulty (0-16)
    subtree_size: int          # 2^lca_height (number of leaves in subtree)
    is_current: bool           # True if this is the current position


def preview_movement(
    current_x: int,
    current_y: int,
    current_z: int,
    virtual_x: int,
    virtual_y: int,
    virtual_z: int,
    axis: str,
    span: int,
    plane: int = 0,
) -> Tuple[str, int, List[CoordPreview]]:
    """Generate preview data for movement visualization.
    
    Parameters
    ----------
    current_x, current_y, current_z : current actual position (u85 values)
    virtual_x, virtual_y, virtual_z : virtual offset from current position
    axis : which axis to visualize ('x', 'y', or 'z')
    span : number of coordinates to show on each side of center
    plane : current plane (0 or 1)
    
    Returns
    -------
    (axis_name, current_value, previews)
    - axis_name: 'X', 'Y', or 'Z'
    - current_value: the u85 value at the center
    - previews: list of CoordPreview for each visible coordinate
    """
    # Get current axis value
    if axis == 'x':
        current_val = current_x
        virtual_offset = virtual_x
        axis_name = 'X'
    elif axis == 'y':
        current_val = current_y
        virtual_offset = virtual_y
        axis_name = 'Y'
    elif axis == 'z':
        current_val = current_z
        virtual_offset = virtual_z
        axis_name = 'Z'
    else:
        raise ValueError(f"Invalid axis: {axis}")
    
    # Virtual position
    virtual_pos = current_val + virtual_offset
    
    # Generate previews for the span
    previews = []
    for offset in range(-span, span + 1):
        axis_value = virtual_pos + offset
        if axis_value < 0 or axis_value > AXIS_MAX:
            continue
        
        signed_offset = offset + virtual_offset  # Total offset from actual position
        lca_h = find_lca_height(current_val, axis_value)
        t_k = terrain_k_value_for_axis(axis, axis_value, plane)
        subtree = 1 << lca_h if lca_h > 0 else 1
        
        previews.append(CoordPreview(
            offset=signed_offset,
            axis_value=axis_value,
            lca_height=lca_h,
            terrain_k=t_k,
            subtree_size=subtree,
            is_current=(offset == -virtual_offset),
        ))
    
    return axis_name, virtual_pos, previews


def terrain_k_value_for_axis(axis: str, axis_value: int, plane: int) -> int:
    """Get terrain_k for a coordinate on a single axis.
    
    Since terrain_k expects x, y, z coordinates, we hold the other axes
    at their current values (approximation for visualization).
    
    For visualization purposes, we use the axis value as all three coordinates
    to get a representative terrain difficulty.
    """
    # Use the axis value as a proxy for full 3D position
    # This is an approximation but sufficient for visualization
    if axis == 'x':
        return terrain_k(x=axis_value, y=axis_value, z=axis_value, plane=plane)
    elif axis == 'y':
        return terrain_k(x=axis_value, y=axis_value, z=axis_value, plane=plane)
    else:
        return terrain_k(x=axis_value, y=axis_value, z=axis_value, plane=plane)
