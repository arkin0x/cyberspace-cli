from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Sequence

from cyberspace_core.coords import coord_to_xyz
from cyberspace_core.movement import decode_nonce


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


def make_hyperjump_event(
    *,
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    to_height: str,
    kind: int = 3333,
) -> Dict[str, Any]:
    tags: List[List[str]] = [
        ["A", "hyperjump"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["B", str(to_height)],
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
    proof_hash_hex: str,
    kind: int = 3333,
) -> Dict[str, Any]:
    tags: List[List[str]] = [
        ["A", "hop"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["proof", proof_hash_hex],
    ]
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
