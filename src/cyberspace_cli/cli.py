from __future__ import annotations
import base64
import json
import secrets
import subprocess
from decimal import Decimal, InvalidOperation

import time
import nest_asyncio
nest_asyncio.apply()  # Allow asyncio.run() in sync CLI context
from typing import Dict, List, Optional, Sequence, Tuple

import typer
from typer.models import OptionInfo

from cyberspace_cli import chains
from cyberspace_cli import targets
from cyberspace_cli.config import load_config, save_config
from cyberspace_cli.paths import hyperjump_cache_path
from cyberspace_cli.helptext import HELP_TEXT
from cyberspace_cli.nostr_event import (
    make_encrypted_content_event,
    make_hop_event,

    make_hyperjump_event,
    make_sidestep_event,
    make_spawn_event,
)

# Hyperjump constants
DEFAULT_HYPERJUMP_RELAY = "wss://hyperjump.arKin0x.com"
HYPERJUMP_KIND = 321
from cyberspace_cli.nostr_signer import create_nip98_auth_header  # For HOSAKA auth
from cyberspace_cli.parsing import normalize_hex_32, parse_destination_xyz_or_coord
from cyberspace_cli.toward import choose_next_axis_value_toward
from cyberspace_cli.nostr_keys import (
    encode_nsec,
    encode_npub,
    generate_privkey_bytes,
    privkey_bytes_from_nsec_or_hex,
    pubkey_hex_from_privkey,
)
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, load_state, save_state
from cyberspace_core.cantor import int_to_bytes_be_min, int_to_hex_be_min, sha256, sha256_int_hex
from cyberspace_core.coords import AXIS_MAX, coord_to_xyz, dataspace_coord_to_gps, gps_to_dataspace_coord, xyz_to_coord
from cyberspace_core.geoid import (
    DEFAULT_GEOID_MODEL,
    GeoidError,
    GeoidModelNotFoundError,
    SUPPORTED_GEOID_MODELS,
    candidate_model_paths,
    default_geoid_search_dirs,
    geoid_undulation_m,
    load_geoid_grid,
    normalize_geoid_model,
)
from cyberspace_core.location_encryption import (
    DEFAULT_SCAN_MAX_HEIGHT,
    decrypt_with_location_key,
    derive_region_key_material_for_height,
    derive_region_key_material_scan,
    encrypt_with_location_key,
)
from cyberspace_core.movement import (
    compute_axis_cantor,
    compute_hop_proof,
    compute_movement_proof_xyz,
    compute_sidestep_proof,
    find_lca_height,
)
from cyberspace_core.movement_debug import axis_cantor_debug

app = typer.Typer(no_args_is_help=True)
chain_app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
target_app = typer.Typer(no_args_is_help=True)
hyperjump_app = typer.Typer(no_args_is_help=True)
geoid_app = typer.Typer(no_args_is_help=True)
app.add_typer(chain_app, name="chain", help="Manage local movement chains.")
app.add_typer(config_app, name="config", help="Show/set persisted CLI defaults.")
app.add_typer(target_app, name="target", help="Manage saved movement targets.")
app.add_typer(geoid_app, name="geoid", help="Inspect geoid dataset configuration and availability.")
app.add_typer(
    hyperjump_app,
    name="hyperjump",
    help="Inspect hyperjumps from anywhere (show/nearest); creating hyperjump actions (to/next/prev) requires being on the hyperjump system.",
)




def _require_hyperjump_system_state() -> Tuple[CyberspaceState, int]:
    state = _require_state()
    label = _require_active_chain_label(state)
    events = chains.read_events(label)
    if not events:
        typer.echo(f"Chain is empty: {label}", err=True)
        raise typer.Exit(code=1)
    current_height = _hyperjump_block_height_from_event(events[-1])
    if current_height is None:
        typer.echo(
            "You are not currently on the hyperjump system. Perform a valid hyperjump first.",
            err=True,
        )
        raise typer.Exit(code=2)
    return state, current_height


