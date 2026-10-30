from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Sequence

from cyberspace_core.coords import coord_to_xyz
from cyberspace_core.movement import decode_nonce
from cyberspace_core.residue import is_lower_hex


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def serialize_event_for_id(
    *,
    pubkey_hex: str,
    created_at: int,
    kind: int,
    tags: Sequence[Sequence[str]],
    content: str,
) -> bytes:
    # NIP-01 canonical serialization: [0, pubkey, created_at, kind, tags, content]
    payload = [0, pubkey_hex, created_at, kind, list(list(t) for t in tags), content]
    s = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return s.encode("utf-8")


def compute_event_id_hex(
    *,
    pubkey_hex: str,
    created_at: int,
    kind: int,
    tags: Sequence[Sequence[str]],
    content: str,
) -> str:
    return _sha256_hex(
        serialize_event_for_id(
            pubkey_hex=pubkey_hex,
            created_at=created_at,
            kind=kind,
            tags=tags,
            content=content,
        )
    )


def new_event(
    *,
    pubkey_hex: str,
    created_at: int,
    kind: int,
    tags: Sequence[Sequence[str]],
    content: str = "",
) -> Dict[str, Any]:
    eid = compute_event_id_hex(
        pubkey_hex=pubkey_hex,
        created_at=created_at,
        kind=kind,
        tags=tags,
        content=content,
    )
    return {
        "id": eid,
        "pubkey": pubkey_hex,
        "created_at": created_at,
        "kind": kind,
        "tags": [list(t) for t in tags],
        "content": content,
        # Signature is intentionally blank for now. We can sign at publish-time.
        "sig": "",
    }


def _sector_tags_from_coord_hex(coord_hex: str) -> List[List[str]]:
    coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
    x, y, z, _plane = coord_to_xyz(coord_int)
    sector_bits = 30
    sx = x >> sector_bits
    sy = y >> sector_bits
    sz = z >> sector_bits
    return [
        ["X", str(sx)],
        ["Y", str(sy)],
        ["Z", str(sz)],
        ["S", f"{sx}-{sy}-{sz}"],
    ]


def make_spawn_event(*, pubkey_hex: str, created_at: int, coord_hex: str, kind: int = 3333) -> Dict[str, Any]:
    tags: List[List[str]] = [["A", "spawn"], ["C", coord_hex]]
    tags.extend(_sector_tags_from_coord_hex(coord_hex))
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content="")


_HEX32 = re.compile(r"[0-9a-f]{64}")


