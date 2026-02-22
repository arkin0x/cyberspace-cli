from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Sequence

from cyberspace_core.coords import coord_to_xyz


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
