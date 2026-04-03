"""Tests for sidestep proof computation (Merkle spatial + Cantor temporal)."""

from __future__ import annotations

import pytest

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256
from cyberspace_core.movement import (
    SIDESTEP_DOMAIN,
    SidestepProof,
    compute_axis_merkle_root,
    compute_axis_merkle_root_streaming,
    compute_sidestep_proof,
    find_lca_height,
    merkle_leaf,
    merkle_parent,
    verify_merkle_inclusion,
)


class TestMerkleLeaf:
    """Test the domain-separated leaf hash."""

    def test_leaf_deterministic(self):
        h1 = merkle_leaf(42)
        h2 = merkle_leaf(42)
        assert h1 == h2

    def test_leaf_different_values(self):
        assert merkle_leaf(0) != merkle_leaf(1)

    def test_leaf_domain_separation(self):
        """Leaf hash differs from plain SHA256 of the same value."""
        val = 100
        plain = sha256(int_to_bytes_be_min(val))
        domained = merkle_leaf(val)
        assert plain != domained

    def test_leaf_is_32_bytes(self):
        assert len(merkle_leaf(999)) == 32


class TestMerkleParent:
    def test_parent_deterministic(self):
        a = merkle_leaf(0)
        b = merkle_leaf(1)
        assert merkle_parent(a, b) == merkle_parent(a, b)

    def test_parent_order_matters(self):
        a = merkle_leaf(0)
        b = merkle_leaf(1)
        assert merkle_parent(a, b) != merkle_parent(b, a)


class TestStreamingMerkleRoot:
    """Test the streaming Merkle root computation."""

    def test_height_0(self):
        root, siblings = compute_axis_merkle_root_streaming(base=100, height=0)
        assert root == merkle_leaf(100)
        assert siblings == []

    def test_height_1(self):
        """Height 1: two leaves, one parent."""
        root, siblings = compute_axis_merkle_root_streaming(base=0, height=1)
        expected = merkle_parent(merkle_leaf(0), merkle_leaf(1))
        assert root == expected
        # Inclusion proof for leaf 0: sibling is leaf 1
        assert len(siblings) == 1
        assert siblings[0] == merkle_leaf(1)

    def test_height_2(self):
        """Height 2: four leaves."""
        root, siblings = compute_axis_merkle_root_streaming(base=0, height=2)
        # Manual computation
        h0 = merkle_leaf(0)
        h1 = merkle_leaf(1)
        h2 = merkle_leaf(2)
        h3 = merkle_leaf(3)
        p01 = merkle_parent(h0, h1)
        p23 = merkle_parent(h2, h3)
        expected_root = merkle_parent(p01, p23)
        assert root == expected_root
        # Inclusion proof for leaf 0: [sibling at level 0 = h1, sibling at level 1 = p23]
        assert len(siblings) == 2
        assert siblings[0] == h1
        assert siblings[1] == p23

    def test_height_3(self):
        """Height 3: eight leaves."""
        root, siblings = compute_axis_merkle_root_streaming(base=0, height=3)
        assert len(siblings) == 3
        assert len(root) == 32

    def test_large_height(self):
        """Height 10 should work with streaming (1024 leaves)."""
        root, siblings = compute_axis_merkle_root_streaming(base=0, height=10)
        assert len(root) == 32
        assert len(siblings) == 10

    def test_nonzero_base(self):
        """Non-zero base should produce different root."""
        r1, _ = compute_axis_merkle_root_streaming(base=0, height=3)
        r2, _ = compute_axis_merkle_root_streaming(base=8, height=3)
        assert r1 != r2


class TestComputeAxisMerkleRoot:
    def test_trivial_axis(self):
        """v1 == v2 should return single leaf hash."""
        root, siblings, h = compute_axis_merkle_root(100, 100)
        assert h == 0
        assert siblings == []
        assert root == merkle_leaf(100)

    def test_adjacent_values(self):
        """Two adjacent values differing in bit 0 → height 1."""
        root, siblings, h = compute_axis_merkle_root(4, 5)
        assert h == 1
        assert len(siblings) == 1

    def test_lca_height_matches(self):
        root, siblings, h = compute_axis_merkle_root(0, 8)
        assert h == find_lca_height(0, 8)
        assert h == 4


class TestVerifyMerkleInclusion:
    def test_verify_leaf_0_height_1(self):
        root, siblings = compute_axis_merkle_root_streaming(base=0, height=1)
        assert verify_merkle_inclusion(
            leaf_value=0, siblings=siblings, expected_root=root, height=1, base=0
        )

    def test_verify_leaf_1_height_1(self):
        """Verify the other leaf (index 1) in a height-1 tree."""
        root, _ = compute_axis_merkle_root_streaming(base=0, height=1)
        # For leaf 1, sibling is leaf 0
        leaf1_siblings = [merkle_leaf(0)]
        assert verify_merkle_inclusion(
            leaf_value=1, siblings=leaf1_siblings, expected_root=root, height=1, base=0
        )

    def test_verify_height_2(self):
        root, siblings = compute_axis_merkle_root_streaming(base=0, height=2)
        # Verify leaf 0 with its inclusion proof
        assert verify_merkle_inclusion(
            leaf_value=0, siblings=siblings, expected_root=root, height=2, base=0
        )

    def test_verify_wrong_root_fails(self):
        root, siblings = compute_axis_merkle_root_streaming(base=0, height=2)
        fake_root = b"\x00" * 32
        assert not verify_merkle_inclusion(
            leaf_value=0, siblings=siblings, expected_root=fake_root, height=2, base=0
        )

    def test_verify_wrong_siblings_fails(self):
        root, _ = compute_axis_merkle_root_streaming(base=0, height=2)
        bad_siblings = [b"\x00" * 32, b"\x00" * 32]
        assert not verify_merkle_inclusion(
            leaf_value=0, siblings=bad_siblings, expected_root=root, height=2, base=0
        )

    def test_verify_trivial(self):
        root = merkle_leaf(42)
        assert verify_merkle_inclusion(
            leaf_value=42, siblings=[], expected_root=root, height=0, base=42
        )

    def test_verify_height_3_leaf_0(self):
        """Verify leaf 0 inclusion in a height-3 tree."""
        root, siblings = compute_axis_merkle_root_streaming(base=100, height=3)
        assert verify_merkle_inclusion(
            leaf_value=100, siblings=siblings, expected_root=root, height=3, base=100
        )