def make_hyperjump_event(
    *,
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    from_height: int,
    to_height: int,
    proof_hash_hex: str,
    ride_openings_hex: str,
    nonce_hex: str,
    as_of: int | None = None,
    kind: int = 3333,
) -> Dict[str, Any]:
    """Create a ride (kind 3333, A=hyperjump) per DECK-0001 5.2, ride openings version 2.

    The tags are the ones the chain rules read on a ride (CYBERSPACE_V2 8.8),
    in the order ONOSENDAI's and cyberspace-mcp's hyperjumpTemplate write
    them: A, e genesis, e previous, c, C, from_height, B, as_of (only when
    given), proof, mp, mn, then the sector tags of C.

    Parameters
    ----------
    from_height : B_from, the block the ride departs from: the station on the
        first ride after boarding (DECK-0001 4.2), the previous ride's B after that (4.3)
    to_height : B_to, the destination block; C is its stop coordinate (section 1)
    proof_hash_hex : the ride's Merkle root (5.4), 32 bytes of lowercase hex
    ride_openings_hex : the mp value (5.5), as ride.encode_ride_openings writes it
    nonce_hex : the re-roll nonce (5.5) as exactly 16 lowercase hex chars. Every
        ride carries it (5.8); only the rides listed in
        decks/grandfathered-v1-hyperjumps.txt were published without one.
    as_of : the station set bound (4.2). Required on the first ride after
        boarding and left out after that; which ride this is is the caller's call.

    A zero-length ride (from_height equal to to_height) does not exist (5.6)
    and is refused, as are an as_of below B or below from_height (4.2: the
    station and the destination both lie within the bound), and ids,
    coordinates or proof values that are not well formed (8.8).
    """
    for name, value in (("genesis_event_id", genesis_event_id), ("previous_event_id", previous_event_id),
                        ("prev_coord_hex", prev_coord_hex), ("coord_hex", coord_hex)):
        if not isinstance(value, str) or not _HEX32.fullmatch(value):
            raise ValueError(f"{name} must be 64 lowercase hex characters")
    for name, height in (("from_height", from_height), ("to_height", to_height), ("as_of", as_of)):
        if height is not None and (isinstance(height, bool) or not isinstance(height, int) or height < 0):
            raise ValueError(f"{name} must be a non-negative block height")
    if from_height == to_height:
        raise ValueError(f"a zero-length ride (block {to_height} to itself) does not exist (DECK-0001 5.6)")
    if as_of is not None and as_of < max(from_height, to_height):
        raise ValueError(
            f"as_of ({as_of}) is below from_height ({from_height}) or B ({to_height}); "
            "the station set bound covers the station and the destination (DECK-0001 4.2)"
        )
    if not isinstance(proof_hash_hex, str) or not _HEX32.fullmatch(proof_hash_hex):
        raise ValueError("proof_hash_hex must be the ride's 32-byte Merkle root as 64 lowercase hex characters (DECK-0001 5.4)")
    if not ride_openings_hex:
        raise ValueError("ride_openings_hex must hold the ride's sampled openings (DECK-0001 5.5)")
    if decode_nonce(nonce_hex) is None:
        raise ValueError("nonce_hex must be exactly 16 lowercase hex characters (DECK-0001 5.2)")
    tags: List[List[str]] = [
        ["A", "hyperjump"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["from_height", str(from_height)],
        ["B", str(to_height)],
    ]
    if as_of is not None:
        tags.append(["as_of", str(as_of)])
    tags += [
        ["proof", proof_hash_hex],
        ["mp", ride_openings_hex],
        ["mn", nonce_hex],
    ]
    tags.extend(_sector_tags_from_coord_hex(coord_hex))
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content="")


# The bag's height tag (spec section 8.6). Uppercase since 2026-10-21: NIP-29
# reads an `h` tag on an event of any kind as the group it is posted to, so a
# NIP-29 relay refused bags that carried ["h", "<height>"]. `h` is read only on
# events written before then (height_from_tags) and never written.
HEIGHT_TAG = "H"
LEGACY_HEIGHT_TAG = "h"
_CANONICAL_HEIGHT = re.compile(r"(0|[1-9][0-9]*)")


def height_from_tags(tags: Any) -> int | None:
    """The height a bag's tags state (spec section 8.6), or None when they state none.

    An event that carries any `H` tag is read by `H` alone, and its `h` tags
    are ignored; an event without `H` is read by a legacy `h`. The tag read
    must appear exactly once with a canonical decimal value (no sign, no
    leading zeros except "0"); more than one, or a malformed value, and the
    bag states no height. That does not make the bag invalid: the height tag
    is optional, and the key that opens the bag says its height anyway.
    """
    if not isinstance(tags, list):
        return None
    rows = [t for t in tags if isinstance(t, list) and t]
    name = HEIGHT_TAG if any(t[0] == HEIGHT_TAG for t in rows) else LEGACY_HEIGHT_TAG
    found = [t for t in rows if t[0] == name]
    if len(found) != 1:
        return None
    value = found[0][1] if len(found[0]) >= 2 else None
    if not isinstance(value, str) or not _CANONICAL_HEIGHT.fullmatch(value):
        return None
    try:
        return int(value)
    except ValueError:
        # Canonical but too long for int() (Python's digit limit): a value
        # from an untrusted event that states no usable height.
        return None


