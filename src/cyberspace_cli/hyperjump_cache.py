"""Hyperjump cache management for cyberspace-cli.

Handles loading, deduplicating, and caching hyperjump anchor events.
"""
from typing import List, Dict
from pathlib import Path
import json

from cyberspace_cli.nostr_utils import get_event_tag
from cyberspace_cli.parsing import normalize_hex_32


def hyperjump_cache_path() -> Path:
    """Get path to hyperjump cache file."""
    from cyberspace_cli.config import get_app_dir
    return get_app_dir() / "hyperjump_cache.jsonl"


def load_hyperjump_cache() -> List[dict]:
    """Load cached hyperjump events from JSONL file.
    
    Returns:
        List of hyperjump event dicts, empty if cache doesn't exist
    """
    cache = hyperjump_cache_path()
    if not cache.exists():
        return []
    
    events: List[dict] = []
    for line in cache.read_text().splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def save_hyperjump_cache(events: List[dict]) -> None:
    """Save hyperjump events to cache file.
    
    Args:
        events: List of hyperjump event dicts to cache
    """
    cache = hyperjump_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    
    lines = []
    for ev in events:
        lines.append(json.dumps(ev, separators=(",", ":")))
    
    cache.write_text("\n".join(lines) + "\n" if lines else "")


def dedup_hyperjumps(events: List[dict]) -> Dict[str, dict]:
    """Deduplicate hyperjump events by coordinate.
    
    Keeps the most recent event for each coordinate based on created_at.
    
    Args:
        events: List of hyperjump events
        
    Returns:
        Dict mapping normalized coord_hex to most recent event
    """
    by_coord: Dict[str, dict] = {}
    for ev in events:
        c = get_event_tag(ev, "C")
        if not c:
            continue
        try:
            c_norm = normalize_hex_32(c)
        except ValueError:
            continue
        prior = by_coord.get(c_norm)
        if prior is None or int(ev.get("created_at", 0)) > int(prior.get("created_at", 0)):
            by_coord[c_norm] = ev
    return by_coord
