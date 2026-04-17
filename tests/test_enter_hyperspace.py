"""Tests for enter-hyperspace action per DECK-0001 §I.3."""

import pytest
from cyberspace_cli.nostr_event import make_enter_hyperspace_event


class TestEnterHyperspaceEvent:
    """Test enter-hyperspace action creation per DECK-0001 §I.3."""

    def test_minimal_enter_hyperspace_event(self):
        """Create minimal enter-hyperspace event with required tags."""
        pubkey_hex = "a" * 64
        created_at = 1234567890
        genesis_event_id = "b" * 64
        previous_event_id = "c" * 64
        prev_coord_hex = "d" * 64
        coord_hex = "e" * 64
        merkle_root_hex = "f" * 64
        block_height = 1606
        axis = "Y"
        proof_hex = "0" * 64
        
        event = make_enter_hyperspace_event(
            pubkey_hex=pubkey_hex,
            created_at=created_at,
            genesis_event_id=genesis_event_id,
            previous_event_id=previous_event_id,
            prev_coord_hex=prev_coord_hex,
            coord_hex=coord_hex,
            merkle_root_hex=merkle_root_hex,
            block_height=block_height,
            axis=axis,
            proof_hex=proof_hex,
        )
        
        # Verify basic structure
        assert event["kind"] == 3333
        assert event["content"] == ""
        assert "tags" in event
        
        # Verify required tags
        def get_tag(tags, key, marker=None):
            """Get tag value by key and optional marker."""
            for tag in tags:
                if len(tag) >= 2 and tag[0] == key:
                    if marker is None:
                        return tag[1]
                    elif len(tag) >= 4 and tag[3] == marker:
                        return tag[1]
            return None
        
        assert get_tag(event["tags"], "A") == "enter-hyperspace"
        assert get_tag(event["tags"], "e", "genesis") == genesis_event_id
        assert get_tag(event["tags"], "e", "previous") == previous_event_id
        assert get_tag(event["tags"], "c") == prev_coord_hex
        assert get_tag(event["tags"], "C") == coord_hex
        assert get_tag(event["tags"], "M") == merkle_root_hex
        assert get_tag(event["tags"], "B") == str(block_height)
        assert get_tag(event["tags"], "axis") == axis
        assert get_tag(event["tags"], "proof") == proof_hex
        
        # Verify sector tags exist
        assert get_tag(event["tags"], "X") is not None
        assert get_tag(event["tags"], "Y") is not None
        assert get_tag(event["tags"], "Z") is not None
        assert get_tag(event["tags"], "S") is not None

    def test_axis_values(self):
        """Test enter-hyperspace with different axis values."""
        for axis in ["X", "Y", "Z"]:
            event = make_enter_hyperspace_event(
                pubkey_hex="a" * 64,
                created_at=1234567890,
                genesis_event_id="b" * 64,
                previous_event_id="c" * 64,
                prev_coord_hex="d" * 64,
                coord_hex="e" * 64,
                merkle_root_hex="f" * 64,
                block_height=1606,
                axis=axis,
                proof_hex="0" * 64,
            )
            
            tags_dict = {tag[0]: tag[1] for tag in event["tags"] if len(tag) >= 2}
            assert tags_dict["axis"] == axis

    def test_invalid_axis_raises(self):
        """Invalid axis value should raise ValueError."""
        with pytest.raises(ValueError, match="axis must be"):
            make_enter_hyperspace_event(
                pubkey_hex="a" * 64,
                created_at=1234567890,
                genesis_event_id="b" * 64,
                previous_event_id="c" * 64,
                prev_coord_hex="d" * 64,
                coord_hex="e" * 64,
                merkle_root_hex="f" * 64,
                block_height=1606,
                axis="invalid",
                proof_hex="0" * 64,
            )

    def test_block_height_as_string(self):
        """Block height should be stored as string in B tag."""
        event = make_enter_hyperspace_event(
            pubkey_hex="a" * 64,
            created_at=1234567890,
            genesis_event_id="b" * 64,
            previous_event_id="c" * 64,
            prev_coord_hex="d" * 64,
            coord_hex="e" * 64,
            merkle_root_hex="f" * 64,
            block_height=850000,
            axis="X",
            proof_hex="0" * 64,
        )
        
        tags_dict = {tag[0]: tag[1] for tag in event["tags"] if len(tag) >= 2}
        assert tags_dict["B"] == "850000"
        assert isinstance(tags_dict["B"], str)