def _query_hyperjump_anchor_for_height(
    *,
    block_height: int,
    relay: str,
    limit: int,
    verbose: bool = False,
) -> Optional[Tuple[str, dict, Tuple[int, int, int, int]]]:
    if block_height < 0:
        return None
    events = _nak_req_events(
        relay=relay,
        kind=HYPERJUMP_KIND,
        tags={"B": [str(block_height)]},
        limit=limit,
        verbose=verbose,
    )
    best: Optional[Tuple[int, str, str, dict]] = None
    for ev in events:
        b_tag = _get_tag(ev, "B")
        c_tag = _get_tag(ev, "C")
        if not b_tag or not c_tag:
            continue
        try:
            b_val = int(str(b_tag), 10)
            c_norm = normalize_hex_32(c_tag)
        except (ValueError, TypeError):
            continue
        if b_val != block_height:
            continue
        created_at = int(ev.get("created_at", 0))
        event_id = str(ev.get("id", ""))
        candidate = (created_at, event_id, c_norm, ev)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    coord_hex = best[2]
    coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
    x, y, z, plane = coord_to_xyz(coord_int)
    return coord_hex, best[3], (x, y, z, plane)


def _print_hyperjump_anchor(*, block_height: int, coord_hex: str, event: dict, xyzp: Tuple[int, int, int, int]) -> None:
    x, y, z, plane = xyzp
    typer.echo(f"hyperjump_block_height={block_height}")
    typer.echo(f"coord: 0x{coord_hex}")
    typer.echo(f"x={x}")
    typer.echo(f"y={y}")
    typer.echo(f"z={z}")
    typer.echo(f"plane={plane} {_plane_label(plane)}")
    event_id = str(event.get("id", ""))
    if event_id:
        typer.echo(f"event_id={event_id}")


@config_app.command("show")
def config_show() -> None:
    """Show persisted CLI config."""
    cfg = load_config()
    typer.echo(f"default_max_lca_height: {cfg.default_max_lca_height}")
    typer.echo(f"gps_geoid_model: {cfg.gps_geoid_model}")


@config_app.command("set")
def config_set(
    max_lca_height: int = typer.Option(
        ...,  # required
        "--max-lca-height",
        min=0,
        help="Persist default for move/toward. 0 disables large hops entirely (not recommended).",
    ),
) -> None:
    """Persist CLI settings so flags are not needed on every command."""
    cfg = load_config()
    cfg.default_max_lca_height = int(max_lca_height)
    save_config(cfg)
    typer.echo("Saved.")
    typer.echo(f"default_max_lca_height: {cfg.default_max_lca_height}")


@config_app.command("set-geoid-model")
def config_set_geoid_model(
    model: str = typer.Argument(
        ...,
        metavar="MODEL",
        help="Default geoid model for --altitude-sealevel auto conversion: egm2008-2_5 or egm2008-1.",
    ),
) -> None:
    """Persist default geoid model for sea-level altitude conversion in `cyberspace gps`."""
    try:
        model_n = normalize_geoid_model(model)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e

    cfg = load_config()
    cfg.gps_geoid_model = model_n
    save_config(cfg)
    typer.echo("Saved.")
    typer.echo(f"gps_geoid_model: {cfg.gps_geoid_model}")
@geoid_app.command("doctor")
def geoid_doctor(
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Optional model to focus on (egm2008-2_5 or egm2008-1). Default: config model.",
    ),
    show_all: bool = typer.Option(
        True,
        "--all/--effective-only",
        help="Show status for all supported models (default) or only the effective model.",
    ),
) -> None:
    """Inspect geoid model configuration and dataset installation health."""
    cfg = load_config()
    model_raw = model or cfg.gps_geoid_model or DEFAULT_GEOID_MODEL
    try:
        effective_model = normalize_geoid_model(model_raw)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e

    typer.echo(f"config_default_model={cfg.gps_geoid_model}")
    typer.echo(f"effective_model={effective_model}")
    typer.echo("search_dirs:")
    for d in default_geoid_search_dirs():
        typer.echo(str(d))

    models_to_check: List[str]
    if show_all:
        models_to_check = [effective_model] + [m for m in SUPPORTED_GEOID_MODELS if m != effective_model]
    else:
        models_to_check = [effective_model]

    for idx, m in enumerate(models_to_check):
        if idx > 0:
            typer.echo("")
        typer.echo(f"model={m}")
        try:
            grid = load_geoid_grid(m)
            typer.echo("status=available")
            typer.echo(f"path={grid.path}")
            typer.echo(f"grid={grid.width}x{grid.height}")
            typer.echo(f"scale={grid.scale}")
            typer.echo(f"offset={grid.offset}")
            try:
                sz = grid.path.stat().st_size
                typer.echo(f"size_bytes={sz}")
            except OSError:
                pass
        except GeoidModelNotFoundError:
            typer.echo("status=missing")
            typer.echo("candidates:")
            for c in candidate_model_paths(m):
                typer.echo(str(c))
        except GeoidError as e:
            typer.echo("status=invalid")
            typer.echo(f"error={e}")


