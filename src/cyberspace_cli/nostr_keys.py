from __future__ import annotations

import secrets
from typing import Iterable, Optional, Tuple


_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_CHARSET_MAP = {c: i for i, c in enumerate(_CHARSET)}


def _require_coincurve_private_key():
    try:
        from coincurve import PrivateKey  # type: ignore

        return PrivateKey
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "coincurve is required for nostr key operations. Install this package with its dependencies."
        ) from e


def _bech32_polymod(values: Iterable[int]) -> int:
    generator = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= generator[i]
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp: str, data: list[int]) -> list[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _bech32_verify_checksum(hrp: str, data: list[int]) -> bool:
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


def bech32_encode(hrp: str, data: list[int]) -> str:
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(_CHARSET[d] for d in combined)


def bech32_decode(bech: str) -> Tuple[Optional[str], Optional[list[int]]]:
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        return (None, None)
    if bech.lower() != bech and bech.upper() != bech:
        return (None, None)
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech):
        return (None, None)
    hrp = bech[:pos]
    data_part = bech[pos + 1 :]
    try:
        data = [_CHARSET_MAP[c] for c in data_part]
    except KeyError:
        return (None, None)
    if not _bech32_verify_checksum(hrp, data):
        return (None, None)
    return (hrp, data[:-6])


def convertbits(data: bytes, from_bits: int, to_bits: int, pad: bool = True) -> Optional[list[int]]:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << to_bits) - 1
    for b in data:
        acc = (acc << from_bits) | b
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    else:
        if bits >= from_bits:
            return None
        if (acc << (to_bits - bits)) & maxv:
            return None
    return ret


def generate_privkey_bytes() -> bytes:
    PrivateKey = _require_coincurve_private_key()
    while True:
        b = secrets.token_bytes(32)
        try:
            PrivateKey(b)
            return b
        except Exception:
            continue


def generate_nsec() -> str:
    return encode_nsec(generate_privkey_bytes())


def privkey_bytes_from_nsec_or_hex(s: str) -> bytes:
    PrivateKey = _require_coincurve_private_key()

    s = s.strip()
    if s.startswith("nsec1"):
        return decode_nsec(s)
    # hex fallback
    h = s.removeprefix("0x")
    raw = bytes.fromhex(h)
    if len(raw) != 32:
        raise ValueError("expected 32-byte hex private key")
    # validate
    PrivateKey(raw)
    return raw


def pubkey_hex_from_privkey(privkey: bytes) -> str:
    PrivateKey = _require_coincurve_private_key()
    pk = PrivateKey(privkey)
    compressed = pk.public_key.format(compressed=True)
    # Compressed form: 0x02/0x03 + 32-byte X coordinate.
    x_only = compressed[1:]
    return x_only.hex()


def encode_nsec(privkey: bytes) -> str:
    data5 = convertbits(privkey, 8, 5, pad=True)
    if data5 is None:
        raise ValueError("convertbits failed")
    return bech32_encode("nsec", data5)


def encode_npub(pubkey: bytes) -> str:
    data5 = convertbits(pubkey, 8, 5, pad=True)
    if data5 is None:
        raise ValueError("convertbits failed")
    return bech32_encode("npub", data5)


def decode_nsec(nsec: str) -> bytes:
    PrivateKey = _require_coincurve_private_key()

    hrp, data = bech32_decode(nsec)
    if hrp != "nsec" or data is None:
        raise ValueError("invalid nsec")
    b = bytes(_convertbits_list(data, 5, 8, pad=False))
    if len(b) != 32:
        raise ValueError("invalid nsec payload")
    PrivateKey(b)  # validate
    return b


def decode_npub(npub: str) -> bytes:
    hrp, data = bech32_decode(npub)
    if hrp != "npub" or data is None:
        raise ValueError("invalid npub")
    b = bytes(_convertbits_list(data, 5, 8, pad=False))
    if len(b) != 32:
        raise ValueError("invalid npub payload")
    return b


def _convertbits_list(data: list[int], from_bits: int, to_bits: int, pad: bool) -> list[int]:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << to_bits) - 1
    for v in data:
        if v < 0 or (v >> from_bits):
            raise ValueError("invalid value in data")
        acc = (acc << from_bits) | v
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    else:
        if bits >= from_bits:
            raise ValueError("invalid padding")
        if (acc << (to_bits - bits)) & maxv:
            raise ValueError("invalid padding")
    return ret
