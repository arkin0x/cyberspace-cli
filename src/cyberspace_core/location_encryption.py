from __future__ import annotations
from dataclasses import dataclass
from typing import List

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256
from cyberspace_core.movement import compute_subtree_cantor
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DEFAULT_SCAN_MAX_HEIGHT = 12


@dataclass(frozen=True)
class RegionKeyMaterial:
    height: int
    region_n: int
    location_decryption_key: bytes
    lookup_id_hex: str


def derive_region_n_for_height(
    *,
    x: int,
    y: int,
    z: int,
    height: int,
    max_compute_height: int = 20,
) -> int:
    if height < 0:
        raise ValueError("height must be >= 0")

    bx = (x >> height) << height if height > 0 else x
    by = (y >> height) << height if height > 0 else y
    bz = (z >> height) << height if height > 0 else z

    rx = compute_subtree_cantor(bx, height, max_compute_height=max_compute_height)
    ry = compute_subtree_cantor(by, height, max_compute_height=max_compute_height)
    rz = compute_subtree_cantor(bz, height, max_compute_height=max_compute_height)
    return cantor_pair(cantor_pair(rx, ry), rz)


def derive_region_keys_from_region_n(region_n: int) -> tuple[bytes, str]:
    region_bytes = int_to_bytes_be_min(region_n)
    location_decryption_key = sha256(region_bytes)
    lookup_id_hex = sha256(location_decryption_key).hex()
    return location_decryption_key, lookup_id_hex


def derive_region_key_material_for_height(
    *,
    x: int,
    y: int,
    z: int,
    height: int,
    max_compute_height: int = 20,
) -> RegionKeyMaterial:
    region_n = derive_region_n_for_height(x=x, y=y, z=z, height=height, max_compute_height=max_compute_height)
    decryption_key, lookup_id_hex = derive_region_keys_from_region_n(region_n)
    return RegionKeyMaterial(
        height=height,
        region_n=region_n,
        location_decryption_key=decryption_key,
        lookup_id_hex=lookup_id_hex,
    )


def derive_region_key_material_scan(
    *,
    x: int,
    y: int,
    z: int,
    min_height: int,
    max_height: int,
    max_compute_height: int = 20,
) -> List[RegionKeyMaterial]:
    if min_height < 0:
        raise ValueError("min_height must be >= 0")
    if max_height < min_height:
        raise ValueError("max_height must be >= min_height")

    out: List[RegionKeyMaterial] = []
    for h in range(min_height, max_height + 1):
        out.append(
            derive_region_key_material_for_height(
                x=x, y=y, z=z, height=h, max_compute_height=max_compute_height
            )
        )
    return out


def encrypt_with_location_key(plaintext: bytes, *, location_decryption_key: bytes, nonce: bytes) -> bytes:
    """Encrypt with AES-256-GCM and return nonce||ciphertext_with_tag bytes."""
    if len(location_decryption_key) != 32:
        raise ValueError("location_decryption_key must be 32 bytes")
    if len(nonce) != 12:
        raise ValueError("nonce must be 12 bytes for AES-256-GCM")
    aes = AESGCM(location_decryption_key)
    ciphertext = aes.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_with_location_key(payload: bytes, *, location_decryption_key: bytes) -> bytes:
    """Decrypt nonce||ciphertext_with_tag payload produced by encrypt_with_location_key."""
    if len(location_decryption_key) != 32:
        raise ValueError("location_decryption_key must be 32 bytes")
    if len(payload) < 12 + 16:
        raise ValueError("encrypted payload too short")
    nonce = payload[:12]
    ciphertext = payload[12:]
    aes = AESGCM(location_decryption_key)
    return aes.decrypt(nonce, ciphertext, None)