@target_app.command("set")
def target_set(
    coord: str = typer.Argument(..., help="256-bit coord hex (0x... optional; leading zeros optional)."),
    label: Optional[str] = typer.Option(None, "--label", help="Human label for this target (default: unnamed_N)."),
) -> None:
    """Add/update a target and set it as current."""
    state = _require_state()
    try:
        tgt_label, coord_hex = targets.set_target(state, coord, label=label)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e

    save_state(state)
    typer.echo(f"(current) {tgt_label} 0x{coord_hex}")


@target_app.command("use")
def target_use(label: str = typer.Argument(..., help="Target label to select as current.")) -> None:
    """Select an existing target label as current."""
    state = _require_state()
    label = chains.normalize_label(label)
    for t in state.targets or []:
        if t.get("label") == label:
            state.active_target_label = label
            save_state(state)
            typer.echo(f"active_target: {label}")
            return

    typer.echo(f"Unknown target label: {label}", err=True)
    raise typer.Exit(code=1)


@target_app.command("list")
def target_list() -> None:
    """List known targets (and show which is current)."""
    state = _require_state()
    lines = targets.format_target_list(state)
    if not lines:
        typer.echo("(no targets yet)")
        return
    for line in lines:
        typer.echo(line)


@app.command()
def help() -> None:
    """Show the extended help / usage guide."""
    typer.echo(HELP_TEXT.strip())


@app.command()
def spec() -> None:
    """Open the Cyberspace spec / README in your browser."""
    import webbrowser

    url = "https://github.com/arkin0x/cyberspace/blob/master/readme.md"

    ok = False
    try:
        ok = bool(webbrowser.open(url, new=2))
    except Exception:
        ok = False

    # Always print for copy/paste (and for headless environments).
    typer.echo(url)
    if not ok:
        typer.echo("(Could not auto-open browser; URL printed above.)", err=True)


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
        targets=[],
        active_target_label="",
    )
    save_state(state)

    typer.echo("Spawned.")
    typer.echo(f"chain: {state.active_chain_label} (len=1)")
    typer.echo(f"npub: {encode_npub(bytes.fromhex(pub_hex))}")
    typer.echo(f"nsec: {encode_nsec(priv)}")
    typer.echo(f"coord: 0x{coord_hex}")
    _coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
    _x, _y, _z, _plane = coord_to_xyz(_coord_int)
    typer.echo(f"plane={_plane} {_plane_label(_plane)}")


@app.command()
def whereami() -> None:
    """Show current coordinate (and decoded x/y/z/plane)."""
    state = _require_state()
    coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x, y, z, plane = coord_to_xyz(coord_int)

    typer.echo(f"coord: 0x{state.coord_hex}")
    typer.echo(f"pubkey: {state.pubkey_hex}")
    typer.echo(f"active_chain: {state.active_chain_label or '(none)'}")
    typer.echo("xyz(u85):")
    typer.echo(f"x={x}")
    typer.echo(f"y={y}")
    typer.echo(f"z={z}")
    typer.echo(f"plane={plane} {_plane_label(plane)}")


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

    typer.echo("sector:")
    typer.echo(f"X={sx}")
    typer.echo(f"Y={sy}")
    typer.echo(f"Z={sz}")
    typer.echo(f"plane={plane} {_plane_label(plane)}")
    typer.echo(f"S tag: {sx}-{sy}-{sz}")


def _bench_worker(height: int, q) -> None:  # pragma: no cover
    """Child process target for `cyberspace bench`.

    This isolates expensive / long-running proof computation so we can enforce a timeout.
    """
    try:
        # LCA height h can be forced by moving 0 -> (2^h - 1).
        x2 = (1 << height) - 1 if height > 0 else 0
        compute_movement_proof_xyz(0, 0, 0, x2, x2, x2, max_compute_height=height)
        q.put({"ok": True})
    except Exception as e:
        q.put({"ok": False, "error": str(e)})


