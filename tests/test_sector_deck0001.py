"""Tests for DECK-0001 sector extraction with de-interleaving."""

import pytest
from cyberspace_core.sector import (
    extract_axis_from_coord256,
    sector_from_coord256,
    extract_hyperjump_sectors,
    coord_matches_hyperjump_plane,
)
from cyberspace_core.coords import coord_to_xyz


class TestExtractAxisFromCoord256:
    """Test de-interleaving of 256-bit coordinates."""

    def test_extract_x_axis(self):
        """X bits are at positions 3, 6, 9, ..."""
        # If only bit 3 is set, X axis should have bit 0 set
        coord = 1 << 3  # Bit 3 set (first X bit)
        x_val = extract_axis_from_coord256(coord, 'X')
        assert x_val == 1  # Bit 0 of X axis
        
    def test_extract_y_axis(self):
        """Y bits are at positions 2, 5, 8, ..."""
        coord = 1 << 2  # Bit 2 set (first Y bit)
        y_val = extract_axis_from_coord256(coord, 'Y')
        assert y_val == 1  # Bit 0 of Y axis
        
    def test_extract_z_axis(self):
        """Z bits are at positions 1, 4, 7, ..."""
        coord = 1 << 1  # Bit 1 set (first Z bit)
        z_val = extract_axis_from_coord256(coord, 'Z')
        assert z_val == 1  # Bit 0 of Z axis
        
    def test_extract_multiple_bits(self):
        """Test extraction with multiple bits set."""
        # Set bit 3 and bit 6 (both X bits, positions 0 and 1 of X axis)
        coord = (1 << 3) | (1 << 6)
        x_val = extract_axis_from_coord256(coord, 'X')
        assert x_val == 0b11  # Bits 0 and 1 set
        
    def test_identity_roundtrip(self):
        """De-interleaving then re-interleaving should be identity."""
        from cyberspace_core.coords import xyz_to_coord
        
        x, y, z, plane = 12345, 67890, 11111, 0
        coord = xyz_to_coord(x, y, z, plane)
        
        extracted_x = extract_axis_from_coord256(coord, 'X')
        extracted_y = extract_axis_from_coord256(coord, 'Y')
        extracted_z = extract_axis_from_coord256(coord, 'Z')
        
        # Extracted values should match original axis values
        assert extracted_x == x
        assert extracted_y == y
        assert extracted_z == z


class TestSectorFromCoord256:
    """Test sector extraction per DECK-0001 §I.2."""

    def test_sector_high_bits(self):
        """Sector is high 55 bits of 85-bit axis value."""
        # High bit set in X axis (bit 255 is highest X bit)
        coord = 1 << 255
        sector = sector_from_coord256(coord, 'X')
        # Should have bit 84 set (85-bit axis, indexed 0-84)
        assert sector == (1 << 84) >> 30
        
    def test_all_axes_same_coord(self):
        """All three axes can be extracted from same coord."""
        # Create coord with known pattern
        x, y, z, plane = 0xFFFFFFFF, 0x12345678, 0xDEADBEEF, 1
        from cyberspace_core.coords import xyz_to_coord
        coord = xyz_to_coord(x, y, z, plane)
        
        sx = sector_from_coord256(coord, 'X')
        sy = sector_from_coord256(coord, 'Y')
        sz = sector_from_coord256(coord, 'Z')
        
        # Sectors should be high 55 bits of each axis
        assert sx == x >> 30
        assert sy == y >> 30
        assert sz == z >> 30


class TestExtractHyperjumpSectors:
    """Test sector extraction from Merkle root."""

    def test_merkle_root_sectors(self):
        """Extract sectors from a known Merkle root."""
        # Block 1606 Merkle root from DECK-0001 examples
        merkle = "744193479b55674c02dec4ed73581eafbd7e2db03442360c9c34f9394031ee8f"
        
        sx, sy, sz = extract_hyperjump_sectors(merkle)
        
        # Verify we got integer sectors
        assert isinstance(sx, int) and sx >= 0
        assert isinstance(sy, int) and sy >= 0
        assert isinstance(sz, int) and sz >= 0
        
        # Sectors should fit in 55 bits
        assert sx < (1 << 55)
        assert sy < (1 << 55)
        assert sz < (1 << 55)

    def test_invalid_merkle_length(self):
        """Should reject wrong-length Merkle roots."""
        with pytest.raises(ValueError, match="64 hex chars"):
            extract_hyperjump_sectors("deadbeef")
            
    def test_invalid_merkle_case(self):
        """Should reject uppercase Merkle roots."""
        with pytest.raises(ValueError, match="lowercase"):
            extract_hyperjump_sectors("744193479B55674C02DEC4ED73581EAFBD7E2DB03442360C9C34F9394031EE8F")


