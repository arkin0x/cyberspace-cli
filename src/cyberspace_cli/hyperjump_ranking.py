"""Hyperjump ranking and display for cyberspace-cli.

Ranks hyperjumps by distance and formats output for display.
"""
from typing import List, Dict, Tuple, Optional

from cyberspace_cli.parsing import coord_to_xyz
from cyberspace_cli.nostr_utils import get_event_tag

# Constants
SECTOR_BITS = 30


def rank_hyperjumps(
    by_coord: Dict[str, dict],
    spawn_x: int, spawn_y: int, spawn_z: int,
    current_x: int, current_y: int, current_z: int,
) -> List[Tuple[int, int, str, dict, Tuple[int, int, int, int]]]:
    """Rank hyperjumps by sector then axis distance.
    
    Args:
        by_coord: Deduped hyperjump events by normalized coord_hex
        spawn_x/y/z: Spawn coordinates (for sector distance)
        current_x/y/z: Current coordinates (for axis distance)
        
    Returns:
        List of (sector_dist, axis_dist, coord_hex, event, (x,y,z,plane))
        sorted by sector distance, then axis distance
    """
    ranked: List[Tuple[int, int, str, dict, Tuple[int, int, int, int]]] = []
    
    for coord_hex, ev in by_coord.items():
        coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
        x, y, z, plane = coord_to_xyz(coord_int)
        
        # Sector coordinates
        hsx = x >> SECTOR_BITS
        hsy = y >> SECTOR_BITS
        hsz = z >> SECTOR_BITS
        
        # Manhattan distances
        sector_dist = abs(hsx - spawn_x) + abs(hsy - spawn_y) + abs(hsz - spawn_z)
        axis_dist = abs(x - current_x) + abs(y - current_y) + abs(z - current_z)
        
        ranked.append((sector_dist, axis_dist, coord_hex, ev, (x, y, z, plane)))
    
    # Sort by sector distance, then axis distance, then coord
    ranked.sort(key=lambda it: (it[0], it[1], it[2]))
    return ranked


def print_ranked_hyperjumps(
    ranked: List[Tuple[int, int, str, dict, Tuple[int, int, int, int]]],
    current_coord_hex: str,
    current_x: int, current_y: int, current_z: int, current_plane: int,
    search_radius: Optional[int] = None,
) -> None:
    """Print ranked hyperjump results.
    
    Args:
        ranked: Ranked hyperjump list from rank_hyperjumps()
        current_coord_hex: Current coordinate (hex)
        current_x/y/z/plane: Current position
        search_radius: Optional search radius that was used
    """
    import typer
    from cyberspace_cli.cli import _plane_label, _direction_hint
    
    typer.echo(f"current: 0x{current_coord_hex}")
    typer.echo(f"x={current_x}")
    typer.echo(f"y={current_y}")
    typer.echo(f"z={current_z}")
    typer.echo(f"plane={current_plane} {_plane_label(current_plane)}")
    
    if search_radius is not None:
        typer.echo(f"search_radius={search_radius}")
    
    typer.echo(f"nearby_hyperjumps: {len(ranked)}")
    
    for i, (sector_dist, _axis_dist, coord_hex, ev, (x, y, z, plane)) in enumerate(ranked, start=1):
        hsx = x >> SECTOR_BITS
        hsy = y >> SECTOR_BITS
        hsz = z >> SECTOR_BITS
        b_tag = get_event_tag(ev, "B") or "?"
        event_id = str(ev.get("id", ""))
        dir_hint = " ".join([
            _direction_hint(current_x, x, "x"),
            _direction_hint(current_y, y, "y"),
            _direction_hint(current_z, z, "z"),
        ])
        
        typer.echo(f"{i}. id={event_id}")
        typer.echo(f"coord=0x{coord_hex}")
        typer.echo(f"B={b_tag}")
        typer.echo(f"x={x}")
        typer.echo(f"y={y}")
        typer.echo(f"z={z}")
        typer.echo(f"plane={plane} {_plane_label(plane)}")
        typer.echo(f"sector_x={hsx}")
        typer.echo(f"sector_y={hsy}")
        typer.echo(f"sector_z={hsz}")
        typer.echo(f"sector_distance={sector_dist}")
        typer.echo(f"direction={dir_hint}")
        typer.echo(f"suggested_move=cyberspace move --to {x},{y},{z},{plane}")
