"""ZK-STARK proofs for Cantor tree verification (PoC/Mock implementation).

This module provides zero-knowledge proof interfaces for Cyberspace Cantor tree
computations. Currently implements a mock/simulation backend for PoC purposes.

Production deployment would replace the mock backend with:
- cairo-lang (StarkWare's Cairo VM and STARK proofs)
- Custom Rust implementation with PyO3 bindings
- Other production STARK backends as they mature

The interface is designed to be backend-agnostic - swap the implementation,
keep the API.

Example usage:
    >>> from cyberspace_core.zk_cantor import prove_single_cantor_pair, verify_single_cantor_pair
    >>> z, proof = prove_single_cantor_pair(3, 5)
    >>> assert verify_single_cantor_pair(z, proof) is True
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Tuple, Optional

from cyberspace_core.cantor import cantor_pair, build_hyperspace_proof, int_to_bytes_be_min


@dataclass(frozen=True)
class ZKCantorProof:
    """A ZK-STARK proof of correct Cantor tree computation.

    Attributes:
        root: The Cantor tree root (public input)
        leaf_count: Number of leaves in the tree (public)
        stark_proof: Serialized STARK proof bytes
        constraint_count: Number of AIR constraints in the proof system
    """

    root: int  # The Cantor tree root (public)
    leaf_count: int  # Number of leaves (public)
    stark_proof: bytes  # The STARK proof object (serialized)
    constraint_count: int  # Number of AIR constraints


def _generate_mock_stark_proof(witness: bytes, public_inputs: bytes) -> bytes:
    """Generate a mock STARK proof for PoC purposes.

    This simulates what a real STARK proof would look like:
    1. Commit to witness (computation trace)
    2. Generate FRI proof of proximity
    3. Serialize proof object

    In production, this would call cairo-lang or Rust STARK backend.

    Args:
        witness: The computation trace (private inputs)
        public_inputs: Public inputs to the circuit

    Returns:
        Serialized proof bytes
    """
    # Mock proof generation: hash of witness + public inputs + metadata
    # This demonstrates the interface, not actual ZK cryptography
    proof_data = hashlib.sha256(witness + public_inputs).digest()

    # Add mock "FRI layers" (in real STARK, these are Merkle paths)
    fri_layers = b"".join(
        hashlib.sha256(proof_data + bytes([i])).digest()[:8]
        for i in range(4)  # Mock 4 FRI layers
    )

    # Serialize: proof_data + fri_layers + metadata
    mock_proof = (
        proof_data +  # 32 bytes: commitment
        fri_layers +  # 32 bytes: mock FRI proof
        b"CANTOR_POC_V1"  # Proof system identifier
    )

    return mock_proof


def _verify_mock_stark_proof(
    proof_bytes: bytes,
    public_inputs: bytes,
    expected_constraints: int,
) -> bool:
    """Verify a mock STARK proof.

    In production, this would call the STARK verifier which checks:
    1. Proof format and commitment openings
    2. AIR constraints satisfaction
    3. FRI proximity testing
    4. Soundness bounds

    For PoC, we verify the mock proof structure.

    Args:
        proof_bytes: Serialized proof to verify
        public_inputs: Public inputs to the circuit
        expected_constraints: Expected number of constraints

    Returns:
        True if proof is valid, False otherwise
    """
    try:
        # Check minimum size
        min_size = 32 + 32 + len(b"CANTOR_POC_V1")
        if len(proof_bytes) < min_size:
            return False

        # Extract proof system identifier
        identifier_offset = 32 + 32
        identifier = proof_bytes[identifier_offset:]
        if not identifier.startswith(b"CANTOR_POC_V1"):
            return False

        # Mock verification: recompute expected proof hash
        # In real STARK, this involves checking polynomial commitments
        proof_commitment = proof_bytes[:32]

        # For mock: we accept any well-formed proof
        # (Real verification would be cryptographic)
        return True

    except Exception:
        return False


def prove_single_cantor_pair(x: int, y: int) -> Tuple[int, ZKCantorProof]:
    """Generate ZK proof for a single Cantor pairing: π(x, y) = z.

    This is the minimal PoC: prove correct computation of one Cantor pair.

    The proof demonstrates that the prover:
    1. Knows x and y (private inputs in real ZK)
    2. Correctly computed z = π(x, y) using Cantor formula
    3. Did so without revealing x, y (in real ZK - mocked here)

    Args:
        x: First input to Cantor pairing
        y: Second input to Cantor pairing

    Returns:
        Tuple of (result, proof) where result = π(x, y)

    Example:
        >>> z, proof = prove_single_cantor_pair(3, 5)
        >>> z
        28
        >>> proof.leaf_count
        2
    """
    # Compute the actual Cantor pairing (this is the "work")
    z = cantor_pair(x, y)

    # Build witness (computation trace)
    # In real STARK, this would include all intermediate values
    # s = x + y
    # s_squared_plus_s = s * (s + 1)
    # halved = s_squared_plus_s // 2
    # z = halved + y
    s = x + y
    intermediate = s * (s + 1) // 2

    witness = (
        x.to_bytes(32, "big") +
        y.to_bytes(32, "big") +
        s.to_bytes(32, "big") +
        intermediate.to_bytes(32, "big") +
        z.to_bytes(32, "big")
    )

    # Public inputs: just the result z
    public_inputs = z.to_bytes(32, "big")

    # Generate mock STARK proof
    stark_proof = _generate_mock_stark_proof(witness, public_inputs)

    # Cantor pairing AIR has 3 constraints:
    # 1. s = x + y
    # 2. intermediate = s * (s + 1) / 2
    # 3. z = intermediate + y
    constraint_count = 3

    return z, ZKCantorProof(
        root=z,
        leaf_count=2,  # Two inputs: x and y
        stark_proof=stark_proof,
        constraint_count=constraint_count,
    )


def verify_single_cantor_pair(z: int, proof: ZKCantorProof) -> bool:
    """Verify ZK proof for a single Cantor pairing.

    This is the "fast path" - verification should be much faster than
    recomputing the Cantor pairing (in real STARK, O(log N) vs O(N)).

    For PoC mock implementation, verification is trivial but demonstrates
    the interface.

    Args:
        z: The claimed result of Cantor pairing
        proof: The ZK proof to verify

    Returns:
        True if proof is valid, False otherwise

    Example:
        >>> z, proof = prove_single_cantor_pair(42, 17)
        >>> verify_single_cantor_pair(z, proof)
        True
        >>> verify_single_cantor_pair(z + 1, proof)
        False
    """
    # Check proof structure
    if proof.root != z:
        return False

    if proof.leaf_count != 2:
        return False

    if proof.constraint_count != 3:
        return False

    # Public inputs for verification
    public_inputs = z.to_bytes(32, "big")

    # Verify the STARK proof
    # In production: calls cairo-lang or Rust verifier
    # For PoC: checks mock proof structure
    return _verify_mock_stark_proof(
        proof.stark_proof,
        public_inputs,
        proof.constraint_count,
    )


# ---------------------------------------------------------------------------
# Future extensions (not yet implemented):
# - prove_cantor_tree(leaves) -> full tree proof
# - verify_cantor_tree(root, proof) -> tree verification
# - Integration with cyberspace-cli verify-zk command
# ---------------------------------------------------------------------------

def prove_cantor_tree(leaves: List[int]) -> Tuple[int, ZKCantorProof]:
    """Generate ZK proof for a full Cantor tree computation.
    
    This extends the single-pair proof to handle the complete Cantor tree
    used in Cyberspace hop/hyperjump/sidestep actions.
    
    The proof demonstrates that the prover:
    1. Knows all leaves (private inputs in real ZK)
    2. Correctly computed the tree root using Cantor pairing throughout
    3. Did so without necessarily revealing intermediate nodes (in real ZK)
    
    Args:
        leaves: List of leaf values [l₁, l₂, ..., lₙ]
               For hyperjump: [temporal_seed, B_from, B_from+1, ..., B_to]
               For hop: [temporal_seed, coord₁, coord₂, ..., coordₙ]
    
    Returns:
        Tuple of (root, proof) where root is the Cantor tree root
        
    Example:
        >>> leaves = [12345, 100, 101, 102]  # temporal_seed + 3 coords
        >>> root, proof = prove_cantor_tree(leaves)
        >>> proof.leaf_count
        4
    """
    if not leaves:
        raise ValueError("leaves list cannot be empty")
    
    if len(leaves) == 1:
        # Trivial case: single leaf is its own root
        root = leaves[0]
        return root, ZKCantorProof(
            root=root,
            leaf_count=1,
            stark_proof=b"SINGLE_LEAF",
            constraint_count=0,
        )
    
    if len(leaves) == 2:
        # Delegate to single pair proof
        z, pair_proof = prove_single_cantor_pair(leaves[0], leaves[1])
        return z, pair_proof
    
    # General case: build full tree with ZK proof
    # Step 1: Compute actual Cantor tree root (the "work")
    root = build_hyperspace_proof(leaves)
    
    # Step 2: Build witness (computation trace)
    # In real STARK, this includes all intermediate tree nodes
    # Use variable-length encoding for leaves
    # Format: [length_byte] [bytes...] for length < 255
    #         [255] [2-byte-length] [bytes...] for length >= 255
    witness_data = b""
    for leaf in leaves:
        leaf_bytes = int_to_bytes_be_min(leaf)
        if len(leaf_bytes) < 255:
            witness_data += bytes([len(leaf_bytes)]) + leaf_bytes
        else:
            length_bytes = len(leaf_bytes).to_bytes(2, "big")
            witness_data += bytes([255]) + length_bytes + leaf_bytes
    
    # Calculate total Cantor pairings: N-1 for N leaves
    num_pairings = len(leaves) - 1
    
    # Build intermediate node trace (for real STARK, this is the execution trace)
    current_level = leaves
    intermediate_trace = []
    
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level) - 1, 2):
            pair_result = cantor_pair(current_level[i], current_level[i + 1])
            intermediate_trace.append(pair_result)
            next_level.append(pair_result)
        
        # Handle odd leaf (carried forward per Cantor tree spec)
        if len(current_level) % 2 == 1:
            next_level.append(current_level[-1])
        
        current_level = next_level
    
    # Add intermediate nodes to witness
    # Use variable-length encoding with length prefix
    # Format: [length_byte] [bytes...] for length < 255
    #         [255] [2-byte-length] [bytes...] for length >= 255
    for node in intermediate_trace:
        node_bytes = int_to_bytes_be_min(node)
        if len(node_bytes) < 255:
            witness_data += bytes([len(node_bytes)]) + node_bytes
        else:
            # Use 2-byte length prefix for very large values
            length_bytes = len(node_bytes).to_bytes(2, "big")
            witness_data += bytes([255]) + length_bytes + node_bytes
    
    # Add metadata
    witness_data += len(leaves).to_bytes(8, "big")
    witness_data += num_pairings.to_bytes(8, "big")
    
    # Step 3: Public inputs (root and leaf count, using variable-length encoding)
    # Format: [length_byte] [root_bytes...] for length < 255
    #         [255] [2-byte-length] [root_bytes...] for length >= 255
    root_bytes = int_to_bytes_be_min(root)
    if len(root_bytes) < 255:
        public_inputs = bytes([len(root_bytes)]) + root_bytes + len(leaves).to_bytes(8, "big")
    else:
        length_bytes = len(root_bytes).to_bytes(2, "big")
        public_inputs = bytes([255]) + length_bytes + root_bytes + len(leaves).to_bytes(8, "big")
    
    # Step 4: Generate mock STARK proof
    stark_proof = _generate_mock_stark_proof(witness_data, public_inputs)
    
    # Step 5: Calculate constraint count
    # Each Cantor pairing has 3 constraints (s=x+y, intermediate=s*(s+1)/2, z=intermediate+y)
    # Tree construction adds log2(N) reduction constraints
    constraint_count = num_pairings * 3 + (len(leaves).bit_length() - 1)
    
    return root, ZKCantorProof(
        root=root,
        leaf_count=len(leaves),
        stark_proof=stark_proof,
        constraint_count=constraint_count,
    )


def verify_cantor_tree(root: int, leaves: List[int], proof: ZKCantorProof) -> bool:
    """Verify ZK proof for a full Cantor tree computation.
    
    This is the "fast path" - in real STARK implementation, verification
    is O(log N) regardless of tree size, compared to O(N) for full recomputation.
    
    For mock implementation, we verify proof structure and check the root
    matches what would be computed from the leaves.
    
    Args:
        root: The claimed Cantor tree root
        leaves: The leaf values used to construct the tree
        proof: The ZK proof to verify
    
    Returns:
        True if proof is valid, False otherwise
        
    Example:
        >>> leaves = [12345, 100, 101, 102]
        >>> root, proof = prove_cantor_tree(leaves)
        >>> verify_cantor_tree(root, leaves, proof)
        True
    """
    if not leaves:
        return False
    
    # Check proof metadata matches
    if proof.root != root:
        return False
    
    if proof.leaf_count != len(leaves):
        return False
    
    # Verify proof structure
    if len(proof.stark_proof) == 0:
        return False
    
    # Check proof system identifier
    if not proof.stark_proof.startswith(b"SINGLE_LEAF") and len(proof.stark_proof) < 32:
        return False
    
    # For single leaf case
    if len(leaves) == 1:
        return leaves[0] == root and proof.stark_proof == b"SINGLE_LEAF"
    
    # For two leaves, use pair verification
    if len(leaves) == 2:
        return verify_single_cantor_pair(root, proof)
    
    # For mock implementation: verify root matches recomputed value
    # In real STARK, this would be the fast cryptographic verification
    # without recomputing the full tree
    expected_root = build_hyperspace_proof(leaves)
    
    if proof.root != expected_root:
        return False
    
    # Verify mock proof structure (production would verify cryptographic proof)
    root_bytes = int_to_bytes_be_min(proof.root)
    if len(root_bytes) < 255:
        public_inputs = bytes([len(root_bytes)]) + root_bytes + len(leaves).to_bytes(8, "big")
    else:
        length_bytes = len(root_bytes).to_bytes(2, "big")
        public_inputs = bytes([255]) + length_bytes + root_bytes + len(leaves).to_bytes(8, "big")
    return _verify_mock_stark_proof(
        proof.stark_proof,
        public_inputs,
        proof.constraint_count,
    )


def prove_hyperspace_traversal(
    previous_event_id: bytes,
    from_height: int,
    to_height: int,
) -> Tuple[int, ZKCantorProof]:
    """Generate ZK proof for Hyperspace traversal (DECK-0001 §8).
    
    This is the convenience wrapper for the common case of hyperjump proofs.
    Constructs leaves as [temporal_seed, B_from, B_from+1, ..., B_to] per spec.
    
    Args:
        previous_event_id: 32-byte event ID of the previous movement event
        from_height: Starting Bitcoin block height
        to_height: Destination Bitcoin block height
    
    Returns:
        Tuple of (proof_root, zk_proof)
        
    Example:
        >>> import os
        >>> prev_id = os.urandom(32)
        >>> root, proof = prove_hyperspace_traversal(prev_id, 1606, 1607)
        >>> proof.leaf_count
        3  # temporal_seed + 1606 + 1607
    """
    from cyberspace_core.cantor import compute_temporal_seed
    
    if len(previous_event_id) != 32:
        raise ValueError("previous_event_id must be 32 bytes")
    
    # Compute temporal seed from previous event ID
    temporal_seed = compute_temporal_seed(previous_event_id)
    
    # Build leaves: [temporal_seed, B_from, B_from+1, ..., B_to]
    if from_height > to_height:
        raise ValueError("from_height must be <= to_height")
    
    leaves = [temporal_seed] + list(range(from_height, to_height + 1))
    
    # Generate proof
    return prove_cantor_tree(leaves)


def verify_hyperspace_traversal(
    root: int,
    previous_event_id: bytes,
    from_height: int,
    to_height: int,
    proof: ZKCantorProof,
) -> bool:
    """Verify ZK proof for Hyperspace traversal.
    
    Convenience wrapper for hyperjump verification.
    
    Args:
        root: The claimed Cantor tree root
        previous_event_id: 32-byte event ID of previous movement
        from_height: Starting Bitcoin block height
        to_height: Destination Bitcoin block height
        proof: The ZK proof to verify
    
    Returns:
        True if proof is valid, False otherwise
    """
    from cyberspace_core.cantor import compute_temporal_seed
    
    if len(previous_event_id) != 32:
        return False
    
    # Reconstruct expected leaves
    temporal_seed = compute_temporal_seed(previous_event_id)
    
    if from_height > to_height:
        return False
    
    leaves = [temporal_seed] + list(range(from_height, to_height + 1))
    
    # Verify using general tree verification
    return verify_cantor_tree(root, leaves, proof)
