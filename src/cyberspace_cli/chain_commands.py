"""Chain management commands for cyberspace-cli."""
from typing import List
import typer


def chain_list_command() -> List[tuple]:
    """List all chains with their lengths."""
    from cyberspace_cli.state import load_state
    from cyberspace_cli.chains import EventChains
    
    chains = EventChains()
    state = load_state()
    active = (state.active_chain_label if state else "") or ""
    labels = chains.list_chain_labels()
    
    result = []
    for label in labels:
        mark = "*" if label == active else " "
        n = chains.chain_length(label)
        result.append((mark, label, n))
    return result


def chain_use_command(label: str) -> str:
    """Set active chain."""
    from cyberspace_cli.state import load_state, save_state
    from cyberspace_cli.chains import EventChains
    
    chains = EventChains()
    state = load_state()
    label = chains.normalize_label(label)
    
    if chains.chain_length(label) == 0:
        raise ValueError(f"Unknown chain: {label}")
    
    state.active_chain_label = label
    save_state(state)
    return label


def chain_status_command() -> dict:
    """Get chain status info."""
    from cyberspace_cli.state import load_state, _require_state
    from cyberspace_cli.chains import EventChains
    from cyberspace_cli.coords import coord_to_xyz
    from cyberspace_cli.cli import _plane_label, _get_tag
    
    chains = EventChains()
    state = _require_state()
    label = chains.active_chain_label(state)
    
    events = chains.read_events(label)
    if not events:
        return {"empty": True, "label": label}
    
    spawn_coord_hex = _get_tag(events[0], "C") or ""
    last_coord_hex = _get_tag(events[-1], "C") or ""
    
    if not spawn_coord_hex or not last_coord_hex:
        raise ValueError("Chain missing C tags")
    
    spawn = int.from_bytes(bytes.fromhex(spawn_coord_hex), "big")
    cur = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    last = int.from_bytes(bytes.fromhex(last_coord_hex), "big")
    
    sx, sy, sz, _ = coord_to_xyz(spawn)
    cx, cy, cz, cplane = coord_to_xyz(cur)
    
    return {
        "label": label,
        "length": len(events),
        "hops": max(0, len(events) - 1),
        "genesis_id": events[0].get("id", ""),
        "last_id": events[-1].get("id", ""),
        "spawn_hex": spawn_coord_hex,
        "current_hex": state.coord_hex,
        "coords_match": cur == last,
        "dx": cx - sx,
        "dy": cy - sy,
        "dz": cz - sz,
        "plane": cplane,
    }


def history_command(
    label: str,
    limit: int = 50,
    json_out: bool = False,
) -> list:
    """Get chain history."""
    from cyberspace_cli.chains import EventChains
    
    chains = EventChains()
    events = chains.read_events(label)
    
    if not events:
        return []
    
    if limit > 0:
        events = events[-limit:]
    
    if json_out:
        return events
    else:
        # Return formatted strings
        result = []
        for i, ev in enumerate(events, start=1):
            result.append(f"{i}. {ev.get('kind', '?')} {ev.get('id', '')[:16]}...")
        return result
