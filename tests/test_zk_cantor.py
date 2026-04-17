"""Tests for ZK-STARK Cantor proofs.

These tests verify the interface and correctness of ZK proof generation
and verification for Cantor tree computations.

Note: This is a PoC/mock implementation. Production would use cairo-lang
or a Rust-based STARK backend.
"""

import pytest
from cyberspace_core.cantor import cantor_pair
from cyberspace_core.zk_cantor import (
    prove_single_cantor_pair,
    verify_single_cantor_pair,
    ZKCantorProof,
)


class TestSingleCantorPair:
    """Test single Cantor pair ZK proof."""

    def test_prove_and_verify_small_numbers(self):
        """Test ZK proof for π(3, 5) = 28."""
        x, y = 3, 5
        expected_z = cantor_pair(x, y)  # Should be 28

        # Generate proof
        z, proof = prove_single_cantor_pair(x, y)

        # Verify result is correct
        assert z == expected_z

        # Verify ZK proof
        assert verify_single_cantor_pair(z, proof) is True

    def test_prove_and_verify_larger_numbers(self):
        """Test ZK proof with larger inputs."""
        x, y = 1000, 2000
        expected_z = cantor_pair(x, y)

        z, proof = prove_single_cantor_pair(x, y)
        assert z == expected_z
        assert verify_single_cantor_pair(z, proof) is True

    def test_verify_fails_with_wrong_result(self):
        """Test that verification fails with incorrect result."""
        x, y = 3, 5
        z, proof = prove_single_cantor_pair(x, y)

        # Tamper with result
        wrong_z = z + 1

        # Verification should fail
        assert verify_single_cantor_pair(wrong_z, proof) is False

    def test_verify_fails_with_tampered_proof(self):
        """Test that verification fails with tampered proof."""
        x, y = 3, 5
        z, proof = prove_single_cantor_pair(x, y)

        # Tamper with proof bytes
        tampered_proof = ZKCantorProof(
            root=proof.root,
            leaf_count=proof.leaf_count,
            stark_proof=bytes([b ^ 0xFF for b in proof.stark_proof]),  # Flip all bits
            constraint_count=proof.constraint_count,
        )

        # Verification should fail
        assert verify_single_cantor_pair(z, tampered_proof) is False

    def test_proof_contains_expected_metadata(self):
        """Test that proof contains expected metadata."""
        x, y = 42, 17
        z, proof = prove_single_cantor_pair(x, y)

        assert proof.root == z
        assert proof.leaf_count == 2  # Two inputs: x and y
        assert proof.constraint_count > 0
        assert len(proof.stark_proof) > 0  # Non-empty proof bytes

    def test_deterministic_proof(self):
        """Test that same inputs produce same proof."""
        x, y = 100, 200

        z1, proof1 = prove_single_cantor_pair(x, y)
        z2, proof2 = prove_single_cantor_pair(x, y)

        assert z1 == z2
        assert proof1.stark_proof == proof2.stark_proof
        assert proof1.constraint_count == proof2.constraint_count