@app.command()
def bench(
    timeout_s: int = typer.Option(60, "--timeout", help="Cancel a single LCA benchmark if it exceeds this many seconds."),
    target_s: float = typer.Option(2.0, "--target", help="Target seconds for selecting the 'Optimal Speed' LCA."),
    max_height: int = typer.Option(22, "--max-height", help="Safety cap on heights to attempt."),
) -> None:
    """Benchmark movement proof compute time by LCA height.

    Runs LCA heights from 0 upward until a height exceeds the timeout.

    Notes:
    - Proof computation is O(2^h) per axis; big heights get expensive fast.
    - The chosen "Optimal Speed" is the height whose runtime is closest to --target.
    """
    import multiprocessing as mp
    import time as _time

    cfg = load_config()

    typer.echo("bench: movement proof runtime by LCA height")
    typer.echo(f"timeout_s={timeout_s} target_s={target_s}")
    typer.echo(f"current_default_max_lca_height={cfg.default_max_lca_height}")

    results: List[Tuple[int, float]] = []

    for h in range(0, max_height + 1):
        q: mp.Queue = mp.Queue()
        p = mp.Process(target=_bench_worker, args=(h, q))

        start = _time.perf_counter()
        p.start()
        p.join(timeout_s)

        if p.is_alive():
            p.terminate()
            p.join(5)
            typer.echo(f"lca_height={h}: >{timeout_s:.0f}s (cancelled)")
            break

        elapsed = _time.perf_counter() - start

        msg = None
        try:
            if not q.empty():
                msg = q.get_nowait()
        except Exception:
            msg = None

        if isinstance(msg, dict) and not msg.get("ok", True):
            typer.echo(f"lca_height={h}: error: {msg.get('error','unknown')}")
            break

        results.append((h, elapsed))
        typer.echo(f"lca_height={h}: {elapsed:.3f}s")

    if not results:
        typer.echo("No benchmark results.", err=True)
        raise typer.Exit(code=1)

    # Pick height closest to target_s.
    optimal_h, optimal_t = min(results, key=lambda it: abs(it[1] - target_s))

    typer.echo("---")
    typer.echo(f"Optimal Speed LCA: {optimal_h} ({optimal_t:.3f}s)")
    typer.echo(f"Recommendation: set --max-lca-height to {optimal_h} for interactive speed.")
    typer.echo(f"Persist: cyberspace config set --max-lca-height {optimal_h}")
    typer.echo(f"Per-command override: cyberspace move --max-lca-height {optimal_h} ...")


@app.command()
@app.command()
def lcaplot(
    axis: str = typer.Option("x", "--axis", help="Axis to plot: x, y, or z."),
    center: Optional[int] = typer.Option(None, "--center", help="Center value."),
    span: int = typer.Option(256, "--span", help="Half-window size."),
    direction: str = typer.Option("+1", "--direction", help="+1 or -1."),
    max_lca_height: int = typer.Option(17, "--max-lca-height", help="Reference max."),
) -> None:
    """Interactive LCA height plot."""
    from cyberspace_cli.state import load_state
    from cyberspace_cli.viz_commands import lcaplot_command
    
    st = load_state()
    curx = cury = curz = None
    if st:
        try:
            coord_int = int.from_bytes(bytes.fromhex(st.coord_hex), "big")
            curx, cury, curz, _ = coord_to_xyz(coord_int)
        except:
            pass
    
    lcaplot_command(
        axis=axis, center=center, span=span, direction=direction,
        max_lca_height=max_lca_height,
        current_x=curx, current_y=cury, current_z=curz,
    )


@app.command("3d")
def three_d_cmd(
    coord: Optional[str] = typer.Option(None, "--coord", help="Coord to visualize."),
    plane: int = typer.Option(0, "--plane", help="Plane (0 or 1)."),
) -> None:
    """3D cyberspace visualization."""
    from cyberspace_cli.viz_commands import three_d_command
    three_d_command(coord=coord, plane=plane)


