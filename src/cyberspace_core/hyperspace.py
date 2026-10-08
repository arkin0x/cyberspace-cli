"""DECK-0001 v3 (Hyperspace) stop coordinates.

Implements the normative parts of DECK-0001 v3 section 1 (stop coordinates)
and section 2.2 (legacy anchor interpretation), plus the section 4.1 distance:

- ``stop_plane(merkle_root_hex)``: plane bit of a block (merkle root LSB).
- ``landfall_xyz(block_hash_hex)`` / ``landfall_coord_hex``: the WGS84 surface
  point chosen by the block hash for plane-0 blocks (section 1.2).
- ``resolve_stop(...)``: derive a stop from anchor tags, treating anchors
  without an ``M`` tag as legacy (``C`` is the merkle root) per section 2.2 and
  checking ``C`` against the derivation when ``M`` is present (section 2.3).
- ``stop_distance(...)``: the max-axis LCA height of section 4.1.
- ``enter_hyperspace_proof`` / ``verify_enter_hyperspace_event``: the entry
  proof of section 3.2.
- ``Line``: the stops a verifier knows by height, with the station of
  section 4.2, for the chain rules of rides (``cyberspace_core.chain``).

The landfall derivation runs in the base spec's decimal profile (precision 96,
ROUND_HALF_EVEN, exact PI_STR, deterministic Taylor sin/cos), reusing the
canonical helpers in ``cyberspace_core.coords`` so the GPS mapping and the
landfall mapping cannot drift apart. ``decks/landfall-reference.py`` in the
spec repository is the independent reference; the golden vectors below are
copied from the DECK and locked by ``tests/test_hyperspace_stops.py``.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256
from cyberspace_core.coords import (
    AXIS_BITS,
    DECIMAL_PREC,
    PI,
    UNITS_PER_KM,
    WGS84_A_M,
    WGS84_F,
    _sin_cos_decimal,
    coord_to_xyz,
    dataspace_xyz_to_ecef_km,
    dataspace_xyz_to_gps,
    ecef_km_to_dataspace_xyz,
    xyz_to_coord,
)
from cyberspace_core.movement import TEMPORAL_MAX_COMPUTE_HEIGHT, compute_subtree_cantor, find_lca_height
from cyberspace_core.terrain import terrain_k

DECK_0001_VERSION = "v3 (2026-08-24)"
LANDFALL_DOMAIN = b"CYBERSPACE_LANDFALL_V1"

PLANE_PORT = 1
PLANE_LANDFALL = 0

# DECK-0001 v3 section 1.2 golden vectors: (height, block hash, landfall coord256).
LANDFALL_GOLDEN_VECTORS: Tuple[Tuple[int, str, str], ...] = (
    (398, "000000002f7d702a27ccd65158740198f79d4ba1ddea8ab14b56b63a6289fe89",
     "56db6db6db6db6db6db6db3e27c436f9d3b79fb5fc6457798936b3e749e38f56"),
    (100399, "000000000003cb256436f213199e7047e187ab99e6d3176262bfb9be49d2a31a",
     "3b6db6db6db6db6db6db6d1eb09e85e5f572906af5a025a39ae284dd83278b72"),
    (300399, "0000000000000000212f189879294318528669d239d5fbd30e6ffcc6015ced21",
     "c492492492492492492492c7807ba8ecefd0a48a7b41dfbb50da5947b489ed8c"),
    (363199, "000000000000000001e65a8804c7d97ee1fd52394632bdebdaf402935dcddeec",
     "a9249249249249249249258087f30451bd8dd013357959fe2b07fa052488980c"),
    (500399, "000000000000000000521f92387f9f43258f62465e9f88b19ecad2c30e44d7ff",
     "3b6db6db6db6db6db6db6d312f699ee9f35318557d9ee813b46f229215524a30"),
    (700398, "00000000000000000005608e4c1ff53901186e766df5eaa87c636857ed814fa9",
     "56db6db6db6db6db6db6dbfdb284c1592e0d02ffd65f9d6c12d48a2b483d7da0"),
    (900399, "00000000000000000001e412795ed39b18e56338e9b3c20d91edf59d20e020c9",
     "c4924924924924924924920c53c81e9d260623340e5c3a75b6de6e4715cd1724"),
    (950399, "00000000000000000001f081b994866dc3beb2c3ecd5976e9bda474e54e027c1",
     "e000000000000000000000618f9c2d172da11fc0701996d4a89df1f60aecf732"),
)


class StopError(ValueError):
    """An anchor's tags cannot be resolved into a valid stop."""


