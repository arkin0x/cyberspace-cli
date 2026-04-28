"""Visualization and utility commands for cyberspace-cli.

Commands: lcaplot, three_d, gps, cantor
These require optional dependencies for GUI/plotting.
"""
from typing import Optional
import typer


def lcaplot_command(
    axis: str = "x",
    center: Optional[int] = None,
    span: int = 256,
    direction: str = "+1",
    max_lca_height: int = 17,
    current_x: Optional[int] = None,
    current_y: Optional[int] = None,
    current_z: Optional[int] = None,
) -> None:
    """Open interactive LCA height plot GUI."""
    try:
        from cyberspace_cli.visualizer.lcaplot_app import run_app
    except Exception as e:
        typer.echo("LCA plot dependencies not installed.", err=True)
        typer.echo("Install: pip install 'cyberspace-cli[visualizer]'", err=True)
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    
    try:
        run_app(
            axis=axis,
            center=center,
            span=span,
            direction=1 if direction in ("+", "+1", "1") else -1,
            max_lca_height=max_lca_height,
            current_x=current_x,
            current_y=current_y,
            current_z=current_z,
        )
    except Exception as e:
        typer.echo(f"Failed to launch lcaplot: {e}", err=True)
        raise typer.Exit(code=1)


def three_d_command(
    coord: Optional[str] = None,
    plane: int = 0,
) -> None:
    """Open 3D visualization of cyberspace."""
    from cyberspace_cli.coords import coord_to_xyz
    from cyberspace_cli.state import load_state
    from cyberspace_cli.parsing import normalize_hex_32
    
    try:
        from cyberspace_cli.visualizer.viz import run_viz_app
    except Exception as e:
        typer.echo("3D visualization dependencies not installed.", err=True)
        typer.echo("Install: pip install 'cyberspace-cli[visualizer]'", err=True)
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    
    if coord:
        try:
            coord_hex = normalize_hex_32(coord)
            coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
        except ValueError as e:
            typer.echo(f"Invalid coord: {e}", err=True)
            raise typer.Exit(code=2)
    else:
        state = load_state()
        if not state:
            typer.echo("No state. Use --coord or run `cyberspace spawn` first.", err=True)
            raise typer.Exit(code=1)
        coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    
    x, y, z, cur_plane = coord_to_xyz(coord_int)
    
    try:
        run_viz_app(center_x=x, center_y=y, center_z=z, plane=plane)
    except Exception as e:
        typer.echo(f"Failed to launch 3D viz: {e}", err=True)
        raise typer.Exit(code=1)


