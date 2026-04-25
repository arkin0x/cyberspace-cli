"""Hyperjump commands for cyberspace-cli.

Commands: sync, nearest
"""
from typing import Optional, Dict, List
import typer

from cyberspace_cli.hyperjump_flow import (
    hyperjump_cache_path,
    load_hyperjump_cache,
    dedup_hyperjumps,
    rank_hyperjumps,
    print_ranked_hyperjumps,
    query_hyperjump_anchors,
    DEFAULT_HYPERJUMP_RELAY,
    HYPERJUMP_KIND,
    SECTOR_BITS,
)
from cyberspace_cli.coords import coord_to_xyz
from cyberspace_cli.nostr_utils import nak_req_events


def hyperjump_sync_command(
    relay: str = DEFAULT_HYPERJUMP_RELAY,
    limit: int = 10000,
    verbose: bool = False,
    resume: bool = False,
) -> None:
    """Sync hyperjump anchors from relay to local cache."""
    from pathlib import Path
    import json
    
    cache = hyperjump_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    
    existing_ids = set()
    existing_events = []
    
    if resume and cache.exists():
        typer.echo("Resuming from existing cache ...")
        with open(cache) as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    ev = json.loads(s)
                    existing_events.append(ev)
                    existing_ids.add(ev.get("id", ""))
                except json.JSONDecodeError:
                    continue
        typer.echo(f"  Loaded {len(existing_events)} cached event(s).")
    
    typer.echo(f"Fetching hyperjump anchors from {relay} ...")
    all_events = list(existing_events)
    seen_ids = set(existing_ids)
    total_fetched = 0
    batch_num = 0
    cursor_until = None
    
    if resume and existing_events:
        oldest_ts = min((ev.get("created_at", 0) for ev in existing_events if ev.get("created_at")), default=0)
        if oldest_ts > 0:
            cursor_until = oldest_ts - 1
            typer.echo(f"  Resuming: fetching events older than timestamp {cursor_until}")
    
    while True:
        batch_num += 1
        batch = nak_req_events(
            relay=relay,
            kind=HYPERJUMP_KIND,
            tags={},
            limit=limit,
            timeout_seconds=300,
            verbose=verbose,
            until=cursor_until,
        )
        if not batch:
            if verbose:
                typer.echo(f"  Batch {batch_num}: empty — pagination complete.")
            break
        
        new_in_batch = 0
        oldest_ts = None
        for ev in batch:
            eid = ev.get("id", "")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                all_events.append(ev)
                new_in_batch += 1
            ts = ev.get("created_at", 0)
            if oldest_ts is None or ts < oldest_ts:
                oldest_ts = ts
        
        total_fetched += len(batch)
        typer.echo(f"  Batch {batch_num}: {len(batch)} event(s), {new_in_batch} new — {len(all_events)} total unique so far")
        
        if len(batch) < limit:
            break
        if new_in_batch == 0:
            break
        if oldest_ts is not None:
            cursor_until = oldest_ts - 1
        else:
            break
    
    if not all_events:
        typer.echo("No hyperjump events found on the relay.")
        return
    
    by_coord = dedup_hyperjumps(all_events)
    
    with open(cache, "w") as f:
        for ev in by_coord.values():
            f.write(json.dumps(ev, separators=(",", ":"), ensure_ascii=False) + "\n")
    
    block_heights = []
    for ev in all_events:
        for tag in ev.get("tags", []):
            if tag[0] == "B":
                try:
                    block_heights.append(int(tag[1]))
                except (ValueError, IndexError):
                    pass
    
    if block_heights:
        typer.echo(f"Block range: {min(block_heights)} to {max(block_heights)}")
    
    typer.echo(f"Cached {len(by_coord)} unique hyperjump(s) to {cache}")
    typer.echo(f"(from {total_fetched} fetched + {len(existing_events)} previously cached)")
    typer.echo(f"Estimated remaining: ~{max(0, 940000 - len(by_coord)):,} events")


