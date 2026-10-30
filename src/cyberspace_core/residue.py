"""Residue openings, version 2 of the hop proof (CYBERSPACE_V2 sections 5.9 to
5.13, 8.4, 8.7.1), ported from the spec's hop-residue-reference.py.

The Cantor work of a hop is unchanged (the three axis trees, the temporal tree
at terrain height K, hop_n). Only the commitment changes: the prover computes
hop_n modulo m primes p_j, each drawn on its own from (previous_event_id, j),
seals that list in a Merkle tree, pays a re-roll price in residue work, and
publishes 16 entries of the list with their paths. The proof tag carries the
seal, mn the nonce, mp the 16 openings.

A Cantor root reduced modulo an odd p is the same tree carried in Z/pZ, with
halving replaced by multiplication by (p + 1) / 2, so a verifier computes
hop_n mod p in word-sized arithmetic without building any root (5.9). Level 1
(5.11) recomputes the 16 opened residues; Level 2 recomputes all m and
rebuilds the seal.

Two engines compute a residue of a root. residue_tree and residue_engine are
the reference's (the tree carried mod p, and Babbage's method of differences
at level k). residue_root is the one this module uses: the same method of
differences, with its difference table packed into one big integer, so that
the 2^k additions per node are three big-integer operations instead of a
Python loop. Every one returns the same value; the tests check it.

The prover never builds hop_n. It builds each root exactly, reduces it modulo
Q (the product of the m primes), pairs the reduced roots modulo Q (exact,
because Q is odd and a product of consecutive integers is even), and descends
a remainder tree from hop_n mod Q to every p_j. The big numbers are gmpy2's
when it is installed, otherwise Python's decimal (libmpdec, whose
multiplication and division are subquadratic, where Python 3.11's int division
is not), and plain int at small heights. The output is the same byte for byte
on every backend, and equal to the reference prover's.

Every tag value is validated before it is parsed: int(s, 16) and
bytes.fromhex accept "0x", "+", "_", whitespace and uppercase, none of which
the tags allow (8.4).
"""

from __future__ import annotations

import decimal
import functools
import hashlib
import math
import multiprocessing
import os
import re
from dataclasses import dataclass
from functools import partial
from typing import Callable, List, Optional, Sequence, Tuple

from cyberspace_core.coords import AXIS_BITS, coord_to_xyz
from cyberspace_core.terrain import terrain_k

try:  # optional: much faster big numbers for the prover and Level 2
    import gmpy2  # type: ignore[import-not-found]

    HAS_GMPY2 = True
except ImportError:  # pragma: no cover - depends on the environment
    gmpy2 = None
    HAS_GMPY2 = False

HOP_RESIDUE_PRIME_DOMAIN = b"CYBERSPACE_HOP_RESIDUE_PRIME_V1"     # 31 bytes
HOP_RESIDUE_LEAF_DOMAIN = b"CYBERSPACE_HOP_RESIDUE_LEAF_V1"       # 30 bytes
HOP_RESIDUE_GRIND_DOMAIN = b"CYBERSPACE_HOP_RESIDUE_GRIND_V1"     # 31 bytes
HOP_RESIDUE_SAMPLE_DOMAIN = b"CYBERSPACE_HOP_RESIDUE_SAMPLE_V1"   # 32 bytes
HOP_SAMPLES = 16              # residues the verifier recomputes
RESIDUE_BLOCK = 8             # residues per Merkle leaf
PRIME_BITS = 61               # every prime is at least 2^61
WIDTH_DIVISOR = 4             # Q spans at least a quarter of the widest root
HOP_GRIND_HEIGHT = 12         # one re-roll attempt is one aligned height-12 tree modulo p_0
# Re-roll budget per height, in attempts (5.10); above h22 each height costs
# 9/4 of the one below, in exact integer arithmetic.
HOP_REROLL_BUDGET = (0, 0, 0, 0, 0, 0, 1, 2, 4, 7, 14, 30, 65, 149, 355, 782, 1753, 4016,
                     8959, 20028, 44826, 99974, 223681)
