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
  cyberspace history --json

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
- cyberspace spec
- cyberspace spawn [--from-key <nsec|hex>] [--chain <label>]
- cyberspace whereami
- cyberspace sector
- cyberspace 3d
  (optional GUI; install: pip install 'cyberspace-cli[visualizer]' and you may need python3-tk)
- cyberspace lcaplot
  (optional GUI; plots lca_height(v, v±1) spikes + 2^h block boundaries; install extras as above)
  Default center: your current coordinate’s selected axis value (if you have local state), else 0.
- cyberspace target <coord256> [--label <name>]
  Set the current movement target (stored locally in state.json).
- cyberspace target list
  List targets and show which is current.
- cyberspace move (--by dx,dy,dz | --by 0,0,0,plane | --to x,y,z[,plane] | --to 0x<coord256> | --toward <dest>) [--max-lca-height N] [--hyperjump] [--exit-hyperjump]
  Default --max-lca-height comes from config (see: cyberspace config show).
  If no destination is provided, `cyberspace move` defaults to moving `--toward` the current target.
  Tip: if you include spaces, quote the comma-list: cyberspace move --by "-1, 0, 0"
  Plane switch: cyberspace move --by 0,0,0,1  (ideaspace)
  Hyperjump: cyberspace move --to 0x<coord256> --hyperjump
             cyberspace move --toward 0x<coord256> --hyperjump
  While on the hyperjump system, normal hops require --exit-hyperjump.
- cyberspace hyperjump nearest [--radius 10] [--coord <coord>] [--relay wss://cyberspace.nostr1.com] [--verbose]
  Queries kind=321 block anchor events in nearby sectors and prints direction hints.
- cyberspace hyperjump show <blockheight> [--relay wss://cyberspace.nostr1.com]
  Shows coordinate/plane info for a specific hyperjump block height.
- cyberspace hyperjump to <blockheight> [--view]
  Moves to a specific hyperjump block height, or only previews it with --view.
- cyberspace hyperjump next [--view]
- cyberspace hyperjump prev [--view]
  Moves to the next/previous hyperjump block, or only previews it with --view.
  Note: action-creating hyperjump commands require that you are currently on the hyperjump system.
- cyberspace bench
  (benchmarks proof compute time by LCA height and recommends a max-lca-height)
- cyberspace config show
- cyberspace config set --max-lca-height N
- cyberspace config set-geoid-model <egm2008-2_5|egm2008-1>
- cyberspace geoid doctor [--model <egm2008-2_5|egm2008-1>] [--effective-only]
- cyberspace gps <lat,lon>
  (or: cyberspace gps --lat <lat> --lon <lon>)
  (for altitude above WGS84 ellipsoid: --altitude-wgs84 <meters>; --no-clamp is implied)
  (for altitude above mean sea level: --altitude-sealevel <meters>; N is auto-derived from geoid model unless overridden by --geoid-offset-m)
  (optional per-command override: --geoid-model <egm2008-2_5|egm2008-1>)
  (or: cyberspace gps --coord <coord256>  # derive lat/lon/alt)
- cyberspace cantor (--from-xyz x,y,z --to-xyz x,y,z | --from-coord <hex> --to-coord <hex>)
- cyberspace history [--limit N] [--json]
- cyberspace encrypt (--text <txt> | --file <path>) --height <h> [--coord <coord256>] [--publish-height] [--hint <text>] [--kind 33330]
  Emits kind=33330 with tags: d, encrypted(aes-256-gcm,<base64 nonce|ciphertext|tag>), version=2; h is only included with --publish-height. --hint sets event content.
- cyberspace decrypt (--event-json '<json>' | --event-file <path>) [--height <h>] [--coord <coord256>]
  Decrypts a location-encrypted event using your current coord (or overridden coord).
- cyberspace scan [--min-height N] [--max-height N] [--coord <coord256>] [--events-file <jsonl|->]
  Prints lookup IDs across heights and optionally matches events by d tag.
- cyberspace chain list
- cyberspace chain use <label>
- cyberspace chain status
- cyberspace target list
- cyberspace target set <coord_hex> [--label <label>]
- cyberspace target use <label>

Security note
This prototype stores the private key locally in plaintext. Treat it like a hot
wallet key.
'''
