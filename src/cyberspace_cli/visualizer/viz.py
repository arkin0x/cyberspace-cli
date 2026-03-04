from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple

import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from cyberspace_core.coords import (
    AXIS_CENTER,
    AXIS_UNITS,
    DATASPACE_AXIS_KM,
    WGS84_A_M,
    coord_to_xyz,
)


@dataclass(frozen=True)
class SceneConfig:
    # Visualization scaling factor applied to *all* distances in km.
    # This is purely a rendering concern.
    scale: float = 0.5

    # Wireframe grid density
    grid_lines: int = 4

    # Color palette (approximate original client screenshot)
    grid_color: str = "#B000FF"  # neon purple
    earth_color: str = "#2E86FF"  # electric-ish blue
    black_sun_color: str = "#5A2D82"  # dark purple

    earth_alpha: float = 0.25
    black_sun_alpha: float = 0.5

    # Whether to show the midplane (y=0) in addition to top/bottom bounds
    show_midplane: bool = False

    # Camera view
    elev_deg: float = 18.0
    azim_deg: float = -58.0


@dataclass(frozen=True)
class Marker:
    # Position in scene units.
    #
    # In dataspace mode this is interpreted as (X_cs, Y_cs, Z_cs) kilometers from center.
    # In sector mode this is interpreted as sector-local normalized coordinates in [-0.5, +0.5)
    # along each axis (still in cyberspace axis orientation).
    position_km: Tuple[float, float, float]
    color: str
    label: str = ""
    size: int = 30
    shape: str = "o"
    edge_color: str = "#FFFFFF"
    edge_width: float = 0.6
    label_color: Optional[str] = None


# Canonical visualization sanity vectors (spec: visualization_vectors.json), plane=0.
# These are intentionally the major axis directions plus center, useful for visual
# orientation checks in the GUI.
_GOLDEN_VECTOR_COORD_HEX: Tuple[Tuple[str, str], ...] = (
    ("GV center", "e000000000000000000000000000000000000000000000000000000000000000"),
    ("GV +X", "e200000000000000000000000000000000000000000000000000000000000000"),
    ("GV -X", "7200000000000000000000000000000000000000000000000000000000000000"),
    ("GV +Y", "e100000000000000000000000000000000000000000000000000000000000000"),
    ("GV -Y", "a900000000000000000000000000000000000000000000000000000000000000"),
    ("GV +Z", "e080000000000000000000000000000000000000000000000000000000000000"),
    ("GV -Z", "c480000000000000000000000000000000000000000000000000000000000000"),
)


def _axis_u85_to_km_from_center(u85: int) -> float:
    """Convert an unsigned 85-bit axis value to kilometers from cube center."""

    # km_from_center = (u - 2^84) * axis_km / 2^85
    # Use Decimal for high precision, then convert to float for plotting.
    km = (Decimal(u85 - AXIS_CENTER) * DATASPACE_AXIS_KM) / Decimal(AXIS_UNITS)
    return float(km)


def coord_to_dataspace_km(coord: int) -> Tuple[float, float, float]:
    """Decode an interleaved coordinate to (x_km, y_km, z_km) from center.

    Returned axes are *cyberspace* axes (not matplotlib axes):
    - +X points to (lat=0, lon=0) on the equator (prime meridian reference)
    - +Y points toward the North Pole ("up")
    - +Z points toward (lat=0, lon=+90E) ("east"; black sun reference is placed on +Z boundary)

    Note: the plane bit (dataspace=0 / ideaspace=1) does not affect XYZ decoding.
    This visualizer renders both planes on the same geometry.

    Note: matplotlib's mplot3d treats its Z axis as the camera "up" axis.
    For semantic correctness (no axis mirroring), we map:
      (X_cs, Y_cs, Z_cs) -> (X_mpl, Y_mpl, Z_mpl) = (X_cs, Z_cs, Y_cs)
    inside draw_scene().
    """

    x_u, y_u, z_u, _plane = coord_to_xyz(coord)
    return (
        _axis_u85_to_km_from_center(x_u),
        _axis_u85_to_km_from_center(y_u),
        _axis_u85_to_km_from_center(z_u),
    )


