# Cyberspace CLI Conformance Checklist
Spec target: `CYBERSPACE_V2.md` version `2026-03-16-h34-corrected`
Repository: `cyberspace-cli`
Status: Implemented with one known non-blocking gap (`sig` signing not yet performed in local event objects)

## 1) Coordinate Encoding (§2)
- Status: Implemented
- `xyz_to_coord`: `src/cyberspace_core/coords.py:91`
- `coord_to_xyz`: `src/cyberspace_core/coords.py:101`

## 2) Sector Tags (§3)
- Status: Implemented
- Sector tag derivation for events:
  - `src/cyberspace_cli/nostr_event.py:74`
  - `src/cyberspace_cli/nostr_event.py:82`
  - `src/cyberspace_cli/nostr_event.py:83`
  - `src/cyberspace_cli/nostr_event.py:84`
  - `src/cyberspace_cli/nostr_event.py:85`
- CLI sector output:
  - `src/cyberspace_cli/cli.py:521`

## 3) Canonical GPS→Dataspace Mapping (§4)
- Status: Implemented
- Canonical version lock:
  - `src/cyberspace_core/coords.py:52`
- Decimal/trig canonicalization:
  - `src/cyberspace_core/coords.py:56`
  - `src/cyberspace_core/coords.py:59`
  - `src/cyberspace_core/coords.py:60`
- H34 scaling (`units_per_km = 1000 * 2^33`):
  - `src/cyberspace_core/coords.py:77`
  - `src/cyberspace_core/coords.py:266`
- Rounding and clamping:
  - `src/cyberspace_core/coords.py:276`
  - `src/cyberspace_core/coords.py:277`
- Input clamp/wrap and altitude handling:
  - `src/cyberspace_core/coords.py:157`
  - `src/cyberspace_core/coords.py:166`
  - `src/cyberspace_core/coords.py:233`
  - `src/cyberspace_core/coords.py:302`
  - `src/cyberspace_core/coords.py:315`
- Reverse consistency (`u85 -> km`):
  - `src/cyberspace_core/coords.py:340`
- Golden vectors test lock:
  - `tests/test_vectors.py:63`

## 4) Movement Proofs (§5)
- Status: Implemented
- LCA and aligned subtree behavior:
  - `src/cyberspace_core/movement.py:16`
  - `src/cyberspace_core/movement.py:22`
  - `src/cyberspace_core/movement.py:49`
- Spatial 3D combine (`region_n`):
  - `src/cyberspace_core/movement.py:130`
- Terrain-derived temporal K:
  - `src/cyberspace_core/terrain.py:31`
  - `src/cyberspace_core/terrain.py:40`
  - `src/cyberspace_core/terrain.py:46`
  - `src/cyberspace_core/terrain.py:85`
  - `src/cyberspace_core/terrain.py:91`
- Canonical previous-event-id parsing (64-char lowercase hex):
  - `src/cyberspace_core/movement.py:103`
  - `src/cyberspace_core/movement.py:138`
- 4D preimage/proof hash:
  - `src/cyberspace_core/movement.py:155`
  - `src/cyberspace_core/movement.py:158`
  - `src/cyberspace_core/movement.py:159`
  - `src/cyberspace_core/movement.py:160`
- Integer byte encoding canonicalization:
  - `src/cyberspace_core/cantor.py:11`
- Temporal/vector tests:
  - `tests/test_vectors.py:145`
  - `tests/test_temporal.py:48`
  - `tests/test_temporal.py:58`
  - `tests/test_temporal.py:68`

## 5) Nostr Movement Chain Integration (§6)
- Status: Implemented (signature generation deferred)
- NIP-01 serialization/id:
  - `src/cyberspace_cli/nostr_event.py:14`
  - `src/cyberspace_cli/nostr_event.py:28`
- Spawn event structure:
  - `src/cyberspace_cli/nostr_event.py:89`
  - `src/cyberspace_cli/nostr_event.py:90`
- Hop event structure:
  - `src/cyberspace_cli/nostr_event.py:140`
  - `src/cyberspace_cli/nostr_event.py:152`
  - `src/cyberspace_cli/nostr_event.py:153`
  - `src/cyberspace_cli/nostr_event.py:154`
  - `src/cyberspace_cli/nostr_event.py:155`
  - `src/cyberspace_cli/nostr_event.py:156`
  - `src/cyberspace_cli/nostr_event.py:157`
- Move-chain linkage from previous event id:
  - `src/cyberspace_cli/cli.py:1660`
  - `src/cyberspace_cli/cli.py:1661`
  - `src/cyberspace_cli/cli.py:1743`
- Known gap:
  - `sig` is intentionally blank in local objects (`src/cyberspace_cli/nostr_event.py:70`)

## 6) Location-Based Encryption & Discovery (§7)
- Status: Implemented
- Region key derivation (`location_decryption_key`, `lookup_id`):
  - `src/cyberspace_core/location_encryption.py:42`
  - `src/cyberspace_core/location_encryption.py:44`
- Region computation by aligned subtree height:
  - `src/cyberspace_core/location_encryption.py:21`
  - `src/cyberspace_core/location_encryption.py:36`
- Encrypted content kind and required `d` tag:
  - `src/cyberspace_cli/nostr_event.py:118`
  - `src/cyberspace_cli/nostr_event.py:128`
  - `src/cyberspace_cli/nostr_event.py:131`
- Optional height hint `h`:
  - `src/cyberspace_cli/nostr_event.py:136`
- CLI workflows:
  - `src/cyberspace_cli/cli.py:1005`
  - `src/cyberspace_cli/cli.py:1076`
  - `src/cyberspace_cli/cli.py:1159`
- Lookup vector test:
  - `tests/test_location_encryption.py:7`

## 7) Visualization Conventions (§10)
- Status: Implemented
- Cyberspace → mpl axis mapping:
  - `src/cyberspace_cli/visualizer/viz.py:107`
- Black sun tangency helper:
  - `src/cyberspace_cli/visualizer/viz.py:121`
- Dataspace km conversion:
  - `src/cyberspace_cli/visualizer/viz.py:84`
- Scene rendering path:
  - `src/cyberspace_cli/visualizer/viz.py:173`
- Visualization conformance tests:
  - `tests/test_visualization_vectors.py:20`
  - `tests/test_visualization_vectors.py:48`
  - `tests/test_visualization_vectors.py:73`

## 8) Validation Snapshot
- Test command:
  - `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- Last full run status:
  - `74 tests`, `OK`
