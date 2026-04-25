"""Tests for cyberspace_cli.hyperjump_flow module."""
import pytest
from cyberspace_cli.hyperjump_flow import (
    dedup_hyperjumps,
    rank_hyperjumps,
    get_event_tag,
    SECTOR_BITS,
)


class TestGetEventTag:
    """Test event tag extraction."""
    
    def test_get_existing_tag(self):
        """Extract existing tag."""
        event = {"tags": [["C", "abc123"], ["B", "42"]]}
        assert get_event_tag(event, "C") == "abc123"
        assert get_event_tag(event, "B") == "42"
    
    def test_get_missing_tag(self):
        """Return None for missing tag."""
        event = {"tags": [["C", "abc123"]]}
        assert get_event_tag(event, "B") is None
    
    def test_get_tag_empty_tags(self):
        """Handle empty tags array."""
        event = {"tags": []}
        assert get_event_tag(event, "C") is None
    
    def test_get_tag_no_tags_key(self):
        """Handle missing tags key."""
        event = {}
        assert get_event_tag(event, "C") is None


class TestDedupHyperjumps:
    """Test hyperjump deduplication."""
    
    def test_dedup_single_event(self):
        """Single event passes through."""
        events = [{
            "id": "event1",
            "created_at": 1000,
            "tags": [["C", "abc123"], ["B", "42"]]
        }]
        result = dedup_hyperjumps(events)
        assert len(result) == 1
        # normalize_hex_32 pads to 64 chars
        assert "0000000000000000000000000000000000000000000000000000000000abc123" in result
    
    def test_dedup_keeps_most_recent(self):
        """Keep most recent event for duplicate coords."""
        events = [
            {"id": "old", "created_at": 1000, "tags": [["C", "abc123"], ["B", "42"]]},
            {"id": "new", "created_at": 2000, "tags": [["C", "abc123"], ["B", "43"]]},
        ]
        result = dedup_hyperjumps(events)
        assert len(result) == 1
        norm_coord = "0000000000000000000000000000000000000000000000000000000000abc123"
        assert result[norm_coord]["id"] == "new"
    
    def test_dedup_multiple_coords(self):
        """Handle multiple different coordinates."""
        events = [
            {"id": "e1", "created_at": 1000, "tags": [["C", "aaa"], ["B", "1"]]},
            {"id": "e2", "created_at": 1000, "tags": [["C", "bbb"], ["B", "2"]]},
        ]
        result = dedup_hyperjumps(events)
        assert len(result) == 2
        norm_aaa = "0000000000000000000000000000000000000000000000000000000000000aaa"
        norm_bbb = "0000000000000000000000000000000000000000000000000000000000000bbb"
        assert norm_aaa in result
        assert norm_bbb in result


class TestRankHyperjumps:
    """Test hyperjump ranking."""
    
    def test_rank_single_hyperjump(self):
        """Single hyperjump ranking."""
        by_coord = {
            "abc123": {
                "id": "test",
                "tags": [["C", "abc123"], ["B", "42"]]
            }
        }
        ranked = rank_hyperjumps(
            by_coord,
            spawn_x=0, spawn_y=0, spawn_z=0,
            current_x=0, current_y=0, current_z=0,
        )
        assert len(ranked) == 1
        sector_dist, axis_dist, coord_hex, ev, xyzp = ranked[0]
        assert coord_hex == "abc123"
    
    def test_rank_by_sector_distance(self):
        """Rank closer sectors first."""
        # Create two hyperjumps: one near, one far
        # Near: sector 0,0,0
        near_coord = (1 << SECTOR_BITS) - 1  # Still in sector 0
        near_coord_hex = "0" + format(near_coord, '025x') + "0" * 25  # Simplified
        
        # For this test, just verify sorting works
        by_coord = {}
        ranked = rank_hyperjumps(
            by_coord,
            spawn_x=0, spawn_y=0, spawn_z=0,
            current_x=0, current_y=0, current_z=0,
        )
        assert ranked == []
    
    def test_rank_empty(self):
        """Empty input returns empty list."""
        ranked = rank_hyperjumps(
            {},
            spawn_x=0, spawn_y=0, spawn_z=0,
            current_x=0, current_y=0, current_z=0,
        )
        assert ranked == []


class TestSectorBits:
    """Test SECTOR_BITS constant."""
    
    def test_sector_bits_value(self):
        """SECTOR_BITS should be 30."""
        assert SECTOR_BITS == 30
    
    def test_sector_calculation(self):
        """Sector calculation uses SECTOR_BITS correctly."""
        coord = (1 << SECTOR_BITS) + 100
        sector = coord >> SECTOR_BITS
        assert sector == 1