def cyberspace_to_mpl(x_cs: float, y_cs: float, z_cs: float) -> Tuple[float, float, float]:
    """Map cyberspace axis coordinates to matplotlib 3D axis coordinates.

    This mapping preserves semantics:
    - +X_cs remains +X (prime meridian direction)
    - +Z_cs maps to +Y_mpl (east / black sun direction)
    - +Y_cs maps to +Z_mpl (up)
    """

    return (x_cs, z_cs, y_cs)


def black_sun_circle_center_mpl(half_extent: float, radius: float) -> Tuple[float, float, float]:
    """Return black sun circle center in mpl coords, tangent to +Z boundary.

    The +Z_cs boundary maps to +Y_mpl = half_extent.
    To make the circle tangent to that boundary in the +Z direction, place
    the center at +Y_mpl = half_extent + radius.
    """

    return (0.0, half_extent + radius, 0.0)


def golden_vector_markers() -> List[Marker]:
    """Return canonical orientation-check markers for dataspace rendering."""
    markers: List[Marker] = []
    for label, coord_hex in _GOLDEN_VECTOR_COORD_HEX:
        coord = int(coord_hex, 16)
        markers.append(
            Marker(
                position_km=coord_to_dataspace_km(coord),
                color="#FFD700",
                label=label,
                size=95,
                shape="^",
                edge_color="#8B7500",
                edge_width=0.9,
                label_color="#000000",
            )
        )
    return markers


def _set_axes_equal(ax) -> None:
    """Make a 3D matplotlib axis have equal scaling."""

    x_limits = ax.get_xlim3d()
    y_limits = ax.get_ylim3d()
    z_limits = ax.get_zlim3d()

    x_range = abs(x_limits[1] - x_limits[0])
    x_middle = np.mean(x_limits)
    y_range = abs(y_limits[1] - y_limits[0])
    y_middle = np.mean(y_limits)
    z_range = abs(z_limits[1] - z_limits[0])
    z_middle = np.mean(z_limits)

    plot_radius = 0.5 * max([x_range, y_range, z_range])

    ax.set_xlim3d([x_middle - plot_radius, x_middle + plot_radius])
    ax.set_ylim3d([y_middle - plot_radius, y_middle + plot_radius])
    ax.set_zlim3d([z_middle - plot_radius, z_middle + plot_radius])


