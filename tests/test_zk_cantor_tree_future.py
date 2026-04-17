"""Tests for ZK-STARK full Cantor tree proofs.

These tests verify the interface and correctness of ZK proof generation
and verification for complete Cantor trees (not just single pairs).

Note: This is a PoC/mock implementation. Production would use cairo-lang
or a Rust-based STARK backend.
"""

import os
import pytest

from cyberspace_core.cantor import build_hyperspace_proof, compute_temporal_seed
from cyberspace_core.zk_cantor import (
    prove_cantor_tree,
    verify_cantor_tree,
    prove_hyperspace_traversal,
    verify_hyperspace_traversal,
    ZKCantorProof,
)


class TestCantorTreeProof:
    """Test full Cantor tree ZK proof."""

    def test_prove_and_verify_height_3_tree(self):
        """Test ZK proof for height-3 Cantor tree (8 leaves)."""
        leaves = [1, 2, 3, 4, 5, 6, 7, 8]

        # Compute expected root using standard Cantor
        expected_root = build_hyperspace_proof(leaves)

        # Generate ZK proof
        root, proof = prove_cantor_tree(leaves)

        # Verify root matches
        assert root == expected_root

        # Verify ZK proof
        assert verify_cantor_tree(root, leaves, proof) is True

    def test_prove_and_verify_height_4_tree(self):
        """Test ZK proof for height-4 Cantor tree (16 leaves)."""
        leaves = list(range(1, 17))

        expected_root = build_hyperspace_proof(leaves)
        root, proof = prove_cantor_tree(leaves)

        assert root == expected_root
        assert verify_cantor_tree(root, leaves, proof) is True

    def test_verify_fails_with_wrong_root(self):
        """Test that verification fails with incorrect root."""
        leaves = [10, 20, 30, 40]
        root, proof = prove_cantor_tree(leaves)

        # Tamper with root
        wrong_root = root + 1

        # Verification should fail
        assert verify_cantor_tree(wrong_root, leaves, proof) is False

    def test_verify_fails_with_tampered_proof(self):
        """Test that verification fails with tampered proof."""
        leaves = [100, 200, 300]
        root, proof = prove_cantor_tree(leaves)

        # Tamper with proof bytes
        tampered_proof = ZKCantorProof(
            root=proof.root,
            leaf_count=proof.leaf_count,
            stark_proof=bytes([b ^ 0xFF for b in proof.stark_proof]),
            constraint_count=proof.constraint_count,
        )

        # Verification should fail
        assert verify_cantor_tree(root, leaves, tampered_proof) is False

    def test_proof_contains_expected_metadata(self):
        """Test that proof contains expected metadata."""
        leaves = [42, 17, 99, 3, 7]
        root, proof = prove_cantor_tree(leaves)

        assert proof.root == root
        assert proof.leaf_count == len(leaves)
        assert proof.constraint_count > 0
        assert len(proof.stark_proof) > 0

    def test_deterministic_proof(self):
        """Test that same inputs produce same proof."""
        leaves = [100, 200, 300, 400]

        root1, proof1 = prove_cantor_tree(leaves)
        root2, proof2 = prove_cantor_tree(leaves)

        assert root1 == root2
        assert proof1.stark_proof == proof2.stark_proof
        assert proof1.constraint_count == proof2.constraint_count

    def test_single_leaf_trivial_case(self):
        """Test single leaf (trivial case: leaf is its own root)."""
        leaves = [12345]

        root, proof = prove_cantor_tree(leaves)

        assert root == 12345
        assert proof.leaf_count == 1
        assert proof.constraint_count == 0
        assert proof.stark_proof == b"SINGLE_LEAF"
        assert verify_cantor_tree(root, leaves, proof) is True

    def test_two_leaves_delegates_to_pair(self):
        """Test two leaves delegates to single pair proof."""
        leaves = [42, 17]

        root, proof = prove_cantor_tree(leaves)

        assert proof.leaf_count == 2
        assert proof.constraint_count == 3  # Cantor pair has 3 constraints
        assert verify_cantor_tree(root, leaves, proof) is True

    def test_odd_leaf_count(self):
        """Test tree with odd number of leaves (5 leaves)."""
        leaves = [1, 2, 3, 4, 5]

        expected_root = build_hyperspace_proof(leaves)
        root, proof = prove_cantor_tree(leaves)

        assert root == expected_root
        assert proof.leaf_count == 5
        assert verify_cantor_tree(root, leaves, proof) is True

    def test_large_leaf_values(self):
        """Test tree with large leaf values (256-bit range)."""
        leaves = [2**128, 2**200, 2**256 - 1, 123456789]

        expected_root = build_hyperspace_proof(leaves)
        root, proof = prove_cantor_tree(leaves)

        assert root == expected_root
        assert verify_cantor_tree(root, leaves, proof) is True

    def test_empty_leaves_rejected(self):
        """Test that empty leaves list is rejected."""
        with pytest.raises(ValueError, match="leaves list cannot be empty"):
            prove_cantor_tree([])

        # Verification should also fail
        assert verify_cantor_tree(0, [], None) is False  # type: ignore


