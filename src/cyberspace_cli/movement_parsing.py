"""Movement destination parsing for cyberspace-cli.

Handles parsing of --to, --by, and --toward arguments into structured destinations.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from cyberspace_core.coords import coord_to_xyz, AXIS_MAX


@dataclass
class MovementDestination:
    """Parsed movement destination."""
    x: int
    y: int
    z: int
    plane: int
    is_relative: bool = False


def parse_movement_destination(
    to: Optional[str],
    by: Optional[str],
    toward: Optional[str],
    current_plane: int,
) -> Tuple[Optional[MovementDestination], Optional[str]]:
    """Parse destination from CLI arguments.
    
    Priority: --by > --to > --toward
    
    Args:
        to: Absolute destination (--to)
        by: Relative movement (--by)
        toward: Continuous target (--toward)
        current_plane: Current plane (for relative)
        
    Returns:
        (MovementDestination, error_message) - one will be None
    """
    if by is not None:
        return _parse_relative_destination(by, current_plane)
    
    if to is not None:
        return _parse_absolute_destination(to, current_plane)
    
    if toward is not None:
        return None, None  # Parsed later in toward flow
    
    return None, None


def _parse_absolute_destination(
    to: str,
    current_plane: int,
) -> Tuple[Optional[MovementDestination], Optional[str]]:
    """Parse --to destination."""
    try:
        if to.startswith("0x") or all(c in "0123456789abcdef" for c in to.lower()):
            coord_hex = to if to.startswith("0x") else f"0x{to}"
            coord_int = int(coord_hex, 16)
            x, y, z, plane = coord_to_xyz(coord_int)
            return MovementDestination(x=x, y=y, z=z, plane=plane), None
        
        parts = to.split(",")
        if len(parts) < 3:
            return None, f"Invalid destination: '{to}'. Expected x,y,z or x,y,z,plane"
        
        x = int(parts[0])
        y = int(parts[1])
        z = int(parts[2])
        plane = int(parts[3]) if len(parts) >= 4 else current_plane
        
        return MovementDestination(x=x, y=y, z=z, plane=plane), None
    except ValueError as e:
        return None, f"Failed to parse '{to}': {e}"


def _parse_relative_destination(
    by: str,
    current_plane: int,
) -> Tuple[Optional[MovementDestination], Optional[str]]:
    """Parse --by destination."""
    try:
        parts = by.split(",")
        if len(parts) < 3:
            return None, f"Invalid format: '{by}'. Expected dx,dy,dz or dx,dy,dz,plane"
        
        dx = int(parts[0])
        dy = int(parts[1])
        dz = int(parts[2])
        
        if dx == 0 and dy == 0 and dz == 0 and len(parts) >= 4:
            plane = int(parts[3])
            return MovementDestination(x=0, y=0, z=0, plane=plane, is_relative=True), None
        
        return MovementDestination(x=dx, y=dy, z=dz, plane=current_plane, is_relative=True), None
    except ValueError as e:
        return None, f"Failed to parse '{by}': {e}"


def parse_toward_destination(
    toward: str,
    current_plane: int,
) -> Tuple[Optional[MovementDestination], Optional[str]]:
    """Parse --toward destination."""
    try:
        if toward.startswith("0x") or all(c in "0123456789abcdef" for c in toward.lower()):
            coord_hex = toward if toward.startswith("0x") else f"0x{toward}"
            coord_int = int(coord_hex, 16)
            x, y, z, plane = coord_to_xyz(coord_int)
            return MovementDestination(x=x, y=y, z=z, plane=plane), None
        
        parts = toward.split(",")
        if len(parts) < 3:
            return None, f"Invalid destination: '{toward}'"
        
        x = int(parts[0])
        y = int(parts[1])
        z = int(parts[2])
        plane = int(parts[3]) if len(parts) >= 4 else current_plane
        
        return MovementDestination(x=x, y=y, z=z, plane=plane), None
    except ValueError as e:
        return None, f"Failed to parse '{toward}': {e}"
