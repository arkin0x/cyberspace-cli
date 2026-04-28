"""Event builders for cyberspace-cli.

Creates signed Nostr events for hop, sidestep, and hyperjump movements.
"""
from typing import List, Optional, Dict, Any
import time

from cyberspace_cli.nostr_event import (
    make_hop_event as _make_hop_event,
    make_sidestep_event as _make_sidestep_event,
    make_hyperjump_event as _make_hyperjump_event,
)


class EventBuilder:
    """Builds movement events with consistent structure."""
    
    def __init__(
        self,
        pubkey_hex: str,
        genesis_event_id: str,
        previous_event_id: str,
    ):
        self.pubkey_hex = pubkey_hex
        self.genesis_event_id = genesis_event_id
        self.previous_event_id = previous_event_id
        self.created_at = int(time.time())
    
    def build_hop_event(
        self,
        prev_coord_hex: str,
        coord_hex: str,
        proof_hash_hex: str,
    ) -> Dict[str, Any]:
        """Build a hop movement event.
        
        Args:
            prev_coord_hex: Previous coordinate (hex)
            coord_hex: New coordinate (hex)
            proof_hash_hex: Hop proof hash (hex)
            
        Returns:
            Signed Nostr event dict
        """
        return _make_hop_event(
            pubkey_hex=self.pubkey_hex,
            created_at=self.created_at,
            genesis_event_id=self.genesis_event_id,
            previous_event_id=self.previous_event_id,
            prev_coord_hex=prev_coord_hex,
            coord_hex=coord_hex,
            proof_hash_hex=proof_hash_hex,
        )
    
    def build_sidestep_event(
        self,
        prev_coord_hex: str,
        coord_hex: str,
        proof_hash_hex: str,
        merkle_roots_hex: str,
        merkle_proofs_hex: str,
        lca_heights: List[int],
    ) -> Dict[str, Any]:
        """Build a sidestep movement event.
        
        Args:
            prev_coord_hex: Previous coordinate (hex)
            coord_hex: New coordinate (hex)
            proof_hash_hex: Sidestep proof hash (hex)
            merkle_roots_hex: Colon-separated Merkle roots
            merkle_proofs_hex: Colon-separated inclusion proofs
            lca_heights: [hx, hy, hz] LCA heights
            
        Returns:
            Signed Nostr event dict
        """
        return _make_sidestep_event(
            pubkey_hex=self.pubkey_hex,
            created_at=self.created_at,
            genesis_event_id=self.genesis_event_id,
            previous_event_id=self.previous_event_id,
            prev_coord_hex=prev_coord_hex,
            coord_hex=coord_hex,
            proof_hash_hex=proof_hash_hex,
            merkle_roots_hex=merkle_roots_hex,
            merkle_proofs_hex=merkle_proofs_hex,
            lca_heights=lca_heights,
        )
    
    def build_hyperjump_event(
        self,
        prev_coord_hex: str,
        coord_hex: str,
        to_height: str,
    ) -> Dict[str, Any]:
        """Build a hyperjump movement event.
        
        Args:
            prev_coord_hex: Previous coordinate (hex)
            coord_hex: New coordinate (hex)
            to_height: Target height (B tag value)
            
        Returns:
            Signed Nostr event dict
        """
        return _make_hyperjump_event(
            pubkey_hex=self.pubkey_hex,
            created_at=self.created_at,
            genesis_event_id=self.genesis_event_id,
            previous_event_id=self.previous_event_id,
            prev_coord_hex=prev_coord_hex,
            coord_hex=coord_hex,
            to_height=to_height,
        )


def make_movement_event(
    event_type: str,
    pubkey_hex: str,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    **kwargs,
) -> Dict[str, Any]:
    """Factory function to build movement events.
    
    Args:
        event_type: 'hop', 'sidestep', or 'hyperjump'
        pubkey_hex: User's public key (hex)
        genesis_event_id: Genesis event ID
        previous_event_id: Previous event ID
        prev_coord_hex: Previous coordinate (hex)
        coord_hex: New coordinate (hex)
        **kwargs: Type-specific arguments:
            - hop: proof_hash_hex
            - sidestep: proof_hash_hex, merkle_roots_hex, merkle_proofs_hex, lca_heights
            - hyperjump: to_height
            
    Returns:
        Signed Nostr event dict
    """
    builder = EventBuilder(pubkey_hex, genesis_event_id, previous_event_id)
    
    if event_type == 'hop':
        return builder.build_hop_event(
            prev_coord_hex, coord_hex, kwargs['proof_hash_hex']
        )
    elif event_type == 'sidestep':
        return builder.build_sidestep_event(
            prev_coord_hex,
            coord_hex,
            kwargs['proof_hash_hex'],
            kwargs['merkle_roots_hex'],
            kwargs['merkle_proofs_hex'],
            kwargs['lca_heights'],
        )
    elif event_type == 'hyperjump':
        return builder.build_hyperjump_event(
            prev_coord_hex, coord_hex, kwargs['to_height']
        )
    else:
        raise ValueError(f"Unknown event type: {event_type}")
