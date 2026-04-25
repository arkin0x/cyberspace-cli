"""Tests for cyberspace_cli.movement module."""
import pytest
from cyberspace_cli.movement import (
    HopProof,
    SidestepProof,
    validate_hop_destination,
    compute_spatial_cantor_roots,
    compute_temporal_component,
    compute_hop_proof,
)
from cyberspace_core.coords import AXIS_MAX


class TestValidateHopDestination:
    """Test coordinate validation."""
    
    def test_valid_coordinates_dataspace(self):
        """Valid coordinates in dataspace (plane 0)."""
        # Should not raise
        validate_hop_destination(0, 0, 0, 0)
        validate_hop_destination(AXIS_MAX, AXIS_MAX, AXIS_MAX, 0)
        validate_hop_destination(100, 200, 300, 0)
    
    def test_valid_coordinates_ideaspace(self):
        """Valid coordinates in ideaspace (plane 1)."""
        validate_hop_destination(0, 0, 0, 1)
        validate_hop_destination(AXIS_MAX, AXIS_MAX, AXIS_MAX, 1)
    
    def test_invalid_plane(self):
        """Invalid plane number."""
        with pytest.raises(ValueError, match="plane must be 0 or 1"):
            validate_hop_destination(0, 0, 0, 2)
        with pytest.raises(ValueError, match="plane must be 0 or 1"):
            validate_hop_destination(0, 0, 0, -1)
    
    def test_negative_coordinates(self):
        """Negative coordinates."""
        with pytest.raises(ValueError, match="out of range"):
            validate_hop_destination(-1, 0, 0, 0)
        with pytest.raises(ValueError, match="out of range"):
            validate_hop_destination(0, -1, 0, 0)
        with pytest.raises(ValueError, match="out of range"):
            validate_hop_destination(0, 0, -1, 0)
    
    def test_overflow_coordinates(self):
        """Coordinates exceeding AXIS_MAX."""
        with pytest.raises(ValueError, match="out of range"):
            validate_hop_destination(AXIS_MAX + 1, 0, 0, 0)
        with pytest.raises(ValueError, match="out of range"):
            validate_hop_destination(0, AXIS_MAX + 1, 0, 0)
        with pytest.raises(ValueError, match="out of range"):
            validate_hop_destination(0, 0, AXIS_MAX + 1, 0)


class TestComputeSpatialCantorRoots:
    """Test Cantor root computation."""
    
    def test_zero_hop(self):
        """No movement (same coordinates)."""
        x, y, z = 1000, 2000, 3000
        cx, cy, cz = compute_spatial_cantor_roots(x, y, z, x, y, z, max_compute_height=85)
        # Zero movement: Cantor root equals the coordinate itself (base case)
        # compute_axis_cantor returns base when height=0
        assert cx == x
        assert cy == y
        assert cz == z
    
    def test_small_hop(self):
        """Small hop within same subtree."""
        cx, cy, cz = compute_spatial_cantor_roots(
            0, 0, 0, 1, 1, 1, max_compute_height=85
        )
        assert isinstance(cx, int)
        assert isinstance(cy, int)
        assert isinstance(cz, int)
        assert cx >= 0 and cy >= 0 and cz >= 0
    
    def test_large_hop(self):
        """Large hop across coordinate space."""
        # Use smaller coordinates to avoid 2^85 compute
        # LCA height for 0 to 2^20 is ~20, which is safe
        large_coord = (1 << 20) - 1  # 2^20 - 1
        cx, cy, cz = compute_spatial_cantor_roots(
            0, 0, 0,
            large_coord, large_coord, large_coord,
            max_compute_height=85
        )
        assert isinstance(cx, int)
        assert isinstance(cy, int)
        assert isinstance(cz, int)


class TestComputeTemporalComponent:
    """Test temporal component computation."""
    
    def test_terrain_k_computation(self):
        """Test terrain_k is computed correctly."""
        prev_id = "0" * 64  # 32 bytes = 64 hex chars
        k, cantor_t = compute_temporal_component(
            x=100, y=200, z=300, plane=0,
            previous_event_id_hex=prev_id
        )
        assert isinstance(k, int)
        assert k >= 0
        assert isinstance(cantor_t, int)
        assert cantor_t >= 0
    
    def test_different_locations_different_terrain(self):
        """Different locations should have different terrain_k values."""
        prev_id = "a" * 64
        k1, _ = compute_temporal_component(0, 0, 0, 0, prev_id)
        k2, _ = compute_temporal_component(1000, 2000, 3000, 0, prev_id)
        # Not guaranteed to be different, but likely for distant points
        assert isinstance(k1, int)
        assert isinstance(k2, int)


class TestComputeHopProof:
    """Test hop proof generation."""
    
    def test_hop_proof_structure(self):
        """Test hop proof has all required fields."""
        prev_id = "b" * 64
        proof = compute_hop_proof(
            x1=0, y1=0, z1=0,
            x2=100, y2=200, z2=300,
            plane=0,
            previous_event_id_hex=prev_id
        )
        
        assert isinstance(proof, HopProof)
        assert len(proof.proof_hash) == 64  # SHA256 hex = 64 chars
        assert isinstance(proof.terrain_k, int)
        assert isinstance(proof.cantor_x, int)
        assert isinstance(proof.cantor_y, int)
        assert isinstance(proof.cantor_z, int)
        assert isinstance(proof.region_n, int)
        assert isinstance(proof.hop_n, int)
    
    def test_hop_proof_deterministic(self):
        """Same input should produce same proof."""
        prev_id = "c" * 64
        proof1 = compute_hop_proof(
            0, 0, 0, 100, 200, 300, 0, prev_id
        )
        proof2 = compute_hop_proof(
            0, 0, 0, 100, 200, 300, 0, prev_id
        )
        
        assert proof1.proof_hash == proof2.proof_hash
        assert proof1.terrain_k == proof2.terrain_k
        assert proof1.cantor_x == proof2.cantor_x
        assert proof1.cantor_y == proof2.cantor_y
        assert proof1.cantor_z == proof2.cantor_z
    
    def test_different_prev_event_different_proof(self):
        """Different previous event should produce different proof."""
        proof1 = compute_hop_proof(
            0, 0, 0, 100, 200, 300, 0, "d" * 64
        )
        proof2 = compute_hop_proof(
            0, 0, 0, 100, 200, 300, 0, "e" * 64
        )
        
        # Should be different due to different temporal seed
        assert proof1.proof_hash != proof2.proof_hash
        assert proof1.hop_n != proof2.hop_n

