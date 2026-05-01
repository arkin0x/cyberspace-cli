from __future__ import annotations
import base64
import json
import secrets
import subprocess
from decimal import Decimal, InvalidOperation

import time
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
move_app = typer.Typer(no_args_is_help=True)
app.add_typer(chain_app, name="chain", help="Manage local movement chains.")
app.add_typer(config_app, name="config", help="Show/set persisted CLI defaults.")
app.add_typer(target_app, name="target", help="Manage saved movement targets.")
app.add_typer(geoid_app, name="geoid", help="Inspect geoid dataset configuration and availability.")
app.add_typer(
    hyperjump_app,
    name="hyperjump",
    help="Inspect hyperjumps from anywhere (show/nearest); creating hyperjump actions (to/next/prev) requires being on the hyperjump system.",
)
app.add_typer(move_app, name="move", help="Movement commands including interactive visualization.")


def _plane_label(plane: int) -> str:
    if plane == 0:
        return "dataspace"
    if plane == 1:
        return "ideaspace"
    return "unknown"


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

def _parse_decimal_option(value: Optional[str], option_name: str) -> Optional[Decimal]:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        raise typer.BadParameter(f"{option_name} expects a numeric value.")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        raise typer.BadParameter(f"{option_name} expects a numeric value.") from None


def _coord_hex_from_xyz(x: int, y: int, z: int, plane: int) -> str:
    coord_int = xyz_to_coord(x, y, z, plane=plane)
    return coord_int.to_bytes(32, "big").hex()


def _get_tag(event: dict, key: str) -> Optional[str]:
    for t in event.get("tags", []):
        if isinstance(t, list) and len(t) >= 2 and t[0] == key:
            return t[1]
    return None


def _get_tag_record(event: dict, key: str) -> Optional[List[str]]:
    for t in event.get("tags", []):
        if isinstance(t, list) and len(t) >= 2 and t[0] == key:
            return t
    return None


def _require_coord_xyz(coord: Optional[str]) -> Tuple[int, int, int, int]:
    if coord is None:
        state = _require_state()
        coord_hex = state.coord_hex
    else:
        coord_hex = normalize_hex_32(coord)
    coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
    return coord_to_xyz(coord_int)