def gps_command(
    coord: Optional[str] = None,
    at: Optional[str] = None,
    lat: Optional[str] = None,
    lon: Optional[str] = None,
    altitude_wgs84_m: Optional[str] = None,
    altitude_sealevel_m: Optional[str] = None,
    geoid_offset_m: Optional[str] = None,
    geoid_model: Optional[str] = None,
    clamp_to_surface: Optional[bool] = None,
) -> None:
    """Convert between GPS and dataspace coord256."""
    from cyberspace_cli.state import load_state
    from cyberspace_cli.parsing import normalize_hex_32
    from cyberspace_cli.coords import coord_to_xyz, dataspace_coord_to_gps, gps_to_dataspace_coord, xyz_to_coord
    from cyberspace_cli.cli import _plane_label
    from cyberspace_core.geoid import geoid_undulation_m
    
    if coord is not None:
        if at is not None or lat is not None or lon is not None:
            typer.echo("Use either --coord OR ('lat,lon' / --lat --lon).", err=True)
            raise typer.Exit(code=2)
        
        try:
            coord_hex = normalize_hex_32(coord)
        except ValueError as e:
            raise typer.BadParameter(str(e))
        
        coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
        x, y, z, plane = coord_to_xyz(coord_int)
        lat_deg, lon_deg, alt_m, _ = dataspace_coord_to_gps(coord_int)
        
        typer.echo(f"coord: 0x{coord_hex}")
        typer.echo(f"xyz(u85): x={x} y={y} z={z} plane={plane} {_plane_label(plane)}")
        typer.echo(f"gps: lat={lat_deg:.10f} lon={lon_deg:.10f} alt_m={alt_m:.3f}")
        return
    
    if at is not None:
        if lat is not None or lon is not None:
            typer.echo("Use either 'lat,lon' OR --lat/--lon.", err=True)
            raise typer.Exit(code=2)
        parts = [p.strip() for p in at.split(",")]
        if len(parts) != 2:
            typer.echo("Expected 'lat,lon' (comma-separated).", err=True)
            raise typer.Exit(code=2)
        lat_s, lon_s = parts[0], parts[1]
    else:
        if lat is None or lon is None:
            typer.echo("Provide 'lat,lon' or both --lat and --lon.", err=True)
            raise typer.Exit(code=2)
        lat_s, lon_s = lat, lon
    
    try:
        lat_deg = float(lat_s)
        lon_deg = float(lon_s)
    except ValueError as e:
        raise typer.BadParameter(f"lat/lon must be numbers: {e}")
    
    # Parse altitude
    alt_m = None
    if altitude_wgs84_m is not None:
        try:
            alt_m = float(altitude_wgs84_m)
        except ValueError as e:
            raise typer.BadParameter(f"--altitude-wgs84 must be a number: {e}")
    elif altitude_sealevel_m is not None:
        try:
            H = float(altitude_sealevel_m)
        except ValueError as e:
            raise typer.BadParameter(f"--altitude-sealevel must be a number: {e}")
        
        if geoid_offset_m is not None:
            try:
                N = float(geoid_offset_m)
            except ValueError as e:
                raise typer.BadParameter(f"--geoid-offset-m must be a number: {e}")
        elif geoid_model is not None:
            N = geoid_undulation_m(lat_deg, lon_deg, model=geoid_model)
        else:
            from cyberspace_cli.config import load_config
            cfg = load_config()
            model_name = cfg.geoid_model or "egm2008-2_5"
            N = geoid_undulation_m(lat_deg, lon_deg, model=model_name)
        
        alt_m = H + N
    
    if clamp_to_surface is None:
        clamp_to_surface = alt_m is None
    
    if alt_m is None:
        alt_m = 0.0
    
    try:
        coord_int = gps_to_dataspace_coord(lat_deg, lon_deg, alt_m, clamp_to_surface=clamp_to_surface)
    except Exception as e:
        typer.echo(f"GPS conversion failed: {e}", err=True)
        raise typer.Exit(code=1)
    
    coord_hex = f"{coord_int:064x}"
    x, y, z, plane = coord_to_xyz(coord_int)
    
    typer.echo(f"coord: 0x{coord_hex}")
    typer.echo(f"xyz(u85): x={x} y={y} z={z} plane={plane} {_plane_label(plane)}")


def cantor_command(
    from_coord: Optional[str] = None,
    to_coord: Optional[str] = None,
    from_xyz: Optional[str] = None,
    to_xyz: Optional[str] = None,
) -> None:
    """Compute and display Cantor pairing information."""
    from cyberspace_cli.parsing import normalize_hex_32
    from cyberspace_cli.coords import coord_to_xyz, xyz_to_coord
    from cyberspace_core.cantor import cantor_pair
    from cyberspace_core.coords import AXIS_BITS
    
    def parse_input(coord_hex: Optional[str], xyz_str: Optional[str]) -> tuple:
        if coord_hex:
            try:
                h = normalize_hex_32(coord_hex)
                v = int.from_bytes(bytes.fromhex(h), "big")
                return coord_to_xyz(v)
            except ValueError as e:
                raise typer.BadParameter(f"Invalid coord: {e}")
        elif xyz_str:
            parts = [int(p.strip()) for p in xyz_str.split(",")]
            if len(parts) != 3:
                raise typer.BadParameter("--from-xyz expects x,y,z")
            return tuple(parts) + (0,)
        else:
            return None
    
    from_result = parse_input(from_coord, from_xyz)
    to_result = parse_input(to_coord, to_xyz)
    
    if not from_result or not to_result:
        typer.echo("Provide both from (--from-coord or --from-xyz) and to (--to-coord or --to-xyz).", err=True)
        raise typer.Exit(code=2)
    
    x1, y1, z1, p1 = from_result
    x2, y2, z2, p2 = to_result
    
    combined_x = cantor_pair(x1, x2)
    combined_y = cantor_pair(y1, y2)
    combined_z = cantor_pair(z1, z2)
    combined = cantor_pair(cantor_pair(combined_x, combined_y), combined_z)
    
    typer.echo(f"combined cantor: {combined}")
    typer.echo(f"coord hex: {combined:064x}")
