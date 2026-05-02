# cyberspace-cli
A CLI client for navigating **Cyberspace v2**.

This repo is intentionally separate from the current research/prototype code under `../v2/`.

## What this CLI does (today)
- Creates/loads an identity (Nostr Schnorr keypair) and spawn event
- Creates and manages **local movement chains** (multiple labeled chains, status/history, JSON export)
- Computes and stores **v2 movement proofs** (per-axis Cantor tree) in hop events
- Supports movement workflows: `move --by`, `move --to`, `move --toward`, plane switching, and target-driven movement
- **Interactive terminal visualization** (`move viz`) for planning movements with LCA heights, terrain difficulty, and compute time estimates
- Supports DECK-0001 hyperjump tooling: nearest/show/to/next/prev queries plus hyperjump movement-event creation
- Includes coordinate and proof tooling: `whereami`, `sector`, `gps` (both directions), `cantor`, `bench`
- Supports location-encrypted content workflows: `encrypt`, `decrypt`, and `scan`
- Supports persisted local config and target management (`config`, `target` commands)
- Includes optional visual tools (`3d`, `lcaplot`) with extra dependencies

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

For the full CLI / subcommand help:
```bash
cyberspace --help
cyberspace move --help
cyberspace target --help
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

# show built-in extended help
cyberspace help

# identity + chain genesis
cyberspace spawn
cyberspace spawn --from-key <nsec_or_32-byte-hex>
cyberspace spawn --chain mychain

# chain management
cyberspace chain list
cyberspace chain use mychain
cyberspace chain status

# targets (purely local convenience)
cyberspace target list
cyberspace target set 0x2b50e88 --label mytarget
cyberspace target use mytarget

# movement (local-only)
# Tip: keep comma-lists unspaced (or quote them) so negatives don't get parsed as flags.
cyberspace move --by -1,0,0
cyberspace move --by "-1, 0, 0"

# interactive terminal visualization for movement planning
cyberspace move viz
# Navigate with arrow keys or a/d, switch axes with x/y/z, use : to jump to an offset, press Enter to execute
# Shows adjacent coordinates, LCA heights, terrain difficulty (K), and estimated compute time

# switch planes (0=dataspace, 1=ideaspace)
cyberspace move --by 0,0,0,1

# Destination can be xyz or a 256-bit coord hex (leading zeros optional)
# Note: plane is optional; defaults to your current plane.
cyberspace move --to x,y,z
cyberspace move --to x,y,z,1
cyberspace move --to 0x2b50e88

# Move continuously toward a destination (each hop is appended immediately; Ctrl+C keeps progress)
# --toward supports a target in a different plane: it will do a final plane-switch hop when xyz matches.
# While running, it prints per-hop progress.
cyberspace move --toward 0x2b50e88
# Publish a hyperjump movement event (A=hyperjump) to a known hyperjump coord.
cyberspace move --to 0x2b50e88 --hyperjump
# Or approach with normal hops and use hyperjump for the final toward step.
cyberspace move --toward 0x2b50e88 --hyperjump
# If you're on the hyperjump system and want a normal hop, confirm with:
cyberspace move --to x,y,z --exit-hyperjump

# If no destination is provided, `cyberspace move` defaults to moving `--toward` the current target.
cyberspace move

# Very large hops are rejected by default because proof computation is O(2^h)
# where h is the per-axis LCA height.
# You can override per-command:
cyberspace move --to 0x2b50e88 --max-lca-height 25

# Or persist a default so you don't need the flag every time:
cyberspace config show
cyberspace config set --max-lca-height 16
cyberspace config set-geoid-model egm2008-2_5
cyberspace config set-geoid-model egm2008-1
cyberspace geoid doctor
cyberspace geoid doctor --effective-only
cyberspace geoid doctor --model egm2008-1

# Benchmark your machine and get a recommended default ("Optimal Speed" near ~2 seconds):
cyberspace bench

cyberspace history --limit 50
cyberspace history --json

# position utilities
cyberspace whereami
cyberspace sector
cyberspace hyperjump nearest
cyberspace hyperjump nearest --radius 10 --relay wss://cyberspace.nostr1.com
cyberspace hyperjump nearest --coord 0x2b50e88
cyberspace hyperjump nearest --verbose
cyberspace hyperjump show 940158
cyberspace hyperjump to 940158
cyberspace hyperjump to 940158 --view
cyberspace hyperjump next
cyberspace hyperjump prev
cyberspace hyperjump next --view

# open the built-in 3D visualizer (optional deps)
cyberspace 3d
# set the default "View Earth" altitude (km above Earth surface)
cyberspace 3d --earth-altitude-km 8000

# sector-local 3D view (renders only the current sector cube; spawn renders only if in the same sector)
cyberspace 3d --sector

# plot LCA spikes + 2^h boundaries around your current axis value (optional deps)
cyberspace lcaplot
cyberspace lcaplot --axis z --span 2048 --max-lca-height 17

cyberspace gps 37.7749,-122.4194
# or
cyberspace gps --lat 37.7749 --lon -122.4194
# altitude above WGS84 ellipsoid (GPS-native): no-clamp is implied
cyberspace gps 37.7749,-122.4194 --altitude-wgs84 123.45
# altitude above mean sea level: geoid separation N is auto-derived (h = H + N)
cyberspace gps 37.7749,-122.4194 --altitude-sealevel 95.0
# optional: manual override for geoid separation N
cyberspace gps 37.7749,-122.4194 --altitude-sealevel 95.0 --geoid-offset-m 30.5
# optional: per-command model override
cyberspace gps 37.7749,-122.4194 --altitude-sealevel 95.0 --geoid-model egm2008-1
# reverse: coord256 -> gps (lat/lon/alt)
cyberspace gps --coord 0xc4943fa01bb22b95946ec1605717047a3b79bd717d5d84e35a12cb56df76134a

# cantor + encryption/debug (prints LCA heights, Cantor roots, and 1-hash/2-hash ids)
cyberspace cantor --from-xyz 0,0,0 --to-xyz 3,2,1

# location-encrypted content events
cyberspace encrypt --text "hello nearby avatars" --height 8
cyberspace encrypt --text "hello nearby avatars" --height 8 --publish-height
cyberspace decrypt --event-file ./event.json
cyberspace scan --min-height 1 --max-height 12
cyberspace scan --events-file ./events.jsonl
```