SMALL_ODD_PRIMES = (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71,
                    73, 79, 83, 89, 97)
PAD_LEAF = bytes(32)

_SMALL_PRIMORIAL = math.prod(SMALL_ODD_PRIMES)
_LOWER_HEX = re.compile(r"[0-9a-f]*")

# Above these heights the work is spread over processes.
PARALLEL_PRIMES = 1 << 15         # prime derivations
PARALLEL_ATTEMPTS = 1 << 10       # expected re-roll attempts (A)
PARALLEL_VERIFY_HEIGHT = 21       # Level 1 samples
# From this h_max the prover's big numbers are decimal rather than int when
# gmpy2 is absent (measured crossover: int is faster below it).
DECIMAL_FROM_HEIGHT = 12


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def be32(n: int) -> bytes:
    return n.to_bytes(4, "big")


def be64(n: int) -> bytes:
    return n.to_bytes(8, "big")


# --------------------------------------------------------------------------- the strict codec (8.4)
def is_lower_hex(value: object, length: int) -> bool:
    """Exactly `length` characters, each one of 0-9 and a-f."""
    return isinstance(value, str) and len(value) == length and _LOWER_HEX.fullmatch(value) is not None


def opening_width(depth: int) -> int:
    """Characters of one opening: 8 residues of 16, then `depth` siblings of 64."""
    return 16 * RESIDUE_BLOCK + 64 * depth


def mp_length(depth: int) -> int:
    return HOP_SAMPLES * opening_width(depth)


Opening = Tuple[List[int], List[bytes]]  # (the block's 8 residues, its siblings from the leaf level up)


def decode_seal(proof: object) -> Optional[bytes]:
    return bytes.fromhex(proof) if is_lower_hex(proof, 64) else None  # type: ignore[arg-type]


def decode_nonce(mn: object) -> Optional[int]:
    return int(mn, 16) if is_lower_hex(mn, 16) else None  # type: ignore[arg-type]


def decode_openings(mp: object, depth: int) -> Optional[List[Opening]]:
    if not is_lower_hex(mp, mp_length(depth)):
        return None
    assert isinstance(mp, str)
    width, off = opening_width(depth), 16 * RESIDUE_BLOCK
    out: List[Opening] = []
    for k in range(HOP_SAMPLES):
        o = mp[k * width:(k + 1) * width]
        block = [int(o[16 * i:16 * (i + 1)], 16) for i in range(RESIDUE_BLOCK)]
        path = [bytes.fromhex(o[off + 64 * d:off + 64 * (d + 1)]) for d in range(depth)]
        out.append((block, path))
    return out


def encode_nonce(nonce: int) -> str:
    if not 0 <= nonce < 1 << 64:
        raise ValueError("a nonce is 64 bits")
    return be64(nonce).hex()


def encode_openings(openings: Sequence[Opening]) -> str:
    """The 16 openings in draw order, each its 8 residues (16 hex each) then its
    siblings from the leaf level up (64 hex each), no separators (8.4)."""
    return "".join("".join(be64(r).hex() for r in block) + "".join(s.hex() for s in path) for block, path in openings)


def encode_tags(seal: bytes, nonce: int, openings: Sequence[Opening]) -> Tuple[str, str, str]:
    """(proof, mn, mp) tag values."""
    return seal.hex(), encode_nonce(nonce), encode_openings(openings)


# --------------------------------------------------------------------------- geometry, primes, price (5.2, 5.3, 5.9, 5.10)
def find_lca_height(v1: int, v2: int) -> int:
    return (v1 ^ v2).bit_length()


