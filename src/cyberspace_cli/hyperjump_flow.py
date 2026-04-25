"""Hyperjump flow orchestration for cyberspace-cli.

Coordinates hyperjump anchor queries and height resolution.
Re-exports cache and ranking functions for backward compatibility.
"""
from typing import Optional, List, Tuple

from cyberspace_cli.nostr_utils import nak_req_events, get_event_tag
from cyberspace_core.coords import xyz_to_coord
from cyberspace_cli.hyperjump_cache import (
    hyperjump_cache_path,
    load_hyperjump_cache,
    save_hyperjump_cache,
    dedup_hyperjumps,
)
from cyberspace_cli.hyperjump_ranking import (
    rank_hyperjumps,
    print_ranked_hyperjumps,
    SECTOR_BITS,
)

# Constants
DEFAULT_HYPERJUMP_RELAY = "wss://hyperjump.arKin0x.com"
HYPERJUMP_KIND = 321


def query_hyperjump_anchors(
    relay: str,
    target_coord_hex: Optional[str] = None,
    limit: int = 25,
) -> List[dict]:
    """Query hyperjump anchor events from relay.
    
    Args:
        relay: Nostr relay URL
        target_coord_hex: Optional specific coordinate to query
        limit: Max events to fetch
        
    Returns:
        List of anchor events
    """
    tags = {}
    if target_coord_hex:
        tags["C"] = [target_coord_hex]
    
    return nak_req_events(
        relay=relay,
        kind=HYPERJUMP_KIND,
        tags=tags,
        limit=limit,
    )


def resolve_hyperjump_height(
    x: int, y: int, z: int, plane: int,
    relay: str = DEFAULT_HYPERJUMP_RELAY,
    query_limit: int = 25,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve hyperjump height (B tag) for a destination.
    
    Queries relay for anchor event at the given coordinate and extracts B tag.
    
    Args:
        x, y, z, plane: Destination coordinates
        relay: Relay to query
        query_limit: Query limit
        
    Returns:
        (height_or_None, error_or_None)
    """
    dest_coord_int = xyz_to_coord(x, y, z, plane)
    dest_coord_hex = f"{dest_coord_int:064x}"
    anchors = query_hyperjump_anchors(relay, dest_coord_hex, query_limit)
    
    if not anchors:
        return None, f"No hyperjump anchor found for 0x{dest_coord_hex}"
    
    anchor = anchors[0]
    b_tag = get_event_tag(anchor, "B")
    
    if not b_tag:
        return None, "Anchor event missing B tag"
    
    return b_tag, None


# Re-export for backward compatibility
__all__ = [
    # Functions
    'hyperjump_cache_path',
    'load_hyperjump_cache',
    'save_hyperjump_cache',
    'dedup_hyperjumps',
    'rank_hyperjumps',
    'print_ranked_hyperjumps',
    'query_hyperjump_anchors',
    'resolve_hyperjump_height',
    # Constants
    'DEFAULT_HYPERJUMP_RELAY',
    'HYPERJUMP_KIND',
    'SECTOR_BITS',
]