@app.command()
def gps(
    coord: Optional[str] = typer.Option(None, "--coord", help="Coord to convert to GPS."),
    at: Optional[str] = typer.Argument(None, help="lat,lon"),
    lat: Optional[str] = typer.Option(None, "--lat"),
    lon: Optional[str] = typer.Option(None, "--lon"),
    altitude_wgs84_m: Optional[str] = typer.Option(None, "--altitude-wgs84", "--alt"),
    altitude_sealevel_m: Optional[str] = typer.Option(None, "--altitude-sealevel"),
    geoid_offset_m: Optional[str] = typer.Option(None, "--geoid-offset-m"),
    geoid_model: Optional[str] = typer.Option(None, "--geoid-model"),
    clamp_to_surface: Optional[bool] = typer.Option(None, "--clamp/--no-clamp"),
) -> None:
    """GPS <-> coord conversion."""
    from cyberspace_cli.viz_commands import gps_command
    gps_command(
        coord=coord, at=at, lat=lat, lon=lon,
        altitude_wgs84_m=altitude_wgs84_m,
        altitude_sealevel_m=altitude_sealevel_m,
        geoid_offset_m=geoid_offset_m,
        geoid_model=geoid_model,
        clamp_to_surface=clamp_to_surface,
    )


@app.command()
def cantor(
    from_coord: Optional[str] = typer.Option(None, "--from-coord"),
    to_coord: Optional[str] = typer.Option(None, "--to-coord"),
    from_xyz: Optional[str] = typer.Option(None, "--from-xyz"),
    to_xyz: Optional[str] = typer.Option(None, "--to-xyz"),
) -> None:
    """Cantor pairing computation."""
    from cyberspace_cli.viz_commands import cantor_command
    cantor_command(
        from_coord=from_coord, to_coord=to_coord,
        from_xyz=from_xyz, to_xyz=to_xyz,
    )


@app.command()
@app.command()
def encrypt(
    text: Optional[str] = typer.Option(None, "--text", help="Plaintext."),
    file: Optional[str] = typer.Option(None, "--file", help="File to encrypt."),
    height: int = typer.Option(..., "--height", help="Region height."),
    key: Optional[str] = typer.Option(None, "--key", help="Key string."),
    key_hex: Optional[str] = typer.Option(None, "--key-hex", help="Key hex."),
    from_coord: Optional[str] = typer.Option(None, "--from-coord", help="Region coord."),
    from_xyz: Optional[str] = typer.Option(None, "--from-xyz", help="Region x,y,z."),
) -> None:
    """Encrypt plaintext with location-based key."""
    from cyberspace_cli.crypto_commands import encrypt_command
    encrypt_command(
        text=text, file=file, height=height, key=key, key_hex=key_hex,
        from_coord=from_coord, from_xyz=from_xyz,
    )


@app.command()
def decrypt(
    ciphertext_hex: str = typer.Argument(..., help="Ciphertext hex."),
    encryption_key_hex: str = typer.Argument(..., help="Encryption key hex."),
) -> None:
    """Decrypt ciphertext."""
    from cyberspace_cli.crypto_commands import decrypt_command
    decrypt_command(ciphertext_hex, encryption_key_hex)


@app.command()
def scan(
    region_key_hex: str = typer.Option(..., "--region-key", help="Region key hex."),
    target: Optional[str] = typer.Option(None, "--target", help="Target coord to search."),
    max_height: int = typer.Option(15, "--max-height", help="Max height to scan."),
    output_dir: Optional[str] = typer.Option(None, "--output", help="Output directory."),
) -> None:
    """Scan region for encrypted events."""
    from cyberspace_cli.crypto_commands import scan_command
    scan_command(region_key_hex, target=target, max_height=max_height, output_dir=output_dir)


@hyperjump_app.command("show")
def hyperjump_show(
    blockheight: int = typer.Argument(
        ...,
        min=0,
        help="Hyperjump block height to inspect.",
    ),
    relay: str = typer.Option(
        DEFAULT_HYPERJUMP_RELAY,
        "--relay",
        help="Relay URL for querying hyperjump anchor events (kind=321).",
    ),
    limit: int = typer.Option(
        25,
        "--limit",
        min=1,
        help="Maximum number of matching events to ask from the relay.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print the Nostr REQ filter and raw nak output for debugging.",
    ),
) -> None:
    """Show a hyperjump anchor for a specific block height."""
    resolved = _query_hyperjump_anchor_for_height(
        block_height=blockheight,
        relay=relay,
        limit=limit,
        verbose=verbose,
    )
    if resolved is None:
        typer.echo(f"No hyperjump found for block height {blockheight}.", err=True)
        raise typer.Exit(code=1)
    coord_hex, ev, xyzp = resolved
    _print_hyperjump_anchor(block_height=blockheight, coord_hex=coord_hex, event=ev, xyzp=xyzp)