def hyperjump_nearest_command(
    relay: str = DEFAULT_HYPERJUMP_RELAY,
    radius: int = 10,
    limit: int = 2000,
    verbose: bool = False,
    coord: Optional[str] = None,
    cache: bool = False,
    count: int = 0,
    expand: bool = False,
) -> None:
    """Find nearest hyperjump anchors."""
    from cyberspace_cli.state import load_state
    from cyberspace_cli.chains import EventChains
    from cyberspace_cli.coords import normalize_hex_32
    
    MAX_TAG_VALUES = 2000
    _EXPAND_RADII = [2, 5, 10, 25, 50, 100, 200, 333]
    
    chains = EventChains()
    state = load_state()
    label = chains.active_chain_label(state)
    cur_coord_hex = state.coord_hex
    cur_coord_int = int.from_bytes(bytes.fromhex(cur_coord_hex), "big")
    cx, cy, cz, cplane = coord_to_xyz(cur_coord_int)
    sx, sy, sz = cx >> SECTOR_BITS, cy >> SECTOR_BITS, cz >> SECTOR_BITS
    
    if coord:
        c_norm = normalize_hex_32(coord)
        c_coord_int = int.from_bytes(bytes.fromhex(c_norm), "big")
        sx, sy, sz, _ = coord_to_xyz(c_coord_int)
        if verbose:
            typer.echo(f"Using override sector: X={sx} Y={sy} Z={sz}")
    
    if cache:
        cached_events = load_hyperjump_cache()
        if not cached_events:
            typer.echo("Cache is empty. Run `hyperjump sync` first.")
            return
        by_coord = dedup_hyperjumps(cached_events)
        ranked = rank_hyperjumps(by_coord, sx, sy, sz, cx, cy, cz)
        if not ranked:
            typer.echo("No hyperjumps found in cache.")
            return
        if count > 0:
            ranked = ranked[:count]
        print_ranked_hyperjumps(ranked, cur_coord_hex, cx, cy, cz, cplane)
        return
    
    if expand:
        radii = [r for r in _EXPAND_RADII if r <= (MAX_TAG_VALUES // 3 - 1) // 2]
        by_coord = {}
        final_radius = 0
        for r in radii:
            if verbose:
                typer.echo(f"Searching radius={r} ...")
            events = nak_req_events(
                relay=relay,
                kind=HYPERJUMP_KIND,
                tags={
                    "X": _axis_value_range(sx, r),
                    "Y": _axis_value_range(sy, r),
                    "Z": _axis_value_range(sz, r),
                },
                limit=limit,
                verbose=verbose,
            )
            by_coord = dedup_hyperjumps(events)
            final_radius = r
            if by_coord:
                break
        if not by_coord:
            typer.echo(f"No hyperjumps found after expanding to radius={final_radius}.")
            return
        ranked = rank_hyperjumps(by_coord, sx, sy, sz, cx, cy, cz)
        if count > 0:
            ranked = ranked[:count]
        print_ranked_hyperjumps(ranked, cur_coord_hex, cx, cy, cz, cplane, search_radius=final_radius)
        return
    
    max_per_axis = MAX_TAG_VALUES // 3
    effective_radius = min(radius, (max_per_axis - 1) // 2)
    if effective_radius != radius and verbose:
        typer.echo(f"Clamped radius from {radius} to {effective_radius} (relay tag limit).")
    
    events = nak_req_events(
        relay=relay,
        kind=HYPERJUMP_KIND,
        tags={
            "X": _axis_value_range(sx, effective_radius),
            "Y": _axis_value_range(sy, effective_radius),
            "Z": _axis_value_range(sz, effective_radius),
        },
        limit=limit,
        verbose=verbose,
    )
    
    by_coord = dedup_hyperjumps(events)
    
    if not by_coord:
        typer.echo("No nearby hyperjumps found.")
        if not expand:
            typer.echo("Hint: try --expand to progressively widen the search, or --cache with `hyperjump sync`.")
        return
    
    ranked = rank_hyperjumps(by_coord, sx, sy, sz, cx, cy, cz)
    if count > 0:
        ranked = ranked[:count]
    print_ranked_hyperjumps(ranked, cur_coord_hex, cx, cy, cz, cplane, search_radius=effective_radius)


def _axis_value_range(center: int, radius: int) -> List[str]:
    """Generate range of sector values."""
    lo = max(0, center - radius)
    hi = center + radius
    return [str(v) for v in range(lo, hi + 1)]