def _hex32(value: str, name: str) -> str:
    s = value.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 64:
        raise StopError(f"{name} must be 32 bytes of hex (got {len(s)} chars)")
    try:
        bytes.fromhex(s)
    except ValueError as e:
        raise StopError(f"{name} is not valid hex") from e
    return s


def stop_plane(merkle_root_hex: str) -> int:
    """DECK-0001 v3 section 1.1: plane = merkle_root_int & 1 (display byte order)."""
    return int(_hex32(merkle_root_hex, "merkle root"), 16) & 1


def landfall_xyz(block_hash_hex: str) -> Tuple[int, int, int]:
    """DECK-0001 v3 section 1.2: the WGS84 surface point chosen by the block hash."""
    h = bytes.fromhex(_hex32(block_hash_hex, "block hash"))
    seed = hashlib.sha256(LANDFALL_DOMAIN + h).digest()
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        ctx.rounding = ROUND_HALF_EVEN
        one = Decimal(1)
        two = Decimal(2)
        u1 = Decimal(int.from_bytes(seed[0:16], "big")) / Decimal(1 << 128)
        u2 = Decimal(int.from_bytes(seed[16:32], "big")) / Decimal(1 << 128)
        lon = (two * u1 - one) * PI
        z = two * u2 - one
        rxy = (one - z * z).sqrt()
        sin_lon, cos_lon = _sin_cos_decimal(lon)
        dx, dy, dz = rxy * cos_lon, rxy * sin_lon, z
        b_m = WGS84_A_M * (one - WGS84_F)
        inv = ((dx * dx + dy * dy) / (WGS84_A_M * WGS84_A_M) + (dz * dz) / (b_m * b_m)).sqrt()
        r = one / inv
        km = Decimal(1000)
        # ECEF kilometres; ecef_km_to_dataspace_xyz applies the section 9.4 axis
        # permutation and the section 9.7 step 9 rounding/clamp.
        return ecef_km_to_dataspace_xyz(r * dx / km, r * dy / km, r * dz / km)


def landfall_coord_hex(block_hash_hex: str) -> str:
    x, y, z = landfall_xyz(block_hash_hex)
    return format(xyz_to_coord(x, y, z, PLANE_LANDFALL), "064x")


@dataclass(frozen=True)
class Stop:
    """A resolved hyperspace stop (one Bitcoin block as a location)."""

    coord_hex: str
    x: int
    y: int
    z: int
    plane: int
    merkle_root_hex: Optional[str]
    block_hash_hex: Optional[str]
    derived: bool  # True when the coordinate was derived locally rather than read from a v3 anchor
    legacy: bool  # True when the source anchor carried no M tag (section 2.2)

    @property
    def kind(self) -> str:
        return "port" if self.plane == PLANE_PORT else "landfall"

    @property
    def xyzp(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.z, self.plane)

    def gps(self) -> Optional[Tuple[float, float, float]]:
        """Informational (lat, lon, alt_m) for a landfall; None for a port."""
        if self.plane != PLANE_LANDFALL:
            return None
        return dataspace_xyz_to_gps(self.x, self.y, self.z)


def stop_from_block(*, merkle_root_hex: str, block_hash_hex: Optional[str]) -> Stop:
    """Section 1: derive a stop from a block's merkle root and hash."""
    m = _hex32(merkle_root_hex, "merkle root")
    plane = int(m, 16) & 1
    h = _hex32(block_hash_hex, "block hash") if block_hash_hex else None
    if plane == PLANE_PORT:
        coord_hex = m
    else:
        if h is None:
            raise StopError("plane-0 block needs its block hash (H) to derive the landfall coordinate")
        coord_hex = landfall_coord_hex(h)
    x, y, z, p = coord_to_xyz(int(coord_hex, 16))
    return Stop(coord_hex, x, y, z, p, m, h, derived=True, legacy=False)


