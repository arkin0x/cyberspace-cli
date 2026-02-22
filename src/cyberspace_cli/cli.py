from __future__ import annotations

import time
from typing import List, Optional, Sequence, Tuple

import typer

from cyberspace_cli import chains
from cyberspace_cli.helptext import HELP_TEXT
from cyberspace_cli.nostr_event import make_hop_event, make_spawn_event
from cyberspace_cli.parsing import normalize_hex_32
from cyberspace_cli.nostr_keys import (
    encode_nsec,
    encode_npub,
    generate_privkey_bytes,
    privkey_bytes_from_nsec_or_hex,
    pubkey_hex_from_privkey,
)
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, load_state, save_state
from cyberspace_core.cantor import int_to_bytes_be_min, int_to_hex_be_min, sha256, sha256_int_hex
from cyberspace_core.coords import AXIS_MAX, coord_to_xyz, gps_to_dataspace_coord, xyz_to_coord
from cyberspace_core.movement import compute_axis_cantor, compute_movement_proof_xyz, find_lca_height
from cyberspace_core.movement_debug import axis_cantor_debug

app = typer.Typer(no_args_is_help=True)
chain_app = typer.Typer(no_args_is_help=True)
app.add_typer(chain_app, name="chain")


def _require_state() -> CyberspaceState:
    state = load_state()
    if not state:
        typer.echo("No local state found. Run `cyberspace spawn` first.", err=True)
        raise typer.Exit(code=1)
    return state


def _require_active_chain_label(state: CyberspaceState) -> str:
    label = (state.active_chain_label or "").strip()
    if not label:
        typer.echo("No active chain selected. Create one with `cyberspace spawn`.", err=True)
        raise typer.Exit(code=1)
    return label


def _coord_hex_from_pubkey_hex(pubkey_hex: str) -> str:
    b = bytes.fromhex(pubkey_hex)
    if len(b) != 32:
        raise ValueError("pubkey must be 32 bytes")
    return b.hex()


def _parse_csv_ints(s: str) -> List[int]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [int(p, 0) for p in parts]


def _parse_coord_hex(s: str) -> str:
    try:
        return normalize_hex_32(s)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


def _coord_hex_from_xyz(x: int, y: int, z: int, plane: int) -> str:
    coord_int = xyz_to_coord(x, y, z, plane=plane)
    return coord_int.to_bytes(32, "big").hex()


def _get_tag(event: dict, key: str) -> Optional[str]:
    for t in event.get("tags", []):
        if isinstance(t, list) and len(t) >= 2 and t[0] == key:
            return t[1]
    return None


@app.command()
def help() -> None:
    """Show the extended help / usage guide."""
    typer.echo(HELP_TEXT.strip())


@app.command()
def spawn(
    from_key: str = typer.Option(
        None,
        "--from-key",
        help="Existing key as NIP-19 nsec... or 32-byte hex.",
    ),
    chain: str = typer.Option(
        None,
        "--chain",
        help="Chain label to create (default: chain-<unix_ts>).",
    ),
) -> None:
    """Generate/import a keypair and create a new local chain with a spawn event."""
    if from_key:
        priv = privkey_bytes_from_nsec_or_hex(from_key)
    else:
        priv = generate_privkey_bytes()

    pub_hex = pubkey_hex_from_privkey(priv)
    coord_hex = _coord_hex_from_pubkey_hex(pub_hex)

    created_at = int(time.time())
    label = chain or f"chain-{created_at}"

    spawn_event = make_spawn_event(pubkey_hex=pub_hex, created_at=created_at, coord_hex=coord_hex)
    chains.create_new_chain(label, spawn_event, overwrite=False)

    state = CyberspaceState(
        version=STATE_VERSION,
        privkey_hex=priv.hex(),
        pubkey_hex=pub_hex,
        coord_hex=coord_hex,
        active_chain_label=chains.normalize_label(label),
    )
    save_state(state)

    typer.echo("Spawned.")
    typer.echo(f"chain: {state.active_chain_label} (len=1)")
    typer.echo(f"npub: {encode_npub(bytes.fromhex(pub_hex))}")
    typer.echo(f"nsec: {encode_nsec(priv)}")
    typer.echo(f"coord: 0x{coord_hex}")


