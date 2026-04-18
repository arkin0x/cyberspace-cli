"""
Tests for ZK-STARK Cantor proof integration.

These tests verify the API design and integration pattern.
When a real STARK library is integrated, these tests will
validate the actual STARK proving/verification.
"""

import unittest
import time

from cyberspace_core.cantor import cantor_pair, build_hyperspace_proof, compute_temporal_seed
from cyberspace_core.zk_stark import (
    CantorZKPublicInputs,
    CantorZKProof,
    prove_cantor_single_pair,
    prove_cantor_tree,
    verify_cantor_proof,
    add_zk_tags_to_event,
    extract_zk_proof_from_event,
)


class TestCantorZKPublicInputs(unittest.TestCase):
    """Test public inputs serialization."""
    
    def test_serialization(self):
        """Public inputs should serialize to hex."""
        inputs = CantorZKPublicInputs(
            root_hex="0x1234abcd",
            leaf_count=42,
            temporal_commitment="0xdeadbeef"
        )
        
        hex_str = inputs.to_hex()
        
        # Check it returns a valid hex string
        self.assertIsInstance(hex_str, str)
        self.assertEqual(len(hex_str), 64)  # SHA256 hash


class TestProveCantorSinglePair(unittest.TestCase):
    """Test single Cantor pair proof generation."""
    
    def test_single_pair_proof(self):
        """Should generate a proof for π(x, y) = z."""
        x, y = 42, 17
        expected = cantor_pair(x, y)
        
        proof = prove_cantor_single_pair(x, y, expected)
        
        # Check proof structure
        self.assertIsInstance(proof, CantorZKProof)
        self.assertEqual(proof.scheme, "poc-commitment-v1")
        self.assertEqual(proof.public_inputs.leaf_count, 2)
        
        # Verify root matches
        root_from_proof = int(proof.public_inputs.root_hex, 16)
        self.assertEqual(root_from_proof, expected)
    
    def test_proof_different_inputs(self):
        """Different inputs should produce different proofs."""
        x1, y1 = 10, 20
        x2, y2 = 30, 40
        
        proof1 = prove_cantor_single_pair(x1, y1, cantor_pair(x1, y1))
        proof2 = prove_cantor_single_pair(x2, y2, cantor_pair(x2, y2))
        
        self.assertNotEqual(proof1.proof_hex, proof2.proof_hex)
        self.assertNotEqual(
            proof1.public_inputs.root_hex,
            proof2.public_inputs.root_hex
        )


class TestProveCantorTree(unittest.TestCase):
    """Test full Cantor tree proof generation."""
    
    def test_tree_proof_3_leaves(self):
        """Should generate proof for 3-leaf tree (like hyperspace entry)."""
        leaves = [100, 200, 300]
        prev_event_id = "a" * 64  # 32-byte hex
        
        proof = prove_cantor_tree(leaves, prev_event_id)
        
        self.assertIsInstance(proof, CantorZKProof)
        self.assertEqual(proof.public_inputs.leaf_count, 3)
        
        # Verify root matches actual computation
        expected_root = build_hyperspace_proof(leaves)
        root_from_proof = int(proof.public_inputs.root_hex, 16)
        self.assertEqual(root_from_proof, expected_root)
    
    def test_tree_proof_temporal_seed_binding(self):
        """Different previous_event_id should produce different temporal commitment."""
        leaves = [100, 200]
        prev_id_1 = "a" * 64
        prev_id_2 = "b" * 64
        
        proof1 = prove_cantor_tree(leaves, prev_id_1)
        proof2 = prove_cantor_tree(leaves, prev_id_2)
        
        self.assertNotEqual(
            proof1.public_inputs.temporal_commitment,
            proof2.public_inputs.temporal_commitment
        )
    
    def test_tree_proof_larger(self):
        """Should handle larger trees (simulating height 10+)."""
        # Height 10 = 2^10 = 1024 leaves
        leaves = list(range(1024))
        prev_event_id = "c" * 64
        
        proof = prove_cantor_tree(leaves, prev_event_id)
        
        self.assertEqual(proof.public_inputs.leaf_count, 1024)
        
        expected_root = build_hyperspace_proof(leaves)
        root_from_proof = int(proof.public_inputs.root_hex, 16)
        self.assertEqual(root_from_proof, expected_root)


