"""Cloud compute orchestration for cyberspace-cli.

Handles HOSAKA cloud fallback when LCA height exceeds local capacity.
Extracted from cli.py to separate cloud concerns from movement logic.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
import asyncio

from cyberspace_cli.cloud_compute import run_cloud_compute


@dataclass
class CloudComputeResult:
    """Result from cloud compute for a single axis."""
    axis: str  # 'x', 'y', or 'z'
    axis_root: int
    lca_height: int
    base: int
    job_id: Optional[str] = None
    cost_sats: int = 0


async def compute_axis_in_cloud(
    axis: str,
    coord1: int,
    coord2: int,
    lca_height: int,
    privkey_hex: str,
    pubkey_hex: str,
    max_compute_height: int,
) -> CloudComputeResult:
    """Compute a single axis root using HOSAKA cloud compute.
    
    Args:
        axis: Which axis ('x', 'y', or 'z')
        coord1: Starting coordinate for this axis
        coord2: Destination coordinate for this axis
        lca_height: LCA height for this axis
        privkey_hex: Nostr private key (hex)
        pubkey_hex: Nostr public key (hex)
        max_compute_height: Maximum local compute capacity
        
    Returns:
        CloudComputeResult with axis root and metadata
    """
    base = (coord1 >> lca_height) << lca_height
    
    result = await run_cloud_compute(
        privkey_hex=privkey_hex,
        pubkey_hex=pubkey_hex,
        job_type="hop",
        params={"height": lca_height, "base": base, "axis": axis},
        lca_height=lca_height,
        max_compute_height=max_compute_height,
    )
    
    # Extract axis root from cloud result
    axis_root_hex = result.get("axis_root_hex", 0)
    if isinstance(axis_root_hex, int):
        axis_root_hex = hex(axis_root_hex)
    if axis_root_hex.startswith("0x"):
        axis_root_hex = axis_root_hex[2:]
    axis_root = int(axis_root_hex, 16) if axis_root_hex else 0
    
    # Extract cost from result
    cost_msats = result.get("cost_msats", 0)
    cost_sats = cost_msats // 1000
    
    return CloudComputeResult(
        axis=axis,
        axis_root=axis_root,
        lca_height=lca_height,
        base=base,
        job_id=result.get("job_id"),
        cost_sats=cost_sats,
    )


def select_axis_for_cloud(
    hx: int, hy: int, hz: int,
    max_compute_height: int,
) -> Optional[str]:
    """Select which axis (if any) needs cloud compute.
    
    Args:
        hx, hy, hz: LCA heights for X, Y, Z axes
        max_compute_height: Maximum local compute capacity
        
    Returns:
        Axis label ('x', 'y', or 'z') that needs cloud compute, or None
    """
    # Find the maximum height
    max_h = max(hx, hy, hz)
    
    # If all axes can be computed locally, no cloud needed
    if max_h <= max_compute_height:
        return None
    
    # Select the axis with maximum height (prioritize X > Y > Z for ties)
    if hx == max_h:
        return 'x'
    elif hy == max_h:
        return 'y'
    else:
        return 'z'


async def compute_spatial_roots_hybrid(
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    max_compute_height: int,
    privkey_hex: str,
    pubkey_hex: str,
) -> Tuple[int, int, int, Dict[str, Any]]:
    """Compute X, Y, Z Cantor roots using hybrid local/cloud approach.
    
    Uses cloud compute for the axis with highest LCA height if it exceeds
    local capacity, and local compute for the other two axes.
    
    Args:
        x1, y1, z1: Starting coordinates
        x2, y2, z2: Destination coordinates
        max_compute_height: Maximum local compute capacity
        privkey_hex: Nostr private key (hex)
        pubkey_hex: Nostr public key (hex)
        
    Returns:
        Tuple of (cantor_x, cantor_y, cantor_z, metadata)
        where metadata contains cloud compute details if used
    """
    from cyberspace_core.movement import find_lca_height, compute_axis_cantor
    
    # Find LCA heights for each axis
    hx = find_lca_height(x1, x2)
    hy = find_lca_height(y1, y2)
    hz = find_lca_height(z1, z2)
    
    # Determine which axis needs cloud compute
    cloud_axis = select_axis_for_cloud(hx, hy, hz, max_compute_height)
    
    metadata = {
        "lca_heights": (hx, hy, hz),
        "cloud_axis": cloud_axis,
        "cloud_result": None,
    }
    
    if cloud_axis is None:
        # All axes can be computed locally
        cantor_x = compute_axis_cantor(x1, x2, max_compute_height=max_compute_height)
        cantor_y = compute_axis_cantor(y1, y2, max_compute_height=max_compute_height)
        cantor_z = compute_axis_cantor(z1, z2, max_compute_height=max_compute_height)
    else:
        # One axis needs cloud compute
        if cloud_axis == 'x':
            cloud_result = await compute_axis_in_cloud(
                'x', x1, x2, hx, privkey_hex, pubkey_hex, max_compute_height
            )
            cantor_x = cloud_result.axis_root
            cantor_y = compute_axis_cantor(y1, y2, max_compute_height=max_compute_height)
            cantor_z = compute_axis_cantor(z1, z2, max_compute_height=max_compute_height)
        elif cloud_axis == 'y':
            cloud_result = await compute_axis_in_cloud(
                'y', y1, y2, hy, privkey_hex, pubkey_hex, max_compute_height
            )
            cantor_x = compute_axis_cantor(x1, x2, max_compute_height=max_compute_height)
            cantor_y = cloud_result.axis_root
            cantor_z = compute_axis_cantor(z1, z2, max_compute_height=max_compute_height)
        else:  # 'z'
            cloud_result = await compute_axis_in_cloud(
                'z', z1, z2, hz, privkey_hex, pubkey_hex, max_compute_height
            )
            cantor_x = compute_axis_cantor(x1, x2, max_compute_height=max_compute_height)
            cantor_y = compute_axis_cantor(y1, y2, max_compute_height=max_compute_height)
            cantor_z = cloud_result.axis_root
        
        metadata["cloud_result"] = cloud_result
    
    return cantor_x, cantor_y, cantor_z, metadata
