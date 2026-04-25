"""Movement validation and configuration for cyberspace-cli.

Validates parsed destinations and builds movement configuration.
"""
from dataclasses import dataclass
from typing import Optional

from cyberspace_core.coords import AXIS_MAX

from cyberspace_cli.movement_parsing import MovementDestination


@dataclass
class MoveConfig:
    """Movement configuration."""
    max_lca_height: int
    max_hops: int
    use_hyperjump: bool
    use_sidestep: bool
    exit_hyperjump: bool
    hyperjump_relay: str
    hyperjump_query_limit: int


def validate_destination(dest: MovementDestination) -> Optional[str]:
    """Validate destination coordinates.
    
    Args:
        dest: MovementDestination to validate
        
    Returns:
        Error message if invalid, None if valid
    """
    if dest.plane not in (0, 1):
        return f"Plane must be 0 or 1, got {dest.plane}"
    
    if dest.is_relative:
        if dest.x == 0 and dest.y == 0 and dest.z == 0:
            return None  # Valid plane switch
        return None  # No range check on deltas
    
    if not (0 <= dest.x <= AXIS_MAX):
        return f"X coordinate {dest.x} out of range [0, {AXIS_MAX}]"
    if not (0 <= dest.y <= AXIS_MAX):
        return f"Y coordinate {dest.y} out of range [0, {AXIS_MAX}]"
    if not (0 <= dest.z <= AXIS_MAX):
        return f"Z coordinate {dest.z} out of range [0, {AXIS_MAX}]"
    
    return None


def validate_plane_switch(current_plane: int, dest_plane: int) -> Optional[str]:
    """Validate plane switch.
    
    Args:
        current_plane: Current plane (0 or 1)
        dest_plane: Destination plane (0 or 1)
        
    Returns:
        Error message if invalid, None if valid
    """
    if dest_plane not in (0, 1):
        return f"Invalid plane {dest_plane}"
    return None


def build_move_config(
    max_lca_height: Optional[int],
    default_max_lca_height: int,
    max_hops: int = 0,
    use_hyperjump: bool = False,
    use_sidestep: bool = False,
    exit_hyperjump: bool = False,
    hyperjump_relay: str = "wss://hyperjump.arKin0x.com",
    hyperjump_query_limit: int = 25,
) -> MoveConfig:
    """Build movement configuration.
    
    Args:
        max_lca_height: Override max LCA height
        default_max_lca_height: Default from config
        max_hops: Max hops for --toward
        use_hyperjump: Use hyperjump flow
        use_sidestep: Use sidestep proof
        exit_hyperjump: Exit hyperjump after move
        hyperjump_relay: Relay for validation
        hyperjump_query_limit: Anchor query limit
        
    Returns:
        MoveConfig with all options
    """
    return MoveConfig(
        max_lca_height=max_lca_height if max_lca_height is not None else default_max_lca_height,
        max_hops=max_hops,
        use_hyperjump=use_hyperjump,
        use_sidestep=use_sidestep,
        exit_hyperjump=exit_hyperjump,
        hyperjump_relay=hyperjump_relay,
        hyperjump_query_limit=hyperjump_query_limit,
    )
