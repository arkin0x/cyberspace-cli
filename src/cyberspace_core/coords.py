"""Cyberspace coordinate utilities.

This module provides:
- Bit-interleaved 256-bit coordinates (X/Y/Z are 85-bit unsigned ints + 1 plane bit)
- Dataspace mapping from GPS (WGS84 lat/lon[/alt]) into the 85-bit axis space
- Inverse mapping from dataspace coord/xyz back to WGS84 GPS (lat/lon/alt)

Axis orientation for the GPS mapping starts from standard Earth-Centered,
Earth-Fixed (ECEF), then permutes axes to match cyberspace naming:

ECEF:
- +X_ecef points to (lat=0°, lon=0°)
- +Y_ecef points to (lat=0°, lon=90°E)
- +Z_ecef points to the North Pole

Cyberspace dataspace:
- +X_cs = +X_ecef
- +Y_cs = +Z_ecef
- +Z_cs = +Y_ecef

## Canonical GPS->dataspace mapping (deterministic)
The GPS->dataspace conversion is consensus-critical. Implementations must avoid
platform float/libm variability and use deterministic Decimal arithmetic.

Canonical constants:
- `CANONICAL_GPS_TO_DATASPACE_SPEC_VERSION = "2026-03-16-h34-corrected"`
- Decimal context: `prec = 96`, `rounding = ROUND_HALF_EVEN`
- π constant: exact decimal string in `PI_STR` (truncated, not rounded)
- Trig termination: `TRIG_EPS = 1e-88`, `TRIG_MAX_ITER = 256`
- H34 scaling: `units_per_km = 1000 * 2^33`

Canonical axis mapping:
- `u = km * units_per_km + 2^84`
- round with `ROUND_HALF_EVEN`
- clamp to `[0, 2^85 - 1]`

This places Earth's center at axis midpoint `2^84` and yields an axis length of
~4.5 trillion km (half-axis ~2.25 trillion km).
"""

from __future__ import annotations

import math
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from typing import Tuple, Union

AXIS_BITS = 85
AXIS_UNITS = 1 << AXIS_BITS  # 2^85
AXIS_MAX = AXIS_UNITS - 1
AXIS_CENTER = 1 << (AXIS_BITS - 1)  # 2^84

CANONICAL_GPS_TO_DATASPACE_SPEC_VERSION = "2026-03-16-h34-corrected"

# Decimal context used for canonical GPS->dataspace conversion.
# This does *not* affect global Decimal state; we always use localcontext().
DECIMAL_PREC = 96  # guard digits for trig + sqrt + scaling

# Trig series termination + safety bound (consensus-critical).
TRIG_EPS = Decimal("1e-88")
TRIG_MAX_ITER = 256

# π constant used for degrees->radians and trig range reduction.
# NOTE: PI_STR is part of the canonical spec. It is truncated (not rounded).
PI_STR = (
    "3.1415926535897932384626433832795028841971693993751058209749445923078164062862089986280348253421170679"
)
PI = Decimal(PI_STR)
TWO_PI = PI * 2
HALF_PI = PI / 2

NumberLike = Union[int, float, str, Decimal]

PLANE_DATASPACE = 0
PLANE_IDEASPACE = 1

# H34 scale (spec §4.4 step 9): units_per_km = 1000 * 2^33.
UNITS_PER_KM_INT = 1000 * (1 << 33)
UNITS_PER_KM = Decimal(UNITS_PER_KM_INT)
KM_PER_UNIT = Decimal(1) / UNITS_PER_KM

# Derived dataspace extents (for visualization/inverse mapping helpers).
DATASPACE_AXIS_KM = Decimal(AXIS_UNITS) / UNITS_PER_KM
DATASPACE_HALF_AXIS_KM = DATASPACE_AXIS_KM / 2

# WGS84 constants (GPS uses WGS84)
WGS84_A_M = Decimal("6378137")
WGS84_F = Decimal(1) / Decimal("298.257223563")
WGS84_E2 = WGS84_F * (Decimal(2) - WGS84_F)