@hyperjump_app.command("to")
def hyperjump_to(
    blockheight: int = typer.Argument(
        ...,
        min=0,
        help="Target hyperjump block height.",
    ),
    view: bool = typer.Option(
        False,
        "--view",
        help="Show the target hyperjump without creating a movement action.",
    ),
    relay: str = typer.Option(
        DEFAULT_HYPERJUMP_RELAY,
        "--relay",
        help="Relay URL for querying hyperjump anchor events (kind=321).",
    ),
    limit: int = typer.Option(
        25,
        "--limit",
        min=1,
        help="Maximum number of matching events to ask from the relay.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print the Nostr REQ filter and raw nak output for debugging.",
    ),
    hyperjump_query_limit: int = typer.Option(
        25,
        "--hyperjump-query-limit",
        min=1,
        help="Validation query limit used when publishing the hyperjump movement event.",
    ),
) -> None:
    """Move to (or view) a specific hyperjump block height."""
    resolved = _query_hyperjump_anchor_for_height(
        block_height=blockheight,
        relay=relay,
        limit=limit,
        verbose=verbose,
    )
    if resolved is None:
        typer.echo(f"No hyperjump found for block height {blockheight}.", err=True)
        raise typer.Exit(code=1)

    coord_hex, ev, xyzp = resolved
    if view:
        _print_hyperjump_anchor(block_height=blockheight, coord_hex=coord_hex, event=ev, xyzp=xyzp)
        return

    # Action-creating commands are restricted to the hyperjump system.
    _state, _current_height = _require_hyperjump_system_state()
    move(
        to=f"0x{coord_hex}",
        by=None,
        toward=None,
        max_lca_height=None,
        max_hops=0,
        hyperjump=True,
        hyperjump_relay=relay,
        hyperjump_query_limit=hyperjump_query_limit,
        exit_hyperjump=False,
    )
    _print_hyperjump_anchor(block_height=blockheight, coord_hex=coord_hex, event=ev, xyzp=xyzp)


@hyperjump_app.command("next")
def hyperjump_next(
    view: bool = typer.Option(
        False,
        "--view",
        help="Show the next hyperjump without creating a movement action.",
    ),
    relay: str = typer.Option(
        DEFAULT_HYPERJUMP_RELAY,
        "--relay",
        help="Relay URL for querying hyperjump anchor events (kind=321).",
    ),
    limit: int = typer.Option(
        25,
        "--limit",
        min=1,
        help="Maximum number of matching events to ask from the relay.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print the Nostr REQ filter and raw nak output for debugging.",
    ),
    hyperjump_query_limit: int = typer.Option(
        25,
        "--hyperjump-query-limit",
        min=1,
        help="Validation query limit used when publishing the hyperjump movement event.",
    ),
) -> None:
    """Move to (or view) the next hyperjump block."""
    _state, current_block_height = _require_hyperjump_system_state()
    target_block_height = current_block_height + 1
    resolved = _query_hyperjump_anchor_for_height(
        block_height=target_block_height,
        relay=relay,
        limit=limit,
        verbose=verbose,
    )
    if resolved is None:
        typer.echo(f"No hyperjump found for block height {target_block_height}.", err=True)
        raise typer.Exit(code=1)

    coord_hex, ev, xyzp = resolved
    if view:
        _print_hyperjump_anchor(block_height=target_block_height, coord_hex=coord_hex, event=ev, xyzp=xyzp)
        return

    move(
        to=f"0x{coord_hex}",
        by=None,
        toward=None,
        max_lca_height=None,
        max_hops=0,
        hyperjump=True,
        hyperjump_relay=relay,
        hyperjump_query_limit=hyperjump_query_limit,
        exit_hyperjump=False,
    )
    _print_hyperjump_anchor(block_height=target_block_height, coord_hex=coord_hex, event=ev, xyzp=xyzp)


