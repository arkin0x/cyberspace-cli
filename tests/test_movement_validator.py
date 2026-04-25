"""Tests for cyberspace_cli.movement_validator module."""
import pytest
from cyberspace_cli.movement_validator import (
    MoveConfig,
    validate_destination,
    validate_plane_switch,
    build_move_config,
)
from cyberspace_cli.movement_parsing import MovementDestination
from cyberspace_core.coords import AXIS_MAX


class TestValidateDestination:
    """Test destination validation."""
    
    def test_valid_absolute_destination(self):
        dest = MovementDestination(x=100, y=200, z=300, plane=0)
        error = validate_destination(dest)
        assert error is None
    
    def test_valid_max_coordinates(self):
        dest = MovementDestination(x=AXIS_MAX, y=AXIS_MAX, z=AXIS_MAX, plane=1)
        error = validate_destination(dest)
        assert error is None
    
    def test_invalid_plane(self):
        dest = MovementDestination(x=0, y=0, z=0, plane=2)
        error = validate_destination(dest)
        assert error is not None
    
    def test_invalid_x_overflow(self):
        dest = MovementDestination(x=AXIS_MAX + 1, y=0, z=0, plane=0)
        error = validate_destination(dest)
        assert error is not None
    
    def test_relative_plane_switch_valid(self):
        dest = MovementDestination(x=0, y=0, z=0, plane=1, is_relative=True)
        error = validate_destination(dest)
        assert error is None


class TestValidatePlaneSwitch:
    """Test plane switch validation."""
    
    def test_valid_plane_switch(self):
        error = validate_plane_switch(current_plane=0, dest_plane=1)
        assert error is None
    
    def test_invalid_dest_plane(self):
        error = validate_plane_switch(current_plane=0, dest_plane=2)
        assert error is not None


class TestBuildMoveConfig:
    """Test configuration building."""
    
    def test_default_config(self):
        config = build_move_config(max_lca_height=None, default_max_lca_height=16)
        assert config.max_lca_height == 16
        assert config.max_hops == 0
    
    def test_override_max_lca_height(self):
        config = build_move_config(max_lca_height=20, default_max_lca_height=16)
        assert config.max_lca_height == 20