def residue_count(h_max: int) -> int:
    """m: enough 61-bit primes for Q to span a quarter of an 85 * 2^h_max bit
    root, rounded up to whole blocks of 8."""
    m = -(-(AXIS_BITS << h_max) // (WIDTH_DIVISOR * PRIME_BITS))
    return max(RESIDUE_BLOCK, -(-m // RESIDUE_BLOCK) * RESIDUE_BLOCK)


def merkle_depth(m: int) -> int:
    blocks, depth = m // RESIDUE_BLOCK, 0
    while (1 << depth) < blocks:
        depth += 1
    return depth


def reroll_budget(h: int) -> int:
    if h < len(HOP_REROLL_BUDGET):
        return HOP_REROLL_BUDGET[h]
    n = h - (len(HOP_REROLL_BUDGET) - 1)
    return HOP_REROLL_BUDGET[-1] * 9 ** n // 4 ** n


def reroll_attempts(heights: Sequence[int]) -> int:
    """A: the summed budgets of the three axis heights and K, at least 1."""
    return max(1, sum(reroll_budget(h) for h in heights))


@dataclass(frozen=True)
class HopGeometry:
    """Everything a verifier derives from the event (5.11 step 1, 8.7.1 steps 1 to 6)."""

    axes: Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]  # (aligned base, LCA height) per axis
    temporal: Tuple[int, int]                                       # (t_base, K)
    h_max: int
    m: int
    depth: int
    attempts: int                                                   # A

    @property
    def heights(self) -> Tuple[int, int, int, int]:
        return self.axes[0][1], self.axes[1][1], self.axes[2][1], self.temporal[1]

    @property
    def terrain_k(self) -> int:
        return self.temporal[1]


def _check_id(previous_event_id: bytes) -> bytes:
    if not isinstance(previous_event_id, (bytes, bytearray)) or len(previous_event_id) != 32:
        raise ValueError("previous_event_id must be 32 bytes")
    return bytes(previous_event_id)


def hop_geometry(previous_event_id: bytes, src_coord: int, dst_coord: int) -> HopGeometry:
    prev = _check_id(previous_event_id)
    x1, y1, z1, _ = coord_to_xyz(src_coord)
    x2, y2, z2, plane2 = coord_to_xyz(dst_coord)
    axes = []
    for a, b in ((x1, x2), (y1, y2), (z1, z2)):
        h = find_lca_height(a, b)
        axes.append(((a >> h) << h, h))
    k = terrain_k(x=x2, y=y2, z=z2, plane=plane2)
    t = int.from_bytes(prev, "big") % (1 << AXIS_BITS)
    temporal = ((t >> k) << k, k)
    heights = [h for _, h in axes] + [k]
    m = residue_count(max(heights))
    return HopGeometry(tuple(axes), temporal, max(heights), m, merkle_depth(m), reroll_attempts(heights))  # type: ignore[arg-type]


def is_sprp2(n: int) -> bool:
    """Base-2 strong probable prime test for odd n > 2."""
    d, r = n - 1, 0
    while not d & 1:
        d, r = d >> 1, r + 1
    x = pow(2, d, n)
    if x == 1 or x == n - 1:
        return True
    for _ in range(r - 1):
        x = x * x % n
        if x == n - 1:
            return True
    return False


def derive_prime(previous_event_id: bytes, j: int) -> int:
    """p_j (5.9): the smallest odd n >= 2^61 + (the top 60 bits of the first 8
    bytes of SHA256(domain || previous_event_id || be64(j))) with no factor in
    SMALL_ODD_PRIMES that is a base-2 strong probable prime. j is 64 bits, never
    truncated to 32."""
    if not 0 <= j < 1 << 64:
        raise ValueError("a prime index is 64 bits")
    x = int.from_bytes(sha256(HOP_RESIDUE_PRIME_DOMAIN + previous_event_id + be64(j))[:8], "big") >> 4
    n = ((1 << PRIME_BITS) + x) | 1
    while math.gcd(n, _SMALL_PRIMORIAL) != 1 or not is_sprp2(n):
        n += 2
    return n


@functools.lru_cache(maxsize=1 << 12)
def hop_prime(previous_event_id: bytes, j: int) -> int:
    return derive_prime(bytes(previous_event_id), j)


def _prime_range(previous_event_id: bytes, lo: int, hi: int) -> List[int]:
    return [derive_prime(previous_event_id, j) for j in range(lo, hi)]


def hop_primes(previous_event_id: bytes, count: int, *, workers: Optional[int] = None) -> List[int]:
    """p_0 to p_(count-1), across processes when there are many."""
    prev = _check_id(previous_event_id)
    workers = workers or os.cpu_count() or 1
    if count < PARALLEL_PRIMES or workers <= 1:
        return _prime_range(prev, 0, count)
    step = -(-count // (workers * 4))
    with multiprocessing.Pool(processes=workers) as pool:
        parts = pool.starmap(_prime_range, [(prev, lo, min(count, lo + step)) for lo in range(0, count, step)])
    return [p for part in parts for p in part]


# --------------------------------------------------------------------------- a root modulo p (5.9)
def pair_mod(a: int, b: int, p: int) -> int:
    """pi(a, b) mod p for odd p: (p + 1) / 2 is the inverse of 2."""
    s = (a + b) % p
    return (s * (s + 1) * ((p + 1) // 2) + b) % p


def residue_tree(base: int, height: int, p: int) -> int:
    """compute_subtree_cantor(base, height) mod p, by the same tree carried mod p."""
    stack: List[Tuple[int, int]] = []
    for i in range(1 << height):
        cur, level = (base + i) % p, 0
        while stack and stack[-1][1] == level:
            cur = pair_mod(stack.pop()[0], cur, p)
            level += 1
        stack.append((cur, level))
    return stack[0][0]


def residue_engine(base: int, height: int, p: int, k: Optional[int] = None) -> int:
    """The reference's method of differences at level k: the level-k nodes of an
    aligned tree are values of one polynomial of degree 2^k at evenly spaced
    points, so after tabulating its differences each further node costs 2^k
    additions modulo p."""
    if k is None:
        k = max(0, min(height, (height - 2) // 2))
    d, nodes = 1 << k, 1 << (height - k)
    n0 = min(nodes, d + 1)
    D = [residue_tree(base + (j << k), k, p) for j in range(n0)] + [0] * (d + 1 - n0)
    for i in range(1, n0):
        for j in range(n0 - 1, i - 1, -1):
            D[j] = (D[j] - D[j - 1]) % p
    stack: List[Tuple[int, int]] = []
    for _ in range(nodes):
        cur, level = D[0], 0
        while stack and stack[-1][1] == level:
            cur = pair_mod(stack.pop()[0], cur, p)
            level += 1
        stack.append((cur, level))
        for i in range(d):
            D[i] = (D[i] + D[i + 1]) % p
    return stack[0][0]


# The packed engine: lane i of one integer holds D[i] in LANE_BITS bits. A step
# of the method (D[i] += D[i + 1] for every i < d, D[d] constant) is then
# P + (P >> LANE_BITS). Lanes start below p < 2^62 and at most double per
# step, so after REDUCE_EVERY steps they are below 2^126 and no lane carries
# into the next; then every lane is reduced modulo p again.
LANE_BITS = 128
REDUCE_EVERY = 64
PACKED_FROM_HEIGHT = 10


def _packed_level(height: int) -> int:
    """The table's level k: tabulating it costs about 4^k pairings, a step costs
    a pass over 2^k lanes. Measured best: 5 at h16, 6 at h20, 7 to 8 at h24."""
    return min(8, (height - 2) // 2, max(5, height // 2 - 4))


def residue_root(base: int, height: int, p: int) -> int:
    """compute_subtree_cantor(base, height) mod p for odd p: the method of
    differences with its table packed into lanes. Equal to residue_tree."""
    if height < PACKED_FROM_HEIGHT:
        return residue_engine(base, height, p)
    k = _packed_level(height)
    d, nodes = 1 << k, 1 << (height - k)
    D = [residue_tree(base + (j << k), k, p) for j in range(d + 1)]
    for i in range(1, d + 1):
        for j in range(d, i - 1, -1):
            D[j] = (D[j] - D[j - 1]) % p
    lane_bytes, mask = LANE_BITS // 8, (1 << LANE_BITS) - 1
    size = lane_bytes * (d + 1)

    def pack(values: List[int]) -> int:
        return int.from_bytes(b"".join(v.to_bytes(lane_bytes, "little") for v in values), "little")

    def reduce(P: int) -> int:
        raw = P.to_bytes(size, "little")
        return pack([int.from_bytes(raw[i:i + lane_bytes], "little") % p for i in range(0, size, lane_bytes)])

    P = pack(D)
    stack: List[Tuple[int, int]] = []
    since = 0
    for _ in range(nodes):
        cur, level = (P & mask) % p, 0
        while stack and stack[-1][1] == level:
            cur = pair_mod(stack.pop()[0], cur, p)
            level += 1
        stack.append((cur, level))
        P += P >> LANE_BITS
        since += 1
        if since == REDUCE_EVERY:
            P, since = reduce(P), 0
    return stack[0][0]


def combine_residues(cx: int, cy: int, cz: int, ct: int, p: int) -> int:
    """hop_n mod p from the four roots mod p: pi(pi(pi(cx, cy), cz), ct)."""
    return pair_mod(pair_mod(pair_mod(cx, cy, p), cz, p), ct, p)


def hop_residue(geometry: HopGeometry, p: int, root: Callable[[int, int, int], int] = residue_root) -> int:
    """hop_n mod p without hop_n (5.9)."""
    cx, cy, cz = (root(base, h, p) for base, h in geometry.axes)
    return combine_residues(cx, cy, cz, root(geometry.temporal[0], geometry.temporal[1], p), p)


def _hop_residue_at(geometry: HopGeometry, previous_event_id: bytes, index: int) -> int:
    return hop_residue(geometry, hop_prime(previous_event_id, index))


# --------------------------------------------------------------------------- the seal and openings (5.10)
def leaf_hash(previous_event_id: bytes, block: int, residues: Sequence[int]) -> bytes:
    return sha256(HOP_RESIDUE_LEAF_DOMAIN + previous_event_id + be64(block) + b"".join(be64(r) for r in residues))


def seal_levels(previous_event_id: bytes, residues: Sequence[int]) -> Tuple[bytes, List[List[bytes]]]:
    """The seal and every level of its tree, leaves first, padded with PAD_LEAF
    to a power of two."""
    B = RESIDUE_BLOCK
    if not residues or len(residues) % B:
        raise ValueError("the residue list is a whole number of blocks of 8")
    level = [leaf_hash(previous_event_id, b, residues[b * B:(b + 1) * B]) for b in range(len(residues) // B)]
    level += [PAD_LEAF] * ((1 << merkle_depth(len(residues))) - len(level))
    levels = [level]
    while len(level) > 1:
        level = [sha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        levels.append(level)
    return levels[-1][0], levels


def open_block(levels: List[List[bytes]], residues: Sequence[int], block: int) -> Opening:
    path, i = [], block
    for level in levels[:-1]:
        path.append(level[i ^ 1])
        i //= 2
    return list(residues[block * RESIDUE_BLOCK:(block + 1) * RESIDUE_BLOCK]), path


def verify_path(leaf: bytes, position: int, siblings: Sequence[bytes], seal: bytes) -> bool:
    cur, i = leaf, position
    for sib in siblings:
        cur = sha256(cur + sib) if i % 2 == 0 else sha256(sib + cur)
        i //= 2
    return cur == seal


@dataclass(frozen=True)
class Attempt:
    seed: bytes
    g_base: int
    r_g: int
    G: bytes


def attempt_detail(previous_event_id: bytes, seal: bytes, nonce: int) -> Attempt:
    """One re-roll attempt (5.10): the seed, the aligned height-12 base it
    chooses, that tree modulo p_0, and G."""
    seed = sha256(HOP_RESIDUE_GRIND_DOMAIN + previous_event_id + seal + be64(nonce))
    g_base = ((int.from_bytes(seed, "big") % (1 << AXIS_BITS)) >> HOP_GRIND_HEIGHT) << HOP_GRIND_HEIGHT
    r_g = residue_root(g_base, HOP_GRIND_HEIGHT, hop_prime(previous_event_id, 0))
    return Attempt(seed, g_base, r_g, sha256(HOP_RESIDUE_GRIND_DOMAIN + seed + be64(r_g)))


def attempt(previous_event_id: bytes, seal: bytes, nonce: int) -> bytes:
    return attempt_detail(previous_event_id, seal, nonce).G


def meets_price(G: bytes, attempts: int) -> bool:
    """G read as a 256-bit integer, times A, below 2^256: probability 1/A."""
    return int.from_bytes(G, "big") * attempts < (1 << 256)


def _nonce_meets_price(previous_event_id: bytes, seal: bytes, attempts: int, nonce: int) -> bool:
    return meets_price(attempt(previous_event_id, seal, nonce), attempts)


def find_nonce(previous_event_id: bytes, seal: bytes, attempts: int, *, workers: Optional[int] = None) -> int:
    """The smallest nonce from 0 that meets the price; the same nonce whether
    the search runs in one process or many."""
    workers = workers or os.cpu_count() or 1
    if attempts >= PARALLEL_ATTEMPTS and workers > 1:
        from cyberspace_core.merkle_engine import parallel_first

        return parallel_first(partial(_nonce_meets_price, previous_event_id, seal, attempts), chunk=256, workers=workers)
    nonce = 0
    while not _nonce_meets_price(previous_event_id, seal, attempts, nonce):
        nonce += 1
    return nonce


def sample_indices(G: bytes, m: int) -> List[int]:
    return [int.from_bytes(sha256(HOP_RESIDUE_SAMPLE_DOMAIN + G + be32(i)), "big") % m for i in range(HOP_SAMPLES)]


# --------------------------------------------------------------------------- every residue, exactly (the prover, Level 2)
_EXACT = decimal.Context(
    prec=decimal.MAX_PREC, Emax=decimal.MAX_EMAX, Emin=decimal.MIN_EMIN,
    traps=[decimal.Inexact, decimal.Rounded, decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow],
)
BACKENDS = ("int", "decimal", "gmpy2")


def default_backend(h_max: int) -> str:
    if HAS_GMPY2:
        return "gmpy2"
    return "decimal" if h_max >= DECIMAL_FROM_HEIGHT else "int"


def _exact_root(big: Callable, base: int, height: int):
    values = [big(v) for v in range(base, base + (1 << height))]
    for _ in range(height):
        nxt = []
        for i in range(0, len(values), 2):
            a, b = values[i], values[i + 1]
            s = a + b
            nxt.append(s * (s + 1) // 2 + b)
        values = nxt
    return values[0]


def hop_residues(previous_event_id: bytes, geometry: HopGeometry, primes: Optional[Sequence[int]] = None,
                 *, backend: Optional[str] = None, workers: Optional[int] = None) -> List[int]:
    """hop_n mod p_j for every j < m, never building hop_n: each root reduced
    modulo Q, the pairings modulo Q (s(s+1) is even and Q odd, so halving is
    exact), then one remainder tree from hop_n mod Q down to every p_j."""
    prev = _check_id(previous_event_id)
    if primes is None:
        primes = hop_primes(prev, geometry.m, workers=workers)
    backend = backend or default_backend(geometry.h_max)
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}")
    if backend == "gmpy2" and not HAS_GMPY2:
        raise ValueError("gmpy2 is not installed")
    with decimal.localcontext(_EXACT):
        big = {"int": int, "decimal": decimal.Decimal, "gmpy2": getattr(gmpy2, "mpz", None)}[backend]
        levels = [[big(p) for p in primes]]
        while len(levels[-1]) > 1:
            lv = levels[-1]
            levels.append([lv[i] * lv[i + 1] if i + 1 < len(lv) else lv[i] for i in range(0, len(lv), 2)])
        Q = levels[-1][0]

        def pair_q(a, b):
            s = (a + b) % Q
            return (s * (s + 1) // 2 + b) % Q

        cx, cy, cz, ct = (_exact_root(big, base, h) % Q for base, h in list(geometry.axes) + [geometry.temporal])
        rem = [pair_q(pair_q(pair_q(cx, cy), cz), ct)]
        for lv in reversed(levels[:-1]):
            rem = [rem[i // 2] % lv[i] for i in range(len(lv))]
        return [int(r) for r in rem]


# --------------------------------------------------------------------------- prove (5.10)
@dataclass(frozen=True)
class HopResidueProof:
    """A version 2 hop proof: the seal for the proof tag, the nonce for mn, the
    16 openings for mp."""

    geometry: HopGeometry
    seal: bytes
    nonce: int
    G: bytes
    openings: Tuple[Opening, ...]

    @property
    def proof(self) -> str:
        return self.seal.hex()

    @property
    def mn(self) -> str:
        return encode_nonce(self.nonce)

    @property
    def mp(self) -> str:
        return encode_openings(self.openings)

    @property
    def terrain_k(self) -> int:
        return self.geometry.terrain_k

    @property
    def lca_heights(self) -> Tuple[int, int, int]:
        return self.geometry.heights[:3]  # type: ignore[return-value]


def prove_hop(previous_event_id: bytes, src_coord: int, dst_coord: int, *,
              backend: Optional[str] = None, workers: Optional[int] = None) -> HopResidueProof:
    """The honest prover: every residue, the seal, the nonce, the openings."""
    prev = _check_id(previous_event_id)
    geometry = hop_geometry(prev, src_coord, dst_coord)
    residues = hop_residues(prev, geometry, backend=backend, workers=workers)
    seal, levels = seal_levels(prev, residues)
    nonce = find_nonce(prev, seal, geometry.attempts, workers=workers)
    G = attempt(prev, seal, nonce)
    openings = tuple(open_block(levels, residues, i // RESIDUE_BLOCK) for i in sample_indices(G, geometry.m))
    return HopResidueProof(geometry, seal, nonce, G, openings)


# --------------------------------------------------------------------------- verify (5.11, 8.7.1 steps 7 to 11)
@dataclass(frozen=True)
class HopFailure:
    """One failed check. step is form, price, residue, path (Level 1) or seal
    (Level 2); sample is the opening i, for residue and path."""

    step: str
    sample: Optional[int] = None
    detail: str = ""

    def __str__(self) -> str:
        return self.detail or (self.step if self.sample is None else f"{self.step} {self.sample}")


def form_failures(proof: object, mn: object, mp: object, depth: int) -> List[HopFailure]:
    """Each of the three tag values against its form and width (8.4)."""
    out = []
    if not is_lower_hex(proof, 64):
        out.append(HopFailure("form", detail="proof: not a seal of 64 lowercase hex characters (8.4)"))
    if not is_lower_hex(mn, 16):
        out.append(HopFailure("form", detail="mn: not a nonce of exactly 16 lowercase hex characters (8.4)"))
    if not is_lower_hex(mp, mp_length(depth)):
        out.append(HopFailure("form", detail=f"mp: not exactly {mp_length(depth)} lowercase hex characters, the 16 openings at depth {depth} (8.4)"))
    return out


class HopTooTall(ValueError):
    """Level 1 would cost more than the caller allowed; no verdict was given."""


def verify_hop_proof(previous_event_id: bytes, src_coord: int, dst_coord: int,
                     proof: object, mn: object, mp: object, *,
                     all_failures: bool = False, workers: Optional[int] = None,
                     max_height: Optional[int] = None) -> List[HopFailure]:
    """Level 1 (5.11): form, price, then for each opening i in ascending order its
    residue and its path. Empty means valid.

    By default it stops at the first failure, which is the one the steps of 5.11
    reach in that order. The paths are cheap and the residues are not, so the
    paths are checked first, and only the residues of the openings up to the
    first bad path are computed; the failure reported is the same.
    all_failures=True reports every price, residue and path failure instead
    (a form failure ends the check, since nothing can be parsed).

    max_height: raise HopTooTall, after the form and price checks pass, if
    h_max exceeds it (Level 1 costs about 2^h_max per opened residue)."""
    prev = _check_id(previous_event_id)
    g = hop_geometry(prev, src_coord, dst_coord)
    bad_form = form_failures(proof, mn, mp, g.depth)
    if bad_form:
        return bad_form if all_failures else bad_form[:1]
    seal, nonce, openings = decode_seal(proof), decode_nonce(mn), decode_openings(mp, g.depth)
    assert seal is not None and nonce is not None and openings is not None
    G = attempt(prev, seal, nonce)
    failures: List[HopFailure] = []
    if not meets_price(G, g.attempts):
        failures.append(HopFailure("price", detail=f"mn: G times A = {g.attempts} is not below 2^256; the nonce misses the re-roll price (5.10)"))
        if not all_failures:
            return failures
    if max_height is not None and g.h_max > max_height:
        raise HopTooTall(f"h_max {g.h_max} exceeds the verification ceiling {max_height}")
    idx = sample_indices(G, g.m)
    paths_ok = [
        verify_path(leaf_hash(prev, i // RESIDUE_BLOCK, block), i // RESIDUE_BLOCK, path, seal)
        for i, (block, path) in zip(idx, openings)
    ]
    first_bad_path = next((s for s, ok in enumerate(paths_ok) if not ok), None)
    upto = HOP_SAMPLES if all_failures or first_bad_path is None else first_bad_path + 1
    workers = workers or os.cpu_count() or 1
    if g.h_max >= PARALLEL_VERIFY_HEIGHT and workers > 1 and upto > 1:
        with multiprocessing.Pool(processes=min(workers, upto)) as pool:
            residues: List[Optional[int]] = pool.map(partial(_hop_residue_at, g, prev), idx[:upto])
    else:
        residues = [None] * upto
    for s in range(upto):
        i = idx[s]
        expected = residues[s] if residues[s] is not None else _hop_residue_at(g, prev, i)
        if openings[s][0][i % RESIDUE_BLOCK] != expected:
            failures.append(HopFailure("residue", s, f"mp: opening {s} (index {i}): residue {i % RESIDUE_BLOCK} of block {i // RESIDUE_BLOCK} is not hop_n mod p_{i} (5.11)"))
            if not all_failures:
                return failures
        if not paths_ok[s]:
            failures.append(HopFailure("path", s, f"mp: opening {s} (block {i // RESIDUE_BLOCK}): its path does not climb to the seal (5.11)"))
            if not all_failures:
                return failures
    return failures


def audit_hop_proof(previous_event_id: bytes, src_coord: int, dst_coord: int,
                    proof: object, mn: object, mp: object, *,
                    backend: Optional[str] = None, workers: Optional[int] = None) -> List[HopFailure]:
    """Level 2 (5.11): Level 1, then every residue recomputed and the seal rebuilt."""
    failures = verify_hop_proof(previous_event_id, src_coord, dst_coord, proof, mn, mp, workers=workers)
    if failures:
        return failures
    g = hop_geometry(previous_event_id, src_coord, dst_coord)
    seal, _ = seal_levels(previous_event_id, hop_residues(previous_event_id, g, backend=backend, workers=workers))
    return [] if seal.hex() == proof else [HopFailure("seal", detail="proof: is not the seal of the true residues (Level 2, 5.11)")]