def resolve_stop(*, c_hex: str, m_hex: Optional[str], h_hex: Optional[str]) -> Stop:
    """Resolve a kind-321 anchor's C/M/H tags into a stop.

    - No ``M`` tag (section 2.2): ``C`` is the merkle root. Plane 1 is a port at
      ``C``; plane 0 derives the landfall from ``H`` (``C`` MUST NOT be used as
      a position).
    - ``M`` present (section 2.3): ``C`` must equal the derivation from ``M`` and
      ``H``; otherwise the anchor is invalid.
    """
    c = _hex32(c_hex, "C")
    if m_hex is None:
        derived = stop_from_block(merkle_root_hex=c, block_hash_hex=h_hex)
        return Stop(
            derived.coord_hex, derived.x, derived.y, derived.z, derived.plane,
            derived.merkle_root_hex, derived.block_hash_hex,
            derived=derived.plane == PLANE_LANDFALL, legacy=True,
        )
    expected = stop_from_block(merkle_root_hex=m_hex, block_hash_hex=h_hex)
    if expected.coord_hex != c:
        raise StopError(
            f"anchor C does not match the DECK-0001 v3 derivation: C={c} expected={expected.coord_hex}"
        )
    return Stop(
        expected.coord_hex, expected.x, expected.y, expected.z, expected.plane,
        expected.merkle_root_hex, expected.block_hash_hex, derived=False, legacy=False,
    )


def stop_distance(p_xyz: Tuple[int, int, int], q_xyz: Tuple[int, int, int]) -> int:
    """Section 4.1: d(p, q) = max per-axis LCA height (plane bits ignored)."""
    return max(find_lca_height(a, b) for a, b in zip(p_xyz, q_xyz))


# ---------------------------------------------------------------- boarding (section 3)

def enter_hyperspace_proof(coord_hex: str, previous_event_id: bytes) -> str:
    """Section 3.2: the entry proof, the base protocol's temporal axis at the
    identity's coordinate with no spatial component. K is the terrain K at C
    including the plane bit (base 5.2), cantor_t is the Cantor root of the
    aligned subtree of height K around t = previous_event_id mod 2^85 (base
    5.3), and the proof is the double SHA-256 of enter_n = pi(0, cantor_t).
    It binds the boarding to its chain position; it is not a fare (section 7)."""
    x, y, z, plane = coord_to_xyz(int(coord_hex, 16))
    k = terrain_k(x=x, y=y, z=z, plane=plane)
    t = int.from_bytes(previous_event_id, "big") % (1 << AXIS_BITS)
    cantor_t = compute_subtree_cantor((t >> k) << k, k, max_compute_height=TEMPORAL_MAX_COMPUTE_HEIGHT)
    return sha256(sha256(int_to_bytes_be_min(cantor_pair(0, cantor_t)))).hex()


def verify_enter_hyperspace_event(event: Dict[str, Any]) -> List[str]:
    """The entry proof of a published enter-hyperspace event (section 3.2).
    Returns the failed checks; empty means the proof holds.

    The proof is seeded by the id the e previous tag names, which is the
    actual previous event whatever its action. That C equals c (section 3.1)
    and that c is the position the chain carries to this event are chain
    rules and stay with the caller, as does the NIP-01 signature."""
    tags = [t for t in (event.get("tags") or []) if isinstance(t, list) and len(t) >= 2]

    def value(name: str) -> Optional[str]:
        return next((t[1] for t in tags if t[0] == name), None)

    if value("A") != "enter-hyperspace":
        return ["A: not an enter-hyperspace"]
    failures: List[str] = []
    prev = next((t[1] for t in tags if t[0] == "e" and len(t) >= 4 and t[3] == "previous"), None)
    if not _is_hex32(prev):
        failures.append("e previous: missing or not 32 bytes of lowercase hex")
    if not _is_hex32(value("C")):
        failures.append("C: missing or not a 32-byte lowercase hex coordinate")
    if not _is_hex32(value("proof")):
        failures.append("proof: missing or not a 32-byte lowercase hex hash")
    if failures:
        return failures
    if value("proof") != enter_hyperspace_proof(value("C"), bytes.fromhex(prev)):  # type: ignore[arg-type]
        return ["proof: does not match the entry proof at this chain position (3.2)"]
    return []