@app.command()
def whereami() -> None:
    """Show current coordinate (and decoded x/y/z/plane)."""
    state = _require_state()
    coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x, y, z, plane = coord_to_xyz(coord_int)

    typer.echo(f"coord: 0x{state.coord_hex}")
    typer.echo(f"pubkey: {state.pubkey_hex}")
    typer.echo(f"active_chain: {state.active_chain_label or '(none)'}")
    typer.echo(f"xyz(u85): x={x} y={y} z={z} plane={plane}")


@app.command()
def sector() -> None:
    """Show current sector id per axis (2^30 gibsons per sector)."""
    state = _require_state()

    coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x, y, z, plane = coord_to_xyz(coord_int)

    sector_bits = 30
    sx = x >> sector_bits
    sy = y >> sector_bits
    sz = z >> sector_bits

    typer.echo(f"sector: X={sx} Y={sy} Z={sz} plane={plane}")
    typer.echo(f"S tag: {sx}-{sy}-{sz}")


@app.command()
def gps(
    at: Optional[str] = typer.Argument(
        None,
        help="Either 'lat,lon' (recommended, works with negative lon) or omit and use --lat/--lon.",
    ),
    lat: Optional[str] = typer.Option(None, "--lat", help="Latitude (alternative to 'lat,lon')."),
    lon: Optional[str] = typer.Option(None, "--lon", help="Longitude (alternative to 'lat,lon')."),
    altitude_m: str = typer.Option("0", "--alt", help="Altitude in meters (default 0)."),
    clamp_to_surface: bool = typer.Option(True, "--clamp/--no-clamp", help="Clamp altitude to WGS84 surface."),
) -> None:
    """Convert GPS to a dataspace coordinate.

    Note: many CLIs treat a negative positional like `-122.4194` as an option flag.
    To avoid that, this command supports either:
    - `cyberspace gps 37.7749,-122.4194`
    - `cyberspace gps --lat 37.7749 --lon -122.4194`
    """

    if at is not None:
        if lat is not None or lon is not None:
            typer.echo("Use either 'lat,lon' OR --lat/--lon (not both).", err=True)
            raise typer.Exit(code=2)
        parts = [p.strip() for p in at.split(",")]
        if len(parts) != 2:
            typer.echo("Expected 'lat,lon' (comma-separated).", err=True)
            raise typer.Exit(code=2)
        lat_s, lon_s = parts[0], parts[1]
    else:
        if lat is None or lon is None:
            typer.echo("Provide either 'lat,lon' or both --lat and --lon.", err=True)
            raise typer.Exit(code=2)
        lat_s, lon_s = lat, lon

    coord_int = gps_to_dataspace_coord(lat_s, lon_s, altitude_m, clamp_to_surface=clamp_to_surface)
    coord_hex = coord_int.to_bytes(32, "big").hex()
    x, y, z, plane = coord_to_xyz(coord_int)

    typer.echo(f"coord: 0x{coord_hex}")
    typer.echo(f"xyz(u85): x={x} y={y} z={z} plane={plane}")


