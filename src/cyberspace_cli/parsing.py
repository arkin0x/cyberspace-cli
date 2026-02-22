from __future__ import annotations

from dataclasses import dataclass

from cyberspace_core.coords import coord_to_xyz


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


@dataclass(frozen=True)
class ParsedDestination:
    x: int
    y: int
    z: int
    plane: int
    kind: str  # "xyz" | "coord"


def parse_destination_xyz_or_coord(value: str, *, default_plane: int) -> ParsedDestination:
    """Parse a destination string.

    Accepted forms:
    - "x,y,z" or "x,y,z,plane" (decimal or 0x... ints)
    - 256-bit coord hex string (with optional 0x; leading zeros optional)

    If xyz is provided without plane, `default_plane` is used.
    """

    v = value.strip()

    if "," in v:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        try:
            ints = [int(p, 0) for p in parts]
        except ValueError as e:
            raise ValueError("invalid integer in xyz list") from e

        if len(ints) == 3:
            x, y, z = ints
            plane = default_plane
            return ParsedDestination(x=x, y=y, z=z, plane=plane, kind="xyz")
        if len(ints) == 4:
            x, y, z, plane = ints
            return ParsedDestination(x=x, y=y, z=z, plane=plane, kind="xyz")

        raise ValueError("xyz form expects 3 or 4 comma-separated integers")

    # coord hex form
    h = normalize_hex_32(v)
    coord_int = int.from_bytes(bytes.fromhex(h), "big")
    x, y, z, plane = coord_to_xyz(coord_int)
    return ParsedDestination(x=x, y=y, z=z, plane=plane, kind="coord")