@hyperjump_app.command("prev")
def hyperjump_prev(
    view: bool = typer.Option(
        False,
        "--view",
        help="Show the previous hyperjump without creating a movement action.",
    ),
    relay: str = typer.Option(
        DEFAULT_HYPERJUMP_RELAY,
        "--relay",
        help="Relay URL for querying hyperjump anchor events (kind=321).",
    ),
    limit: int = typer.Option(
        25,
        "--limit",
        min=1,
        help="Maximum number of matching events to ask from the relay.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print the Nostr REQ filter and raw nak output for debugging.",
    ),
    hyperjump_query_limit: int = typer.Option(
        25,
        "--hyperjump-query-limit",
        min=1,
        help="Validation query limit used when publishing the hyperjump movement event.",
    ),
) -> None:
    """Move to (or view) the previous hyperjump block."""
    _state, current_block_height = _require_hyperjump_system_state()
    target_block_height = current_block_height - 1
    if target_block_height < 0:
        typer.echo("No previous hyperjump exists before block height 0.", err=True)
        raise typer.Exit(code=2)

    resolved = _query_hyperjump_anchor_for_height(
        block_height=target_block_height,
        relay=relay,
        limit=limit,
        verbose=verbose,
    )
    if resolved is None:
        typer.echo(f"No hyperjump found for block height {target_block_height}.", err=True)
        raise typer.Exit(code=1)

    coord_hex, ev, xyzp = resolved
    if view:
        _print_hyperjump_anchor(block_height=target_block_height, coord_hex=coord_hex, event=ev, xyzp=xyzp)
        return

    move(
        to=f"0x{coord_hex}",
        by=None,
        toward=None,
        max_lca_height=None,
        max_hops=0,
        hyperjump=True,
        hyperjump_relay=relay,
        hyperjump_query_limit=hyperjump_query_limit,
        exit_hyperjump=False,
    )
    _print_hyperjump_anchor(block_height=target_block_height, coord_hex=coord_hex, event=ev, xyzp=xyzp)


# Maximum number of tag values per relay request.  Relays typically reject
# filters whose total tag-value count exceeds ~2000.  With 3 axis tags the
# per-axis budget is MAX_TAG_VALUES // 3, giving a max radius of roughly 333.
MAX_TAG_VALUES = 2000

# Progressive expansion schedule: radii to try in order when --expand is used.
_EXPAND_RADII = [2, 5, 10, 25, 50, 100, 200, 333]


# Hyperjump cache functions moved to cyberspace_cli.hyperjump_cache
# (re-exported from cyberspace_cli.hyperjump_flow)
@app.command("sync")
def hyperjump_sync_cmd(
    relay: str = typer.Option(
        DEFAULT_HYPERJUMP_RELAY,
        "--relay",
        help="Relay URL for querying hyperjump anchor events (kind=321).",
    ),
    limit: int = typer.Option(
        10000,
        "--limit",
        min=1,
        help="Maximum events per relay request (relay may cap this).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print progress details.",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume from existing cache (append new events instead of overwriting).",
    ),
) -> None:
    """Download all hyperjump anchor events from the relay and cache locally."""
    from cyberspace_cli.hyperjump_commands import hyperjump_sync_command
    
    hyperjump_sync_command(relay=relay, limit=limit, verbose=verbose, resume=resume)


@app.command("nearest")
def hyperjump_nearest_cmd(
    relay: str = typer.Option(
        DEFAULT_HYPERJUMP_RELAY,
        "--relay",
        help="Relay URL for querying hyperjump anchor events (kind=321).",
    ),
    radius: int = typer.Option(
        10,
        "--radius",
        min=0,
        help="Sector scan radius around current sector for X/Y/Z (default: ±10).",
    ),
    limit: int = typer.Option(
        2000,
        "--limit",
        min=1,
        help="Maximum number of matching events to ask from the relay.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print the Nostr REQ filter and raw nak output for debugging.",
    ),
    coord: Optional[str] = typer.Option(
        None,
        "--coord",
        help="Override current coord for sector calculation.",
    ),
    cache: bool = typer.Option(
        False,
        "--cache",
        help="Search local cache instead of relay (requires `hyperjump sync`).",
    ),
    count: int = typer.Option(
        0,
        "--count",
        "-n",
        min=0,
        help="Limit number of results (0 = all).",
    ),
    expand: bool = typer.Option(
        False,
        "--expand",
        help="Progressively expand search radius until results found.",
    ),
) -> None:
    """Find nearest hyperjump anchors."""
    from cyberspace_cli.hyperjump_commands import hyperjump_nearest_command
    
    hyperjump_nearest_command(
        relay=relay,
        radius=radius,
        limit=limit,
        verbose=verbose,
        coord=coord,
        cache=cache,
        count=count,
        expand=expand,
    )