def make_encrypted_content_event(
    *,
    pubkey_hex: str,
    created_at: int,
    lookup_id_hex: str,
    algorithm: str,
    ciphertext_b64: str,
    version: str = "2",
    height_hint: int | None = None,
    content: str = "",
    kind: int = 33330,
) -> Dict[str, Any]:
    tags: List[List[str]] = [
        ["d", lookup_id_hex],
        ["encrypted", algorithm, ciphertext_b64],
        ["version", version],
    ]
    if height_hint is not None:
        tags.append([HEIGHT_TAG, str(int(height_hint))])
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content=content)


def make_hop_event(
    *,
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    proof_hex: str,
    nonce_hex: Optional[str] = None,
    openings_hex: Optional[str] = None,
    kind: int = 3333,
) -> Dict[str, Any]:
    """Create a hop movement event (kind 3333, A=hop, CYBERSPACE_V2 8.4).

    Version 2 (residue openings, 5.10): proof_hex is the seal, nonce_hex the
    re-roll nonce (the mn tag, 16 lowercase hex characters) and openings_hex
    the 16 openings (the mp tag), written in that order after the proof, each
    exactly once. Without nonce_hex and openings_hex the event is a version 1
    hop whose proof is the 5.6 proof_hash: what a HOSAKA result carries until
    HOSAKA switches to version 2."""
    if not is_lower_hex(proof_hex, 64):
        raise ValueError("proof_hex must be 64 lowercase hex characters (CYBERSPACE_V2 8.4)")
    if (nonce_hex is None) != (openings_hex is None):
        raise ValueError("a version 2 hop carries both mn and mp; a version 1 hop carries neither")
    tags: List[List[str]] = [
        ["A", "hop"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["proof", proof_hex],
    ]
    if nonce_hex is not None and openings_hex is not None:
        if not is_lower_hex(nonce_hex, 16):
            raise ValueError("nonce_hex must be exactly 16 lowercase hex characters (CYBERSPACE_V2 8.4)")
        if not openings_hex or not is_lower_hex(openings_hex, len(openings_hex)):
            raise ValueError("openings_hex must be non-empty lowercase hex (CYBERSPACE_V2 8.4)")
        tags += [["mn", nonce_hex], ["mp", openings_hex]]
    tags.extend(_sector_tags_from_coord_hex(coord_hex))
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content="")


def make_sidestep_event(
    *,
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    proof_hash_hex: str,
    merkle_roots_hex: str,
    merkle_proofs_hex: str,
    nonce_hex: str,
    lca_heights: tuple,
    kind: int = 3333,
) -> Dict[str, Any]:
    """Create a sidestep movement event (kind 3333, A=sidestep), version 3.

    Parameters
    ----------
    merkle_roots_hex : colon-separated hex string "M_x:M_y:M_z" (each 64 hex chars)
    merkle_proofs_hex : colon-separated hex string "proof_x:proof_y:proof_z"
        Each per-axis segment is the nine openings of CYBERSPACE_V2 6.10 (the
        destination's path, then the eight sampled paths), each h sibling
        hashes, so 64*h*9 hex chars per axis. Empty string for trivial axes (h=0).
    nonce_hex : the re-roll nonce of 6.10 as exactly 16 lowercase hex chars (the mn tag, 8.5)
    lca_heights : (hx, hy, hz) tuple of per-axis LCA heights
    """
    if decode_nonce(nonce_hex) is None:
        raise ValueError("nonce_hex must be exactly 16 lowercase hex characters (CYBERSPACE_V2 8.5)")
    hx, hy, hz = lca_heights
    tags: List[List[str]] = [
        ["A", "sidestep"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["proof", proof_hash_hex],
        ["mr", merkle_roots_hex],
        ["mp", merkle_proofs_hex],
        ["mn", nonce_hex],
        ["hx", str(hx)],
        ["hy", str(hy)],
        ["hz", str(hz)],
    ]
    tags.extend(_sector_tags_from_coord_hex(coord_hex))
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content=proof_hash_hex)
