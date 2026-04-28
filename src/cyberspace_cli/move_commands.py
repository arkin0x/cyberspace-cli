"""Move command execution for cyberspace-cli.

Orchestrates single hops, continuous movement, and hyperjump validation.
"""
from typing import Optional
import typer


def move_command(
    to: Optional[str] = None,
    by: Optional[str] = None,
    toward: Optional[str] = None,
    max_lca_height: Optional[int] = None,
    max_hops: int = 0,
    hyperjump: bool = False,
    hyperjump_relay: str = "wss://hyperjump.arKin0x.com",
    hyperjump_query_limit: int = 25,
    sidestep: bool = False,
    exit_hyperjump: bool = False,
) -> None:
    """Execute a move command."""
    from cyberspace_cli.config import load_config
    from cyberspace_cli.cli_utils import require_state
    from cyberspace_cli.chains import EventChains
    from cyberspace_cli.movement_validator import build_move_config
    from cyberspace_cli.hop_executor import HopExecutor
    from cyberspace_cli.move_toward import execute_toward_loop
    from cyberspace_cli.hyperjump_flow import resolve_hop_hyperjump_height
    from cyberspace_cli.parsing import parse_destination_xyz_or_coord, _parse_csv_ints
    from cyberspace_cli.coords import coord_to_xyz
    from cyberspace_cli.cli import _hyperjump_block_height_from_event, _require_active_chain_label
    
    # Validate flags
    if sidestep and hyperjump:
        typer.echo("--sidestep cannot be combined with --hyperjump.", err=True)
        raise typer.Exit(code=2)
    
    chains = EventChains()
    state = _require_state()
    label = _require_active_chain_label(state)
    
    cfg = load_config()
    config = build_move_config(
        max_lca_height=max_lca_height,
        default_max_lca_height=int(cfg.default_max_lca_height),
        max_hops=max_hops,
        use_hyperjump=hyperjump,
        use_sidestep=sidestep,
        exit_hyperjump=exit_hyperjump,
        hyperjump_relay=hyperjump_relay,
        hyperjump_query_limit=hyperjump_query_limit,
    )
    
    # Load chain
    events = chains.read_events(label)
    if not events:
        typer.echo(f"Chain is empty: {label}", err=True)
        raise typer.Exit(code=1)
    
    genesis_id = events[0]["id"]
    prev_event_id = events[-1]["id"]
    prev_coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x1, y1, z1, plane1 = coord_to_xyz(prev_coord_int)
    
    # Default to target if no destination
    if to is None and by is None and toward is None:
        from cyberspace_cli.targets import get_current_target
        t = get_current_target(state)
        if t and t.get("coord_hex"):
            toward = f"0x{t['coord_hex']}"
        else:
            typer.echo("Specify --to, --by, or --toward (or set a target).", err=True)
            raise typer.Exit(code=2)
    
    if sum(v is not None for v in (to, by, toward)) != 1:
        typer.echo("Specify exactly one of --to, --by, or --toward.", err=True)
        raise typer.Exit(code=2)
    
    # Hyperjump validation
    if hyperjump and by is not None:
        typer.echo("--hyperjump only works with --to or --toward.", err=True)
        raise typer.Exit(code=2)
    if hyperjump and exit_hyperjump:
        typer.echo("--hyperjump and --exit-hyperjump are mutually exclusive.", err=True)
        raise typer.Exit(code=2)
    
    # Check hyperjump system
    in_hyperjump = _hyperjump_block_height_from_event(events[-1]) is not None
    if in_hyperjump and not hyperjump and not exit_hyperjump:
        typer.echo("On hyperjump system. Use --exit-hyperjump for normal moves.", err=True)
        raise typer.Exit(code=2)
    
    # Toward mode
    if toward is not None:
        try:
            target = parse_destination_xyz_or_coord(toward, default_plane=plane1)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        
        hyperjump_height = resolve_hop_hyperjump_height(
            target.x, target.y, target.z, target.plane,
            config.use_hyperjump, config.hyperjump_relay, config.hyperjump_query_limit,
        )
        
        executor = HopExecutor(
            chains=chains, state=state, genesis_id=genesis_id, prev_event_id=prev_event_id,
            x1=x1, y1=y1, z1=z1, plane1=plane1,
            max_compute_height=config.max_lca_height,
            privkey_hex=state.privkey_hex, pubkey_hex=state.pubkey_hex, label=label,
        )
        
        execute_toward_loop(
            executor=executor,
            target_x=target.x, target_y=target.y, target_z=target.z, target_plane=target.plane,
            max_hops=config.max_hops,
            sidestep=config.use_sidestep,
            hyperjump_to_height=hyperjump_height,
        )
        return
    
    # Single hop modes
    if to is not None:
        try:
            dest = parse_destination_xyz_or_coord(to, default_plane=plane1)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        
        hyperjump_height = resolve_hop_hyperjump_height(
            dest.x, dest.y, dest.z, dest.plane,
            config.use_hyperjump, config.hyperjump_relay, config.hyperjump_query_limit,
        )
        
        executor = HopExecutor(
            chains=chains, state=state, genesis_id=genesis_id, prev_event_id=prev_event_id,
            x1=x1, y1=y1, z1=z1, plane1=plane1,
            max_compute_height=config.max_lca_height,
            privkey_hex=state.privkey_hex, pubkey_hex=state.pubkey_hex, label=label,
        )
        
        executor.execute(
            x2=dest.x, y2=dest.y, z2=dest.z, plane2=dest.plane,
            use_sidestep=config.use_sidestep,
            hyperjump_to_height=hyperjump_height,
        )
        return
    
    # By mode
    vals = _parse_csv_ints(by or "")
    if len(vals) not in (3, 4):
        raise typer.BadParameter("--by expects dx,dy,dz (or 0,0,0,plane)")
    
    executor = HopExecutor(
        chains=chains, state=state, genesis_id=genesis_id, prev_event_id=prev_event_id,
        x1=x1, y1=y1, z1=z1, plane1=plane1,
        max_compute_height=config.max_lca_height,
        privkey_hex=state.privkey_hex, pubkey_hex=state.pubkey_hex, label=label,
    )
    
    if len(vals) == 3:
        dx, dy, dz = vals
        executor.execute(
            x2=x1 + dx, y2=y1 + dy, z2=z1 + dz, plane2=plane1,
            use_sidestep=config.use_sidestep,
        )
        return
    
    dx, dy, dz, plane2 = vals
    if (dx, dy, dz) != (0, 0, 0):
        raise typer.BadParameter("--by with plane only supports 0,0,0,plane")
    if plane2 not in (0, 1):
        raise typer.BadParameter("plane must be 0 or 1")
    
    executor.execute(
        x2=x1, y2=y1, z2=z1, plane2=plane2,
        use_sidestep=config.use_sidestep,
    )