def _is_hex32(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


# ---------------------------------------------------------------- the line (sections 1, 4, 5)

class Line:
    """The stops a verifier knows, one per block height from 0 to the tip.

    Rides are checked against it: a ride's C is the stop coordinate of its B
    (5.5 Level 1 step 2), its leaves need each passed block's hash (5.3), and
    the first ride after boarding departs from the station (4.2), which ranges
    over every stop up to the declared bound. A height above the tip does not
    exist as far as this line knows. The heights MUST run without a gap from
    0, because a station computed over a line with holes could differ from
    the station every other verifier computes.

    How the stops are obtained (a node, header blobs, anchors) is out of scope
    (section 2.3). The station here is a linear scan, which is exact and fine
    for small lines; section 4.4 describes the sorted lookup a full line needs."""

    def __init__(self, stops: Mapping[int, Stop]):
        heights = sorted(stops)
        if heights != list(range(len(heights))):
            raise ValueError("a line's heights must run from 0 without a gap")
        self._stops = dict(stops)
        self.tip = len(heights) - 1

    @classmethod
    def from_blocks(cls, blocks: Iterable[Mapping[str, Any]]) -> "Line":
        """A line from records carrying `height`, `merkle_root` and
        `block_hash` (lowercase hex, display order), each stop derived per
        section 1."""
        return cls({int(b["height"]): stop_from_block(merkle_root_hex=b["merkle_root"], block_hash_hex=b["block_hash"]) for b in blocks})

    def stop(self, height: int) -> Optional[Stop]:
        return self._stops.get(height)

    def block_hash(self, height: int) -> bytes:
        """Block `height`'s 32-byte hash in display order, for the ride leaves (5.3)."""
        stop = self._stops[height]
        if stop.block_hash_hex is None:
            raise KeyError(f"block {height} has no block hash on this line")
        return bytes.fromhex(stop.block_hash_hex)

    def station(self, coord_hex: str, bound: int) -> int:
        """Section 4.2: the height of the stop with height <= bound nearest the
        coordinate by the distance of 4.1, ties broken by the lowest height."""
        if not 0 <= bound <= self.tip:
            raise ValueError(f"station bound {bound} is not a height on this line (0..{self.tip})")
        x, y, z, _ = coord_to_xyz(int(coord_hex, 16))
        return min(range(bound + 1), key=lambda h: (stop_distance((x, y, z), self._stops[h].xyzp[:3]), h))


def axis_gibsons_to_km(gibsons: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        return Decimal(gibsons) / UNITS_PER_KM


def cube_side_km(height: int) -> Decimal:
    """Side length in km of an aligned cube of the given height."""
    return axis_gibsons_to_km(1 << height) if height > 0 else Decimal(0)


def straight_line_km(p_xyz: Tuple[int, int, int], q_xyz: Tuple[int, int, int]) -> float:
    """Euclidean distance in km between two dataspace points (informational)."""
    a = dataspace_xyz_to_ecef_km(*p_xyz)
    b = dataspace_xyz_to_ecef_km(*q_xyz)
    return float(sum((u - v) ** 2 for u, v in zip(a, b)).sqrt())


def geodesic_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """WGS84 geodesic distance in km (Vincenty inverse, informational floats)."""
    a = float(WGS84_A_M)
    f = float(WGS84_F)
    b = a * (1.0 - f)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    L = math.radians(lon2 - lon1)
    U1, U2 = math.atan((1 - f) * math.tan(phi1)), math.atan((1 - f) * math.tan(phi2))
    sU1, cU1, sU2, cU2 = math.sin(U1), math.cos(U1), math.sin(U2), math.cos(U2)
    lam = L
    for _ in range(200):
        sl, cl = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(cU2 * sl, cU1 * sU2 - sU1 * cU2 * cl)
        if sin_sigma == 0.0:
            return 0.0
        cos_sigma = sU1 * sU2 + cU1 * cU2 * cl
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cU1 * cU2 * sl / sin_sigma
        cos2_alpha = 1.0 - sin_alpha * sin_alpha
        cos_2sm = cos_sigma - 2.0 * sU1 * sU2 / cos2_alpha if cos2_alpha != 0.0 else 0.0
        C = f / 16.0 * cos2_alpha * (4.0 + f * (4.0 - 3.0 * cos2_alpha))
        lam_prev = lam
        lam = L + (1.0 - C) * f * sin_alpha * (
            sigma + C * sin_sigma * (cos_2sm + C * cos_sigma * (-1.0 + 2.0 * cos_2sm * cos_2sm))
        )
        if abs(lam - lam_prev) < 1e-12:
            break
    u2 = cos2_alpha * (a * a - b * b) / (b * b)
    A = 1.0 + u2 / 16384.0 * (4096.0 + u2 * (-768.0 + u2 * (320.0 - 175.0 * u2)))
    B = u2 / 1024.0 * (256.0 + u2 * (-128.0 + u2 * (74.0 - 47.0 * u2)))
    d_sigma = B * sin_sigma * (
        cos_2sm + B / 4.0 * (
            cos_sigma * (-1.0 + 2.0 * cos_2sm * cos_2sm)
            - B / 6.0 * cos_2sm * (-3.0 + 4.0 * sin_sigma * sin_sigma) * (-3.0 + 4.0 * cos_2sm * cos_2sm)
        )
    )
    return b * A * (sigma - d_sigma) / 1000.0
