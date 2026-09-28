"""DECK-0001 section 5: a ride's proof, with ride openings version 2.

A ride from B_from to B_to passes the blocks lo + 1 .. hi. Each block's leaf
is a Cantor tree seeded by the rider's previous event id, at a height the
block's hash chooses (5.3), and the proof is the Merkle root over those
leaves, padded to a power of two with PAD_LEAF (5.4). Version 2 of the
openings (5.5, 5.8) draws the SAMPLES sampled positions from G, and G costs
work: one attempt is one Cantor tree at GRIND_HEIGHT, and the prover
publishes (in the mn tag) a nonce whose G, read as an integer, times
A = ceil(n / SAMPLES) is below 2^256. A fresh set of samples therefore costs
about one thirty-second of the ride, so a prover that skips blocks gains
nothing by retrying until the samples miss them. The leaves and the root are
unchanged from version 1; only the sample positions moved, from the root to G.

This CLI does not build rides yet: its hyperjump is still the pre-v3 event,
with no proof and no openings. This module is the construction and the
Level 1 check of a ride's proof, locked to the spec's
decks/hyperjump-reference.py, for when it does and for checking the rides
other clients publish.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from cyberspace_core.cantor import int_to_bytes_be_min, sha256
from cyberspace_core.coords import AXIS_BITS
from cyberspace_core.movement import compute_subtree_cantor, decode_nonce, encode_nonce, meets_price

K_LINE = 6
SAMPLES = 32
GRIND_HEIGHT = 16
HYPERSPACE_TERRAIN_DOMAIN = b"CYBERSPACE_HYPERSPACE_TERRAIN_V1"
HYPERSPACE_SEED_DOMAIN = b"CYBERSPACE_HYPERSPACE_SEED_V1"
HYPERSPACE_LEAF_DOMAIN = b"CYBERSPACE_HYPERSPACE_LEAF_V1"
HYPERSPACE_GRIND_DOMAIN = b"CYBERSPACE_HYPERSPACE_GRIND_V1"
HYPERSPACE_SAMPLE_DOMAIN = b"CYBERSPACE_HYPERSPACE_SAMPLE_V2"
PAD_LEAF = bytes(32)
# A block's height is K_b + K_LINE, and K_b is a popcount of 16 bits.
MAX_BLOCK_HEIGHT = K_LINE + 16
# A nonce search that expects at least this many attempts runs across
# processes, one attempt (one height-16 tree, about as much as one block) per task.
PARALLEL_RIDE_ATTEMPTS = 4

BlockHash = Callable[[int], bytes]


def line_terrain_k(block_hash: bytes) -> int:
    """5.3 step 1: the popcount of the first 16 bits of SHA256(TERRAIN_DOMAIN || H_b)."""
    d = sha256(HYPERSPACE_TERRAIN_DOMAIN + block_hash)
    return bin((d[0] << 8) | d[1]).count("1")


def ride_leaf(previous_event_id: bytes, b: int, block_hash: bytes) -> bytes:
    """5.3: block b's leaf. `block_hash` is the block's 32-byte hash in display order."""
    h = line_terrain_k(block_hash) + K_LINE
    t = int.from_bytes(sha256(HYPERSPACE_SEED_DOMAIN + previous_event_id + b.to_bytes(8, "big")), "big") % (1 << AXIS_BITS)
    cantor_t = compute_subtree_cantor((t >> h) << h, h, max_compute_height=MAX_BLOCK_HEIGHT)
    return sha256(HYPERSPACE_LEAF_DOMAIN + b.to_bytes(8, "big") + int_to_bytes_be_min(cantor_t))


def ride_depth(n: int) -> int:
    """log2 of the padded leaf count: the siblings in each path (5.5)."""
    return (n - 1).bit_length() if n > 0 else 0


def merkle_levels(leaves: Sequence[bytes]) -> List[List[bytes]]:
    """5.4: every level of the tree over the leaves padded with PAD_LEAF to a
    power of two, the leaves first and the root last."""
    level = list(leaves) + [PAD_LEAF] * ((1 << ride_depth(len(leaves))) - len(leaves))
    out = [level]
    while len(level) > 1:
        level = [sha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        out.append(level)
    return out


def path_of(levels: List[List[bytes]], index: int) -> List[bytes]:
    """The siblings of the leaf at `index`, from the leaf level to the root."""
    out = []
    for level in levels[:-1]:
        out.append(level[index ^ 1])
        index >>= 1
    return out


def verify_path(leaf: bytes, index: int, path: Sequence[bytes], root: bytes) -> bool:
    for sibling in path:
        leaf = sha256(leaf + sibling) if index % 2 == 0 else sha256(sibling + leaf)
        index >>= 1
    return leaf == root


# ---------------------------------------------------------------- the re-roll price (5.5)

def attempts_required(n: int) -> int:
    """A = max(1, ceil(n / SAMPLES)): an attempt costs about one block, so
    the price of one set of samples is about one thirty-second of the ride."""
    return max(1, -(-n // SAMPLES))


def grind_attempt(previous_event_id: bytes, root: bytes, nonce: int) -> bytes:
    """One attempt (5.5), one Cantor tree at GRIND_HEIGHT; returns G. The
    height is fixed, so a prover cannot pass over the expensive attempts."""
    if not 0 <= nonce < 1 << 64:
        raise ValueError("nonce must be an unsigned 64-bit integer")
    seed = sha256(HYPERSPACE_GRIND_DOMAIN + previous_event_id + root + nonce.to_bytes(8, "big"))
    g_base = ((int.from_bytes(seed, "big") % (1 << AXIS_BITS)) >> GRIND_HEIGHT) << GRIND_HEIGHT
    cantor_g = compute_subtree_cantor(g_base, GRIND_HEIGHT, max_compute_height=GRIND_HEIGHT)
    return sha256(HYPERSPACE_GRIND_DOMAIN + seed + int_to_bytes_be_min(cantor_g))


def sample_indices(G: bytes, n: int) -> List[int]:
    """5.5: SHA256(SAMPLE_DOMAIN || G || be32(i)) mod n for i in 0..31, positions
    among the n real leaves (0 is block lo + 1)."""
    return [int.from_bytes(sha256(HYPERSPACE_SAMPLE_DOMAIN + G + i.to_bytes(4, "big")), "big") % n for i in range(SAMPLES)]


def _attempt_meets_price(previous_event_id: bytes, root: bytes, attempts: int, nonce: int) -> bool:
    return meets_price(grind_attempt(previous_event_id, root, nonce), attempts)


def find_ride_nonce(
    previous_event_id: bytes,
    root: bytes,
    n: int,
    *,
    start: int = 0,
    workers: Optional[int] = None,
    on_progress: Optional[Callable[[int], None]] = None,
) -> int:
    """The smallest nonce >= start that meets the price for a ride of n blocks.
    A long ride needs thousands of height-16 attempts, so from
    PARALLEL_RIDE_ATTEMPTS expected attempts they run across processes
    (workers=1 keeps them here). on_progress hears how many nonces have been
    tried; `start` resumes an interrupted search, every nonce below it having
    failed, and gives the answer an uninterrupted search would have."""
    attempts = attempts_required(n)
    check = partial(_attempt_meets_price, previous_event_id, root, attempts)
    if attempts >= PARALLEL_RIDE_ATTEMPTS and workers != 1:
        from cyberspace_core.merkle_engine import parallel_first

        return parallel_first(check, start=start, chunk=1, workers=workers, on_progress=on_progress)
    nonce = start
    while not check(nonce):
        nonce += 1
        if on_progress is not None:
            on_progress(nonce - start)
    return nonce


# ---------------------------------------------------------------- prove and verify (5.5, 5.6)

def prove_ride(
    previous_event_id: bytes,
    lo: int,
    hi: int,
    block_hash: BlockHash,
    *,
    workers: Optional[int] = None,
    on_progress: Optional[Callable[[int], None]] = None,
) -> Tuple[bytes, int, List[List[bytes]]]:
    """(root, nonce, openings) for the blocks lo + 1 .. hi: every leaf and the
    root, then the nonce, then the paths at the positions drawn from G. A
    zero-length ride is the zero root, nonce 0 and no openings (5.6)."""
    n = hi - lo
    if n < 0:
        raise ValueError("lo must not exceed hi")
    if n == 0:
        return PAD_LEAF, 0, []
    levels = merkle_levels([ride_leaf(previous_event_id, b, block_hash(b)) for b in range(lo + 1, hi + 1)])
    root = levels[-1][0]
    nonce = find_ride_nonce(previous_event_id, root, n, workers=workers, on_progress=on_progress)
    G = grind_attempt(previous_event_id, root, nonce)
    return root, nonce, [path_of(levels, i) for i in sample_indices(G, n)]


def verify_ride(
    previous_event_id: bytes,
    lo: int,
    hi: int,
    block_hash: BlockHash,
    root: bytes,
    nonce: int,
    openings: List[List[bytes]],
) -> List[str]:
    """Level 1 of a ride's proof (5.5 steps 3 to 6): replay one attempt and
    check the price, draw the samples from G, recompute each sampled leaf from
    its block and carry it to the root. Returns the failed checks."""
    n = hi - lo
    if n == 0:
        failures = []
        if root != PAD_LEAF:
            failures.append("proof: a zero-length ride's root is 32 zero bytes (5.6)")
        if nonce != 0:
            failures.append("mn: a zero-length ride's nonce is 16 zeros (5.6)")
        if openings:
            failures.append("mp: a zero-length ride has nothing to open (5.6)")
        return failures
    depth = ride_depth(n)
    if len(openings) != SAMPLES or any(len(p) != depth for p in openings):
        return [f"mp: expected {SAMPLES} paths of {depth} siblings (5.5)"]
    G = grind_attempt(previous_event_id, root, nonce)
    if not meets_price(G, attempts_required(n)):
        # Every sampled leaf repeats a block's work; none of it can rescue an unpaid G.
        return [f"mn: nonce {encode_nonce(nonce)} does not meet the re-roll price, A={attempts_required(n)} (5.5)"]
    failures = []
    for i, (idx, path) in enumerate(zip(sample_indices(G, n), openings)):
        b = lo + 1 + idx
        if not verify_path(ride_leaf(previous_event_id, b, block_hash(b)), idx, path, root):
            failures.append(f"mp: sample {i} (block {b}) does not reach the root")
    return failures


def encode_ride_openings(openings: List[List[bytes]]) -> str:
    """The mp value (5.5): the paths joined by ':', each its siblings as lowercase hex."""
    return ":".join("".join(s.hex() for s in path) for path in openings)


def _is_hex(value: str) -> bool:
    return all(c in "0123456789abcdef" for c in value)


def decode_ride_openings(value: str, n: int) -> Optional[List[List[bytes]]]:
    """The openings in an mp value for a ride of n blocks, or None when
    malformed. A zero-length ride's mp is empty."""
    if n == 0:
        return [] if value == "" else None
    depth = ride_depth(n)
    parts = value.split(":")
    if len(parts) != SAMPLES or any(len(p) != 64 * depth or not _is_hex(p) for p in parts):
        return None
    return [[bytes.fromhex(p[64 * k:64 * (k + 1)]) for k in range(depth)] for p in parts]


