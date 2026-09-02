"""Check a HOSAKA result before it becomes a signed movement event.

Hops: the cloud root itself is operator trust (it is the work we paid not to
do), but everything around it is cheap to recompute: terrain K, the temporal
root, trivial axes, any axis within the local ceiling, and the envelope
hashes. Sidesteps: full Level 1 verification per CYBERSPACE_V2 6.11, all O(h).

Every function returns the list of failed checks. Empty means append.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256
from cyberspace_core.movement import (
    AXIS_BITS,
    TEMPORAL_MAX_COMPUTE_HEIGHT,
    compute_axis_cantor,
    compute_subtree_cantor,
    find_lca_height,
    merkle_leaf,
    verify_merkle_inclusion,
)
from cyberspace_core.terrain import terrain_k


@dataclass
class CloudHop:
    """What the move command needs from a completed cloud hop."""

    proof_hash: str
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
    inclusion_proofs: Dict[str, List[bytes]]
    lca_heights: Tuple[int, int, int]
    proof_hash: str
    terrain_k: int
    job_id: str = ""
    cost_msats: int = 0
    source: str = "cloud"
    region_m: int = 0
    sidestep_n: int = field(default=0, repr=False)


def _dsha_hex(n: int) -> str:
    return sha256(sha256(int_to_bytes_be_min(n))).hex()


def _temporal(previous_event_id_hex: str, k: int) -> int:
    t = int.from_bytes(bytes.fromhex(previous_event_id_hex), "big") % (1 << AXIS_BITS)
    t_base = (t >> k) << k if k > 0 else t
    return compute_subtree_cantor(t_base, k, max_compute_height=TEMPORAL_MAX_COMPUTE_HEIGHT)


def _heights(x1, y1, z1, x2, y2, z2) -> Tuple[int, int, int]:
    return find_lca_height(x1, x2), find_lca_height(y1, y2), find_lca_height(z1, z2)


def verify_cloud_hop(
    result: Dict[str, Any],
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    *,
    plane: int,
    previous_event_id_hex: str,
    local_ceiling: int,
) -> List[str]:
    failures: List[str] = []
    hx, hy, hz = _heights(x1, y1, z1, x2, y2, z2)

    for name in ("hop_n", "region_n", "cantor_x", "cantor_y", "cantor_z", "cantor_t"):
        env = result.get(name)
        if not isinstance(env, dict) or not env.get("public_proof"):
            failures.append(f"{name}: envelope missing")
            continue
        if env.get("secret_key") and sha256(bytes.fromhex(env["secret_key"])).hex() != env["public_proof"]:
            failures.append(f"{name}: public_proof is not sha256(secret_key)")
    if failures:
        return failures

    k = terrain_k(x=x2, y=y2, z=z2, plane=plane)
    if int(result.get("K", -1)) != k:
        failures.append(f"K: server {result.get('K')} but terrain gives {k}")
    if result["cantor_t"]["public_proof"] != _dsha_hex(_temporal(previous_event_id_hex, k)):
        failures.append("cantor_t: does not match the temporal root for this previous_event_id and K")

    if int(result.get("max_height", -1)) != max(hx, hy, hz):
        failures.append(f"max_height: server {result.get('max_height')} but axes give {max(hx, hy, hz)}")

    for axis, v1, v2, h in (("x", x1, x2, hx), ("y", y1, y2, hy), ("z", z1, z2, hz)):
        env = result[f"cantor_{axis}"]
        if h == 0:
            if env["public_proof"] != _dsha_hex(v2):
                failures.append(f"cantor_{axis}: trivial axis root is not the coordinate")
        elif h <= local_ceiling:
            local_root = compute_axis_cantor(v1, v2, max_compute_height=h)
            if env["public_proof"] != _dsha_hex(local_root):
                failures.append(f"cantor_{axis}: h={h} root differs from the local recomputation")

    if len(str(result["hop_n"]["public_proof"])) != 64:
        failures.append("hop_n: public_proof is not 32 bytes of hex")
    return failures


def cloud_hop_from_result(job: Dict[str, Any], x1, y1, z1, x2, y2, z2) -> CloudHop:
    result = job["result"]
    return CloudHop(
        proof_hash=result["hop_n"]["public_proof"],
        terrain_k=int(result["K"]),
        lookup_id=result["region_n"]["public_proof"],
        location_decryption_key=result["region_n"].get("secret_key", ""),
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

    roots: List[int] = []
    for i, (axis, v1, v2) in enumerate((("x", x1, x2), ("y", y1, y2), ("z", z1, z2))):
        h = heights[i]
        base = (min(v1, v2) >> h) << h
        bases = result.get("bases")
        if bases and int(bases[i]) != base:
            failures.append(f"bases[{axis}]: server {bases[i]} but aligned base is {base}")
        try:
            root = bytes.fromhex(result[f"merkle_{axis}"])
            siblings = [bytes.fromhex(s) for s in result["inclusion_proofs"][axis]]
        except (KeyError, ValueError, TypeError):
            failures.append(f"merkle_{axis}: root or inclusion path missing")
            continue
        if h == 0:
            if siblings or root != merkle_leaf(v2):
                failures.append(f"merkle_{axis}: trivial axis root is not the leaf hash")
        elif not verify_merkle_inclusion(v2, siblings, root, h, base):
            failures.append(f"merkle_{axis}: inclusion path does not prove the destination leaf")
        roots.append(int.from_bytes(root, "big"))
    if failures:
        return failures

    region_m = cantor_pair(cantor_pair(roots[0], roots[1]), roots[2])
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
        inclusion_proofs={a: [bytes.fromhex(s) for s in result["inclusion_proofs"][a]] for a in ("x", "y", "z")},
        lca_heights=heights,
        proof_hash=result["proof_hash"],
        terrain_k=k,
        job_id=job["id"],
        cost_msats=int(job.get("cost_msats") or 0),
        region_m=region_m,
        sidestep_n=cantor_pair(region_m, _temporal(previous_event_id_hex, k)),
    )
