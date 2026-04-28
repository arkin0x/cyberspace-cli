"""Move toward loop execution for cyberspace-cli.

Handles continuous movement toward a target coordinate.
"""
from typing import Optional

import typer

from cyberspace_cli.hop_executor import HopExecutor


def execute_toward_loop(
    executor: HopExecutor,
    target_x: int, target_y: int, target_z: int, target_plane: int,
    max_hops: int,
    sidestep: bool,
    hyperjump_to_height: Optional[str],
) -> None:
    """Execute continuous movement toward target.
    
    Args:
        executor: HopExecutor instance
        target_x/y/z/plane: Destination
        max_hops: Maximum hops (0 = unlimited)
        sidestep: Use sidestep proofs
        hyperjump_to_height: Height for final hyperjump
    """
    from cyberspace_cli.toward import choose_next_axis_value_toward
    
    hops = 0
    try:
        while True:
            # Check if arrived
            if (executor.x1, executor.y1, executor.z1, executor.plane1) == (target_x, target_y, target_z, target_plane):
                typer.echo("Arrived.")
                typer.echo(f"coord: 0x{executor.state.coord_hex}")
                return
            
            # Check max hops
            if max_hops and hops >= max_hops:
                typer.echo(f"Stopped after max_hops={max_hops}.")
                typer.echo(f"coord: 0x{executor.state.coord_hex}")
                return
            
            # Plane switch at target
            if (executor.x1, executor.y1, executor.z1) == (target_x, target_y, target_z) and executor.plane1 != target_plane:
                final_hyperjump = hyperjump_to_height is not None
                executor.execute(
                    x2=executor.x1, y2=executor.y1, z2=executor.z1, plane2=target_plane,
                    use_sidestep=sidestep,
                    hyperjump_to_height=hyperjump_to_height if final_hyperjump else None,
                )
                hops += 1
                _print_hop_status(executor, hops)
                continue
            
            # Normal hop toward target
            next_coord = choose_next_axis_value_toward(
                executor.x1, executor.y1, executor.z1,
                target_x, target_y, target_z,
                executor.plane1,
            )
            
            try:
                executor.execute(
                    x2=next_coord.x, y2=next_coord.y, z2=next_coord.z, plane2=next_coord.plane,
                    use_sidestep=sidestep,
                    hyperjump_to_height=None,
                )
                hops += 1
                _print_hop_status(executor, hops)
            except Exception as e:
                typer.echo(f"Cannot continue toward target: {e}", err=True)
                raise typer.Exit(code=2)
    except typer.Exit:
        raise


def _print_hop_status(executor: HopExecutor, hop_num: int) -> None:
    """Print hop status after execution."""
    plane_name = "dataspace" if executor.plane1 == 0 else "ideaspace"
    typer.echo(f"hop: {hop_num}")
    typer.echo(f"x={executor.x1}")
    typer.echo(f"y={executor.y1}")
    typer.echo(f"z={executor.z1}")
    typer.echo(f"plane={executor.plane1} {plane_name}")
