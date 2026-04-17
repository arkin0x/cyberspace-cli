"""Tests for updated hyperjump action per DECK-0001 §7-8."""

import pytest
from cyberspace_cli.nostr_event import make_hyperjump_event
from cyberspace_core.cantor import build_hyperspace_proof, compute_temporal_seed


class TestHyperjumpEventUpdated:
    """Test hyperjump action with DECK-0001 compliant tags."""

    def test_hyperjump_with_from_tags_and_proof(self):
        """Hyperjump event should include from_height, from_hj, and proof tags."""
        pubkey_hex = "a" * 64
        created_at = 1234567890
        genesis_event_id = "b" * 64
        previous_event_id = "c" * 64
        prev_coord_hex = "d" * 64
        coord_hex = "e" * 64
        from_height = 1606
        from_hj_hex = "f" * 64
        to_height = 1607
        
        # Compute hyperspace proof (temporal seed + block heights)
        prev_event_id_bytes = bytes.fromhex(previous_event_id)
        temporal_seed = compute_temporal_seed(prev_event_id_bytes)
        leaves = [temporal_seed, from_height, to_height]
        proof_root = build_hyperspace_proof(leaves)
        proof_hex = format(proof_root, 'x')
        
        event = make_hyperjump_event(
            pubkey_hex=pubkey_hex,
            created_at=created_at,
            genesis_event_id=genesis_event_id,
            previous_event_id=previous_event_id,
            prev_coord_hex=prev_coord_hex,
            coord_hex=coord_hex,
            to_height=to_height,
            from_height=from_height,
            from_hj_hex=from_hj_hex,
            proof_hex=proof_hex,
        )
        
        # Verify required tags per DECK-0001 §7
        def get_tag(tags, key, marker=None):
            for tag in tags:
                if len(tag) >= 2 and tag[0] == key:
                    if marker is None:
                        return tag[1]
                    elif len(tag) >= 4 and tag[3] == marker:
                        return tag[1]
            return None
        
        assert get_tag(event["tags"], "A") == "hyperjump"
        assert get_tag(event["tags"], "e", "genesis") == genesis_event_id
        assert get_tag(event["tags"], "e", "previous") == previous_event_id
        assert get_tag(event["tags"], "c") == prev_coord_hex
        assert get_tag(event["tags"], "C") == coord_hex
        assert get_tag(event["tags"], "from_height") == str(from_height)
        assert get_tag(event["tags"], "from_hj") == from_hj_hex
        assert get_tag(event["tags"], "B") == str(to_height)
        assert get_tag(event["tags"], "proof") == proof_hex
        
        # Verify sector tags
        assert get_tag(event["tags"], "X") is not None
        assert get_tag(event["tags"], "Y") is not None
        assert get_tag(event["tags"], "Z") is not None
        assert get_tag(event["tags"], "S") is not None

    def test_hyperjump_backward_compatibility(self):
        """Hyperjump event should work without optional DECK-0001 tags for backward compat."""
        # This tests that old-style calls still work (without from_height, from_hj, proof)
        event = make_hyperjump_event(
            pubkey_hex="a" * 64,
            created_at=1234567890,
            genesis_event_id="b" * 64,
            previous_event_id="c" * 64,
            prev_coord_hex="d" * 64,
            coord_hex="e" * 64,
            to_height=1607,
        )
        
        assert event["kind"] == 3333
        # Old style won't have from_height, from_hj, proof tags

    def test_hyperjump_proof_hex_format(self):
        """Proof should be stored as lowercase hex string."""
        prev_event_id = "c" * 64
        prev_event_id_bytes = bytes.fromhex(prev_event_id)
        temporal_seed = compute_temporal_seed(prev_event_id_bytes)
        leaves = [temporal_seed, 1606, 1607]
        proof_root = build_hyperspace_proof(leaves)
        proof_hex = format(proof_root, 'x')
        
        event = make_hyperjump_event(
            pubkey_hex="a" * 64,
            created_at=1234567890,
            genesis_event_id="b" * 64,
            previous_event_id=prev_event_id,
            prev_coord_hex="d" * 64,
            coord_hex="e" * 64,
            to_height=1607,
            from_height=1606,
            from_hj_hex="f" * 64,
            proof_hex=proof_hex,
        )
        
        def get_tag(tags, key):
            for tag in tags:
                if len(tag) >= 2 and tag[0] == key:
                    return tag[1]
            return None
        
        proof_tag = get_tag(event["tags"], "proof")
        assert proof_tag == proof_hex
        assert proof_tag == proof_tag.lower()