@app.command()
def cantor(
    from_coord: Optional[str] = typer.Option(None, "--from-coord", help="256-bit coord hex (with optional 0x; leading zeros optional)."),
    to_coord: Optional[str] = typer.Option(None, "--to-coord", help="256-bit coord hex (with optional 0x; leading zeros optional)."),
    from_xyz: Optional[str] = typer.Option(None, "--from-xyz", help="x,y,z (u85 integers)."),
    to_xyz: Optional[str] = typer.Option(None, "--to-xyz", help="x,y,z (u85 integers)."),
    plane: int = typer.Option(0, "--plane", help="Plane bit (only used with --from-xyz/--to-xyz)."),
    max_height: int = typer.Option(8, "--max-height", help="Max LCA height to print full Cantor tree levels."),
    max_compute_height: int = typer.Option(
        20,
        "--max-compute-height",
        help="Refuse to compute Cantor roots if any axis LCA height exceeds this (O(2^h)).",
    ),
) -> None:
    """Debug Cantor movement/encryption numbers between two coordinates.

    Prints, per axis:
    - LCA height
    - aligned subtree base/range
    - the full Cantor pairing tree up to the LCA root (for small heights)

    Also prints:
    - combined 3D Cantor number
    - encryption key = sha256(cantor_number)  (single hash)
    - discovery id   = sha256(encryption_key) (double hash)

    Notes:
    - This is O(2^h) per axis for height h; use small coordinates or a small --max-height.
    """

    using_coords = from_coord is not None or to_coord is not None
    using_xyz = from_xyz is not None or to_xyz is not None
    if using_coords and using_xyz:
        typer.echo("Use either --from-coord/--to-coord OR --from-xyz/--to-xyz (not both).", err=True)
        raise typer.Exit(code=2)

    if using_coords:
        if from_coord is None or to_coord is None:
            typer.echo("Both --from-coord and --to-coord are required.", err=True)
            raise typer.Exit(code=2)
        fc_hex = _parse_coord_hex(from_coord)
        tc_hex = _parse_coord_hex(to_coord)

        fc_int = int.from_bytes(bytes.fromhex(fc_hex), "big")
        tc_int = int.from_bytes(bytes.fromhex(tc_hex), "big")

        x1, y1, z1, p1 = coord_to_xyz(fc_int)
        x2, y2, z2, p2 = coord_to_xyz(tc_int)
        if p1 != p2:
            typer.echo("Plane mismatch: from/to are in different planes.", err=True)
            raise typer.Exit(code=2)
        plane = p1
    else:
        if from_xyz is None or to_xyz is None:
            typer.echo("Both --from-xyz and --to-xyz are required.", err=True)
            raise typer.Exit(code=2)

        a = _parse_csv_ints(from_xyz)
        b = _parse_csv_ints(to_xyz)
        if len(a) != 3 or len(b) != 3:
            raise typer.BadParameter("--from-xyz/--to-xyz expect x,y,z")
        x1, y1, z1 = a
        x2, y2, z2 = b

        if plane not in (0, 1):
            raise typer.BadParameter("--plane must be 0 or 1")

        fc_hex = _coord_hex_from_xyz(x1, y1, z1, plane)
        tc_hex = _coord_hex_from_xyz(x2, y2, z2, plane)

    if any(v < 0 for v in (x1, y1, z1, x2, y2, z2)):
        typer.echo("Axis values must be non-negative (u85).", err=True)
        raise typer.Exit(code=2)

    typer.echo("from:")
    typer.echo(f"  coord: 0x{fc_hex}")
    typer.echo(f"  xyz:   x={x1} y={y1} z={z1} plane={plane}")
    typer.echo("to:")
    typer.echo(f"  coord: 0x{tc_hex}")
    typer.echo(f"  xyz:   x={x2} y={y2} z={z2} plane={plane}")

    def _print_axis(name: str, v1: int, v2: int) -> int:
        height = find_lca_height(v1, v2)
        base = (v1 >> height) << height
        leaf_count = 1 << height
        leaf_min = base
        leaf_max = base + leaf_count - 1

        if height > max_compute_height:
            typer.echo(
                f"axis {name}: lca_height={height} exceeds --max-compute-height={max_compute_height}; refusing to compute root.",
                err=True,
            )
            raise typer.Exit(code=2)

        typer.echo(f"axis {name}:")
        typer.echo(f"  v1={v1} v2={v2}")
        typer.echo(f"  lca_height={height}")
        typer.echo(f"  subtree_base={base}")
        typer.echo(f"  subtree_range=[{leaf_min}..{leaf_max}] leaves={leaf_count}")

        if height <= max_height:
            dbg = axis_cantor_debug(v1, v2, max_height=max_height)
            for level, values in enumerate(dbg.levels):
                hex_values = [int_to_hex_be_min(v) for v in values]
                typer.echo(f"  level_{level} ({len(values)} nodes): {hex_values}")
            root = dbg.root
        else:
            typer.echo(f"  tree_levels: omitted (height {height} > --max-height {max_height})")
            root = compute_axis_cantor(v1, v2)

        typer.echo(f"  cantor_root_hex={int_to_hex_be_min(root)}")
        typer.echo(f"  cantor_root_bytes={len(int_to_bytes_be_min(root))}")
        return root

    cx = _print_axis("X", x1, x2)
    cy = _print_axis("Y", y1, y2)
    cz = _print_axis("Z", z1, z2)

    # Combine in 3D.
    from cyberspace_core.cantor import cantor_pair

    combined = cantor_pair(cantor_pair(cx, cy), cz)
    encryption_key_hex = sha256_int_hex(combined)
    discovery_id_hex = sha256(bytes.fromhex(encryption_key_hex)).hex()

    combined_bytes = int_to_bytes_be_min(combined)

    typer.echo("combined:")
    typer.echo(f"  cantor_number_hex={int_to_hex_be_min(combined)}")
    typer.echo(f"  cantor_number_bytes={len(combined_bytes)}")
    typer.echo(f"  encryption_key_sha256={encryption_key_hex}")
    typer.echo(f"  discovery_id_sha256_sha256={discovery_id_hex}")


