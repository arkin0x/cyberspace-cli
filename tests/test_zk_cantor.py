"""
Tests for ZK-STARK Cantor proof implementation.

These tests verify:
1. Single Cantor pair proofs are valid
2. Full tree proofs reconstruct correctly
3. Tampered proofs are detected
4. Golden vectors match expected outputs
"""

import unittest
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from cyberspace_core.cantor import cantor_pair
from cyberspace_core.zk import (
    prove_cantor_pair,
    verify_cantor_pair,
    prove_cantor_tree,
    verify_cantor_tree,
    benchmark_cantor_pair,
    benchmark_cantor_tree,
    CantorProof,
    CantorTreeProof,
)


class TestCantorPairProof(unittest.TestCase):
    """Test single Cantor pair ZK proofs."""
    
    def test_basic_pair_proof(self):
        """Test proof generation and verification for basic inputs."""
        x, y = 42, 17
        
        # Generate proof
        proof = prove_cantor_pair(x, y)
        
        # Verify proof
        is_valid, z = verify_cantor_pair(proof)
        
        # Assertions
        self.assertTrue(is_valid, "Proof should be valid")
        self.assertEqual(z, cantor_pair(x, y), "Z should match Cantor pairing")
        self.assertEqual(proof.z, z, "Proof z should match verified z")
        self.assertTrue(proof.constraints_satisfied, "All constraints should be satisfied")
    
    def test_large_inputs(self):
        """Test with larger axis values (simulating real cyberspace coordinates)."""
        # 85-bit axis values (scaled down for testing)
        x = 1_000_000_000
        y = 2_000_000_000
        
        proof = prove_cantor_pair(x, y)
        is_valid, z = verify_cantor_pair(proof)
        
        self.assertTrue(is_valid)
        self.assertEqual(z, cantor_pair(x, y))
    
    def test_witness_correctness(self):
        """Test that witness values satisfy all constraints."""
        x, y = 100, 200
        proof = prove_cantor_pair(x, y)
        w = proof.witness
        
        # Manually verify witness
        self.assertEqual(w.s, x + y, "s should equal x + y")
        self.assertEqual(w.t, w.s + 1, "t should equal s + 1")
        self.assertEqual(w.u, w.s * w.t, "u should equal s * t")
        self.assertEqual(w.v, w.u // 2, "v should equal u / 2")
        self.assertEqual(w.z, w.v + y, "z should equal v + y")
        self.assertEqual(w.z, cantor_pair(x, y), "z should match Cantor formula")
    
    def test_tampered_proof_detection(self):
        """Test that tampered proofs are detected."""
        x, y = 42, 17
        proof = prove_cantor_pair(x, y)
        
        # Tamper with witness
        proof.witness.s += 1
        
        is_valid, z = verify_cantor_pair(proof)
        self.assertFalse(is_valid, "Tampered proof should be invalid")
    
    def test_golden_vector(self):
        """Test against known golden vector."""
        # Precomputed golden vector
        x, y = 12345, 67890
        expected_z = 3218935620  # cantor_pair(12345, 67890)
        
        proof = prove_cantor_pair(x, y)
        is_valid, z = verify_cantor_pair(proof)
        
        self.assertTrue(is_valid)
        self.assertEqual(z, expected_z, f"Z should be {expected_z}")
        self.assertEqual(proof.x, x)
        self.assertEqual(proof.y, y)


class TestCantorTreeProof(unittest.TestCase):
    """Test full Cantor tree ZK proofs."""
    
    def test_small_tree(self):
        """Test proof for small tree (4 leaves)."""
        leaves = [10, 20, 30, 40]
        
        proof = prove_cantor_tree(leaves)
        is_valid, root = verify_cantor_tree(proof)
        
        self.assertTrue(is_valid, "Tree proof should be valid")
        self.assertTrue(proof.constraints_satisfied)
        self.assertGreater(proof.tree_height, 0, "Tree should have height > 0")
    
    def test_temporal_seed_integration(self):
        """Test tree with temporal seed (as used in hyperspace proofs)."""
        # Simulate hyperspace proof: [temporal_seed, B_from, B_from+1, ..., B_to]
        temporal_seed = 12345678901234567890
        from_height = 1606
        to_height = 1610
        
        leaves = [temporal_seed] + list(range(from_height, to_height + 1))
        
        proof = prove_cantor_tree(leaves)
        is_valid, root = verify_cantor_tree(proof)
        
        self.assertTrue(is_valid, "Hyperspace-style proof should be valid")
        self.assertEqual(len(proof.pair_proofs), len(leaves) - 1, "Should have N-1 pair proofs")
    
    def test_tampered_tree_detection(self):
        """Test that tampered tree proofs are detected."""
        leaves = [10, 20, 30, 40]
        proof = prove_cantor_tree(leaves)
        
        # Tamper with a pair proof
        proof.pair_proofs[0].witness.s += 1
        
        is_valid, root = verify_cantor_tree(proof)
        self.assertFalse(is_valid, "Tampered tree proof should be invalid")
    
    def test_wrong_root_detection(self):
        """Test that wrong root is detected."""
        leaves = [10, 20, 30, 40]
        proof = prove_cantor_tree(leaves)
        
        # Tamper with claimed root
        proof.root += 1
        
        is_valid, root = verify_cantor_tree(proof)
        self.assertFalse(is_valid, "Wrong root should be detected")
    
    def test_single_leaf(self):
        """Test edge case: single leaf (no pairings needed)."""
        leaves = [42]
        
        proof = prove_cantor_tree(leaves)
        is_valid, root = verify_cantor_tree(proof)
        
        self.assertTrue(is_valid)
        self.assertEqual(root, 42)
        self.assertEqual(proof.tree_height, 0)
        self.assertEqual(len(proof.pair_proofs), 0)


class TestBenchmark(unittest.TestCase):
    """Test benchmarking functions."""
    
    def test_benchmark_pair(self):
        """Test single pair benchmark."""
        result = benchmark_cantor_pair(1000, 2000)
        
        self.assertIn('prove_time_ms', result)
        self.assertIn('verify_time_ms', result)
        self.assertIn('speedup', result)
        self.assertIn('proof_size_bytes', result)
        
        self.assertTrue(result['is_valid'])
        self.assertGreater(result['speedup'], 1, "Verification should be faster than proving")
    
    def test_benchmark_tree(self):
        """Test tree benchmark."""
        result = benchmark_cantor_tree(16)
        
        self.assertIn('num_leaves', result)
        self.assertIn('tree_height', result)
        self.assertIn('num_pairings', result)
        self.assertIn('prove_time_ms', result)
        self.assertIn('verify_time_ms', result)
        self.assertIn('proof_size_kb', result)
        
        self.assertTrue(result['is_valid'])


class TestSerialization(unittest.TestCase):
    """Test proof serialization/deserialization."""
    
    def test_pair_proof_serialization(self):
        """Test CantorProof round-trip serialization."""
        proof = prove_cantor_pair(42, 17)
        
        # Serialize
        proof_dict = proof.to_dict()
        
        # Deserialize
        restored = CantorProof.from_dict(proof_dict)
        
        # Verify restored proof
        is_valid, z = verify_cantor_pair(restored)
        self.assertTrue(is_valid, "Restored proof should be valid")
        self.assertEqual(z, proof.z)
    
    def test_tree_proof_serialization(self):
        """Test CantorTreeProof round-trip serialization."""
        leaves = [10, 20, 30, 40, 50]
        proof = prove_cantor_tree(leaves)
        
        # Serialize
        proof_dict = proof.to_dict()
        
        # Deserialize
        restored = CantorTreeProof.from_dict(proof_dict)
        
        # Verify restored proof
        is_valid, root = verify_cantor_tree(restored)
        self.assertTrue(is_valid, "Restored tree proof should be valid")
        self.assertEqual(root, proof.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