def draw_scene(
    ax,
    *,
    cfg: SceneConfig,
    markers: Optional[List[Marker]] = None,
) -> None:
    """Draw the dataspace scene into a provided 3D matplotlib axis.

    Markers positions are interpreted as (X_cs, Y_cs, Z_cs) kilometers from center.
    Internally we map to matplotlib coordinates without mirroring:
      (X_cs, Y_cs, Z_cs) -> (X_mpl, Y_mpl, Z_mpl) = (X_cs, Z_cs, Y_cs)
    """

    ax.clear()

    half_axis_km = float(Decimal(DATASPACE_AXIS_KM) / 2)

    s = float(cfg.scale)
    half_cs = half_axis_km  # unscaled physical half extent in km
    half = half_cs * s

    # Grids: midplane + top/bottom boundaries for cyberspace Y ("up")
    # In mpl coords, those planes are z = const.
    n = max(3, int(cfg.grid_lines))
    xs = np.linspace(-half, half, n)
    ys = np.linspace(-half, half, n)
    X, Y = np.meshgrid(xs, ys)

    def grid_at_cs_y(y_cs_km: float) -> None:
        # constant mpl z
        _, _, z_mpl = cyberspace_to_mpl(0.0, y_cs_km * s, 0.0)
        Z = np.full_like(X, z_mpl)
        ax.plot_wireframe(
            X,
            Y,
            Z,
            rstride=1,
            cstride=1,
            color=cfg.grid_color,
            linewidth=0.6,
            alpha=0.6,
        )

    if cfg.show_midplane:
        grid_at_cs_y(0.0)
    grid_at_cs_y(+half_cs)
    grid_at_cs_y(-half_cs)

    # Earth sphere (to-scale relative to dataspace cube)
    # Since mpl's z axis is "up", and we've mapped cs Y->mpl Z, this makes Earth look upright.
    earth_radius_km = float(Decimal(WGS84_A_M) / Decimal(1000))
    r_e = earth_radius_km * s

    u = np.linspace(0, 2 * np.pi, 64)
    v = np.linspace(0, np.pi, 32)
    xe = r_e * np.outer(np.cos(u), np.sin(v))
    ye = r_e * np.outer(np.sin(u), np.sin(v))
    ze = r_e * np.outer(np.ones_like(u), np.cos(v))
    ax.plot_surface(
        xe,
        ye,
        ze,
        color=cfg.earth_color,
        alpha=cfg.earth_alpha,
        linewidth=0,
        shade=True,
    )

    t = np.linspace(0, 2 * np.pi, 256)

    # Equator ring in cyberspace coordinates: Y_cs=0.
    # In mpl coordinates, that is Z=0.
    ax.plot(r_e * np.cos(t), r_e * np.sin(t), np.zeros_like(t), color="#7FD3FF", linewidth=1.0)

    # Prime meridian ring: Z_cs=0 (great circle through +X and +Y).
    # In mpl coordinates, Z_cs maps to Y.
    ax.plot(r_e * np.cos(t), np.zeros_like(t), r_e * np.sin(t), color="#7FD3FF", linewidth=1.0)

    # Black sun: reference marker for +Z_cs (east direction).
    # In mpl coords, Z_cs maps to Y.
    black_sun_radius_km = earth_radius_km * 2.2 * s
    r_b = float(black_sun_radius_km)
    black_sun_center = black_sun_circle_center_mpl(half_extent=half, radius=r_b)

    # Draw the black sun as a filled circle (disk) tangent to the +Z boundary.
    t_circle = np.linspace(0, 2 * np.pi, 180)
    xb = black_sun_center[0] + r_b * np.cos(t_circle)
    yb = np.full_like(xb, black_sun_center[1])
    zb = black_sun_center[2] + r_b * np.sin(t_circle)
    disk_verts = [list(zip(xb, yb, zb))]
    ax.add_collection3d(
        Poly3DCollection(
            disk_verts,
            facecolors=cfg.black_sun_color,
            edgecolors=cfg.black_sun_color,
            linewidths=1.0,
            alpha=cfg.black_sun_alpha,
        )
    )
    ax.plot(xb, yb, zb, color=cfg.black_sun_color, linewidth=1.2, alpha=min(1.0, cfg.black_sun_alpha + 0.25))

    # Axis direction markers (helps disambiguate + and -)
    a = half * 0.22
    ax.quiver(0, 0, 0, a, 0, 0, color="#FFFFFF", linewidth=1.2)
    ax.quiver(0, 0, 0, 0, a, 0, color="#FFFFFF", linewidth=1.2)
    ax.quiver(0, 0, 0, 0, 0, a, color="#FFFFFF", linewidth=1.2)
    ax.text(a, 0, 0, "+X", color="#FFFFFF")
    ax.text(0, a, 0, "+Z (black sun / east)", color="#FFFFFF")
    ax.text(0, 0, a, "+Y", color="#FFFFFF")

    # Markers
    for m in markers or []:
        x_cs, y_cs, z_cs = m.position_km
        px, py, pz = cyberspace_to_mpl(x_cs * s, y_cs * s, z_cs * s)
        ax.scatter(
            [px],
            [py],
            [pz],
            color=m.color,
            s=m.size,
            marker=m.shape,
            depthshade=False,
            edgecolors=m.edge_color,
            linewidths=m.edge_width,
        )
        if m.label:
            ax.text(px, py, pz, f" {m.label}", color=(m.label_color or m.color))

    # Labels reflect cyberspace axes, even though mpl axes are permuted.
    ax.set_xlabel("X (prime meridian)")
    ax.set_ylabel("Z (black sun)")
    ax.set_zlabel("Y (up / north)")

    ax.set_title("Cyberspace Dataspace (Earth @ origin)")

    ax.view_init(elev=cfg.elev_deg, azim=cfg.azim_deg)

    # Bound extents tightly to dataspace cube (in mpl space)
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)
    ax.set_zlim(-half, half)
    _set_axes_equal(ax)

    # Hide tick labels to keep the 'space' aesthetic
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])