class TestHyperspaceTraversalProof:
    """Test Hyperspace traversal ZK proof (DECK-0001 §8)."""

    def test_prove_and_verify_single_block_jump(self):
        """Test ZK proof for 1-block hyperjump."""
        prev_event_id = os.urandom(32)
        from_height = 1606
        to_height = 1607

        # Generate proof
        root, proof = prove_hyperspace_traversal(prev_event_id, from_height, to_height)

        # Verify
        assert verify_hyperspace_traversal(root, prev_event_id, from_height, to_height, proof) is True

    def test_leaf_count_includes_temporal_seed(self):
        """Test that leaf count includes temporal seed."""
        prev_event_id = os.urandom(32)
        from_height = 100
        to_height = 105  # 6 blocks

        root, proof = prove_hyperspace_traversal(prev_event_id, from_height, to_height)

        # Expected: 1 (temporal_seed) + 6 (block heights) = 7 leaves
        assert proof.leaf_count == 7

    def test_proof_incorporates_temporal_seed(self):
        """Test that different previous events produce different proofs."""
        prev_event_id_1 = os.urandom(32)
        prev_event_id_2 = os.urandom(32)
        from_height = 500
        to_height = 501

        root1, proof1 = prove_hyperspace_traversal(prev_event_id_1, from_height, to_height)
        root2, proof2 = prove_hyperspace_traversal(prev_event_id_2, from_height, to_height)

        # Different temporal seeds should produce different roots
        assert root1 != root2
        assert proof1.stark_proof != proof2.stark_proof

    def test_verify_fails_with_wrong_previous_event(self):
        """Test that verification fails with wrong previous event ID."""
        prev_event_id = os.urandom(32)
        wrong_prev_id = os.urandom(32)
        from_height = 800
        to_height = 801

        root, proof = prove_hyperspace_traversal(prev_event_id, from_height, to_height)

        # Verification with wrong prev_event_id should fail
        assert verify_hyperspace_traversal(root, wrong_prev_id, from_height, to_height, proof) is False

    def test_verify_fails_with_wrong_heights(self):
        """Test that verification fails with incorrect block heights."""
        prev_event_id = os.urandom(32)
        from_height = 1000
        to_height = 1002

        root, proof = prove_hyperspace_traversal(prev_event_id, from_height, to_height)

        # Verification with wrong heights should fail
        assert verify_hyperspace_traversal(root, prev_event_id, 1000, 1003, proof) is False
        assert verify_hyperspace_traversal(root, prev_event_id, 999, 1002, proof) is False

    def test_invalid_height_range_rejected(self):
        """Test that from_height > to_height is rejected."""
        prev_event_id = os.urandom(32)

        with pytest.raises(ValueError, match="from_height must be <= to_height"):
            prove_hyperspace_traversal(prev_event_id, 500, 499)

    def test_invalid_prev_event_length_rejected(self):
        """Test that non-32-byte prev_event_id is rejected."""
        prev_event_id = os.urandom(31)  # Wrong length

        with pytest.raises(ValueError, match="previous_event_id must be 32 bytes"):
            prove_hyperspace_traversal(prev_event_id, 100, 101)

        # Verification should also return False
        root, _ = prove_hyperspace_traversal(os.urandom(32), 100, 101)
        assert verify_hyperspace_traversal(root, prev_event_id, 100, 101, None) is False  # type: ignore

    def test_multi_block_jump(self):
        """Test ZK proof for multi-block hyperjump (10 blocks)."""
        prev_event_id = os.urandom(32)
        from_height = 10000
        to_height = 10010  # 11 leaves total (temporal seed + 11 heights)

        root, proof = prove_hyperspace_traversal(prev_event_id, from_height, to_height)

        assert proof.leaf_count == 12
        assert verify_hyperspace_traversal(root, prev_event_id, from_height, to_height, proof) is True

    def test_temporal_seed_prevents_replay(self):
        """Test that temporal seed binding prevents proof replay attacks.
        
        This is the critical security property: even with the same path,
        different chain positions (prev_event_id) produce different proofs.
        """
        from_height = 2000
        to_height = 2001

        # Simulate two different chain positions
        prev_event_id_1 = bytes([0] * 32)  # Position 1
        prev_event_id_2 = bytes([255] * 32)  # Position 2

        root1, proof1 = prove_hyperspace_traversal(prev_event_id_1, from_height, to_height)
        root2, proof2 = prove_hyperspace_traversal(prev_event_id_2, from_height, to_height)

        # Same path, different positions = different proofs
        assert root1 != root2
        assert proof1.stark_proof != proof2.stark_proof

        # Proof from position 1 should NOT verify at position 2
        assert verify_hyperspace_traversal(root1, prev_event_id_2, from_height, to_height, proof1) is False
        assert verify_hyperspace_traversal(root2, prev_event_id_1, from_height, to_height, proof2) is False


class TestConstraintCounting:
    """Test constraint count calculations."""

    def test_constraint_count_scales_with_tree_size(self):
        """Test that constraint count increases with tree size."""
        _, proof_4 = prove_cantor_tree([1, 2, 3, 4])
        _, proof_8 = prove_cantor_tree(list(range(8)))
        _, proof_16 = prove_cantor_tree(list(range(16)))

        assert proof_4.constraint_count < proof_8.constraint_count
        assert proof_8.constraint_count < proof_16.constraint_count

    def test_constraint_count_formula(self):
        """Verify constraint count formula: N-1 pairings × 3 constraints + log2(N) reduction."""
        leaves = [1, 2, 3, 4, 5, 6, 7, 8]  # 8 leaves
        _, proof = prove_cantor_tree(leaves)

        # 7 pairings × 3 constraints = 21
        # log2(8) = 3, so 3-1 = 2 reduction constraints
        # Total: 21 + 2 = 23
        expected_constraints = (len(leaves) - 1) * 3 + (len(leaves).bit_length() - 1)
        assert proof.constraint_count == expected_constraints
