"""Movement logic for cyberspace-cli.

This module handles coordinate transformations, Cantor computations,
and hop proof generation. Extracted from cli.py for maintainability.
"""
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

from cyberspace_core.coords import AXIS_BITS, AXIS_MAX
from cyberspace_core.movement import compute_subtree_cantor
from cyberspace_core.terrain import terrain_k
from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min


@dataclass
class HopProof:
    """Proof data for a hop event."""
    proof_hash: str
    terrain_k: int
    cantor_x: int
    cantor_y: int
    cantor_z: int
    region_n: Optional[int] = None
    hop_n: Optional[int] = None


@dataclass
class SidestepProof:
    """Proof data for a sidestep event."""
    proof_hash: str
    terrain_k: int
    merkle_x: bytes
    merkle_y: bytes
    merkle_z: bytes
    inclusion_proofs: Dict[str, list]
    lca_heights: Tuple[int, int, int]


def validate_hop_destination(
    x: int, y: int, z: int, plane: int
) -> None:
    """Validate hop destination coordinates.
    
    Args:
        x, y, z: Destination coordinates
        plane: Destination plane (0 for dataspace, 1 for ideaspace)
        
    Raises:
        ValueError: If coordinates are invalid
    """
    if plane not in (0, 1):
        raise ValueError(f"Destination plane must be 0 or 1, got {plane}")
    
    if not (0 <= x <= AXIS_MAX and 0 <= y <= AXIS_MAX and 0 <= z <= AXIS_MAX):
        raise ValueError(
            f"Destination out of range: (x={x}, y={y}, z={z}) "
            f"must be within [0, {AXIS_MAX}]"
        )


def compute_spatial_cantor_roots(
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    max_compute_height: int,
) -> Tuple[int, int, int]:
    """Compute Cantor roots for X, Y, Z axes.
    
    Args:
        x1, y1, z1: Starting coordinates
        x2, y2, z2: Destination coordinates
        max_compute_height: Maximum LCA height for local compute
        
    Returns:
        Tuple of (cantor_x, cantor_y, cantor_z)
    """
    from cyberspace_core.movement import compute_axis_cantor
    
    cantor_x = compute_axis_cantor(x1, x2, max_compute_height=max_compute_height)
    cantor_y = compute_axis_cantor(y1, y2, max_compute_height=max_compute_height)
    cantor_z = compute_axis_cantor(z1, z2, max_compute_height=max_compute_height)
    
    return cantor_x, cantor_y, cantor_z


def compute_temporal_component(
    x: int, y: int, z: int, plane: int,
    previous_event_id_hex: str,
) -> Tuple[int, int]:
    """Compute temporal seed and subtree Cantor.
    
    Args:
        x, y, z, plane: Destination coordinates
        previous_event_id_hex: Previous event ID (hex string)
        
    Returns:
        Tuple of (terrain_k_val, cantor_t)
    """
    terrain_k_val = terrain_k(x=x, y=y, z=z, plane=plane)
    
    # Temporal seed from previous event
    prev_id_bytes = bytes.fromhex(previous_event_id_hex)
    t = int.from_bytes(prev_id_bytes, "big") % (2**85)
    t_base = (t >> terrain_k_val) << terrain_k_val if terrain_k_val > 0 else t
    cantor_t = compute_subtree_cantor(t_base, terrain_k_val)
    
    return terrain_k_val, cantor_t


def compute_hop_proof(
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    plane: int,
    previous_event_id_hex: str,
) -> HopProof:
    """Compute hop proof for normal movement.
    
    Args:
        x1, y1, z1: Starting coordinates
        x2, y2, z2: Destination coordinates
        plane: Destination plane
        previous_event_id_hex: Previous event ID (hex string)
        
    Returns:
        HopProof object with proof data
    """
    # Compute spatial roots
    cantor_x, cantor_y, cantor_z = compute_spatial_cantor_roots(
        x1, y1, z1, x2, y2, z2,
        max_compute_height=AXIS_BITS  # Local compute uses full precision
    )
    
    # Combine spatial roots
    region_n = cantor_pair(cantor_pair(cantor_x, cantor_y), cantor_z)
    
    # Compute temporal component
    terrain_k_val, cantor_t = compute_temporal_component(
        x2, y2, z2, plane, previous_event_id_hex
    )
    
    # Combine into hop_n
    hop_n = cantor_pair(region_n, cantor_t)
    
    # Compute proof hash (double SHA256)
    proof_hash = compute_proof_hash(hop_n)
    
    return HopProof(
        proof_hash=proof_hash,
        terrain_k=terrain_k_val,
        cantor_x=cantor_x,
        cantor_y=cantor_y,
        cantor_z=cantor_z,
        region_n=region_n,
        hop_n=hop_n,
    )


def compute_proof_hash(hop_n: int) -> str:
    """Compute double SHA256 proof hash.
    
    Args:
        hop_n: Hop number (Cantor pairing result)
        
    Returns:
        64-character hex string
    """
    import hashlib
    from cyberspace_core.cantor import int_to_bytes_be_min
    
    hop_bytes = int_to_bytes_be_min(hop_n)
    return hashlib.sha256(hashlib.sha256(hop_bytes).digest()).digest().hex()
