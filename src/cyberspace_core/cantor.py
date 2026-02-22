from __future__ import annotations

import hashlib


def cantor_pair(a: int, b: int) -> int:
    s = a + b
    return (s * (s + 1)) // 2 + b


def int_to_bytes_be_min(n: int) -> bytes:
    if n < 0:
        raise ValueError("expected non-negative int")
    if n == 0:
        return b"\x00"
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_int_hex(n: int) -> str:
    return sha256_hex(int_to_bytes_be_min(n))


def int_to_hex_be_min(n: int, *, prefix: str = "0x") -> str:
    """Hex string for an int using minimal big-endian bytes (0 -> 0x00).

    This avoids Python's base-10 int->str conversion limits for extremely large integers.
    """
    return prefix + int_to_bytes_be_min(n).hex()