def draw_sector_scene(
    ax,
    *,
    cfg: SceneConfig,
    markers: Optional[List[Marker]] = None,
    sector_label: str = "",
) -> None:
    """Draw a sector-local cube scene into a provided 3D matplotlib axis.

    Marker positions are interpreted as sector-local normalized cyberspace coords in
    [-0.5, +0.5) along each axis. The scene is a cube; no Earth or other global
    geometry is rendered.
    """


    ax.clear()

    s = float(cfg.scale)
    half = 0.5 * s

    # Sector cube wireframe (all 6 faces).
    n = max(3, int(cfg.grid_lines))
    v = np.linspace(-half, half, n)
    A, B = np.meshgrid(v, v)

    def wf_x(x0: float) -> None:
        Y = A
        Z = B
        X = np.full_like(Y, x0)
        ax.plot_wireframe(X, Y, Z, rstride=1, cstride=1, color=cfg.grid_color, linewidth=0.6, alpha=0.8)

    def wf_y(y0: float) -> None:
        X = A
        Z = B
        Y = np.full_like(X, y0)
        ax.plot_wireframe(X, Y, Z, rstride=1, cstride=1, color=cfg.grid_color, linewidth=0.6, alpha=0.8)

    def wf_z(z0: float) -> None:
        X = A
        Y = B
        Z = np.full_like(X, z0)
        ax.plot_wireframe(X, Y, Z, rstride=1, cstride=1, color=cfg.grid_color, linewidth=0.6, alpha=0.8)

    wf_x(-half)
    wf_x(+half)
    wf_y(-half)
    wf_y(+half)
    wf_z(-half)
    wf_z(+half)

    # Axis direction markers
    a = half * 0.55
    ax.quiver(0, 0, 0, a, 0, 0, color="#FFFFFF", linewidth=1.2)
    ax.quiver(0, 0, 0, 0, a, 0, color="#FFFFFF", linewidth=1.2)
    ax.quiver(0, 0, 0, 0, 0, a, color="#FFFFFF", linewidth=1.2)
    ax.text(a, 0, 0, "+X", color="#FFFFFF")
    ax.text(0, a, 0, "+Z", color="#FFFFFF")
    ax.text(0, 0, a, "+Y", color="#FFFFFF")

    # Markers
    for m in markers or []:
        x_cs, y_cs, z_cs = m.position_km
        px, py, pz = cyberspace_to_mpl(x_cs * s, y_cs * s, z_cs * s)
        ax.scatter(
            [px],
            [py],
            [pz],
            color=m.color,
            s=m.size,
            depthshade=False,
            edgecolors=m.edge_color,
            linewidths=m.edge_width,
        )
        if m.label:
            ax.text(px, py, pz, f" {m.label}", color=(m.label_color or m.color))

    ax.set_xlabel("X (sector-local)")
    ax.set_ylabel("Z (sector-local)")
    ax.set_zlabel("Y (sector-local)")

    title = "Cyberspace Sector"
    if sector_label:
        title += f"  S={sector_label}"
    ax.set_title(title)

    ax.view_init(elev=cfg.elev_deg, azim=cfg.azim_deg)
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)
    ax.set_zlim(-half, half)
    _set_axes_equal(ax)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])


__all__ = [
    "Marker",
    "SceneConfig",
    "coord_to_dataspace_km",
    "cyberspace_to_mpl",
    "black_sun_circle_center_mpl",
    "draw_scene",
    "draw_sector_scene",
    "golden_vector_markers",
]
