"""Tests for cyberspace_cli.movement_parsing module."""
import pytest
from cyberspace_cli.movement_parsing import (
    MovementDestination,
    parse_movement_destination,
    parse_toward_destination,
)
from cyberspace_core.coords import AXIS_MAX


class TestParseMovementDestination:
    """Test destination parsing."""
    
    def test_parse_absolute_xyz(self):
        """Parse absolute destination as x,y,z."""
        dest, error = parse_movement_destination(
            to="100,200,300",
            by=None,
            toward=None,
            current_plane=0,
        )
        assert error is None
        assert dest.x == 100
        assert dest.y == 200
        assert dest.z == 300
        assert dest.plane == 0
        assert dest.is_relative is False
    
    def test_parse_absolute_with_plane(self):
        """Parse absolute destination with explicit plane."""
        dest, error = parse_movement_destination(
            to="100,200,300,1",
            by=None,
            toward=None,
            current_plane=0,
        )
        assert error is None
        assert dest.plane == 1
    
    def test_parse_coord_hex(self):
        """Parse destination as coord hex."""
        dest, error = parse_movement_destination(
            to="0x" + "0" * 64,
            by=None,
            toward=None,
            current_plane=0,
        )
        assert error is None
        assert dest.x == 0
        assert dest.y == 0
        assert dest.z == 0
        assert dest.plane == 0
    
    def test_parse_relative_zero(self):
        """Parse relative movement of zero (plane switch)."""
        dest, error = parse_movement_destination(
            to=None,
            by="0,0,0,1",
            toward=None,
            current_plane=0,
        )
        assert error is None
        assert dest.is_relative is True
        assert dest.x == 0
        assert dest.y == 0
        assert dest.z == 0
        assert dest.plane == 1
    
    def test_parse_relative_movement(self):
        """Parse relative movement with deltas."""
        dest, error = parse_movement_destination(
            to=None,
            by="10,-20,5",
            toward=None,
            current_plane=0,
        )
        assert error is None
        assert dest.is_relative is True
        assert dest.x == 10
        assert dest.y == -20
        assert dest.z == 5
    
    def test_invalid_format_too_few_parts(self):
        """Invalid destination with too few parts."""
        dest, error = parse_movement_destination(
            to="100,200",
            by=None,
            toward=None,
            current_plane=0,
        )
        assert error is not None
        assert "Invalid destination" in error
    
    def test_by_takes_precedence(self):
        """--by takes precedence over --to."""
        dest, error = parse_movement_destination(
            to="100,200,300",
            by="1,2,3",
            toward=None,
            current_plane=0,
        )
        assert error is None
        assert dest.is_relative is True
        assert dest.x == 1


class TestParseTowardDestination:
    """Test --toward destination parsing."""
    
    def test_parse_toward_xyz(self):
        """Parse toward destination as x,y,z."""
        dest, error = parse_toward_destination(
            toward="1000,2000,3000",
            current_plane=0,
        )
        assert error is None
        assert dest.x == 1000
        assert dest.y == 2000
        assert dest.z == 3000
    
    def test_parse_toward_hex(self):
        """Parse toward destination as coord hex."""
        dest, error = parse_toward_destination(
            toward="0x" + "1" * 64,
            current_plane=0,
        )
        assert error is None
        assert dest is not None
    
    def test_parse_toward_invalid(self):
        """Parse invalid toward destination."""
        dest, error = parse_toward_destination(
            toward="invalid",
            current_plane=0,
        )
        assert error is not None