## Optional GUI dependencies
The `cyberspace 3d` and `cyberspace lcaplot` commands require extra dependencies:
```bash
pip install 'cyberspace-cli[visualizer]'
```

On Linux you may also need `python3-tk` for Tkinter.

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
## Spec conformance checklist
- `docs/spec-conformance/CYBERSPACE_V2_2026-03-16-h34.md`

## Geoid models for sea-level altitude conversion (MSL -> WGS84)
When you provide `--altitude-sealevel`, the CLI converts orthometric height `H` to ellipsoidal height `h` using:
- `h = H + N`
- `N` = geoid undulation from a gridded geoid model.

Supported models:
- `egm2008-2_5` (default): good balance of precision vs footprint.
- `egm2008-1`: finer grid, larger footprint.

Switch defaults with:
```bash
cyberspace config set-geoid-model egm2008-2_5
cyberspace config set-geoid-model egm2008-1
```

Verify install health with:
```bash
cyberspace geoid doctor
cyberspace geoid doctor --effective-only
cyberspace geoid doctor --model egm2008-1
```

Data tradeoffs (GeographicLib geoid datasets):
- `egm2008-2_5`: ~75 MB installed, ~35 MB download.
- `egm2008-1`: ~470 MB installed, ~170 MB download.

Purpose/tradeoff summary:
- Use `egm2008-2_5` for most CLI/mobile workflows where storage and install friction matter.
- Use `egm2008-1` when you want denser geoid sampling and can afford the larger dataset.

Data search paths:
- `CYBERSPACE_GEOID_PATH` (highest precedence)
- `GEOGRAPHICLIB_GEOID_PATH`
- `GEOGRAPHICLIB_DATA/geoids`
- `CYBERSPACE_HOME/geoids` (or `~/.cyberspace/geoids`)
- `/usr/share/GeographicLib/geoids`
- `/usr/local/share/GeographicLib/geoids`
- `/opt/homebrew/share/GeographicLib/geoids`

Sources for model sizes and usage:
- GeographicLib geoid dataset table: https://geographiclib.sourceforge.io/C++/doc/geoid.html
- GeoidEval model/cache notes: https://geographiclib.sourceforge.io/html/GeoidEval.1.html
- PROJ EGM2008 2.5' grid size reference: https://ftp.osuosl.org/pub/osgeo/download/proj/vdatum/egm08_25/
- PROJ EGM96 15' grid size reference: https://download.osgeo.org/proj/vdatum/egm96_15/

## Security
This prototype stores the private key locally in plaintext. Treat it like a hot wallet key.
