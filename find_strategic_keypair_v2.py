#!/usr/bin/env python3
"""Find strategic keypair with aligned sector for hyperspace entry.

Uses the same pubkey derivation as cyberspace-cli: X coordinate from compressed pubkey.
"""

import secrets
import time

def pubkey_hex_from_privkey(privkey_bytes):
    """Derive pubkey X coordinate from private key using coincurve (same as CLI)."""
    from coincurve import PrivateKey
    pk = PrivateKey(privkey_bytes)
    compressed = pk.public_key.format(compressed=True)
    # Compressed form: 0x02/0x03 + 32-byte X coordinate
    x_only = compressed[1:]
    return x_only.hex()

def compute_sectors_from_pubkey(pubkey_hex):
    """Compute XYZ sectors from pubkey (used as coord256 directly)."""
    coord_int = int.from_bytes(bytes.fromhex(pubkey_hex), 'big')
    
    # De-interleave XYZXYZ...P pattern
    x, y, z = 0, 0, 0
    for i in range(85):
        x |= ((coord_int >> (i * 3)) & 1) << i
        y |= ((coord_int >> (i * 3 + 1)) & 1) << i
        z |= ((coord_int >> (i * 3 + 2)) & 1) << i
    
    # Extract sectors (top 55 bits of each 85-bit coordinate)
    return x >> 30, y >> 30, z >> 30

def find_valid_keypair(max_sector=1_000_000_000, max_attempts=20_000_000):
    """Find keypair where pubkey-derived coordinate has at least one sector < max_sector."""
    for attempt in range(max_attempts):
        privkey = secrets.token_bytes(32)
        pubkey = pubkey_hex_from_privkey(privkey)
        sx, sy, sz = compute_sectors_from_pubkey(pubkey)
        
        min_sector = min(sx, sy, sz)
        if min_sector < max_sector:
            axis = ['X', 'Y', 'Z'][[sx, sy, sz].index(min_sector)]
            return privkey.hex(), pubkey, axis, (sx, sy, sz), attempt + 1
        
        if (attempt + 1) % 100000 == 0:
            print(f"  Attempt {attempt + 1:,}...")
    
    return None, None, None, None, max_attempts

if __name__ == "__main__":
    print("Starting strategic keypair search...")
    print("Target: at least one sector < 1,000,000,000")
    print("Expected attempts: ~12 million (6-7 minutes at 32K/s)")
    print()
    
    start = time.time()
    privkey, pubkey, axis, sectors, attempts = find_valid_keypair()
    elapsed = time.time() - start
    
    if privkey:
        print(f"\n✅ SUCCESS on attempt {attempts:,} ({elapsed:.1f}s)")
        print(f"Private key: {privkey}")
        print(f"Public key:  {pubkey}")
        print(f"Aligned axis: {axis}")
        print(f"Sectors: X={sectors[0]:,}, Y={sectors[1]:,}, Z={sectors[2]:,}")
        print(f"Min sector: {min(sectors):,} ({'<' if min(sectors) < 1_000_000 else '>'} 1B)")
        print(f"\nSpeed: {attempts / elapsed:,.0f} attempts/second")
        print(f"\n=== SAVE THESE FOR SPAWN ===")
        print(f"cyberspace spawn --from-key {privkey}")
    else:
        print(f"\n❌ No valid keypair found in {attempts:,} attempts ({elapsed:.1f}s)")