@app.command()
def move(
    to: Optional[str] = typer.Option(None, "--to", help="Destination x,y,z[,plane] or coord hex."),
    by: Optional[str] = typer.Option(None, "--by", help="Relative dx,dy,dz or 0,0,0,plane."),
    toward: Optional[str] = typer.Option(None, "--toward", help="Continuous movement target."),
    max_lca_height: Optional[int] = typer.Option(None, "--max-lca-height", help="Max LCA height."),
    max_hops: int = typer.Option(0, "--max-hops", help="Max hops for --toward."),
    hyperjump: bool = typer.Option(False, "--hyperjump", help="Use hyperjump flow."),
    hyperjump_relay: str = typer.Option("wss://hyperjump.arKin0x.com", "--hyperjump-relay"),
    hyperjump_query_limit: int = typer.Option(25, "--hyperjump-query-limit", min=1),
    sidestep: bool = typer.Option(False, "--sidestep", help="Use Merkle proofs."),
    exit_hyperjump: bool = typer.Option(False, "--exit-hyperjump"),
) -> None:
    """Move by appending a hop, sidestep, or hyperjump event."""
    from cyberspace_cli.move_commands import move_command
    move_command(
        to=to, by=by, toward=toward,
        max_lca_height=max_lca_height, max_hops=max_hops,
        hyperjump=hyperjump, hyperjump_relay=hyperjump_relay,
        hyperjump_query_limit=hyperjump_query_limit,
        sidestep=sidestep, exit_hyperjump=exit_hyperjump,
    )


@app.command()
def history(
    limit: int = typer.Option(50, "--limit", help="Max events."),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON."),
) -> None:
    """Show chain history."""
    import json
    from cyberspace_cli.state import _require_state
    from cyberspace_cli.chains import EventChains
    from cyberspace_cli.chain_commands import history_command
    
    state = _require_state()
    chains_obj = EventChains()
    label = chains_obj.active_chain_label(state)
    
    events = history_command(label, limit=limit, json_out=json_out)
    
    if not events:
        if not json_out:
            typer.echo(f"(empty chain) {label}")
        return
    
    if json_out:
        for ev in events:
            typer.echo(json.dumps(ev, separators=(",", ":"), ensure_ascii=False))
    else:
        for line in events:
            typer.echo(line)


@chain_app.command("list")
def chain_list() -> None:
    """List known chains."""
    from cyberspace_cli.chain_commands import chain_list_command
    
    results = chain_list_command()
    if not results:
        typer.echo("(no chains yet)")
        return
    
    for mark, label, n in results:
        typer.echo(f"{mark} {label} (len={n})")


@chain_app.command("use")
def chain_use(label: str) -> None:
    """Set active chain."""
    from cyberspace_cli.chain_commands import chain_use_command
    
    try:
        active = chain_use_command(label)
        typer.echo(f"active_chain: {active}")
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@chain_app.command("status")
def chain_status() -> None:
    """Show chain status."""
    from cyberspace_cli.chain_commands import chain_status_command
    from cyberspace_cli.cli import _plane_label
    
    try:
        info = chain_status_command()
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)
    
    if info.get("empty"):
        typer.echo(f"(empty chain) {info['label']}")
        return
    
    typer.echo(f"active_chain: {info['label']}")
    typer.echo(f"length: {info['length']} (hops={info['hops']})")
    typer.echo(f"genesis: {info['genesis_id']}")
    typer.echo(f"last:    {info['last_id']}")
    typer.echo(f"spawn:   0x{info['spawn_hex']}")
    typer.echo(f"current: 0x{info['current_hex']}")
    if not info.get("coords_match", True):
        typer.echo("warning: state coord != last chain coord", err=True)
    typer.echo(f"delta_xyz: dx={info['dx']} dy={info['dy']} dz={info['dz']} (plane={info['plane']} {_plane_label(info['plane'])})")


@app.command()
def history(
    limit: int = typer.Option(50, "--limit", help="Max events."),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """Show chain history."""
    import json
    from cyberspace_cli.state import _require_state
    from cyberspace_cli.chains import EventChains
    from cyberspace_cli.chain_commands import history_command
    
    state = _require_state()
    chains_obj = EventChains()
    label = chains_obj.active_chain_label(state)
    
    events = history_command(label, limit=limit, json_out=json_out)
    
    if not events:
        if not json_out:
            typer.echo(f"(empty chain) {label}")
        return
    
    if json_out:
        for ev in events:
            typer.echo(json.dumps(ev, separators=(",", ":"), ensure_ascii=False))
    else:
        for line in events:
            typer.echo(line)


if __name__ == "__main__":
    app()

if __name__ == "__main__":
    app()