@app.command()
def move(
    to: str = typer.Option(None, "--to", help="Absolute xyz[,plane] as comma-separated ints."),
    by: str = typer.Option(None, "--by", help="Relative dx,dy,dz as comma-separated ints."),
) -> None:
    """Move locally by appending a hop event to the active chain."""
    state = _require_state()
    label = _require_active_chain_label(state)

    events = chains.read_events(label)
    if not events:
        typer.echo(f"Chain is empty: {label}", err=True)
        raise typer.Exit(code=1)

    genesis_id = events[0]["id"]
    prev_event_id = events[-1]["id"]

    prev_coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x1, y1, z1, plane1 = coord_to_xyz(prev_coord_int)

    if (to is None and by is None) or (to is not None and by is not None):
        typer.echo("Specify exactly one of --to or --by.", err=True)
        raise typer.Exit(code=2)

    if to is not None:
        vals = _parse_csv_ints(to)
        if len(vals) not in (3, 4):
            raise typer.BadParameter("--to expects x,y,z or x,y,z,plane")
        x2, y2, z2 = vals[0], vals[1], vals[2]
        plane2 = vals[3] if len(vals) == 4 else plane1
    else:
        vals = _parse_csv_ints(by or "")
        if len(vals) != 3:
            raise typer.BadParameter("--by expects dx,dy,dz")
        dx, dy, dz = vals
        x2, y2, z2, plane2 = x1 + dx, y1 + dy, z1 + dz, plane1

    if plane2 != plane1:
        typer.echo("Plane changes are not supported yet (must remain in same plane).", err=True)
        raise typer.Exit(code=2)

    if not (0 <= x2 <= AXIS_MAX and 0 <= y2 <= AXIS_MAX and 0 <= z2 <= AXIS_MAX):
        typer.echo(
            "Destination is out of u85 range. "
            f"dest=(x={x2}, y={y2}, z={z2}) must be within [0, {AXIS_MAX}]. "
            f"current=(x={x1}, y={y1}, z={z1}).",
            err=True,
        )
        raise typer.Exit(code=2)

    coord_hex = _coord_hex_from_xyz(x2, y2, z2, plane2)

    proof = compute_movement_proof_xyz(x1, y1, z1, x2, y2, z2)

    created_at = int(time.time())
    hop_event = make_hop_event(
        pubkey_hex=state.pubkey_hex,
        created_at=created_at,
        genesis_event_id=genesis_id,
        previous_event_id=prev_event_id,
        prev_coord_hex=state.coord_hex,
        coord_hex=coord_hex,
        proof_hash_hex=proof.proof_hash,
    )
    chains.append_event(label, hop_event)

    state.coord_hex = coord_hex
    save_state(state)

    typer.echo(f"Moved. chain={label} len={chains.chain_length(label)}")
    typer.echo(f"coord: 0x{coord_hex}")
    typer.echo(f"proof: {proof.proof_hash}")