class TestSidestepProof:
    """Test the full sidestep proof computation."""

    # Use a deterministic previous_event_id for tests
    PREV_ID = "a" * 64

    def test_basic_sidestep(self):
        """Simple sidestep where coordinates differ on one axis."""
        proof = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=1, y2=0, z2=0,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        assert isinstance(proof, SidestepProof)
        assert len(proof.merkle_x) == 32
        assert len(proof.merkle_y) == 32
        assert len(proof.merkle_z) == 32
        assert len(proof.proof_hash) == 64  # hex string of SHA256
        assert proof.lca_heights == (1, 0, 0)

    def test_multi_axis_sidestep(self):
        """Sidestep where coordinates differ on multiple axes."""
        proof = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=4, y2=2, z2=1,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        assert proof.lca_heights[0] == find_lca_height(0, 4)  # 3
        assert proof.lca_heights[1] == find_lca_height(0, 2)  # 2
        assert proof.lca_heights[2] == find_lca_height(0, 1)  # 1

    def test_proof_deterministic(self):
        """Same inputs produce same proof."""
        p1 = compute_sidestep_proof(
            x1=10, y1=20, z1=30,
            x2=11, y2=20, z2=30,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        p2 = compute_sidestep_proof(
            x1=10, y1=20, z1=30,
            x2=11, y2=20, z2=30,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        assert p1.proof_hash == p2.proof_hash
        assert p1.region_m == p2.region_m

    def test_different_prev_id_different_proof(self):
        """Different previous_event_id produces different proof (temporal binding)."""
        p1 = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=1, y2=0, z2=0,
            plane=0,
            previous_event_id_hex="a" * 64,
        )
        p2 = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=1, y2=0, z2=0,
            plane=0,
            previous_event_id_hex="b" * 64,
        )
        assert p1.proof_hash != p2.proof_hash
        # Spatial component should be the same (same coordinates)
        assert p1.merkle_x == p2.merkle_x
        assert p1.region_m == p2.region_m
        # Temporal component differs
        assert p1.cantor_t != p2.cantor_t

    def test_sidestep_differs_from_hop(self):
        """Sidestep proof hash differs from hop proof hash (different spatial construction)."""
        from cyberspace_core.movement import compute_hop_proof
        sid = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=1, y2=0, z2=0,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        hop = compute_hop_proof(
            0, 0, 0, 1, 0, 0,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        assert sid.proof_hash != hop.proof_hash

    def test_inclusion_proofs_verify(self):
        """The inclusion proofs in the sidestep proof should verify against roots."""
        proof = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=4, y2=2, z2=1,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        # Verify X axis inclusion proof for the source leaf
        hx, hy, hz = proof.lca_heights
        base_x = (0 >> hx) << hx
        assert verify_merkle_inclusion(
            leaf_value=base_x,  # leaf 0 = base
            siblings=proof.inclusion_proofs["x"],
            expected_root=proof.merkle_x,
            height=hx,
            base=base_x,
        )

    def test_double_sha256_proof_hash(self):
        """Verify proof_hash is double SHA256 of sidestep_n."""
        proof = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=1, y2=0, z2=0,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        expected = sha256(sha256(int_to_bytes_be_min(proof.sidestep_n))).hex()
        assert proof.proof_hash == expected

    def test_region_m_structure(self):
        """Verify region_m = π(π(mx, my), mz) structure."""
        proof = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=1, y2=0, z2=0,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        mx = int.from_bytes(proof.merkle_x, "big")
        my = int.from_bytes(proof.merkle_y, "big")
        mz = int.from_bytes(proof.merkle_z, "big")
        expected = cantor_pair(cantor_pair(mx, my), mz)
        assert proof.region_m == expected

    def test_invalid_prev_id(self):
        """Invalid previous event ID should raise ValueError."""
        with pytest.raises(ValueError, match="64 hex chars"):
            compute_sidestep_proof(
                x1=0, y1=0, z1=0,
                x2=1, y2=0, z2=0,
                plane=0,
                previous_event_id_hex="short",
            )

    def test_higher_lca_heights(self):
        """Test with heights that would be too expensive for Cantor but fine for Merkle."""
        # Height ~15 on one axis — streaming Merkle handles this easily
        # v1=0, v2=16384 gives h=15 (since 16384 = 2^14, XOR = 2^14, bit_length = 15)
        proof = compute_sidestep_proof(
            x1=0, y1=0, z1=0,
            x2=16384, y2=0, z2=0,
            plane=0,
            previous_event_id_hex=self.PREV_ID,
        )
        assert proof.lca_heights[0] == 15
        assert len(proof.inclusion_proofs["x"]) == 15
        assert len(proof.proof_hash) == 64
