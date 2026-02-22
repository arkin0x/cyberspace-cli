from __future__ import annotations


def normalize_hex_32(s: str) -> str:
    """Normalize a hex string into exactly 32 bytes (64 lowercase hex chars).

    Accepts inputs with or without a leading `0x`, and with or without leading zeros.

    Examples:
    - "0x1" -> "0000...0001" (64 hex chars)
    - "abc" -> "0000...0abc" (64 hex chars)

    Raises ValueError if the input is not hex or is longer than 32 bytes.
    """
    s = s.strip().lower()
    s = s.removeprefix("0x")
    if not s:
        raise ValueError("empty hex string")
    if len(s) > 64:
        raise ValueError("hex string too long (expected <= 32 bytes)")
    # Validate hex
    try:
        int(s, 16)
    except ValueError as e:
        raise ValueError("invalid hex") from e

    # Left-pad to 32 bytes.
    return s.zfill(64)