class TestCoordMatchesHyperjumpPlane:
    """Test sector-plane entry validation."""

    def test_matches_x_plane(self):
        """Coordinate in X-plane of Hyperjump."""
        merkle = "744193479b55674c02dec4ed73581eafbd7e2db03442360c9c34f9394031ee8f"
        sx, _, _ = extract_hyperjump_sectors(merkle)
        
        # Create coord with same X sector
        from cyberspace_core.coords import xyz_to_coord
        # Use sx << 30 to get coord with that sector
        coord = xyz_to_coord(sx << 30, 0, 0, 0)
        
        assert coord_matches_hyperjump_plane(coord, merkle, 'X')
        
    def test_no_match_wrong_axis(self):
        """Coordinate not in Hyperjump's plane."""
        merkle = "744193479b55674c02dec4ed73581eafbd7e2db03442360c9c34f9394031ee8f"
        sx, sy, sz = extract_hyperjump_sectors(merkle)
        
        from cyberspace_core.coords import xyz_to_coord
        # Use different sector for X
        coord = xyz_to_coord((sx + 1) << 30, sy << 30, sz << 30, 0)
        
        # Should NOT match X-plane (different sector)
        assert not coord_matches_hyperjump_plane(coord, merkle, 'X')
        
    def test_matches_y_plane(self):
        """Coordinate in Y-plane of Hyperjump."""
        merkle = "744193479b55674c02dec4ed73581eafbd7e2db03442360c9c34f9394031ee8f"
        _, sy, _ = extract_hyperjump_sectors(merkle)
        
        from cyberspace_core.coords import xyz_to_coord
        coord = xyz_to_coord(0, sy << 30, 0, 0)
        
        assert coord_matches_hyperjump_plane(coord, merkle, 'Y')
        
    def test_matches_z_plane(self):
        """Coordinate in Z-plane of Hyperjump."""
        merkle = "744193479b55674c02dec4ed73581eafbd7e2db03442360c9c34f9394031ee8f"
        _, _, sz = extract_hyperjump_sectors(merkle)
        
        from cyberspace_core.coords import xyz_to_coord
        coord = xyz_to_coord(0, 0, sz << 30, 0)
        
        assert coord_matches_hyperjump_plane(coord, merkle, 'Z')

    def test_invalid_axis(self):
        """Should reject invalid axis names."""
        merkle = "744193479b55674c02dec4ed73581eafbd7e2db03442360c9c34f9394031ee8f"
        from cyberspace_core.coords import xyz_to_coord
        coord = xyz_to_coord(0, 0, 0, 0)
        
        with pytest.raises(ValueError, match="axis must be"):
            coord_matches_hyperjump_plane(coord, merkle, 'P')  # Invalid


class TestDeck0001Compliance:
    """Verify DECK-0001 spec compliance."""

    def test_sector_extraction_85_bits(self):
        """Axis values should be 85 bits per spec §I.2."""
        from cyberspace_core.coords import AXIS_BITS
        assert AXIS_BITS == 85
        
        max_coord = (1 << 256) - 1
        x_val = extract_axis_from_coord256(max_coord, 'X')
        assert x_val.bit_length() <= 85
        
    def test_sector_55_bits(self):
        """Sectors should be 55 bits per spec §I.2."""
        max_coord = (1 << 256) - 1
        sector = sector_from_coord256(max_coord, 'X')
        assert sector.bit_length() <= 55
        
    def test_interleave_order_xyz(self):
        """Bit pattern should be XYZXYZXYZ...P per spec §2.2."""
        # The first 4 bits (positions 0-3) should be P, Z, Y, X
        # P at position 0
        # Z at position 1
        # Y at position 2  
        # X at position 3
        
        from cyberspace_core.coords import xyz_to_coord
        
        # Test with X=1, Y=0, Z=0, P=0
        coord = xyz_to_coord(1, 0, 0, 0)
        assert coord & (1 << 3)  # X's first bit
        
        # Test with Y=1
        coord = xyz_to_coord(0, 1, 0, 0)
        assert coord & (1 << 2)  # Y's first bit
        
        # Test with Z=1
        coord = xyz_to_coord(0, 0, 1, 0)
        assert coord & (1 << 1)  # Z's first bit
