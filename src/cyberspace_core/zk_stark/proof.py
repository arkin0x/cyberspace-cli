"""
ZK-STARK proof integration for Nostr events.

This module provides the integration layer between ZK proofs and
Cyberspace Nostr events. It handles:
- Proof generation for Cantor tree computations
- Proof verification (placeholder for actual STARK verification)
- Nostr event tag encoding/decoding
- Proof serialization

Status: Proof-of-Concept (uses hash-based commitments)
Production: Replace with actual STARK proofs using Cairo/Winterfell
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

from cyberspace_core.cantor import build_hyperspace_proof, compute_temporal_seed
from cyberspace_core.zk_stark.circuit import (
    cantor_tree_circuit,
    verify_tree_constraints,
)


# ============================================================================
# Proof Data Structures
# ============================================================================

@dataclass
class CantorZKPublicInputs:
    """Public inputs to the ZK-STARK proof.
    
    These values are visible to the verifier and are NOT private.
    In production, the STARK proof commits to these values.
    
    Attributes:
        root_hex: The Cantor tree root (what we're proving) - 64-char hex
        leaf_count: Number of leaves in the tree
        temporal_commitment: SHA256(temporal_seed) - binds proof to chain position
    """
    root_hex: str
    leaf_count: int
    temporal_commitment: str
    
    def to_hex(self) -> str:
        """Serialize public inputs to hex for Nostr event tag."""
        data = asdict(self)
        json_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
        return hashlib.sha256(json_bytes).hexdigest()


@dataclass
class CantorZKProof:
    """ZK-STARK proof wrapper for Cantor tree computation.
    
    In production, proof_hex would contain the actual STARK proof:
    - Polynomial commitments (PCPP + FRI)
    - DEEP-ALI constraint evaluations
    - Proof-of-work trace
    
    For PoC, uses hash-based commitments to demonstrate the API pattern.
    
    Attributes:
        scheme: Proof scheme identifier (e.g., "winterfell-stark-v1")
        proof_hex: The proof bytes as hex string
        public_inputs: Public inputs bound to the proof
    """
    scheme: str
    proof_hex: str
    public_inputs: CantorZKPublicInputs
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON encoding."""
        return {
            "scheme": self.scheme,
            "proof": self.proof_hex,
            "public_inputs": asdict(self.public_inputs)
        }
    
    def to_hex(self) -> str:
        """Serialize to hex for Nostr event tag."""
        json_bytes = json.dumps(self.to_dict(), sort_keys=True).encode('utf-8')
        return json_bytes.hex()
    
    @classmethod
    def from_hex(cls, hex_str: str) -> CantorZKProof:
        """Deserialize from hex."""
        json_bytes = bytes.fromhex(hex_str)
        data = json.loads(json_bytes.decode('utf-8'))
        
        public_inputs = CantorZKPublicInputs(
            root_hex=data["public_inputs"]["root_hex"],
            leaf_count=data["public_inputs"]["leaf_count"],
            temporal_commitment=data["public_inputs"]["temporal_commitment"]
        )
        
        return cls(
            scheme=data["scheme"],
            proof_hex=data["proof"],
            public_inputs=public_inputs
        )
    
    @property
    def proof_size_bytes(self) -> int:
        """Estimate proof size in bytes."""
        return len(self.proof_hex) // 2


# ============================================================================
# Prover Interface (PoC)
# ============================================================================

def prove_cantor_single_pair(
    x: int,
    y: int,
    expected_root: int,
    scheme: str = "poc-commitment-v1"
) -> CantorZKProof:
    """Generate a ZK proof for a single Cantor pairing: π(x, y) = expected_root.
    
    THIS IS A PLACEHOLDER for actual STARK proving.
    
    In production with Winterfell/Cairo, this would:
    1. Build arithmetic circuit (AIR) for Cantor pairing
    2. Generate execution trace (5 constraints per pairing)
    3. Create STARK proof with polynomial commitments
    4. Return proof with ~20-50 KB size
    
    For PoC, creates a hash-based commitment demonstrating the API pattern.
    
    Args:
        x: First input value
        y: Second input value
        expected_root: Expected Cantor pairing result
        scheme: Proof scheme identifier
        
    Returns:
        CantorZKProof object (PoC placeholder)
    """
    # Temporal commitment placeholder
    temporal_seed = 0
    temporal_commitment = hashlib.sha256(
        temporal_seed.to_bytes(32, "big")
    ).hexdigest()
    
    # Create public inputs
    public_inputs = CantorZKPublicInputs(
        root_hex=f"0x{expected_root:x}",
        leaf_count=2,
        temporal_commitment=f"0x{temporal_commitment}"
    )
    
    # Generate PoC "proof" (hash-based commitment)
    proof_data = {
        "x": x,
        "y": y,
        "computation": f"(({x}+{y})*({x}+{y}+1))/2 + {y} = {expected_root}",
        "temporal_commitment": temporal_commitment
    }
    proof_json = json.dumps(proof_data, sort_keys=True).encode('utf-8')
    proof_hex = hashlib.sha256(proof_json).hexdigest()
    
    return CantorZKProof(
        scheme=scheme,
        proof_hex=proof_hex,
        public_inputs=public_inputs
    )


def prove_cantor_tree(
    leaves: List[int],
    previous_event_id_hex: str,
    scheme: str = "poc-commitment-v1"
) -> CantorZKProof:
    """Generate a ZK proof for a full Cantor tree computation.
    
    THIS IS A PLACEHOLDER for actual STARK proving.
    
    In production, this would:
    1. Compute temporal_seed = int.from_bytes(previous_event_id, "big") % 2^256
    2. Build tree execution trace using circuit constraints
    3. Generate STARK proving correct constraint satisfaction
    4. Return STARK proof (~20-50 KB for typical heights)
    
    PoC Implementation:
    - Generates hash-based commitment
    - Computes full circuit trace (demonstrates the computation)
    - Returns proof object compatible with future STARK integration
    
    Args:
        leaves: List of leaf values (coordinates)
        previous_event_id_hex: Previous movement event ID (64-char hex)
        scheme: Proof scheme identifier
        
    Returns:
        CantorZKProof object
        
    Raises:
        ValueError: If leaves list is empty
    """
    if not leaves:
        raise ValueError("Cannot create proof over empty leaf list")
    
    # Compute actual Cantor root
    tree_root = build_hyperspace_proof(leaves)
    
    # Compute temporal seed per DECK-0001 §8
    temporal_seed = compute_temporal_seed(bytes.fromhex(previous_event_id_hex))
    temporal_commitment = hashlib.sha256(
        temporal_seed.to_bytes(32, "big")
    ).hexdigest()
    
    # Build circuit trace (demonstrating the constraint structure)
    # In production, this trace is used for STARK proving
    tree_trace = cantor_tree_circuit(leaves)
    
    # Verify constraints (in production, STARK proves this implicitly)
    is_valid, violations = verify_tree_constraints(tree_trace)
    if not is_valid:
        raise ValueError(f"Circuit constraints violated: {violations}")
    
    # Create public inputs
    public_inputs = CantorZKPublicInputs(
        root_hex=f"0x{tree_root:x}",
        leaf_count=len(leaves),
        temporal_commitment=f"0x{temporal_commitment}"
    )
    
    # Generate PoC proof
    proof_data = {
        "leaves": leaves,
        "root": tree_root,
        "temporal_commitment": temporal_commitment,
        "tree_height": len(leaves).bit_length(),
        "constraint_satisfied": is_valid,
        "num_constraints": 5 * (len(leaves) - 1)  # 5 constraints per pairing
    }
    proof_json = json.dumps(proof_data, sort_keys=True).encode('utf-8')
    proof_hex = hashlib.sha256(proof_json).hexdigest()
    
    return CantorZKProof(
        scheme=scheme,
        proof_hex=proof_hex,
        public_inputs=public_inputs
    )


# ============================================================================
# Verifier Interface (PoC)
# ============================================================================

def verify_cantor_proof(
    proof: CantorZKProof,
    expected_root: int
) -> Tuple[bool, str]:
    """Verify a ZK-STARK proof for Cantor tree computation.
    
    THIS IS A PLACEHOLDER for actual STARK verification.
    
    In production with STARKs, this would:
    1. Parse STARK proof structure
    2. Verify polynomial commitments (FRI, DEEP-ALI)
    3. Check constraint satisfaction (implicitly via proof)
    4. Return True only if proof is valid
    
    Performance Target: < 10 ms for any tree height
    
    PoC Implementation:
    - Verifies public inputs match expected root
    - Returns success/failure with timing information
    
    Args:
        proof: The ZK proof object
        expected_root: The expected Cantor tree root
        
    Returns:
        Tuple of (is_valid, status_message)
    """
    start_time = time.perf_counter()
    
    # Check scheme
    if proof.scheme not in ["poc-commitment-v1", "winterfell-stark-v1", "cairo"]:
        return False, f"Unknown proof scheme: {proof.scheme}"
    
    # Verify root matches
    proof_root = int(proof.public_inputs.root_hex, 16)
    if proof_root != expected_root:
        elapsed_us = (time.perf_counter() - start_time) * 1e6
        return False, f"Root mismatch (elapsed: {elapsed_us:.1f} μs)"
    
    # In production: STARK verification happens here
    # For PoC: assume valid if structure is correct
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    
    return True, f"Verification successful ({elapsed_ms:.3f} ms)"


def verify_proof_timing(
    proof: CantorZKProof,
    expected_root: int,
    target_ms: float = 10.0
) -> Tuple[bool, float, str]:
    """Verify proof and measure timing against target.
    
    Args:
        proof: ZK proof to verify
        expected_root: Expected Cantor root
        target_ms: Target verification time in milliseconds
        
    Returns:
        Tuple of (is_valid, elapsed_ms, status_message)
    """
    is_valid, status = verify_cantor_proof(proof, expected_root)
    
    # Extract timing from status if present
    if "ms)" in status:
        elapsed_ms = float(status.split("(")[1].split(" ms")[0])
    else:
        elapsed_ms = 0.0
    
    if is_valid and elapsed_ms > target_ms:
        return False, elapsed_ms, f"Verification too slow: {elapsed_ms:.3f}ms > {target_ms}ms target"
    
    return is_valid, elapsed_ms, status


# ============================================================================
# Nostr Event Integration
# ============================================================================

def add_zk_tags_to_event(
    event: dict,
    zk_proof: CantorZKProof
) -> dict:
    """Add ZK-STARK proof tags to a Nostr event.
    
    Adds the following tags:
    - zk_proof: The STARK proof (hex-encoded)
    - zk_public_inputs: Public inputs hash (for quick verification)
    - zk_scheme: Proof scheme identifier
    
    Args:
        event: Nostr event dict with existing tags
        zk_proof: The ZK-STARK proof object
        
    Returns:
        Modified event dict with ZK tags added
    """
    if "tags" not in event:
        event["tags"] = []
    
    # Add zk_proof tag
    event["tags"].append(["zk_proof", zk_proof.to_hex()])
    
    # Add zk_public_inputs tag
    event["tags"].append(["zk_public_inputs", zk_proof.public_inputs.to_hex()])
    
    # Add zk_scheme tag
    event["tags"].append(["zk_scheme", zk_proof.scheme])
    
    return event


def extract_zk_proof_from_event(event: dict) -> Optional[CantorZKProof]:
    """Extract ZK-STARK proof from a Nostr event.
    
    Args:
        event: Nostr event dict
        
    Returns:
        CantorZKProof object, or None if no ZK proof present
    """
    tags = event.get("tags", [])
    
    zk_proof_hex = None
    for tag in tags:
        if tag[0] == "zk_proof" and len(tag) > 1:
            zk_proof_hex = tag[1]
            break
    
    if zk_proof_hex is None:
        return None
    
    return CantorZKProof.from_hex(zk_proof_hex)


# ============================================================================
# Benchmarking Utilities
# ============================================================================

def benchmark_proof_generation(
    num_leaves: int,
    previous_event_id_hex: str,
    iterations: int = 1
) -> dict:
    """Benchmark ZK proof generation for different tree sizes.
    
    Args:
        num_leaves: Number of leaves in Cantor tree
        previous_event_id_hex: Previous event ID for temporal seed
        iterations: Number of iterations for averaging
        
    Returns:
        Dictionary with benchmark statistics
    """
    leaves = list(range(num_leaves))
    
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        proof = prove_cantor_tree(leaves, previous_event_id_hex)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    import statistics
    
    return {
        "num_leaves": num_leaves,
        "tree_height": num_leaves.bit_length() if num_leaves > 0 else 0,
        "iterations": iterations,
        "mean_time_s": statistics.mean(times),
        "stddev_s": statistics.stdev(times) if len(times) > 1 else 0.0,
        "proof_size_bytes": proof.proof_size_bytes,
        "root_hex": proof.public_inputs.root_hex,
    }


def benchmark_verification(
    num_leaves: int,
    previous_event_id_hex: str,
    iterations: int = 10
) -> dict:
    """Benchmark ZK proof verification for different tree sizes.
    
    Args:
        num_leaves: Number of leaves
        previous_event_id_hex: Previous event ID
        iterations: Number of verification iterations
        
    Returns:
        Dictionary with benchmark statistics
    """
    # Generate proof first
    leaves = list(range(num_leaves))
    proof = prove_cantor_tree(leaves, previous_event_id_hex)
    expected_root = build_hyperspace_proof(leaves)
    
    # Benchmark verification
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        is_valid, _ = verify_cantor_proof(proof, expected_root)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        assert is_valid, "Verification failed during benchmark"
    
    import statistics
    
    elapsed_ms = statistics.mean(times) * 1000
    
    return {
        "num_leaves": num_leaves,
        "iterations": iterations,
        "mean_time_ms": elapsed_ms,
        "stddev_ms": statistics.stdev(times) * 1000 if len(times) > 1 else 0.0,
        "meets_target": elapsed_ms < 10.0,
        "target_ms": 10.0,
    }
