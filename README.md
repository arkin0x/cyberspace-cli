# cyberspace-cli
A CLI client for navigating **Cyberspace v2**.

This repo is intentionally separate from the current research/prototype code under `../v2/`.

## What this CLI does (today)
- Creates/loads an identity (Nostr Schnorr keypair)
- Creates and manages a **local movement chain**: a labeled series of **Nostr-style JSON events**
- Computes and stores **v2 movement proofs** (per-axis Cantor tree) in hop events

## What this CLI does NOT do (yet)
- Publish events to relays
- Sign events (`sig` is currently left blank so we can sign at publish-time)

## Install
### Dev install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## Quick usage
For the extended guide (also available offline):
```bash
cyberspace help
```

Typical flow:
```bash
# create identity + genesis event (also selects this chain as active)
cyberspace spawn

# move locally (appends a hop event)
cyberspace move --by 1,0,0

# inspect your chain
cyberspace chain status
cyberspace history
```

## Command reference
```bash
# open the upstream spec
cyberspace spec

# identity + chain genesis
cyberspace spawn
cyberspace spawn --from-key <nsec_or_32-byte-hex>
cyberspace spawn --chain mychain

# chain management
cyberspace chain list
cyberspace chain use mychain
cyberspace chain status

# movement (local-only)
# Tip: keep comma-lists unspaced (or quote them) so negatives don’t get parsed as flags.
cyberspace move --by -1,0,0
cyberspace move --by "-1, 0, 0"

# Destination can be xyz or a 256-bit coord hex (leading zeros optional)
cyberspace move --to x,y,z
cyberspace move --to 0x2b50e88

# Move continuously toward a destination (each hop is appended immediately; Ctrl+C keeps progress)
cyberspace move --toward 0x2b50e88

# Very large hops are rejected by default because proof computation is O(2^h)
# where h is the per-axis LCA height. You can override (not recommended):
cyberspace move --to 0x2b50e88 --max-lca-height 25

cyberspace history --limit 50
cyberspace history --json

# position utilities
cyberspace whereami
cyberspace sector
cyberspace gps 37.7749,-122.4194
# or
cyberspace gps --lat 37.7749 --lon -122.4194

# cantor + encryption/debug (prints LCA heights, Cantor roots, and 1-hash/2-hash ids)
cyberspace cantor --from-xyz 0,0,0 --to-xyz 3,2,1
```

## Local storage
- State: `~/.cyberspace/state.json`
  - Includes the current coordinate and which chain is active.
- Chains: `~/.cyberspace/chains/<label>.jsonl`
  - One JSON event per line.

## Environment variables
- `CYBERSPACE_HOME`: override `~/.cyberspace`
- `CYBERSPACE_STATE_PATH`: override the state path (useful for testing)

## Tests (golden vectors)
```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

## Security
This prototype stores the private key locally in plaintext. Treat it like a hot wallet key.
