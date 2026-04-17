"""Tests for hyperspace Cantor tree proof construction per DECK-0001 §8."""

import pytest
from cyberspace_core.cantor import cantor_pair, build_hyperspace_proof, compute_temporal_seed


class TestTemporalSeed:
    """Test temporal seed computation per DECK-0001 §8."""

    def test_temporal_seed_from_event_id(self):
        """Temporal seed is previous_event_id % 2^256."""
        # Example event ID (32 bytes as hex)
        prev_event_id = bytes.fromhex("a" * 64)
        seed = compute_temporal_seed(prev_event_id)
        
        # Should be in range [0, 2^256)
        assert 0 <= seed < 2**256
        
        # Deterministic
        seed2 = compute_temporal_seed(prev_event_id)
        assert seed == seed2

    def test_temporal_seed_different_event_ids(self):
        """Different event IDs produce different temporal seeds."""
        prev_id_1 = bytes.fromhex("a" * 64)
        prev_id_2 = bytes.fromhex("b" * 64)
        
        seed_1 = compute_temporal_seed(prev_id_1)
        seed_2 = compute_temporal_seed(prev_id_2)
        
        assert seed_1 != seed_2


class TestHyperspaceProof:
    """Test Cantor tree construction for hyperspace traversal proof."""

    def test_single_block_hyperjump(self):
        """1-block hyperjump: 3 leaves → 2 Cantor pairings.
        
        Leaves: [temporal_seed, B_from, B_to] where B_to = B_from + 1
        """
        temporal_seed = 12345
        b_from = 1606
        b_to = 1607
        
        leaves = [temporal_seed, b_from, b_to]
        root = build_hyperspace_proof(leaves)
        
        # Manual verification:
        # Level 1: pair(temporal_seed, b_from), carry b_to
        # Level 2: pair(pair(temporal_seed, b_from), b_to)
        level1_0 = cantor_pair(temporal_seed, b_from)
        # Now we have [level1_0, b_to]
        expected_root = cantor_pair(level1_0, b_to)
        
        assert root == expected_root

    def test_multi_block_hyperjump(self):
        """100-block hyperjump: 102 leaves → ~100 pairings."""
        temporal_seed = 999999
        b_from = 850000
        b_to = 850100
        
        leaves = [temporal_seed] + list(range(b_from, b_to + 1))
        root = build_hyperspace_proof(leaves)
        
        # Should complete without error
        assert isinstance(root, int)
        assert root > 0

    def test_proof_deterministic(self):
        """Same leaves produce same root."""
        leaves = [12345, 1606, 1607, 1608]
        
        root1 = build_hyperspace_proof(leaves)
        root2 = build_hyperspace_proof(leaves)
        
        assert root1 == root2

    def test_proof_changes_with_temporal_seed(self):
        """Different temporal seed produces different root."""
        b_from = 1606
        b_to = 1607
        
        leaves1 = [12345, b_from, b_to]
        leaves2 = [54321, b_from, b_to]
        
        root1 = build_hyperspace_proof(leaves1)
        root2 = build_hyperspace_proof(leaves2)
        
        assert root1 != root2

    def test_proof_changes_with_path_length(self):
        """Different path length produces different root."""
        temporal_seed = 12345
        
        # 1-block jump
        leaves1 = [temporal_seed, 1606, 1607]
        # 2-block jump
        leaves2 = [temporal_seed, 1606, 1607, 1608]
        
        root1 = build_hyperspace_proof(leaves1)
        root2 = build_hyperspace_proof(leaves2)
        
        assert root1 != root2

    def test_empty_leaves_raises_error(self):
        """Empty leaves list should raise an error."""
        with pytest.raises(ValueError):
            build_hyperspace_proof([])

    def test_single_leaf_returns_leaf(self):
        """Single leaf returns that leaf as root."""
        leaves = [42]
        root = build_hyperspace_proof(leaves)
        assert root == 42

    def test_two_leaves_single_pairing(self):
        """Two leaves require exactly one pairing."""
        leaves = [100, 200]
        root = build_hyperspace_proof(leaves)
        expected = cantor_pair(100, 200)
        assert root == expected
