"""Check a HOSAKA result before it becomes a signed movement event.

Hops (residue openings, CYBERSPACE_V2 5.9 to 5.11): a result carries the
flat fields seal, mn and mp, and is checked at Level 1 exactly as a verifier
will check the published event: the geometry, K and the price derived here
from the coordinates and the previous event id, then the 16 opened residues
and their paths. Nothing is taken from the server.

A version 1 result (hop_n and the Cantor envelopes, no seal, mn or mp) is
refused outright (straddling_v1_hop). It would become a version 1 hop, which
chain rules revision 2026-10-08-residue-openings rejects unless its id is on
grandfathered-v1-hops.txt, and a hop signed now never is: signing it would
freeze the chain at the hop before it. HOSAKA switches to version 2 at once
(no result carries both shapes), so there is nothing to fall back to.
run_cloud_move also refuses before quoting when the limits do not report
hop_proof_version 2, so a version 1 result reaches this check only from a
job that straddled the switch. Such a job is eligible for a refund, which
the HOSAKA operator runs after checking that nothing was published.

Sidesteps: full Level 1 verification per CYBERSPACE_V2 6.11, all O(h),
with the re-roll nonce read from the result's mn field (16 lowercase hex
characters, exactly as the event's mn tag).

Every function returns the list of failed checks. Empty means append.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256
from cyberspace_core.coords import xyz_to_coord
from cyberspace_core.movement import (
    AXIS_BITS,
    TEMPORAL_MAX_COMPUTE_HEIGHT,
    compute_subtree_cantor,
    decode_nonce,
    find_lca_height,
    verify_sidestep_openings,
)
from cyberspace_core.movement import MAX_VERIFY_HEIGHT
from cyberspace_core.residue import HopTooTall, is_lower_hex, verify_hop_proof
from cyberspace_core.terrain import terrain_k

V2_HOP_FIELDS = ("seal", "mn", "mp")
# The hop proof version HOSAKA must serve (GET /api/v1/limits hop_proof_version).
HOP_PROOF_VERSION = 2


def straddling_v1_hop(result: Any, job_id: Optional[str]) -> Optional[str]:
    """The refusal for a hop job that finished in the version 1 shape (hop_n
    and none of seal, mn and mp), else None. Only a job that straddled
    HOSAKA's switch to version 2 can do that. It is refused and never signed,
    and the job is eligible for a refund to the HOSAKA balance, which the
    HOSAKA operator runs with a helper after checking that nothing was
    published; nothing here or on HOSAKA refunds it automatically. Refusing
    is the recommended default for a straddling job, pending the owner's
    ruling, and it matches ONOSENDAI's straddlingV1Hop."""
    if not isinstance(result, dict) or "hop_n" not in result or any(name in result for name in V2_HOP_FIELDS):
        return None
    job = f"job {job_id}" if job_id else "this job"
    return (
        f"HOSAKA finished this hop ({job}) in the old proof format, version 1 (hop_n, with no seal, mn or mp). "
        "Chain rules revision 2026-10-08-residue-openings rejects a version 1 hop unless it is listed in "
        "grandfathered-v1-hops.txt, and a hop signed now never is (CYBERSPACE_V2 5.13), so the result is refused. "
        "Nothing was signed and you did not move. This job is eligible for a refund to your HOSAKA balance."
    )


@dataclass
class CloudHop:
    """What the move command needs from a completed cloud hop: the proof
    (the seal), mn and mp tag values."""

    proof: str
    mn: str
    mp: str
    terrain_k: int
    lookup_id: str
    location_decryption_key: str
    job_id: str
    cost_msats: int
    lca_heights: Tuple[int, int, int]
    source: str = "cloud"


@dataclass
class CloudSidestep:
    """Same attribute names as cyberspace_core.movement.SidestepProof, so the
    event construction in the move command does not care where it came from."""

    merkle_x: bytes
    merkle_y: bytes
    merkle_z: bytes
    openings: Dict[str, List[List[bytes]]]
    lca_heights: Tuple[int, int, int]
    proof_hash: str
    terrain_k: int
    job_id: str = ""
    cost_msats: int = 0
    source: str = "cloud"
    region_m: int = 0
    sidestep_n: int = field(default=0, repr=False)
    nonce: int = 0


