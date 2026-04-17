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


def make_hyperjump_event(
    *,
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    to_height: str,
    from_height: int | None = None,
    from_hj_hex: str | None = None,
    proof_hex: str | None = None,
    kind: int = 3333,
) -> Dict[str, Any]:
    """Create a hyperjump action event per DECK-0001 §7.
    
    This action traverses between Hyperjumps within Hyperspace.
    
    Args:
        pubkey_hex: 64-char hex pubkey
        created_at: Unix timestamp
        genesis_event_id: The spawn event ID (64-char hex)
        previous_event_id: The previous movement event ID (64-char hex)
        prev_coord_hex: The previous coordinate (64-char hex)
        coord_hex: The destination Hyperjump coordinate (64-char hex)
        to_height: The destination Bitcoin block height
        from_height: The origin Bitcoin block height (DECK-0001, optional for backward compat)
        from_hj_hex: The origin Hyperjump Merkle root (DECK-0001, optional for backward compat)
        proof_hex: Hyperspace proof as hex string (DECK-0001, optional for backward compat)
        kind: Event kind (default: 3333)
        
    Returns:
        Complete Nostr event dict with blank signature
    """
    tags: List[List[str]] = [
        ["A", "hyperjump"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["B", str(to_height)],
    ]
    
    # DECK-0001 §7 tags (optional for backward compatibility)
    if from_height is not None:
        tags.append(["from_height", str(from_height)])
    if from_hj_hex is not None:
        tags.append(["from_hj", from_hj_hex])
    if proof_hex is not None:
        tags.append(["proof", proof_hex])
    
    tags.extend(_sector_tags_from_coord_hex(coord_hex))
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content="")


def make_enter_hyperspace_event(
    *,
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    merkle_root_hex: str,
    block_height: int,
    axis: str,
    proof_hex: str,
    kind: int = 3333,
) -> Dict[str, Any]:
    """Create an enter-hyperspace action event per DECK-0001 §I.3.
    
    This action boards the Hyperspace network from Cyberspace via a sector-plane entry.
    The coordinate must be on a sector plane that matches the target Hyperjump's sector
    on the specified axis (X, Y, or Z).
    
    Args:
        pubkey_hex: 64-char hex pubkey
        created_at: Unix timestamp
        genesis_event_id: The spawn event ID (64-char hex)
        previous_event_id: The previous movement event ID (64-char hex)
        prev_coord_hex: The previous coordinate (64-char hex)
        coord_hex: The entered coordinate on the sector plane (64-char hex)
        merkle_root_hex: The Merkle root of the Hyperjump being entered (64-char hex)
        block_height: The Bitcoin block height of the Hyperjump
        axis: Which plane was used ('X', 'Y', or 'Z')
        proof_hex: Standard Cantor proof for reaching the coordinate (64-char hex)
        kind: Event kind (default: 3333)
        
    Returns:
        Complete Nostr event dict with blank signature
        
    Raises:
        ValueError: If axis is not 'X', 'Y', or 'Z'
    """
    if axis not in ('X', 'Y', 'Z'):
        raise ValueError(f"axis must be 'X', 'Y', or 'Z', got '{axis}'")
    
    tags: List[List[str]] = [
        ["A", "enter-hyperspace"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["M", merkle_root_hex],
        ["B", str(block_height)],
        ["axis", axis],
        ["proof", proof_hex],
    ]
    tags.extend(_sector_tags_from_coord_hex(coord_hex))
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content="")


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
        tags.append(["h", str(int(height_hint))])
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
    lca_heights: tuple,
    kind: int = 3333,
) -> Dict[str, Any]:
    """Create a sidestep movement event (kind 3333, A=sidestep).

    Parameters
    ----------
    merkle_roots_hex : colon-separated hex string "M_x:M_y:M_z" (each 64 hex chars)
    merkle_proofs_hex : colon-separated hex string "proof_x:proof_y:proof_z"
        Each per-axis proof is concatenated sibling hashes (64*h hex chars per axis).
        Empty string for trivial axes (h=0).
    lca_heights : (hx, hy, hz) tuple of per-axis LCA heights
    """
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
        ["hx", str(hx)],
        ["hy", str(hy)],
        ["hz", str(hz)],
    ]
    tags.extend(_sector_tags_from_coord_hex(coord_hex))
    return new_event(pubkey_hex=pubkey_hex, created_at=created_at, kind=kind, tags=tags, content=proof_hash_hex)