def _load_event_from_input(*, event_json: Optional[str], event_file: Optional[str]) -> dict:
    if (event_json is None and event_file is None) or (event_json is not None and event_file is not None):
        typer.echo("Specify exactly one of --event-json or --event-file.", err=True)
        raise typer.Exit(code=2)

    raw = ""
    if event_json is not None:
        raw = event_json.strip()
    else:
        try:
            with open(event_file or "", "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except OSError as e:
            typer.echo(f"Failed to read event file: {e}", err=True)
            raise typer.Exit(code=1)

    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        typer.echo(f"Invalid JSON: {e}", err=True)
        raise typer.Exit(code=2)

    if not isinstance(event, dict):
        typer.echo("Event JSON must be an object.", err=True)
        raise typer.Exit(code=2)
    return event


def _parse_encrypted_payload_tag(event: dict) -> Tuple[str, bytes]:
    encrypted_tag = _get_tag_record(event, "encrypted")
    if not encrypted_tag or len(encrypted_tag) < 3:
        typer.echo("Event is missing required encrypted tag.", err=True)
        raise typer.Exit(code=2)
    alg = encrypted_tag[1]
    ct_b64 = encrypted_tag[2]
    if not isinstance(alg, str) or not isinstance(ct_b64, str):
        typer.echo("Encrypted tag must be [\"encrypted\", <alg>, <ciphertext_b64>].", err=True)
        raise typer.Exit(code=2)
    try:
        payload = base64.b64decode(ct_b64, validate=True)
    except Exception:
        typer.echo("Encrypted tag ciphertext must be valid base64.", err=True)
        raise typer.Exit(code=2)
    return alg, payload


DEFAULT_HYPERJUMP_RELAY = "wss://cyberspace.nostr1.com"
HYPERJUMP_KIND = 321
SECTOR_BITS = 30


def _nak_req_events(
    *,
    relay: str,
    kind: int,
    tags: Dict[str, List[str]],
    limit: int,
    timeout_seconds: int = 20,
    verbose: bool = False,
    until: int | None = None,
    since: int | None = None,
) -> List[dict]:
    """Fetch events from relay with optional timestamp pagination.
    
    Parameters
    ----------
    until : only fetch events with created_at <= this unix timestamp
    since : only fetch events with created_at >= this unix timestamp
    """
    cmd = ["nak", "req", "-q", "-k", str(kind), "-l", str(limit)]
    if until is not None:
        cmd.extend(["--until", str(until)])
    if since is not None:
        cmd.extend(["--since", str(since)])
    req_filter: Dict[str, object] = {"kinds": [kind], "limit": limit}
    if until is not None:
        req_filter["until"] = until
    if since is not None:
        req_filter["since"] = since
    for tag_name, values in tags.items():
        req_filter[f"#{tag_name}"] = values
        for v in values:
            cmd.extend(["--tag", f"{tag_name}={v}"])
    cmd.append(relay)
    if verbose:
        typer.echo("req_filter:")
        typer.echo(json.dumps(req_filter, separators=(",", ":"), ensure_ascii=False))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        typer.echo("`nak` is not installed or not available in PATH.", err=True)
        raise typer.Exit(code=1)
    except OSError as e:
        typer.echo(f"Nostr query failed to start: {e}", err=True)
        raise typer.Exit(code=1)
    except subprocess.TimeoutExpired:
        typer.echo(f"Nostr query timed out after {timeout_seconds}s.", err=True)
        return []
    if verbose:
        typer.echo(f"nak_exit_code: {proc.returncode}")
        typer.echo("nak_stdout:")
        stdout = proc.stdout or ""
        if stdout.strip():
            for ln in stdout.rstrip("\n").splitlines():
                typer.echo(ln)
        else:
            typer.echo("(empty)")
        typer.echo("nak_stderr:")
        stderr = proc.stderr or ""
        if stderr.strip():
            for ln in stderr.rstrip("\n").splitlines():
                typer.echo(ln)
        else:
            typer.echo("(empty)")

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if stderr:
            typer.echo(f"Nostr query failed: {stderr}", err=True)
        else:
            typer.echo("Nostr query failed.", err=True)
        raise typer.Exit(code=1)

    out: List[dict] = []
    for line in (proc.stdout or "").splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _axis_value_range(center: int, radius: int) -> List[str]:
    lo = max(0, center - radius)
    hi = center + radius
    return [str(v) for v in range(lo, hi + 1)]


def _direction_hint(current: int, target: int, axis: str) -> str:
    if target > current:
        return f"{axis}+ ({target - current})"
    if target < current:
        return f"{axis}- ({current - target})"
    return f"{axis}= (0)"


def _hyperjump_block_height_from_event(event: dict) -> Optional[int]:
    if _get_tag(event, "A") != "hyperjump":
        return None
    b_tag = _get_tag(event, "B")
    c_tag = _get_tag(event, "C")
    if not b_tag or not c_tag:
        return None
    try:
        normalize_hex_32(c_tag)
        h = int(str(b_tag), 10)
    except (ValueError, TypeError):
        return None
    if h < 0:
        return None
    return h


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
def lcaplot(
    axis: str = typer.Option(
        "x",
        "--axis",
        help="Axis to plot: x, y, or z (used for labeling and for picking the default --center from your current coord).",
    ),
    center: Optional[int] = typer.Option(
        None,
        "--center",
        help="Center axis value (u85 int). Default: current coord's axis value if available, else 0.",
    ),
    span: int = typer.Option(
        256,
        "--span",
        help="Half-window size: plots v in [center-span .. center+span] (clamped to axis range).",
    ),
    direction: str = typer.Option(
        "+1",
        "--direction",
        help="Adjacent direction to plot: +1 or -1 (plots lca_height(v, v±1)).",
    ),
    max_lca_height: int = typer.Option(
        17,
        "--max-lca-height",
        help="Reference max LCA height: draws a horizontal line at h and optionally overlays 2^h block boundaries.",
    ),
) -> None:
    """Open an interactive GUI plot of adjacent-hop LCA heights along one axis.

    This visualizes spikes in lca_height(v, v±1) which correspond to binary carry/borrow boundaries.

    Requires optional dependencies: pip install 'cyberspace-cli[visualizer]' (and you may need python3-tk).
    """

    axis_n = (axis or "x").strip().lower()
    if axis_n not in ("x", "y", "z"):
        typer.echo("--axis must be one of: x, y, z", err=True)
        raise typer.Exit(code=2)

    d = (direction or "+1").strip().lower()
    if d in ("+", "+1", "1"):
        dir_int = 1
    elif d in ("-", "-1"):
        dir_int = -1
    else:
        typer.echo("--direction must be +1 or -1", err=True)
        raise typer.Exit(code=2)

    # Best-effort: use current coord as a default center if available.
    st = load_state()
    curx = cury = curz = None
    if st:
        try:
            coord_int = int.from_bytes(bytes.fromhex(st.coord_hex), "big")
            curx, cury, curz, _plane = coord_to_xyz(coord_int)
        except Exception:
            curx = cury = curz = None

    if center is None:
        if axis_n == "x" and curx is not None:
            center = curx
        elif axis_n == "y" and cury is not None:
            center = cury
        elif axis_n == "z" and curz is not None:
            center = curz
        else:
            center = 0

    # Import lazily so heavy deps (tkinter/matplotlib) are only required when invoking this command.
    try:
        from cyberspace_cli.visualizer.lcaplot_app import run_app  # type: ignore
    except Exception as e:
        typer.echo("LCA plot dependencies are not installed.", err=True)
        typer.echo("Install extras: pip install 'cyberspace-cli[visualizer]'", err=True)
        typer.echo("System deps: you may also need python3-tk.", err=True)
        typer.echo(f"Import error: {e}", err=True)
        raise typer.Exit(code=1)

    try:
        run_app(
            axis=axis_n,
            center=int(center),
            span=int(span),
            direction=dir_int,
            max_lca_height=int(max_lca_height),
            current_x=curx,
            current_y=cury,
            current_z=curz,
        )
    except Exception as e:
        typer.echo(f"Failed to launch lcaplot: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("3d")
def three_d(
    coord: Optional[str] = typer.Option(
        None,
        "--coord",
        help="Override the current coord hex (256-bit; optional 0x prefix; leading zeros optional).",
    ),
    spawn_coord: Optional[str] = typer.Option(
        None,
        "--spawn-coord",
        help="Override the spawn coord hex (256-bit; optional 0x prefix; leading zeros optional).",
    ),
    sector: bool = typer.Option(
        False,
        "--sector",
        help="Render only the current sector cube (2^30 axis-units per sector). In this mode spawn is only rendered if it's in the same sector.",
    ),
    scale: Optional[float] = typer.Option(None, "--scale", help="Render scaling multiplier."),
    grid_lines: Optional[int] = typer.Option(None, "--grid-lines", help="Wireframe grid density."),
    earth_altitude_km: Optional[float] = typer.Option(
        None,
        "--earth-altitude-km",
        help="Default altitude above Earth's surface (km) used by the UI's 'View Earth' control.",
    ),
    show_spawn: bool = typer.Option(True, "--spawn/--no-spawn", help="Show spawn marker (default: on)."),
    show_current: bool = typer.Option(True, "--current/--no-current", help="Show current marker (default: on)."),
) -> None:
    """Open the 3D visualizer with your current coordinate (and spawn, if available)."""

    state = _require_state()

    # Current coordinate (from state unless overridden)
    cur_hex_norm = normalize_hex_32(coord or state.coord_hex)
    cur_hex = f"0x{cur_hex_norm}" if show_current else None

    # Spawn coordinate (best effort)
    spawn_hex_norm = ""
    if spawn_coord:
        spawn_hex_norm = normalize_hex_32(spawn_coord)
    else:
        label = (state.active_chain_label or "").strip()
        if label:
            try:
                events = chains.read_events(label)
            except Exception:
                events = []
            if events:
                c = _get_tag(events[0], "C")
                if c:
                    try:
                        spawn_hex_norm = normalize_hex_32(c)
                    except ValueError:
                        spawn_hex_norm = ""

    if not spawn_hex_norm:
        # Fallback: spawn is pubkey interpreted as a 256-bit coord.
        spawn_hex_norm = _coord_hex_from_pubkey_hex(state.pubkey_hex)

    spawn_hex = f"0x{spawn_hex_norm}" if show_spawn else None

    # Import lazily so heavy deps (matplotlib/numpy) are only required when invoking this command.
    try:
        from cyberspace_cli.visualizer.app import run_app  # type: ignore
    except Exception as e:
        typer.echo("3D visualizer dependencies are not installed.", err=True)
        typer.echo("Install extras: pip install 'cyberspace-cli[visualizer]'", err=True)
        typer.echo("System deps: you may also need python3-tk.", err=True)
        typer.echo(f"Import error: {e}", err=True)
        raise typer.Exit(code=1)

    effective_scale = float(scale) if scale is not None else (1.0 if sector else 0.5)
    effective_grid_lines = int(grid_lines) if grid_lines is not None else (6 if sector else 4)
    if earth_altitude_km is not None and earth_altitude_km < 0:
        typer.echo("--earth-altitude-km must be >= 0.", err=True)
        raise typer.Exit(code=2)
    effective_earth_altitude_km = float(earth_altitude_km) if earth_altitude_km is not None else 12000.0

    try:
        run_app(
            current_coord_hex=cur_hex,
            spawn_coord_hex=spawn_hex,
            scale=effective_scale,
            grid_lines=effective_grid_lines,
            earth_altitude_km=effective_earth_altitude_km,
            mode=("sector" if sector else "dataspace"),
        )
    except Exception as e:
        typer.echo(f"Failed to launch visualizer: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def gps(
    coord: Optional[str] = typer.Option(
        None,
        "--coord",
        help="Cyberspace coord256 hex to convert to GPS (lat/lon/alt).",
    ),
    at: Optional[str] = typer.Argument(
        None,
        help="Either 'lat,lon' (recommended, works with negative lon) or omit and use --lat/--lon.",
    ),
    lat: Optional[str] = typer.Option(None, "--lat", help="Latitude (alternative to 'lat,lon')."),
    lon: Optional[str] = typer.Option(None, "--lon", help="Longitude (alternative to 'lat,lon')."),
    altitude_wgs84_m: Optional[str] = typer.Option(
        None,
        "--altitude-wgs84",
        "--alt-wgs84",
        "--alt",
        help="Altitude in meters above the WGS84 ellipsoid (GPS-native reference).",
    ),
    altitude_sealevel_m: Optional[str] = typer.Option(
        None,
        "--altitude-sealevel",
        "--alt-sealevel",
        help="Altitude in meters above mean sea level (MSL / orthometric height).",
    ),
    geoid_offset_m: Optional[str] = typer.Option(
        None,
        "--geoid-offset-m",
        help="Geoid separation N in meters used with sea-level altitude (h = H + N).",
    ),
    geoid_model: Optional[str] = typer.Option(
        None,
        "--geoid-model",
        help="Geoid model for auto sea-level conversion (egm2008-2_5 default, or egm2008-1).",
    ),
    clamp_to_surface: Optional[bool] = typer.Option(
        None,
        "--clamp/--no-clamp",
        help="Clamp altitude to WGS84 surface. If altitude is provided and this flag is omitted, --no-clamp is implied.",
    ),
) -> None:
    """Convert between GPS and dataspace coord256.

    Note: many CLIs treat a negative positional like `-122.4194` as an option flag.
    To avoid that, this command supports either:
    - `cyberspace gps 37.7749,-122.4194`
    - `cyberspace gps --lat 37.7749 --lon -122.4194`
    - `cyberspace gps 37.7749,-122.4194 --altitude-wgs84 123.45`
    - `cyberspace gps 37.7749,-122.4194 --altitude-sealevel 95.0`
    - `cyberspace gps 37.7749,-122.4194 --altitude-sealevel 95.0 --geoid-offset-m 30.5`
    - `cyberspace gps --coord 0x<coord256>`

    Altitude references:
    - `--altitude-wgs84` (`--alt`) is ellipsoid height `h`.
    - `--altitude-sealevel` is orthometric/MSL height `H`; if `--geoid-offset-m` is omitted,
      geoid separation `N` is auto-derived from `--geoid-model` (or config), using `h = H + N`.
    - If an altitude option is provided and `--clamp/--no-clamp` is omitted, `--no-clamp` is implied.
    """

    if coord is not None:
        if at is not None or lat is not None or lon is not None:
            typer.echo("Use either --coord OR ('lat,lon' / --lat --lon).", err=True)
            raise typer.Exit(code=2)
        if altitude_wgs84_m is not None or altitude_sealevel_m is not None or geoid_offset_m is not None or geoid_model is not None or clamp_to_surface is not None:
            typer.echo("--altitude-* / --geoid-* / --clamp only apply when converting GPS -> coord.", err=True)
            raise typer.Exit(code=2)

        try:
            coord_hex = normalize_hex_32(coord)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e

        coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
        x, y, z, plane = coord_to_xyz(coord_int)
        lat_deg, lon_deg, alt_m, _plane = dataspace_coord_to_gps(coord_int)

        typer.echo(f"coord: 0x{coord_hex}")
        typer.echo(f"xyz(u85): x={x} y={y} z={z} plane={plane} {_plane_label(plane)}")
        typer.echo(f"gps: lat={lat_deg:.10f} lon={lon_deg:.10f} alt_m={alt_m:.3f}")
        return

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
    alt_wgs84 = _parse_decimal_option(altitude_wgs84_m, "--altitude-wgs84/--alt")
    alt_sealevel = _parse_decimal_option(altitude_sealevel_m, "--altitude-sealevel")
    geoid_offset = _parse_decimal_option(geoid_offset_m, "--geoid-offset-m")

    if alt_wgs84 is not None and alt_sealevel is not None:
        typer.echo("Use either --altitude-wgs84 OR --altitude-sealevel (not both).", err=True)
        raise typer.Exit(code=2)

    if geoid_offset is not None and alt_sealevel is None:
        typer.echo("--geoid-offset-m requires --altitude-sealevel.", err=True)
        raise typer.Exit(code=2)

    if geoid_model is not None and alt_sealevel is None:
        typer.echo("--geoid-model requires --altitude-sealevel.", err=True)
        raise typer.Exit(code=2)

    has_altitude = alt_wgs84 is not None or alt_sealevel is not None
    if has_altitude and clamp_to_surface is True:
        typer.echo("Cannot use --clamp with altitude options. Omit --clamp or use --no-clamp.", err=True)
        raise typer.Exit(code=2)
    effective_clamp = bool(clamp_to_surface) if clamp_to_surface is not None else (False if has_altitude else True)

    if alt_sealevel is not None and geoid_offset is not None:
        altitude_input_m = alt_sealevel + geoid_offset
    elif alt_sealevel is not None:
        cfg = load_config()
        model_raw = geoid_model or cfg.gps_geoid_model or DEFAULT_GEOID_MODEL
        try:
            model_n = normalize_geoid_model(model_raw)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        try:
            n_m = Decimal(
                str(
                    geoid_undulation_m(
                        float(lat_s),
                        float(lon_s),
                        model=model_n,
                    )
                )
            )
        except GeoidError as e:
            searched = "\n".join(str(p) for p in candidate_model_paths(model_n))
            typer.echo(str(e), err=True)
            typer.echo(
                f"Install '{model_n}.pgm' (GeographicLib geoid data) into one of these paths:\n{searched}",
                err=True,
            )
            raise typer.Exit(code=1)
        altitude_input_m = alt_sealevel + n_m
    elif alt_wgs84 is not None:
        altitude_input_m = alt_wgs84
    else:
        altitude_input_m = Decimal(0)

    coord_int = gps_to_dataspace_coord(
        lat_s,
        lon_s,
        str(altitude_input_m),
        clamp_to_surface=effective_clamp,
    )
    coord_hex = coord_int.to_bytes(32, "big").hex()
    x, y, z, plane = coord_to_xyz(coord_int)

    typer.echo(f"coord: 0x{coord_hex}")
    typer.echo(f"xyz(u85): x={x} y={y} z={z} plane={plane} {_plane_label(plane)}")


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
    typer.echo(f"  xyz:   x={x1} y={y1} z={z1} plane={plane} {_plane_label(plane)}")
    typer.echo("to:")
    typer.echo(f"  coord: 0x{tc_hex}")
    typer.echo(f"  xyz:   x={x2} y={y2} z={z2} plane={plane} {_plane_label(plane)}")

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
            root = compute_axis_cantor(v1, v2, max_compute_height=max_compute_height)

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
def encrypt(
    text: Optional[str] = typer.Option(None, "--text", help="Plaintext content to encrypt."),
    file: Optional[str] = typer.Option(None, "--file", help="Path to plaintext file to encrypt."),
    height: int = typer.Option(
        ...,
        "--height",
        min=0,
        help="Aligned region height used for key derivation (higher = larger discovery radius).",
    ),
    coord: Optional[str] = typer.Option(
        None,
        "--coord",
        help="Override coordinate used for key derivation (defaults to current coord from local state).",
    ),
    publish_height: bool = typer.Option(
        False,
        "--publish-height",
        help="Publish h tag in the encrypted event (disabled by default).",
    ),
    hint: Optional[str] = typer.Option(
        None,
        "--hint",
        help="Optional plaintext hint stored in the event content field.",
    ),
    kind: int = typer.Option(33330, "--kind", help="Nostr event kind for encrypted content (default: 33330)."),
) -> None:
    """Encrypt text/file content into a location-encrypted nostr-style event."""
    if (text is None and file is None) or (text is not None and file is not None):
        typer.echo("Specify exactly one of --text or --file.", err=True)
        raise typer.Exit(code=2)

    state = _require_state()
    x, y, z, _plane = _require_coord_xyz(coord)

    plaintext: bytes
    if text is not None:
        plaintext = text.encode("utf-8")
    else:
        try:
            with open(file or "", "rb") as f:
                plaintext = f.read()
        except OSError as e:
            typer.echo(f"Failed to read file: {e}", err=True)
            raise typer.Exit(code=1)

    try:
        material = derive_region_key_material_for_height(x=x, y=y, z=z, height=height, max_compute_height=height)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)

    payload = encrypt_with_location_key(
        plaintext,
        location_decryption_key=material.location_decryption_key,
        nonce=secrets.token_bytes(12),
    )

    event = make_encrypted_content_event(
        pubkey_hex=state.pubkey_hex,
        created_at=int(time.time()),
        lookup_id_hex=material.lookup_id_hex,
        algorithm="aes-256-gcm",
        ciphertext_b64=base64.b64encode(payload).decode("ascii"),
        height_hint=(height if publish_height else None),
        content=(hint or ""),
        kind=kind,
    )
    typer.echo(json.dumps(event, separators=(",", ":"), ensure_ascii=False))


@app.command()
def decrypt(
    event_json: Optional[str] = typer.Option(None, "--event-json", help="Raw nostr event JSON object."),
    event_file: Optional[str] = typer.Option(None, "--event-file", help="Path to file containing a nostr event JSON object."),
    height: Optional[int] = typer.Option(
        None,
        "--height",
        min=0,
        help="Override height for key derivation. If omitted, uses h tag or scans 0..--max-height.",
    ),
    max_height: int = typer.Option(
        DEFAULT_SCAN_MAX_HEIGHT,
        "--max-height",
        min=0,
        help="Max height to scan when --height is omitted and event has no valid h tag.",
    ),
    coord: Optional[str] = typer.Option(
        None,
        "--coord",
        help="Override coordinate used for key derivation (defaults to current coord from local state).",
    ),
) -> None:
    """Decrypt a location-encrypted nostr event using local/current coordinate key material."""
    event = _load_event_from_input(event_json=event_json, event_file=event_file)
    d_tag = _get_tag(event, "d")
    if not d_tag:
        typer.echo("Event is missing required d tag.", err=True)
        raise typer.Exit(code=2)

    x, y, z, _plane = _require_coord_xyz(coord)

    candidate_heights: List[int] = []
    if height is not None:
        candidate_heights = [height]
    else:
        h_tag = _get_tag(event, "h")
        if h_tag is not None:
            try:
                h_val = int(h_tag, 10)
                if h_val >= 0:
                    candidate_heights.append(h_val)
            except ValueError:
                pass
        candidate_heights.extend([h for h in range(0, max_height + 1) if h not in candidate_heights])

    chosen_height: Optional[int] = None
    chosen_key: Optional[bytes] = None
    for h in candidate_heights:
        try:
            material = derive_region_key_material_for_height(x=x, y=y, z=z, height=h, max_compute_height=h)
        except ValueError:
            continue
        if material.lookup_id_hex == d_tag:
            chosen_height = h
            chosen_key = material.location_decryption_key
            break

    if chosen_height is None or chosen_key is None:
        typer.echo("No matching lookup_id found for this event at the current coordinate.", err=True)
        raise typer.Exit(code=1)

    alg, payload = _parse_encrypted_payload_tag(event)
    if alg != "aes-256-gcm":
        typer.echo(f"Unsupported encryption algorithm: {alg}", err=True)
        raise typer.Exit(code=2)
    try:
        plaintext = decrypt_with_location_key(payload, location_decryption_key=chosen_key)
    except Exception as e:
        typer.echo(f"Decryption failed: {e}", err=True)
        raise typer.Exit(code=1)
    try:
        decoded = plaintext.decode("utf-8")
    except UnicodeDecodeError:
        decoded = ""

    typer.echo(f"height: {chosen_height}")
    typer.echo(f"lookup_id: {d_tag}")
    if decoded:
        typer.echo(decoded)
    else:
        typer.echo(base64.b64encode(plaintext).decode("ascii"))


@app.command()
def scan(
    min_height: int = typer.Option(1, "--min-height", min=0, help="First height to include."),
    max_height: int = typer.Option(
        DEFAULT_SCAN_MAX_HEIGHT,
        "--max-height",
        min=0,
        help="Last height to include (inclusive).",
    ),
    coord: Optional[str] = typer.Option(
        None,
        "--coord",
        help="Override coordinate used for key derivation (defaults to current coord from local state).",
    ),
    events_file: Optional[str] = typer.Option(
        None,
        "--events-file",
        help="Optional JSONL file of nostr events. Use '-' to read JSONL from stdin.",
    ),
) -> None:
    """Scan heights for lookup IDs and optionally match against encrypted events."""
    if max_height < min_height:
        typer.echo("--max-height must be >= --min-height.", err=True)
        raise typer.Exit(code=2)

    x, y, z, _plane = _require_coord_xyz(coord)
    materials = derive_region_key_material_scan(
        x=x,
        y=y,
        z=z,
        min_height=min_height,
        max_height=max_height,
        max_compute_height=max_height,
    )

    events: List[dict] = []
    if events_file:
        raw_lines: List[str] = []
        if events_file == "-":
            raw = typer.get_text_stream("stdin").read()
            raw_lines = [ln for ln in raw.splitlines() if ln.strip()]
        else:
            try:
                with open(events_file, "r", encoding="utf-8") as f:
                    raw_lines = [ln for ln in f.read().splitlines() if ln.strip()]
            except OSError as e:
                typer.echo(f"Failed to read events file: {e}", err=True)
                raise typer.Exit(code=1)

        for ln in raw_lines:
            try:
                ev = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                events.append(ev)

    index: dict[str, List[dict]] = {}
    for ev in events:
        d = _get_tag(ev, "d")
        if not d:
            continue
        index.setdefault(d, []).append(ev)

    for m in materials:
        matches = index.get(m.lookup_id_hex, [])
        typer.echo(f"h={m.height} d={m.lookup_id_hex} matches={len(matches)}")
        for ev in matches:
            typer.echo(f"  id={ev.get('id','')} pubkey={ev.get('pubkey','')} kind={ev.get('kind','')}")

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


def _load_hyperjump_cache() -> List[dict]:
    """Load locally cached hyperjump events from the JSONL file."""
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


def _dedup_hyperjumps(events: List[dict]) -> Dict[str, dict]:
    """Deduplicate hyperjump events by coordinate, keeping the most recent."""
    by_coord: Dict[str, dict] = {}
    for ev in events:
        c = _get_tag(ev, "C")
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


def _rank_hyperjumps(
    by_coord: Dict[str, dict],
    sx: int, sy: int, sz: int,
    cx: int, cy: int, cz: int,
) -> List[Tuple[int, int, str, dict, Tuple[int, int, int, int]]]:
    """Rank hyperjumps by sector distance then axis distance from current position."""
    ranked: List[Tuple[int, int, str, dict, Tuple[int, int, int, int]]] = []
    for coord_hex, ev in by_coord.items():
        coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
        x, y, z, plane = coord_to_xyz(coord_int)
        hsx = x >> SECTOR_BITS
        hsy = y >> SECTOR_BITS
        hsz = z >> SECTOR_BITS
        sector_dist = abs(hsx - sx) + abs(hsy - sy) + abs(hsz - sz)
        axis_dist = abs(x - cx) + abs(y - cy) + abs(z - cz)
        ranked.append((sector_dist, axis_dist, coord_hex, ev, (x, y, z, plane)))
    ranked.sort(key=lambda it: (it[0], it[1], it[2]))
    return ranked


def _print_ranked_hyperjumps(
    ranked: List[Tuple[int, int, str, dict, Tuple[int, int, int, int]]],
    cur_coord_hex: str,
    cx: int, cy: int, cz: int, cplane: int,
    search_radius: Optional[int] = None,
) -> None:
    """Print ranked hyperjump results in the standard output format."""
    typer.echo(f"current: 0x{cur_coord_hex}")
    typer.echo(f"x={cx}")
    typer.echo(f"y={cy}")
    typer.echo(f"z={cz}")
    typer.echo(f"plane={cplane} {_plane_label(cplane)}")
    if search_radius is not None:
        typer.echo(f"search_radius={search_radius}")
    typer.echo(f"nearby_hyperjumps: {len(ranked)}")

    for i, (sector_dist, _axis_dist, coord_hex, ev, (x, y, z, plane)) in enumerate(ranked, start=1):
        hsx = x >> SECTOR_BITS
        hsy = y >> SECTOR_BITS
        hsz = z >> SECTOR_BITS
        b_tag = _get_tag(ev, "B") or "?"
        event_id = str(ev.get("id", ""))
        dir_hint = " ".join([_direction_hint(cx, x, "x"), _direction_hint(cy, y, "y"), _direction_hint(cz, z, "z")])
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


@hyperjump_app.command("sync")
def hyperjump_sync(
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
    """Download all hyperjump anchor events from the relay and cache locally.

    Paginates through the relay in timestamp-ordered batches to fetch ALL events,
    not just the first batch. Creates a local JSONL file at
    ~/.cyberspace/hyperjump_cache.jsonl so that `hyperjump nearest --cache`
    can search instantly without relay queries.

    Use --resume to append new events instead of overwriting existing cache.
    Re-run to refresh the cache with the latest events.
    """
    cache = hyperjump_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)

    # If resuming, load existing events and find the oldest block height
    existing_ids: set = set()
    existing_events: list = []
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

    # Helper to extract B tag from event
    def get_block_height(ev: dict) -> int:
        for tag in ev.get("tags", []):
            if tag[0] == "B":
                try:
                    return int(tag[1])
                except (ValueError, IndexError):
                    pass
        return -1

    # Find the oldest timestamp we've already cached (for resume)
    cursor_until: int | None = None
    if resume and existing_events:
        oldest_ts = min((ev.get("created_at", 0) for ev in existing_events if ev.get("created_at")), default=0)
        if oldest_ts > 0:
            cursor_until = oldest_ts - 1
            min_b = min((get_block_height(ev) for ev in existing_events if get_block_height(ev) >= 0), default=None)
            max_b = max((get_block_height(ev) for ev in existing_events if get_block_height(ev) >= 0), default=None)
            typer.echo(f"  Resuming: fetching events older than timestamp {cursor_until}")
            if min_b is not None and max_b is not None:
                typer.echo(f"  Current cache covers blocks {min_b} to {max_b}")

    while True:
        batch_num += 1
        batch = _nak_req_events(
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
        oldest_ts: int | None = None
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
        typer.echo(
            f"  Batch {batch_num}: {len(batch)} event(s), "
            f"{new_in_batch} new — {len(all_events)} total unique so far"
        )

        # If we got fewer than the limit, we've exhausted the relay
        if len(batch) < limit:
            break

        # If no new events in this batch, we're cycling — done
        if new_in_batch == 0:
            break

        # Move cursor to before the oldest timestamp in this batch
        if oldest_ts is not None:
            cursor_until = oldest_ts - 1
        else:
            break

    if not all_events:
        typer.echo("No hyperjump events found on the relay.")
        return

    # Deduplicate by coordinate (keep most recent per coord).
    by_coord = _dedup_hyperjumps(all_events)

    with open(cache, "w") as f:
        for ev in by_coord.values():
            f.write(json.dumps(ev, separators=(",", ":"), ensure_ascii=False) + "\n")

    # Report block range covered
    if all_events:
        block_heights = [bh for ev in all_events if (bh := get_block_height(ev)) >= 0]
        if block_heights:
            typer.echo(f"Block range: {min(block_heights)} to {max(block_heights)}")
    
    typer.echo(f"Cached {len(by_coord)} unique hyperjump(s) to {cache}")
    typer.echo(f"(from {total_fetched} fetched + {len(existing_events)} previously cached)")
    typer.echo(f"Estimated remaining: ~{max(0, 940000 - len(by_coord)):,} events")


@hyperjump_app.command("nearest")
def hyperjump_nearest(
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
        help="Coordinate override used to calculate nearest hyperjumps (defaults to current coord).",
    ),
    expand: bool = typer.Option(
        False,
        "--expand",
        "-e",
        help="Progressively expand search radius until a hyperjump is found (overrides --radius).",
    ),
    cache: bool = typer.Option(
        False,
        "--cache",
        "-c",
        help="Search the local cache instead of querying the relay. Run `hyperjump sync` first.",
    ),
    count: int = typer.Option(
        0,
        "--count",
        "-n",
        min=0,
        help="Limit display to the N nearest results (0 = show all).",
    ),
) -> None:
    """Find nearby hyperjumps and print directions from the current position.

    By default, queries the relay for hyperjumps within --radius sectors.
    Use --expand to automatically widen the search until at least one
    hyperjump is found. Use --cache to search the local cache (created by
    `hyperjump sync`) for instant results without relay queries.
    """
    state = load_state()
    default_plane = 0
    state_coord_int = None
    if state is not None:
        state_coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
        _, _, _, default_plane = coord_to_xyz(state_coord_int)

    if coord is None:
        if state is None or state_coord_int is None:
            typer.echo("No local state found. Run `cyberspace spawn` first or provide --coord.", err=True)
            raise typer.Exit(code=1)
        cur_coord_hex = state.coord_hex
        cur_coord_int = state_coord_int
        cx, cy, cz, cplane = coord_to_xyz(cur_coord_int)
    else:
        try:
            parsed = parse_destination_xyz_or_coord(coord, default_plane=default_plane)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        cx, cy, cz, cplane = parsed.x, parsed.y, parsed.z, parsed.plane
        cur_coord_hex = _coord_hex_from_xyz(cx, cy, cz, cplane)

    sx = cx >> SECTOR_BITS
    sy = cy >> SECTOR_BITS
    sz = cz >> SECTOR_BITS

    # ---------- Cache mode: search local file, no relay queries ----------
    if cache:
        cached_events = _load_hyperjump_cache()
        if not cached_events:
            typer.echo(
                "No local cache found. Run `cyberspace hyperjump sync` first.",
                err=True,
            )
            raise typer.Exit(code=1)
        by_coord = _dedup_hyperjumps(cached_events)
        ranked = _rank_hyperjumps(by_coord, sx, sy, sz, cx, cy, cz)
        if not ranked:
            typer.echo("No hyperjumps found in cache.")
            return
        if count > 0:
            ranked = ranked[:count]
        _print_ranked_hyperjumps(ranked, cur_coord_hex, cx, cy, cz, cplane)
        return

    # ---------- Expand mode: progressive radius expansion ----------
    if expand:
        # Build the radius schedule: start small, grow until we find something.
        radii = [r for r in _EXPAND_RADII if r <= (MAX_TAG_VALUES // 3 - 1) // 2]
        by_coord: Dict[str, dict] = {}
        final_radius = 0
        for r in radii:
            if verbose:
                typer.echo(f"Searching radius={r} ...")
            events = _nak_req_events(
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
            by_coord = _dedup_hyperjumps(events)
            final_radius = r
            if by_coord:
                break
        if not by_coord:
            typer.echo(
                f"No hyperjumps found after expanding to radius={final_radius}. "
                "Try `hyperjump sync` + `hyperjump nearest --cache` for a global search."
            )
            return
        ranked = _rank_hyperjumps(by_coord, sx, sy, sz, cx, cy, cz)
        if count > 0:
            ranked = ranked[:count]
        _print_ranked_hyperjumps(ranked, cur_coord_hex, cx, cy, cz, cplane, search_radius=final_radius)
        return

    # ---------- Fixed-radius mode (original behaviour) ----------
    # Clamp radius so we don't exceed relay tag-value limits.
    max_per_axis = MAX_TAG_VALUES // 3
    effective_radius = min(radius, (max_per_axis - 1) // 2)
    if effective_radius != radius and verbose:
        typer.echo(f"Clamped radius from {radius} to {effective_radius} (relay tag limit).")

    events = _nak_req_events(
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

    by_coord = _dedup_hyperjumps(events)

    if not by_coord:
        typer.echo("No nearby hyperjumps found.")
        if not expand:
            typer.echo("Hint: try --expand to progressively widen the search, or --cache with `hyperjump sync`.")
        return

    ranked = _rank_hyperjumps(by_coord, sx, sy, sz, cx, cy, cz)
    if count > 0:
        ranked = ranked[:count]
    _print_ranked_hyperjumps(ranked, cur_coord_hex, cx, cy, cz, cplane, search_radius=effective_radius)


@app.command()
def move(
    to: str = typer.Option(
        None,
        "--to",
        help="Destination as x,y,z[,plane] OR 256-bit coord hex (0x...; leading zeros optional).",
    ),
    by: str = typer.Option(
        None,
        "--by",
        help="Relative dx,dy,dz as comma-separated ints. For plane switches, use 0,0,0,<plane> (plane is 0 or 1).",
    ),
    toward: str = typer.Option(
        None,
        "--toward",
        help="Continuously make hops toward a destination (x,y,z[,plane] or 256-bit coord hex).",
    ),
    max_lca_height: Optional[int] = typer.Option(
        None,
        "--max-lca-height",
        help="Refuse moves if any axis LCA height exceeds this (default: config value; see `cyberspace config show`).",
    ),
    max_hops: int = typer.Option(
        0,
        "--max-hops",
        help="Stop after this many hops when using --toward (0 means until reached).",
    ),
    hyperjump: bool = typer.Option(
        False,
        "--hyperjump",
        help="Publish a hyperjump movement event (A=hyperjump) after validating destination as a known hyperjump anchor.",
    ),
    hyperjump_relay: str = typer.Option(
        DEFAULT_HYPERJUMP_RELAY,
        "--hyperjump-relay",
        help="Relay URL used to validate hyperjump destinations.",
    ),
    hyperjump_query_limit: int = typer.Option(
        25,
        "--hyperjump-query-limit",
        min=1,
        help="Max anchor events to query when validating a hyperjump destination.",
    ),
    sidestep: bool = typer.Option(
        False,
        "--sidestep",
        help="Use Merkle sidestep proof instead of Cantor hop proof. Required for LCA heights above Cantor capacity.",
    ),
    exit_hyperjump: bool = typer.Option(
        False,
        "--exit-hyperjump",
        help="Allow a normal hop while on the hyperjump system (explicitly exits the hyperjump flow).",
    ),
) -> None:
    """Move locally by appending a hop, sidestep, or hyperjump event to the active chain."""
    if isinstance(hyperjump, OptionInfo):
        hyperjump = False
    if isinstance(hyperjump_relay, OptionInfo):
        hyperjump_relay = DEFAULT_HYPERJUMP_RELAY
    if isinstance(hyperjump_query_limit, OptionInfo):
        hyperjump_query_limit = 25
    if isinstance(sidestep, OptionInfo):
        sidestep = False
    if isinstance(exit_hyperjump, OptionInfo):
        exit_hyperjump = False
    if sidestep and hyperjump:
        typer.echo("--sidestep cannot be combined with --hyperjump.", err=True)
        raise typer.Exit(code=2)
    state = _require_state()
    label = _require_active_chain_label(state)

    cfg = load_config()
    effective_max_lca_height = int(max_lca_height) if max_lca_height is not None else int(cfg.default_max_lca_height)

    events = chains.read_events(label)
    if not events:
        typer.echo(f"Chain is empty: {label}", err=True)
        raise typer.Exit(code=1)

    genesis_id = events[0]["id"]
    prev_event_id = events[-1]["id"]

    prev_coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x1, y1, z1, plane1 = coord_to_xyz(prev_coord_int)

    # If no explicit destination is provided, fall back to the current target.
    if to is None and by is None and toward is None:
        t = targets.get_current_target(state)
        if t and t.get("coord_hex"):
            toward = f"0x{t['coord_hex']}"
        else:
            typer.echo(
                "Specify exactly one of --to, --by, or --toward (or set a target with `cyberspace target <coord>`).",
                err=True,
            )
            raise typer.Exit(code=2)

    if sum(v is not None for v in (to, by, toward)) != 1:
        typer.echo("Specify exactly one of --to, --by, or --toward.", err=True)
        raise typer.Exit(code=2)
    if hyperjump and by is not None:
        typer.echo("--hyperjump is only supported with --to or --toward destinations.", err=True)
        raise typer.Exit(code=2)
    if hyperjump and exit_hyperjump:
        typer.echo("--exit-hyperjump cannot be combined with --hyperjump.", err=True)
        raise typer.Exit(code=2)

    in_hyperjump_system = _hyperjump_block_height_from_event(events[-1]) is not None
    if in_hyperjump_system and not hyperjump and not exit_hyperjump:
        typer.echo(
            "You are on the hyperjump system. Normal move commands are blocked unless you pass --exit-hyperjump.",
            err=True,
        )
        raise typer.Exit(code=2)

    def _plane_name(p: int) -> str:
        return "dataspace" if p == 0 else "ideaspace"

    def _do_single_hop(
        *,
        x2: int,
        y2: int,
        z2: int,
        plane2: int,
        max_compute_height: int,
        hyperjump_to_height: Optional[str] = None,
        use_sidestep: bool = False,
    ):
        nonlocal x1, y1, z1, plane1, prev_event_id

        if plane2 not in (0, 1):
            typer.echo("Destination plane must be 0 (dataspace) or 1 (ideaspace).", err=True)
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
        proof = None
        sidestep_proof = None

        if hyperjump_to_height is None:
            # Guard against absurd hops: LCA height drives O(2^h) compute.
            hx = find_lca_height(x1, x2)
            hy = find_lca_height(y1, y2)
            hz = find_lca_height(z1, z2)

            if use_sidestep:
                # Sidestep: use Merkle proofs on all axes (no max_compute_height limit
                # because streaming Merkle only needs O(h) memory, not O(2^h)).
                try:
                    sidestep_proof = compute_sidestep_proof(
                        x1,
                        y1,
                        z1,
                        x2,
                        y2,
                        z2,
                        plane=plane2,
                        previous_event_id_hex=prev_event_id,
                    )
                except ValueError as e:
                    typer.echo(f"Failed to compute sidestep proof: {e}", err=True)
                    raise typer.Exit(code=2)
            else:
                if max(hx, hy, hz) > max_compute_height:
                    typer.echo(
                        "Move is too large for a single hop. "
                        f"LCA heights: X={hx} Y={hy} Z={hz} (max={max(hx, hy, hz)}), "
                        f"limit={max_compute_height}. "
                        "Use --sidestep for Merkle proof, or raise --max-lca-height for an expensive Cantor hop.",
                        err=True,
                    )
                    raise typer.Exit(code=2)

                try:
                    proof = compute_hop_proof(
                        x1,
                        y1,
                        z1,
                        x2,
                        y2,
                        z2,
                        plane=plane2,
                        previous_event_id_hex=prev_event_id,
                        max_compute_height=max_compute_height,
                    )
                except ValueError as e:
                    typer.echo(f"Failed to compute movement proof: {e}", err=True)
                    raise typer.Exit(code=2)

        created_at = int(time.time())
        if sidestep_proof is not None:
            # Encode Merkle roots and inclusion proofs as colon-separated hex
            merkle_roots_hex = ":".join(
                root.hex() for root in (sidestep_proof.merkle_x, sidestep_proof.merkle_y, sidestep_proof.merkle_z)
            )
            merkle_proofs_hex = ":".join(
                "".join(s.hex() for s in sidestep_proof.inclusion_proofs[axis])
                for axis in ("x", "y", "z")
            )
            movement_event = make_sidestep_event(
                pubkey_hex=state.pubkey_hex,
                created_at=created_at,
                genesis_event_id=genesis_id,
                previous_event_id=prev_event_id,
                prev_coord_hex=state.coord_hex,
                coord_hex=coord_hex,
                proof_hash_hex=sidestep_proof.proof_hash,
                merkle_roots_hex=merkle_roots_hex,
                merkle_proofs_hex=merkle_proofs_hex,
                lca_heights=sidestep_proof.lca_heights,
            )
        elif hyperjump_to_height is None:
            movement_event = make_hop_event(
                pubkey_hex=state.pubkey_hex,
                created_at=created_at,
                genesis_event_id=genesis_id,
                previous_event_id=prev_event_id,
                prev_coord_hex=state.coord_hex,
                coord_hex=coord_hex,
                proof_hash_hex=proof.proof_hash,
            )
        else:
            movement_event = make_hyperjump_event(
                pubkey_hex=state.pubkey_hex,
                created_at=created_at,
                genesis_event_id=genesis_id,
                previous_event_id=prev_event_id,
                prev_coord_hex=state.coord_hex,
                coord_hex=coord_hex,
                to_height=hyperjump_to_height,
            )
        chains.append_event(label, movement_event)

        state.coord_hex = coord_hex
        save_state(state)

        prev_event_id = movement_event["id"]
        x1, y1, z1, plane1 = x2, y2, z2, plane2

        typer.echo(f"Moved. chain={label} len={chains.chain_length(label)}")
        typer.echo(f"coord: 0x{coord_hex}")
        if sidestep_proof is not None:
            typer.echo(f"action: sidestep")
            typer.echo(f"proof: {sidestep_proof.proof_hash}")
            typer.echo(f"terrain_k: {sidestep_proof.terrain_k}")
            typer.echo(f"lca_heights: X={sidestep_proof.lca_heights[0]} Y={sidestep_proof.lca_heights[1]} Z={sidestep_proof.lca_heights[2]}")
        elif proof is not None:
            typer.echo(f"proof: {proof.proof_hash}")
            typer.echo(f"terrain_k: {proof.terrain_k}")
        else:
            typer.echo(f"action: hyperjump")
            typer.echo(f"B: {hyperjump_to_height}")

        return sidestep_proof or proof

    def _resolve_hyperjump_height_for_destination(*, x: int, y: int, z: int, plane: int) -> Optional[str]:
        if not hyperjump:
            return None
        dest_coord_hex = _coord_hex_from_xyz(x, y, z, plane)
        anchors = _nak_req_events(
            relay=hyperjump_relay,
            kind=HYPERJUMP_KIND,
            tags={"C": [dest_coord_hex]},
            limit=hyperjump_query_limit,
        )
        if not anchors:
            typer.echo(
                f"Destination is not a known hyperjump coordinate on relay {hyperjump_relay}: 0x{dest_coord_hex}",
                err=True,
            )
            raise typer.Exit(code=2)
        anchor = anchors[0]
        b_tag = _get_tag(anchor, "B")
        if not b_tag:
            typer.echo("Matched hyperjump anchor event is missing required B tag.", err=True)
            raise typer.Exit(code=2)
        return b_tag

    if toward is not None:
        try:
            target = parse_destination_xyz_or_coord(toward, default_plane=plane1)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e

        tx, ty, tz, target_plane = target.x, target.y, target.z, target.plane
        hyperjump_to_height = _resolve_hyperjump_height_for_destination(
            x=tx,
            y=ty,
            z=tz,
            plane=target_plane,
        )

        hops = 0
        try:
            while True:
                # Only the *final* state must match the target plane.
                if (x1, y1, z1, plane1) == (tx, ty, tz, target_plane):
                    typer.echo("Arrived.")
                    typer.echo(f"coord: 0x{state.coord_hex}")
                    return

                if max_hops and hops >= max_hops:
                    typer.echo(f"Stopped after max_hops={max_hops}.")
                    typer.echo(f"coord: 0x{state.coord_hex}")
                    return

                # If we've reached the target xyz but we're in the wrong plane, the last hop is a plane switch.
                if (x1, y1, z1) == (tx, ty, tz) and plane1 != target_plane:
                    final_hyperjump = hyperjump_to_height is not None
                    _do_single_hop(
                        x2=x1,
                        y2=y1,
                        z2=z1,
                        plane2=target_plane,
                        max_compute_height=effective_max_lca_height,
                        hyperjump_to_height=hyperjump_to_height if final_hyperjump else None,
                        use_sidestep=sidestep,
                    )
                    hops += 1

                    typer.echo(f"hop: {hops}")
                    typer.echo(f"x={x1}")
                    typer.echo(f"y={y1}")
                    typer.echo(f"z={z1}")
                    typer.echo(f"plane={plane1} {_plane_name(plane1)}")
                    continue

                # When sidestep is enabled, allow boundary crossings up to this
                # ceiling.  Merkle streaming at h=25 takes ~50s per axis which is
                # a practical upper bound for interactive use.
                # With the parallel C-accelerated Merkle engine, h33 takes ~15min
                # on a 16-core system (~10M leaves/sec). h36 takes ~1.8 hours.
                # h40 ~= 30 hours. Beyond 40 is impractical on consumer hardware.
                SIDESTEP_BOUNDARY_CEILING = 40

                def _axis_step(axis: str, current: int, target: int) -> Tuple[int, int, bool]:
                    try:
                        r = choose_next_axis_value_toward(
                            current=current, target=target, max_lca_height=effective_max_lca_height
                        )
                        return r.next, r.lca_height, False
                    except ValueError as e:
                        msg = str(e)
                        if not msg.startswith("cannot progress from"):
                            raise

                        # We're pinned at a 2^h block edge. Cross the boundary using a 1-step hop,
                        # temporarily allowing one higher LCA height.
                        nxt = current + 1 if target > current else current - 1
                        if not (0 <= nxt <= AXIS_MAX):
                            raise

                        needed = find_lca_height(current, nxt)
                        if sidestep:
                            # Sidestep uses streaming Merkle proofs (O(h) memory),
                            # so we can afford higher LCA crossings.
                            if needed > SIDESTEP_BOUNDARY_CEILING:
                                raise ValueError(
                                    f"{msg} (boundary crossing would require LCA height={needed}, "
                                    f"exceeds sidestep ceiling={SIDESTEP_BOUNDARY_CEILING})"
                                )
                        elif needed != effective_max_lca_height + 1:
                            raise ValueError(
                                f"{msg} (boundary crossing would require max_lca_height={needed}; "
                                f"rerun with --max-lca-height {needed})"
                            )
                        return nxt, needed, True

                try:
                    x2, hx, bx = _axis_step("X", x1, tx)
                    y2, hy, by_ = _axis_step("Y", y1, ty)
                    z2, hz, bz = _axis_step("Z", z1, tz)
                except ValueError as e:
                    typer.echo(f"Cannot continue toward target: {e}", err=True)
                    raise typer.Exit(code=2)

                hop_limit = effective_max_lca_height
                boundary_axes = [a for a, used in (('X', bx), ('Y', by_), ('Z', bz)) if used]
                if boundary_axes:
                    # Use the actual max LCA needed across all boundary axes.
                    boundary_heights = [h for h, used in ((hx, bx), (hy, by_), (hz, bz)) if used]
                    hop_limit = max(boundary_heights) if boundary_heights else effective_max_lca_height + 1
                    typer.echo(
                        "LCA boundary encountered on axis "
                        + ",".join(boundary_axes)
                        + f"; temporarily increasing max_lca_height from {effective_max_lca_height} to {hop_limit} for this hop.",
                        err=True,
                    )

                # Intermediate hops can be in either plane; we keep the current plane until we need to switch.
                final_hyperjump = bool(
                    hyperjump_to_height is not None and (x2, y2, z2, plane1) == (tx, ty, tz, target_plane)
                )
                hop_proof = _do_single_hop(
                    x2=x2,
                    y2=y2,
                    z2=z2,
                    plane2=plane1,
                    max_compute_height=hop_limit,
                    hyperjump_to_height=hyperjump_to_height if final_hyperjump else None,
                    use_sidestep=sidestep,
                )
                hops += 1

                typer.echo(f"hop: {hops}")
                typer.echo(f"x={x1} remaining={tx - x1}")
                typer.echo(f"y={y1} remaining={ty - y1}")
                typer.echo(f"z={z1} remaining={tz - z1}")
                typer.echo(f"plane={plane1} {_plane_name(plane1)}")
                if hop_proof is not None:
                    typer.echo(f"lca_height: X={hx} Y={hy} Z={hz} limit={hop_limit}")
                    typer.echo(f"terrain_k: {hop_proof.terrain_k}")
        except KeyboardInterrupt:
            typer.echo(f"Interrupted after hops={hops}.", err=True)
            typer.echo(f"coord: 0x{state.coord_hex}")
            raise typer.Exit(code=130)

    if to is not None:
        try:
            dest = parse_destination_xyz_or_coord(to, default_plane=plane1)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        hyperjump_to_height = _resolve_hyperjump_height_for_destination(
            x=dest.x,
            y=dest.y,
            z=dest.z,
            plane=dest.plane,
        )

        _do_single_hop(
            x2=dest.x,
            y2=dest.y,
            z2=dest.z,
            plane2=dest.plane,
            max_compute_height=effective_max_lca_height,
            hyperjump_to_height=hyperjump_to_height,
            use_sidestep=sidestep,
        )
        return

    # by
    vals = _parse_csv_ints(by or "")
    if len(vals) not in (3, 4):
        raise typer.BadParameter("--by expects dx,dy,dz (or 0,0,0,plane for plane switches)")

    if len(vals) == 3:
        dx, dy, dz = vals
        _do_single_hop(
            x2=x1 + dx,
            y2=y1 + dy,
            z2=z1 + dz,
            plane2=plane1,
            max_compute_height=effective_max_lca_height,
            use_sidestep=sidestep,
        )
        return

    dx, dy, dz, plane2 = vals
    if (dx, dy, dz) != (0, 0, 0):
        raise typer.BadParameter("--by with an explicit plane only supports 0,0,0,plane")
    if plane2 not in (0, 1):
        raise typer.BadParameter("plane must be 0 (dataspace) or 1 (ideaspace)")

    _do_single_hop(
        x2=x1,
        y2=y1,
        z2=z1,
        plane2=plane2,
        max_compute_height=effective_max_lca_height,
        use_sidestep=sidestep,
    )


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
    typer.echo(f"delta_xyz: dx={dx} dy={dy} dz={dz} (plane={cplane} {_plane_label(cplane)})")


@move_app.command("viz")
def move_viz() -> None:
    """Launch interactive terminal visualization for movement planning.
    
    Opens a TUI showing your current position on a selected axis with
    adjacent coordinates, their LCA heights, and terrain difficulty.
    Use arrow keys or a/d to explore, Enter to commit movement.
    """
    from cyberspace_cli.viz.move_viz import move_viz_command
    move_viz_command()


if __name__ == "__main__":
    app()
