from __future__ import annotations

import hashlib


def cantor_pair(a: int, b: int) -> int:
    s = a + b
    return (s * (s + 1)) // 2 + b


def int_to_bytes_be_min(n: int) -> bytes:
    if n < 0:
        raise ValueError("expected non-negative int")
    if n == 0:
        return b"\x00"
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_int_hex(n: int) -> str:
    return sha256_hex(int_to_bytes_be_min(n))


def int_to_hex_be_min(n: int, *, prefix: str = "0x") -> str:
    """Hex string for an int using minimal big-endian bytes (0 -> 0x00).

    This avoids Python's base-10 int->str conversion limits for extremely large integers.
    """
    return prefix + int_to_bytes_be_min(n).hex()


def compute_temporal_seed(previous_event_id: bytes) -> int:
    """Compute temporal seed from previous event ID per DECK-0001 §8.
    
    temporal_seed = int.from_bytes(previous_event_id, "big") % 2^256
    
    Args:
        previous_event_id: The NIP-01 event ID (32 bytes) of the most recent movement event
        
    Returns:
        The temporal seed for Cantor tree construction
    """
    if len(previous_event_id) != 32:
        raise ValueError("previous_event_id must be 32 bytes")
    
    seed_int = int.from_bytes(previous_event_id, "big")
    return seed_int % (2**256)


def build_hyperspace_proof(leaves: list[int]) -> int:
    """Build Cantor pairing tree from leaves, return root per DECK-0001 §8.
    
    Cantor tree construction:
    1. Pair adjacent elements using cantor_pair()
    2. Carry forward unpaired leaf to next level
    3. Repeat until single root remains
    
    For hyperspace traversal, leaves = [temporal_seed, B_from, B_from+1, ..., B_to]
    
    Args:
        leaves: List of integers to build tree from
        
    Returns:
        The root of the Cantor tree
        
    Raises:
        ValueError: If leaves list is empty
    """
    if not leaves:
        raise ValueError("leaves list cannot be empty")
    
    if len(leaves) == 1:
        return leaves[0]
    
    current_level = leaves
    
    while len(current_level) > 1:
        next_level = []
        # Pair adjacent elements
        for i in range(0, len(current_level) - 1, 2):
            parent = cantor_pair(current_level[i], current_level[i+1])
            next_level.append(parent)
        # Carry forward unpaired leaf
        if len(current_level) % 2 == 1:
            next_level.append(current_level[-1])
        current_level = next_level
    
    return current_level[0]  # Root
