HELP_TEXT = r'''
Cyberspace CLI (v2)

This tool manages a *local* movement chain in Cyberspace. Publishing to relays is
intentionally not implemented yet.

Quick start

  # install (dev)
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -U pip
  pip install -e .

  # create identity + genesis event
  cyberspace spawn

  # show current coordinate
  cyberspace whereami

  # move (local-only) and append a hop event to the active chain
  cyberspace move --by 1,0,0

  # inspect chain
  cyberspace chain status
  cyberspace history

Core ideas
- Your Nostr pubkey (32-byte x-only hex) is your spawn coordinate.
- A chain is a labeled JSONL file containing Nostr-style events.
- Each hop includes a v2 Cantor-tree proof hash in a "proof" tag.

Local storage
- State:  ~/.cyberspace/state.json
- Chains: ~/.cyberspace/chains/<label>.jsonl

Environment variables
- CYBERSPACE_HOME: override ~/.cyberspace
- CYBERSPACE_STATE_PATH: override the state.json path (useful for tests)

Commands (high-level)
- cyberspace spawn [--from-key <nsec|hex>] [--chain <label>]
- cyberspace whereami
- cyberspace sector
- cyberspace move (--by dx,dy,dz | --to x,y,z[,plane])
  Tip: if you include spaces, quote the comma-list: cyberspace move --by "-1, 0, 0"
- cyberspace gps <lat,lon>
  (or: cyberspace gps --lat <lat> --lon <lon>)
- cyberspace history [--limit N]
- cyberspace chain list
- cyberspace chain use <label>
- cyberspace chain status

Security note
This prototype stores the private key locally in plaintext. Treat it like a hot
wallet key.
'''
