"""Tests for Cantor pairing arithmetic circuit.

These tests verify the correctness of the circuit arithmetization
that would be used in ZK-STARK proofs.
"""

import unittest
from cyberspace_core.zk_stark.circuit import (
    cantor_circuit_forward,
    cantor_direct,
    verify_circuit_constraints,
    cantor_tree_circuit,
    verify_tree_constraints,
    count_constraints,
    FIELD_MODULUS,
)


class TestCantorCircuit(unittest.TestCase):
    """Test individual Cantor pairing circuit"""
    
    def test_zero_inputs(self):
        """Test π(0, 0) = 0"""
        trace = cantor_circuit_forward(0, 0)
        self.assertEqual(trace.result, 0)
        is_valid, violations = verify_circuit_constraints(trace)
        self.assertTrue(is_valid, f"Violations: {violations}")
    
    def test_symmetric_inputs(self):
        """Test that circuit is not symmetric: π(x,y) != π(y,x) in general"""
        trace1 = cantor_circuit_forward(5, 3)
        trace2 = cantor_circuit_forward(3, 5)
        
        # Cantor pairing is NOT symmetric
        self.assertNotEqual(trace1.result, trace2.result)
        
        # But both should be valid
        self.assertTrue(verify_circuit_constraints(trace1)[0])
        self.assertTrue(verify_circuit_constraints(trace2)[0])
    
    def test_known_vectors(self):
        """Test against known Cantor pairing values"""
        test_vectors = [
            (0, 0, 0),
            (1, 0, 1),
            (0, 1, 2),
            (2, 0, 3),
            (1, 1, 4),
            (0, 2, 5),
            (42, 17, 1787),
        ]
        
        for x, y, expected in test_vectors:
            with self.subTest(x=x, y=y):
                trace = cantor_circuit_forward(x, y)
                self.assertEqual(trace.result, expected)
                self.assertEqual(trace.result, cantor_direct(x, y))
                
                is_valid, violations = verify_circuit_constraints(trace)
                self.assertTrue(is_valid, f"Violations: {violations}")
    
    def test_large_values(self):
        """Test with large coordinate values"""
        x, y = 1000000, 999999
        trace = cantor_circuit_forward(x, y)
        expected = cantor_direct(x, y)
        
        self.assertEqual(trace.result, expected)
        is_valid, violations = verify_circuit_constraints(trace)
        self.assertTrue(is_valid)
    
    def test_field_modulus_boundary(self):
        """Test behavior near field modulus"""
        # Values should wrap correctly
        x = FIELD_MODULUS - 1
        y = 1
        trace = cantor_circuit_forward(x, y)
        
        # Direct computation with modular reduction
        expected = cantor_direct(x, y) % FIELD_MODULUS
        self.assertEqual(trace.result, expected)


class TestCantorTree(unittest.TestCase):
    """Test Cantor tree circuit over multiple leaves"""
    
    def test_single_leaf(self):
        """Trivial tree with one leaf"""
        tree = cantor_tree_circuit([42])
        self.assertEqual(tree.root, 42)
        self.assertEqual(len(tree.traces), 0)
        
        is_valid, violations = verify_tree_constraints(tree)
        self.assertTrue(is_valid)
    
    def test_two_leaves(self):
        """Simple tree with two leaves"""
        tree = cantor_tree_circuit([5, 3])
        
        # Should have one pairing
        self.assertEqual(len(tree.traces), 1)
        self.assertEqual(len(tree.traces), count_constraints(2)["num_pairings"])
        
        # Root should equal direct computation
        expected = cantor_direct(5, 3)
        self.assertEqual(tree.root, expected)
        
        is_valid, violations = verify_tree_constraints(tree)
        self.assertTrue(is_valid)
    
    def test_four_leaves(self):
        """Complete binary tree with 4 leaves"""
        leaves = [10, 20, 30, 40]
        tree = cantor_tree_circuit(leaves)
        
        # 4 leaves → 3 pairings
        self.assertEqual(len(tree.traces), 3)
        
        # Verify manually:
        # Level 1: π(10,20), π(30,40)
        p1 = cantor_direct(10, 20)
        p2 = cantor_direct(30, 40)
        # Level 2: π(p1, p2)
        expected_root = cantor_direct(p1, p2)
        
        self.assertEqual(tree.root, expected_root)
        
        is_valid, violations = verify_tree_constraints(tree)
        self.assertTrue(is_valid)
    
    def test_odd_number_of_leaves(self):
        """Tree with odd number of leaves (carry-forward)"""
        leaves = [1, 2, 3]
        tree = cantor_tree_circuit(leaves)
        
        # 3 leaves → 2 pairings
        # Level 1: π(1,2), carry 3
        # Level 2: π(π(1,2), 3)
        self.assertEqual(len(tree.traces), 2)
        
        p1 = cantor_direct(1, 2)
        expected_root = cantor_direct(p1, 3)
        self.assertEqual(tree.root, expected_root)
        
        is_valid, violations = verify_tree_constraints(tree)
        self.assertTrue(is_valid)
    
    def test_temporal_seed_pattern(self):
        """Test the hyperspace proof pattern: [temporal_seed, B_from, B_to]"""
        temporal_seed = 0x1234567890abcdef
        b_from = 1606
        b_to = 1607
        
        leaves = [temporal_seed, b_from, b_to]
        tree = cantor_tree_circuit(leaves)
        
        # 3 leaves → 2 pairings
        self.assertEqual(len(tree.traces), 2)
        
        # Verify tree structure
        is_valid, violations = verify_tree_constraints(tree)
        self.assertTrue(is_valid)


class TestConstraintCounting(unittest.TestCase):
    """Test constraint counting for STARK circuit sizing"""
    
    def test_empty_tree(self):
        counts = count_constraints(0)
        self.assertEqual(counts["total_constraints"], 0)
    
    def test_single_leaf(self):
        counts = count_constraints(1)
        self.assertEqual(counts["total_constraints"], 0)
    
    def test_small_trees(self):
        trees = [
            (2, 5),      # 2 leaves → 1 pairing → 5 constraints
            (4, 15),     # 4 leaves → 3 pairings → 15 constraints
            (8, 35),     # 8 leaves → 7 pairings → 35 constraints
            (16, 75),    # 16 leaves → 15 pairings → 75 constraints
        ]
        
        for leaves, expected_constraints in trees:
            with self.subTest(leaves=leaves):
                counts = count_constraints(leaves)
                self.assertEqual(counts["total_constraints"], expected_constraints)
    
    def test_realistic_heights(self):
        """Test constraint counts for realistic tree heights"""
        height_constraints = [
            (10, 5_115),           # h10: 1024 leaves
            (15, 163_835),         # h15: 32K leaves
            (20, 5_242_875),       # h20: 1M leaves
        ]
        
        for height, expected_constraints in height_constraints:
            with self.subTest(height=height):
                leaves = 2 ** height
                counts = count_constraints(leaves)
                self.assertEqual(counts["total_constraints"], expected_constraints)


if __name__ == "__main__":
    unittest.main()