def _height(value: Optional[str]) -> Optional[int]:
    return int(value) if isinstance(value, str) and value.isascii() and value.isdigit() else None


def verify_ride_event(event: Dict[str, Any], block_hash: BlockHash) -> List[str]:
    """Level 1 of a published hyperjump's proof (5.5 steps 3 to 6). Returns
    the failed checks; empty means the proof holds.

    The rest of a ride's validity needs the chain and Bitcoin's block data and
    stays with the caller: the chain rule of 4.3 (station and as_of), C
    against the stop coordinate of B (section 1), and the NIP-01 signature.
    `block_hash(b)` returns block b's 32-byte hash in display order.

    A ride without an mn tag is invalid unless its id is listed in
    decks/grandfathered-v1-hyperjumps.txt (5.8). A listed ride's root and
    openings are taken as audited and not recomputed, so no block hash is
    needed for it; its tags are still checked."""
    from cyberspace_core.grandfathered import GRANDFATHERED_V1_HYPERJUMPS, is_grandfathered

    tags = [t for t in (event.get("tags") or []) if isinstance(t, list) and len(t) >= 2]

    def value(name: str) -> Optional[str]:
        return next((t[1] for t in tags if t[0] == name), None)

    if value("A") != "hyperjump":
        return ["A: not a hyperjump"]
    failures: List[str] = []
    prev_hex = next((t[1] for t in tags if t[0] == "e" and len(t) >= 4 and t[3] == "previous"), None)
    if not isinstance(prev_hex, str) or len(prev_hex) != 64 or not _is_hex(prev_hex):
        failures.append("e previous: missing or not 32 bytes of lowercase hex")
    from_height, to_height = _height(value("from_height")), _height(value("B"))
    if from_height is None:
        failures.append("from_height: missing or not a base-10 block height")
    if to_height is None:
        failures.append("B: missing or not a base-10 block height")
    proof = value("proof")
    if not isinstance(proof, str) or len(proof) != 64 or not _is_hex(proof):
        failures.append("proof: missing or not a 32-byte lowercase hex root")
    if value("mp") is None:
        failures.append("mp: missing")
    if failures:
        return failures
    assert from_height is not None and to_height is not None and prev_hex is not None and proof is not None
    lo, hi = min(from_height, to_height), max(from_height, to_height)

    mn = value("mn")
    if mn is None:
        if not is_grandfathered(event, GRANDFATHERED_V1_HYPERJUMPS):
            failures.append("mn: missing; a ride without mn not listed in decks/grandfathered-v1-hyperjumps.txt (5.8)")
        return failures
    nonce = decode_nonce(mn)
    if nonce is None:
        return ["mn: not exactly 16 lowercase hex characters"]
    openings = decode_ride_openings(value("mp") or "", hi - lo)
    if openings is None:
        if hi == lo:
            return ["mp: a zero-length ride has nothing to open (5.6)"]
        return [f"mp: not {SAMPLES} colon-joined paths of {ride_depth(hi - lo)} siblings each (5.5)"]
    return verify_ride(bytes.fromhex(prev_hex), lo, hi, block_hash, bytes.fromhex(proof), nonce, openings)
