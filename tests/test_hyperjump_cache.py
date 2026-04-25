"""Tests for cyberspace_cli.hyperjump_cache module."""
import pytest
from cyberspace_cli.hyperjump_cache import dedup_hyperjumps


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
        norm_coord = "0000000000000000000000000000000000000000000000000000000000abc123"
        assert norm_coord in result
    
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
    
    def test_dedup_skips_missing_c_tag(self):
        """Skip events without C tag."""
        events = [
            {"id": "no_c", "created_at": 1000, "tags": [["B", "42"]]},
            {"id": "has_c", "created_at": 1000, "tags": [["C", "abc"], ["B", "1"]]},
        ]
        result = dedup_hyperjumps(events)
        # Events without C tag are skipped, so only has_c remains
        assert len(result) == 1
        norm_abc = "0000000000000000000000000000000000000000000000000000000000000abc"
        assert norm_abc in result
    
    def test_dedup_empty_list(self):
        """Empty list returns empty dict."""
        result = dedup_hyperjumps([])
        assert result == {}