def xyz_to_coord(x: int, y: int, z: int, plane: int = PLANE_DATASPACE) -> int:
    """Convert (x, y, z, plane) to a 256-bit interleaved coordinate."""
    coord = plane & 1
    for i in range(AXIS_BITS):
        coord |= ((z >> i) & 1) << (1 + i * 3)
        coord |= ((y >> i) & 1) << (2 + i * 3)
        coord |= ((x >> i) & 1) << (3 + i * 3)
    return coord


def coord_to_xyz(coord: int) -> Tuple[int, int, int, int]:
    """Convert a 256-bit interleaved coordinate back to (x, y, z, plane)."""
    plane = coord & 1
    x = y = z = 0
    for i in range(AXIS_BITS):
        z |= ((coord >> (1 + i * 3)) & 1) << i
        y |= ((coord >> (2 + i * 3)) & 1) << i
        x |= ((coord >> (3 + i * 3)) & 1) << i
    return (x, y, z, plane)


def _clamp_int(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def geodetic_to_ecef_m_float(lat_deg: float, lon_deg: float, alt_m: float = 0.0) -> Tuple[float, float, float]:
    """Convert WGS84 geodetic to ECEF in meters using binary floats.

    Kept for reference/benchmarking. Not used by the canonical GPS->dataspace path.
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    # Radius of curvature in the prime vertical
    a = float(WGS84_A_M)
    e2 = float(WGS84_E2)
    n = a / math.sqrt(1.0 - e2 * sin_lat * sin_lat)

    x = (n + alt_m) * cos_lat * cos_lon
    y = (n + alt_m) * cos_lat * sin_lon
    z = (n * (1.0 - e2) + alt_m) * sin_lat
    return (x, y, z)


def _to_decimal(x: NumberLike) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        # Canonical conversion from float to decimal
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x)
    raise TypeError(f"unsupported numeric type: {type(x)}")


def _wrap_lon_deg(lon_deg: Decimal) -> Decimal:
    """Wrap longitude to [-180, 180)."""
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        # Python's Decimal % is well-defined.
        lon = (lon_deg + Decimal(180)) % Decimal(360)
        return lon - Decimal(180)


def _clamp_lat_deg(lat_deg: Decimal) -> Decimal:
    if lat_deg < Decimal(-90):
        return Decimal(-90)
    if lat_deg > Decimal(90):
        return Decimal(90)
    return lat_deg


def _sin_cos_decimal(x: Decimal) -> Tuple[Decimal, Decimal]:
    """Deterministic sin/cos for Decimal radians.

    Uses range reduction to [-pi/2, pi/2] then Taylor series.

    This is intended for consensus use (avoid platform libm variance).
    """
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        ctx.rounding = ROUND_HALF_EVEN

        # Reduce to (-pi, pi]
        x = x % TWO_PI
        if x > PI:
            x -= TWO_PI

        # Reduce to [-pi/2, pi/2] using symmetries.
        cos_sign = Decimal(1)
        if x > HALF_PI:
            x = PI - x
            cos_sign = Decimal(-1)
        elif x < -HALF_PI:
            x = -PI - x
            cos_sign = Decimal(-1)

        x2 = x * x

        # Taylor series with deterministic termination.
        # Terminate when abs(term) < TRIG_EPS (consensus-critical).

        # sin
        sin_sum = x
        sin_term = x
        for k in range(1, TRIG_MAX_ITER + 1):
            # term *= -x^2 / ((2k)*(2k+1))
            denom = Decimal((2 * k) * (2 * k + 1))
            sin_term = -sin_term * x2 / denom
            sin_sum += sin_term
            if abs(sin_term) < TRIG_EPS:
                break
        else:
            raise ValueError("sin() Taylor series did not converge")

        # cos
        cos_sum = Decimal(1)
        cos_term = Decimal(1)
        for k in range(1, TRIG_MAX_ITER + 1):
            # term *= -x^2 / ((2k-1)*(2k))
            denom = Decimal((2 * k - 1) * (2 * k))
            cos_term = -cos_term * x2 / denom
            cos_sum += cos_term
            if abs(cos_term) < TRIG_EPS:
                break
        else:
            raise ValueError("cos() Taylor series did not converge")

        return (sin_sum, cos_sum * cos_sign)


def geodetic_to_ecef_m(lat_deg: NumberLike, lon_deg: NumberLike, alt_m: NumberLike = 0) -> Tuple[Decimal, Decimal, Decimal]:
    """Convert WGS84 geodetic (lat, lon, altitude) to ECEF (x,y,z) in meters.

    Canonical / deterministic implementation using Decimal.

    - `lat_deg` is clamped to [-90, 90]
    - `lon_deg` is wrapped to [-180, 180)
    """
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        ctx.rounding = ROUND_HALF_EVEN

        lat_d = _clamp_lat_deg(_to_decimal(lat_deg))
        lon_d = _wrap_lon_deg(_to_decimal(lon_deg))
        alt_d = _to_decimal(alt_m)

        # degrees -> radians
        lat = lat_d * PI / Decimal(180)
        lon = lon_d * PI / Decimal(180)

        sin_lat, cos_lat = _sin_cos_decimal(lat)
        sin_lon, cos_lon = _sin_cos_decimal(lon)

        # Radius of curvature in the prime vertical
        one = Decimal(1)
        n = WGS84_A_M / (one - WGS84_E2 * sin_lat * sin_lat).sqrt()

        x = (n + alt_d) * cos_lat * cos_lon
        y = (n + alt_d) * cos_lat * sin_lon
        z = (n * (one - WGS84_E2) + alt_d) * sin_lat
        return (x, y, z)


def _km_to_axis_u(km_from_center: Decimal) -> int:
    """Map kilometers (centered at 0) into an unsigned 85-bit axis value (Decimal).

    Rounding is consensus-critical and uses ROUND_HALF_EVEN.
    """
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        ctx.rounding = ROUND_HALF_EVEN

        u = km_from_center * UNITS_PER_KM + Decimal(AXIS_CENTER)
        u_int = int(u.to_integral_value(rounding=ROUND_HALF_EVEN))
        return _clamp_int(u_int, 0, AXIS_MAX)


def ecef_km_to_dataspace_xyz(x_km: NumberLike, y_km: NumberLike, z_km: NumberLike) -> Tuple[int, int, int]:
    """Convert ECEF kilometers to dataspace (x,y,z) 85-bit axis values.

    Note: this function applies the axis permutation described in the module docstring:
      X_cs = X_ecef
      Y_cs = Z_ecef
      Z_cs = Y_ecef
    """
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        ctx.rounding = ROUND_HALF_EVEN

        x_km_d = _to_decimal(x_km)
        y_km_d = _to_decimal(y_km)
        z_km_d = _to_decimal(z_km)

        x_cs_km = x_km_d
        y_cs_km = z_km_d
        z_cs_km = y_km_d
        return (_km_to_axis_u(x_cs_km), _km_to_axis_u(y_cs_km), _km_to_axis_u(z_cs_km))


def gps_to_dataspace_xyz(
    lat_deg: NumberLike,
    lon_deg: NumberLike,
    altitude_m: NumberLike = 0,
    *,
    clamp_to_surface: bool = True,
) -> Tuple[int, int, int]:
    """Convert a GPS coordinate to dataspace (x,y,z) axis values.

    Canonical conversion uses Decimal throughout.

    If clamp_to_surface is True, altitude is forced to 0m (WGS84 ellipsoid surface).
    """
    alt = Decimal(0) if clamp_to_surface else _to_decimal(altitude_m)
    x_m, y_m, z_m = geodetic_to_ecef_m(lat_deg, lon_deg, alt)

    # meters -> kilometers
    km = Decimal(1000)
    return ecef_km_to_dataspace_xyz(x_m / km, y_m / km, z_m / km)


def gps_to_dataspace_coord(
    lat_deg: NumberLike,
    lon_deg: NumberLike,
    altitude_m: NumberLike = 0,
    *,
    clamp_to_surface: bool = True,
) -> int:
    """Convert a GPS coordinate to an interleaved 256-bit dataspace coordinate."""
    x, y, z = gps_to_dataspace_xyz(
        lat_deg,
        lon_deg,
        altitude_m,
        clamp_to_surface=clamp_to_surface,
    )
    return xyz_to_coord(x, y, z, plane=PLANE_DATASPACE)


def _axis_u_to_km(axis_u: int) -> Decimal:
    """Map an unsigned 85-bit axis value back to centered kilometers."""
    if not (0 <= int(axis_u) <= AXIS_MAX):
        raise ValueError(f"axis value {axis_u} is out of range [0, {AXIS_MAX}]")

    with localcontext() as ctx:
        ctx.prec = DECIMAL_PREC
        ctx.rounding = ROUND_HALF_EVEN

        return (Decimal(int(axis_u)) - Decimal(AXIS_CENTER)) * KM_PER_UNIT


def dataspace_xyz_to_ecef_km(x: int, y: int, z: int) -> Tuple[Decimal, Decimal, Decimal]:
    """Convert dataspace xyz (u85) back to ECEF kilometers.

    This applies the inverse axis permutation used by `ecef_km_to_dataspace_xyz`:
      X_ecef = X_cs
      Y_ecef = Z_cs
      Z_ecef = Y_cs
    """
    x_cs_km = _axis_u_to_km(x)
    y_cs_km = _axis_u_to_km(y)
    z_cs_km = _axis_u_to_km(z)

    x_ecef_km = x_cs_km
    y_ecef_km = z_cs_km
    z_ecef_km = y_cs_km
    return (x_ecef_km, y_ecef_km, z_ecef_km)


def ecef_m_to_geodetic_float(x_m: float, y_m: float, z_m: float) -> Tuple[float, float, float]:
    """Convert ECEF meters to WGS84 geodetic (lat_deg, lon_deg, alt_m) using floats."""
    a = float(WGS84_A_M)
    f = float(WGS84_F)
    e2 = float(WGS84_E2)
    b = a * (1.0 - f)
    ep2 = (a * a - b * b) / (b * b)

    p = math.hypot(x_m, y_m)
    if p < 1e-9:
        lat = math.pi / 2.0 if z_m >= 0.0 else -math.pi / 2.0
        lon = 0.0
        alt = abs(z_m) - b
        return (math.degrees(lat), lon, alt)

    lon = math.atan2(y_m, x_m)
    theta = math.atan2(a * z_m, b * p)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)

    lat = math.atan2(z_m + ep2 * b * sin_t * sin_t * sin_t, p - e2 * a * cos_t * cos_t * cos_t)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)

    n = a / math.sqrt(1.0 - e2 * sin_lat * sin_lat)
    if abs(cos_lat) < 1e-12:
        alt = abs(z_m) - b
    else:
        alt = p / cos_lat - n

    lat_deg = math.degrees(lat)
    lon_deg = math.degrees(lon)
    lon_deg = ((lon_deg + 180.0) % 360.0) - 180.0
    return (lat_deg, lon_deg, alt)


def dataspace_xyz_to_gps(x: int, y: int, z: int) -> Tuple[float, float, float]:
    """Convert dataspace xyz (u85) to WGS84 geodetic (lat_deg, lon_deg, alt_m)."""
    x_km, y_km, z_km = dataspace_xyz_to_ecef_km(x, y, z)

    km_to_m = Decimal(1000)
    x_m = float(x_km * km_to_m)
    y_m = float(y_km * km_to_m)
    z_m = float(z_km * km_to_m)

    return ecef_m_to_geodetic_float(x_m, y_m, z_m)


def dataspace_coord_to_gps(coord: int) -> Tuple[float, float, float, int]:
    """Convert an interleaved 256-bit coordinate to GPS + plane.

    Returns `(lat_deg, lon_deg, alt_m, plane)`.
    """
    x, y, z, plane = coord_to_xyz(coord)
    lat_deg, lon_deg, alt_m = dataspace_xyz_to_gps(x, y, z)
    return (lat_deg, lon_deg, alt_m, plane)