@app.command()
def history(
    limit: int = typer.Option(50, "--limit", help="Max events to print."),
    json_out: bool = typer.Option(False, "--json", help="Print raw event JSON objects (one per line)."),
) -> None:
    """Show the active chain.

    By default this prints a human-readable summary.

    Use `--json` to print the full underlying Nostr-style event objects (JSON), one per line.
    """
    import json

    state = _require_state()
    label = _require_active_chain_label(state)

    events = chains.read_events(label)
    if not events:
        if not json_out:
            typer.echo(f"(empty chain) {label}")
        return

    if limit > 0:
        events = events[-limit:]

    if json_out:
        # Machine-friendly: print exactly the events, nothing else.
        for ev in events:
            typer.echo(json.dumps(ev, separators=(",", ":"), ensure_ascii=False))
        return

    typer.echo(f"chain: {label} (showing {len(events)} events)")
    for i, ev in enumerate(events):
        action = _get_tag(ev, "A") or "?"
        coord = _get_tag(ev, "C") or ""
        proof = _get_tag(ev, "proof") or ""
        eid = ev.get("id", "")

        line = f"{i:04d} {action:5} id={eid} coord=0x{coord}"
        if proof:
            line += f" proof={proof}"
        typer.echo(line)


@chain_app.command("list")
def chain_list() -> None:
    """List known local chains and show which is active."""
    state = load_state()
    active = (state.active_chain_label if state else "") or ""
    labels = chains.list_chain_labels()
    if not labels:
        typer.echo("(no chains yet)")
        return

    for label in labels:
        mark = "*" if label == active else " "
        n = chains.chain_length(label)
        typer.echo(f"{mark} {label} (len={n})")


@chain_app.command("use")
def chain_use(label: str) -> None:
    """Set the active chain label in local state."""
    state = _require_state()
    label = chains.normalize_label(label)
    if chains.chain_length(label) == 0:
        typer.echo(f"Unknown chain: {label}", err=True)
        raise typer.Exit(code=1)

    state.active_chain_label = label
    save_state(state)
    typer.echo(f"active_chain: {label}")


@chain_app.command("status")
def chain_status() -> None:
    """Show active chain status (length + delta from spawn in X/Y/Z)."""
    state = _require_state()
    label = _require_active_chain_label(state)

    events = chains.read_events(label)
    if not events:
        typer.echo(f"(empty chain) {label}")
        return

    spawn_coord_hex = _get_tag(events[0], "C") or ""
    last_coord_hex = _get_tag(events[-1], "C") or ""

    if not spawn_coord_hex or not last_coord_hex:
        typer.echo("Chain missing C tags; cannot compute distance.", err=True)
        raise typer.Exit(code=1)

    spawn = int.from_bytes(bytes.fromhex(spawn_coord_hex), "big")
    cur = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    last = int.from_bytes(bytes.fromhex(last_coord_hex), "big")

    sx, sy, sz, splane = coord_to_xyz(spawn)
    cx, cy, cz, cplane = coord_to_xyz(cur)

    dx, dy, dz = cx - sx, cy - sy, cz - sz

    typer.echo(f"active_chain: {label}")
    typer.echo(f"length: {len(events)} (hops={max(0, len(events) - 1)})")
    typer.echo(f"genesis: {events[0].get('id','')}")
    typer.echo(f"last:    {events[-1].get('id','')}")
    typer.echo(f"spawn:   0x{spawn_coord_hex}")
    typer.echo(f"current: 0x{state.coord_hex}")
    if cur != last:
        typer.echo("warning: state coord != last chain coord", err=True)
    typer.echo(f"delta_xyz: dx={dx} dy={dy} dz={dz} (plane={cplane})")


if __name__ == "__main__":
    app()