def _dsha_hex(n: int) -> str:
    return sha256(sha256(int_to_bytes_be_min(n))).hex()


def _temporal(previous_event_id_hex: str, k: int) -> int:
    t = int.from_bytes(bytes.fromhex(previous_event_id_hex), "big") % (1 << AXIS_BITS)
    t_base = (t >> k) << k if k > 0 else t
    return compute_subtree_cantor(t_base, k, max_compute_height=TEMPORAL_MAX_COMPUTE_HEIGHT)


def _as_int(value: Any) -> Optional[int]:
    """A small non-negative integer field: a JSON number, or its canonical decimal string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value < 1 << 32 else None
    if isinstance(value, str) and len(value) <= 10 and value.isascii() and value.isdigit() and (value == "0" or value[0] != "0"):
        return int(value)
    return None


def _envelope_failures(name: str, env: Any) -> List[str]:
    """An envelope is {public_proof, secret_key?}: 32-byte lowercase hex, and
    public_proof = sha256(secret_key) when the key is given."""
    if not isinstance(env, dict):
        return [f"{name}: envelope missing or not an object"]
    if not is_lower_hex(env.get("public_proof"), 64):
        return [f"{name}: public_proof is not 32 bytes of lowercase hex"]
    key = env.get("secret_key")
    if key:
        if not is_lower_hex(key, 64):
            return [f"{name}: secret_key is not 32 bytes of lowercase hex"]
        if sha256(bytes.fromhex(key)).hex() != env["public_proof"]:
            return [f"{name}: public_proof is not sha256(secret_key)"]
    return []


def _heights(x1, y1, z1, x2, y2, z2) -> Tuple[int, int, int]:
    return find_lca_height(x1, x2), find_lca_height(y1, y2), find_lca_height(z1, z2)


def verify_cloud_hop(
    result: Dict[str, Any],
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    *,
    plane: int,
    previous_event_id_hex: str,
    job_id: Optional[str] = None,
) -> List[str]:
    """Level 1 of a cloud hop result before it is signed. A version 1 result
    is refused with straddling_v1_hop's words; any other result missing one
    of seal, mn and mp is a failed check."""
    refusal = straddling_v1_hop(result, job_id)
    if refusal:
        return [refusal]
    failures: List[str] = []
    for name in V2_HOP_FIELDS:
        if name not in result:
            failures.append(f"{name}: missing from the result (it carries {', '.join(n for n in V2_HOP_FIELDS if n in result) or 'none of seal, mn and mp'})")
    if "region_n" in result:
        failures += _envelope_failures("region_n", result["region_n"])
    k = terrain_k(x=x2, y=y2, z=z2, plane=plane)
    if "K" in result and _as_int(result["K"]) != k:
        failures.append(f"K: server {result.get('K')!r} but terrain gives {k}")
    if failures:
        return failures
    # Level 1 (5.11): the source plane does not enter the geometry, only x, y, z.
    try:
        found = verify_hop_proof(
            bytes.fromhex(previous_event_id_hex),
            xyz_to_coord(x1, y1, z1, plane=plane),
            xyz_to_coord(x2, y2, z2, plane=plane),
            result["seal"], result["mn"], result["mp"],
            max_height=MAX_VERIFY_HEIGHT,
        )
    except HopTooTall as e:
        return [f"Level 1: not checked, {e}; the result is refused"]
    return [f"Level 1: {f}" for f in found]


def cloud_hop_from_result(job: Dict[str, Any], x1, y1, z1, x2, y2, z2, *, plane: int = 0) -> CloudHop:
    """The proof object of a result that verify_cloud_hop accepted."""
    result = job["result"]
    region = result.get("region_n") if isinstance(result.get("region_n"), dict) else {}
    return CloudHop(
        proof=result["seal"],
        mn=result["mn"],
        mp=result["mp"],
        terrain_k=terrain_k(x=x2, y=y2, z=z2, plane=plane),  # any server K was checked against this
        lookup_id=region.get("public_proof", ""),
        location_decryption_key=region.get("secret_key", "") or "",
        job_id=job["id"],
        cost_msats=int(job.get("cost_msats") or 0),
        lca_heights=_heights(x1, y1, z1, x2, y2, z2),
    )


def verify_cloud_sidestep(
    result: Dict[str, Any],
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    *,
    plane: int,
    previous_event_id_hex: str,
) -> List[str]:
    failures: List[str] = []
    heights = _heights(x1, y1, z1, x2, y2, z2)
    if [int(h) for h in result.get("lca_heights", [])] != list(heights):
        failures.append(f"lca_heights: server {result.get('lca_heights')} but axes give {list(heights)}")
        return failures

    # 6.16: a result without a nonce is a version 2 proof. The exemption list
    # names published events; a cloud result is a new proof, so nothing excuses it.
    nonce = decode_nonce(result.get("mn"))
    if nonce is None:
        failures.append(f"mn: {result.get('mn')!r} is not a nonce of 16 lowercase hex characters (a version 2 result is refused, 6.16)")
    roots: List[bytes] = []
    openings: Dict[str, List[List[bytes]]] = {}
    for i, (axis, v1, v2) in enumerate((("x", x1, x2), ("y", y1, y2), ("z", z1, z2))):
        h = heights[i]
        base = (min(v1, v2) >> h) << h
        bases = result.get("bases")
        if bases and int(bases[i]) != base:
            failures.append(f"bases[{axis}]: server {bases[i]} but aligned base is {base}")
        try:
            root = bytes.fromhex(result[f"merkle_{axis}"])
            openings[axis] = [[bytes.fromhex(s) for s in path] for path in result["openings"][axis]]
        except (KeyError, ValueError, TypeError):
            failures.append(f"merkle_{axis}: root or openings missing")
            continue
        if len(root) != 32:
            failures.append(f"merkle_{axis}: root is not 32 bytes")
            continue
        roots.append(root)
    if failures:
        return failures

    # 6.10, 6.11: G from the nonce and all three roots must meet the price;
    # then on every axis the destination's path and the eight paths at the
    # positions drawn from G, each sampled leaf recomputed under OUR seed, the
    # previous event id and the axis. A tree built for anyone else fails here,
    # as does a v1 result with a single path (6.15).
    assert nonce is not None
    failures += verify_sidestep_openings(bytes.fromhex(previous_event_id_hex), (x1, y1, z1), (x2, y2, z2), roots, nonce, openings)
    if failures:
        return failures

    region_m = cantor_pair(cantor_pair(int.from_bytes(roots[0], "big"), int.from_bytes(roots[1], "big")), int.from_bytes(roots[2], "big"))
    if result.get("region_m_hex") and int(result["region_m_hex"], 16) != region_m:
        failures.append("region_m: does not match the pairing of the three roots")
    k = terrain_k(x=x2, y=y2, z=z2, plane=plane)
    if int(result.get("terrain_k", -1)) != k:
        failures.append(f"terrain_k: server {result.get('terrain_k')} but terrain gives {k}")
    sidestep_n = cantor_pair(region_m, _temporal(previous_event_id_hex, k))
    if result.get("proof_hash") != _dsha_hex(sidestep_n):
        failures.append("proof_hash: does not equal the double SHA-256 of sidestep_n")
    return failures


def cloud_sidestep_from_result(job: Dict[str, Any], x1, y1, z1, x2, y2, z2, *, plane: int, previous_event_id_hex: str) -> CloudSidestep:
    result = job["result"]
    heights = _heights(x1, y1, z1, x2, y2, z2)
    roots = [bytes.fromhex(result[f"merkle_{a}"]) for a in ("x", "y", "z")]
    region_m = cantor_pair(cantor_pair(int.from_bytes(roots[0], "big"), int.from_bytes(roots[1], "big")), int.from_bytes(roots[2], "big"))
    k = int(result["terrain_k"])
    return CloudSidestep(
        merkle_x=roots[0],
        merkle_y=roots[1],
        merkle_z=roots[2],
        openings={a: [[bytes.fromhex(s) for s in path] for path in result["openings"][a]] for a in ("x", "y", "z")},
        lca_heights=heights,
        proof_hash=result["proof_hash"],
        terrain_k=k,
        job_id=job["id"],
        cost_msats=int(job.get("cost_msats") or 0),
        region_m=region_m,
        sidestep_n=cantor_pair(region_m, _temporal(previous_event_id_hex, k)),
        nonce=int(result["mn"], 16),
    )