class TestVerifyCantorProof(unittest.TestCase):
    """Test proof verification."""
    
    def test_verify_valid_proof(self):
        """Should verify a valid proof."""
        x, y = 42, 17
        expected = cantor_pair(x, y)
        
        proof = prove_cantor_single_pair(x, y, expected)
        verified = verify_cantor_proof(proof, expected)
        
        self.assertTrue(verified)
    
    def test_verify_root_mismatch(self):
        """Should fail verification with wrong root."""
        x, y = 42, 17
        expected = cantor_pair(x, y)
        wrong_root = expected + 1
        
        proof = prove_cantor_single_pair(x, y, expected)
        verified, _ = verify_cantor_proof(proof, wrong_root)
        
        self.assertFalse(verified)
    
    def test_verification_time(self):
        """Verification should be fast (< 10 ms target)."""
        # Create a "large" tree proof
        leaves = list(range(1024))
        prev_event_id = "d" * 64
        
        proof = prove_cantor_tree(leaves, prev_event_id)
        expected_root = build_hyperspace_proof(leaves)
        
        # Time the verification
        start = time.perf_counter()
        verified, _ = verify_cantor_proof(proof, expected_root)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        self.assertTrue(verified)
        self.assertLess(elapsed_ms, 10.0, f"Verification took {elapsed_ms:.3f}ms, target is <10ms")
        print(f"\n✅ Verification time: {elapsed_ms:.3f} ms (target: <10 ms)")


class TestNostrIntegration(unittest.TestCase):
    """Test Nostr event tag integration."""
    
    def test_add_zk_tags_to_event(self):
        """Should add ZK tags to Nostr event."""
        event = {
            "kind": 3333,
            "tags": [
                ["A", "hop"],
                ["proof", "0x1234"]
            ],
            "content": ""
        }
        
        x, y = 42, 17
        proof = prove_cantor_single_pair(x, y, cantor_pair(x, y))
        
        result = add_zk_tags_to_event(event, proof)
        
        # Check new tags were added
        tag_names = [tag[0] for tag in result["tags"]]
        self.assertIn("zk_proof", tag_names)
        self.assertIn("zk_public_inputs", tag_names)
        self.assertIn("zk_scheme", tag_names)
        
        # Original tags preserved
        self.assertIn(["A", "hop"], result["tags"])
    
    def test_extract_zk_proof_from_event(self):
        """Should extract ZK proof from Nostr event."""
        event = {"tags": []}
        
        x, y = 42, 17
        original_proof = prove_cantor_single_pair(x, y, cantor_pair(x, y))
        
        # Add proof to event
        event = add_zk_tags_to_event(event, original_proof)
        
        # Extract it back
        extracted = extract_zk_proof_from_event(event)
        
        self.assertIsInstance(extracted, CantorZKProof)
        self.assertEqual(extracted.scheme, original_proof.scheme)
        self.assertEqual(
            extracted.public_inputs.root_hex,
            original_proof.public_inputs.root_hex
        )
    
    def test_extract_no_proof(self):
        """Should return None if no ZK proof present."""
        event = {
            "kind": 3333,
            "tags": [["A", "hop"]]
        }
        
        extracted = extract_zk_proof_from_event(event)
        self.assertIsNone(extracted)


class TestEndToEnd(unittest.TestCase):
    """End-to-end integration tests."""
    
    def test_full_workflow(self):
        """Complete workflow: prove → add to event → extract → verify."""
        # 1. Generate proof
        leaves = [100, 200, 300, 400, 500]
        prev_event_id = "e" * 64
        
        proof = prove_cantor_tree(leaves, prev_event_id)
        expected_root = build_hyperspace_proof(leaves)
        
        # 2. Add to Nostr event
        event = {
            "kind": 3333,
            "tags": [
                ["A", "hyperjump"],
                ["B", "850000"],
                ["proof", f"0x{expected_root:x}"]
            ],
            "content": ""
        }
        event = add_zk_tags_to_event(event, proof)
        
        # 3. Extract proof from event
        extracted = extract_zk_proof_from_event(event)
        self.assertIsNotNone(extracted)
        
        # 4. Verify proof
        verified, _ = verify_cantor_proof(extracted, expected_root)
        self.assertTrue(verified)
        
        print("\n✅ End-to-end workflow successful")


if __name__ == "__main__":
    # Run tests with verbosity
    unittest.main(verbosity=2)
