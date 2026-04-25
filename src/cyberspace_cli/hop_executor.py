"""Single hop execution for cyberspace-cli.

Executes individual movement hops with cloud compute fallback.
"""
from typing import Optional, Any, Dict, Tuple
import asyncio
import hashlib

import typer

from cyberspace_cli.movement import (
    compute_hop_proof, 
    validate_hop_destination, 
    HopProof,
    compute_temporal_component,
    compute_proof_hash,
)
from cyberspace_cli.cloud_orchestration import compute_spatial_roots_hybrid
from cyberspace_cli.event_builders import make_movement_event
from cyberspace_cli.hyperjump_flow import resolve_hyperjump_height
from cyberspace_core.coords import AXIS_MAX, xyz_to_coord
from cyberspace_core.movement import compute_axis_cantor, find_lca_height
from cyberspace_core.cantor import cantor_pair


class HopExecutor:
    """Execute single hops and manage chain state."""
    
    def __init__(
        self,
        chains,
        state,
        genesis_id: str,
        prev_event_id: str,
        x1: int, y1: int, z1: int, plane1: int,
        max_compute_height: int,
        privkey_hex: str,
        pubkey_hex: str,
        label: str,
    ):
        self.chains = chains
        self.state = state
        self.genesis_id = genesis_id
        self.prev_event_id = prev_event_id
        self.x1, self.y1, self.z1, self.plane1 = x1, y1, z1, plane1
        self.max_compute_height = max_compute_height
        self.privkey_hex = privkey_hex
        self.pubkey_hex = pubkey_hex
        self.label = label
        self.coord_hex = self._coord_hex(x1, y1, z1, plane1)
    
    def execute(
        self,
        x2: int, y2: int, z2: int, plane2: int,
        use_sidestep: bool = False,
        hyperjump_to_height: Optional[str] = None,
    ) -> Optional[Any]:
        """Execute a single hop.
        
        Returns proof object or None for hyperjump.
        """
        # Validate
        try:
            validate_hop_destination(x2, y2, z2, plane2)
        except ValueError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=2)
        
        self.coord_hex = self._coord_hex(x2, y2, z2, plane2)
        proof = None
        sidestep_proof = None
        
        if hyperjump_to_height is None:
            hx = find_lca_height(self.x1, x2)
            hy = find_lca_height(self.y1, y2)
            hz = find_lca_height(self.z1, z2)
            
            if use_sidestep:
                # TODO: Implement sidestep
                pass
            else:
                proof = self._compute_proof(x2, y2, z2, plane2, hx, hy, hz)
        
        # Build and append event
        event = self._build_event(
            sidestep_proof if sidestep_proof else 'hop' if proof else 'hyperjump',
            proof,
            hyperjump_to_height,
        )
        
        self.chains.append_event(self.label, event)
        
        # Update state
        self.state.coord_hex = self.coord_hex
        from cyberspace_cli.state import save_state
        save_state(self.state)
        
        self.prev_event_id = event["id"]
        self.x1, self.y1, self.z1, self.plane1 = x2, y2, z2, plane2
        
        # Print result
        typer.echo(f"Moved. chain={self.label} len={self.chains.chain_length(self.label)}")
        typer.echo(f"coord: 0x{self.coord_hex}")
        if sidestep_proof:
            typer.echo(f"action: sidestep")
            typer.echo(f"proof: {sidestep_proof.proof_hash}")
            typer.echo(f"terrain_k: {sidestep_proof.terrain_k}")
            typer.echo(f"lca_heights: X={sidestep_proof.lca_heights[0]} Y={sidestep_proof.lca_heights[1]} Z={sidestep_proof.lca_heights[2]}")
        elif proof:
            typer.echo(f"proof: {proof.proof_hash}")
            typer.echo(f"terrain_k: {proof.terrain_k}")
        else:
            typer.echo(f"action: hyperjump")
            typer.echo(f"B: {hyperjump_to_height}")
        
        return sidestep_proof or proof
    
    def _compute_proof(
        self, x2: int, y2: int, z2: int, plane2: int,
        hx: int, hy: int, hz: int,
    ) -> Optional[HopProof]:
        """Compute hop proof, using cloud if needed."""
        max_h = max(hx, hy, hz)
        
        if max_h > self.max_compute_height:
            # Cloud compute
            typer.echo(f"   ☁️  LCA height {max_h} exceeds local limit ({self.max_compute_height})")
            typer.echo(f"   Computing highest axis in cloud...")
            
            cantor_x, cantor_y, cantor_z, metadata = asyncio.run(
                compute_spatial_roots_hybrid(
                    self.x1, self.y1, self.z1,
                    x2, y2, z2,
                    self.max_compute_height,
                    self.privkey_hex,
                    self.pubkey_hex,
                )
            )
            
            if metadata.get("cloud_result"):
                cr = metadata["cloud_result"]
                typer.echo(f"   ✓ {cr.axis.upper()} axis root computed (h={cr.lca_height})")
            
            region_n = cantor_pair(cantor_pair(cantor_x, cantor_y), cantor_z)
            typer.echo(f"   region_n: {region_n}")
            
            terrain_k_val, cantor_t = compute_temporal_component(
                x2, y2, z2, plane2, self.prev_event_id
            )
            hop_n = cantor_pair(region_n, cantor_t)
            proof_hash = compute_proof_hash(hop_n)
            
            typer.echo(f"   terrain_k: {terrain_k_val}")
            typer.echo(f"   proof_hash: {proof_hash[:32]}...")
            
            return HopProof(
                proof_hash=proof_hash,
                terrain_k=terrain_k_val,
                cantor_x=cantor_x,
                cantor_y=cantor_y,
                cantor_z=cantor_z,
                region_n=region_n,
                hop_n=hop_n,
            )
        else:
            # Local compute - use existing function
            return compute_hop_proof(
                self.x1, self.y1, self.z1,
                x2, y2, z2,
                plane2,
                self.prev_event_id,
            )
    
    def _build_event(
        self,
        event_type: str,
        proof: Optional[HopProof],
        hyperjump_to_height: Optional[str],
    ) -> Dict:
        """Build movement event."""
        if event_type == 'sidestep':
            # TODO: Handle sidestep
            raise NotImplementedError("Sidestep not yet implemented in HopExecutor")
        elif event_type == 'hop':
            return make_movement_event(
                event_type='hop',
                pubkey_hex=self.pubkey_hex,
                genesis_event_id=self.genesis_id,
                previous_event_id=self.prev_event_id,
                prev_coord_hex=self.state.coord_hex,
                coord_hex=self.coord_hex,
                proof_hash_hex=proof.proof_hash,
            )
        else:  # hyperjump
            return make_movement_event(
                event_type='hyperjump',
                pubkey_hex=self.pubkey_hex,
                genesis_event_id=self.genesis_id,
                previous_event_id=self.prev_event_id,
                prev_coord_hex=self.state.coord_hex,
                coord_hex=self.coord_hex,
                to_height=hyperjump_to_height,
            )
    
    def _coord_hex(self, x: int, y: int, z: int, plane: int) -> str:
        """Convert coords to hex."""
        coord_int = xyz_to_coord(x, y, z, plane)
        return f"{coord_int:064x}"


def resolve_hop_hyperjump_height(
    x: int, y: int, z: int, plane: int,
    hyperjump_enabled: bool,
    relay: str,
    query_limit: int,
) -> Optional[str]:
    """Resolve hyperjump height for destination.
    
    Returns height string or None if not a hyperjump anchor.
    Raises typer.Exit if validation fails.
    """
    if not hyperjump_enabled:
        return None
    
    height, error = resolve_hyperjump_height(
        x, y, z, plane, relay, query_limit
    )
    
    if error:
        typer.echo(error, err=True)
        raise typer.Exit(code=2)
    
    return height
