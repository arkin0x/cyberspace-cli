"""Utility helpers for cyberspace-cli."""
from typing import Dict, List, Optional, Tuple
from decimal import Decimal, InvalidOperation
import typer


def plane_label(plane: int) -> str:
    """Get plane name."""
    return "dataspace" if plane == 0 else "ideaspace" if plane == 1 else "unknown"


def require_state():
    """Load and return state."""
    from cyberspace_cli.state import load_state
    state = load_state()
    if state is None:
        typer.echo("No state found. Run `cyberspace spawn` first.", err=True)
        raise typer.Exit(code=1)
    return state


def require_active_chain_label(state) -> str:
    """Get active chain label from state."""
    from cyberspace_cli.chains import EventChains
    chains = EventChains()
    label = chains.active_chain_label(state)
    if not label:
        typer.echo("No active chain. Use `cyberspace chain use <label>`.", err=True)
        raise typer.Exit(code=1)
    return label


def coord_hex_from_xyz(x: int, y: int, z: int, plane: int) -> str:
    """Convert coordinates to hex string."""
    from cyberspace_cli.coords import xyz_to_coord
    coord_int = xyz_to_coord(x, y, z, plane)
    return f"{coord_int:064x}"


def parse_csv_ints(s: str) -> List[int]:
    """Parse comma-separated integers."""
    return [int(p.strip()) for p in s.split(",")]


def get_tag(event: dict, key: str) -> Optional[str]:
    """Get tag value from event."""
    tags = event.get("tags", [])
    for tag in tags:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] == key:
            return tag[1]
    return None


def get_tag_record(event: dict, key: str) -> Optional[List[str]]:
    """Get full tag record from event."""
    tags = event.get("tags", [])
    for tag in tags:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] == key:
            return tag
    return None


def axis_value_range(center: int, radius: int) -> List[str]:
    """Generate range of sector values."""
    lo = max(0, center - radius)
    hi = center + radius
    return [str(v) for v in range(lo, hi + 1)]


def direction_hint(current: int, target: int, axis: str) -> str:
    """Get direction hint string."""
    if target > current:
        return f"{axis}+ ({target - current})"
    if target < current:
        return f"{axis}- ({current - target})"
    return f"{axis}= (0)"


def hyperjump_block_height_from_event(event: dict) -> Optional[int]:
    """Extract block height from hyperjump event."""
    if get_tag(event, "A") != "hyperjump":
        return None
    b_tag = get_tag(event, "B")
    if b_tag:
        try:
            return int(b_tag)
        except ValueError:
            pass
    return None


def query_hyperjump_anchor_for_height(
    block_height: int,
    relay: str,
    limit: int = 2000,
    verbose: bool = False,
) -> Optional[Tuple[str, dict, Tuple[int, int, int, int]]]:
    """Query relay for hyperjump at specific block height."""
    from cyberspace_cli.nostr_utils import nak_req_events
    from cyberspace_core.coords import coord_to_xyz
    
    events = nak_req_events(
        relay=relay,
        kind=321,
        tags={"B": [str(block_height)]},
        limit=limit,
        verbose=verbose,
    )
    
    if not events:
        return None
    
    ev = events[0]
    coord_hex = get_tag(ev, "C")
    if not coord_hex:
        return None
    
    try:
        coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
        xyzp = coord_to_xyz(coord_int)
    except:
        return None
    
    return coord_hex, ev, xyzp


def print_hyperjump_anchor(
    block_height: int,
    coord_hex: str,
    event: dict,
    xyzp: Tuple[int, int, int, int],
) -> None:
    """Print hyperjump anchor details."""
    x, y, z, plane = xyzp
    typer.echo(f"block_height: {block_height}")
    typer.echo(f"coord: 0x{coord_hex}")
    typer.echo(f"x={x}")
    typer.echo(f"y={y}")
    typer.echo(f"z={z}")
    typer.echo(f"plane={plane} {plane_label(plane)}")
