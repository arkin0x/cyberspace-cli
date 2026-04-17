# DECK-0001 Implementation Status

**Branch:** `deck-0001-implementation` (to be created)
**Spec:** `~/repos/cyberspace/decks/DECK-0001-hyperspace.md` (PR #14)
**Started:** 2026-04-16
**Last updated:** 2026-04-16 22:30

---

## Implementation Checklist

### 1. ✅ SPEC CONFORMANCE
- [x] Reviewed DECK-0001-hyperspace.md (PR #14, commit d4cd829)
- [ ] Audit existing CLI commands against spec
- [ ] Document gaps in this file

### 2. ✅ SIDESTEP IMPLEMENTATION (already complete)
- [x] Sidestep action implemented (kind=3333, A=sidestep) with Merkle proof
- [x] Integrated into move --toward logic (commit 6640df9)
- [ ] Add --sidestep flag to move command (if not present)
- [ ] Add benchmark-sidestep command
- [ ] Test with various LCA heights

**Status:** MERKLE ENGINE EXISTS. Need to verify CLI integration and add benchmark command.

### 3. ❌ ENTER-HYPERSPACE IMPLEMENTATION
- [ ] Implement enter-hyperspace action (kind=3333, A=enter-hyperspace)
- [ ] Required tags: A, e genesis, e previous, c, C, M, B, axis, proof, X, Y, Z, S
- [ ] Implement sector extraction (de-interleaving) per spec §I.2
- [ ] Implement validation per spec §I.3
- [ ] Add enter-hyperspace command to CLI

**Status:** NOT STARTED

### 4. ⚠️ HYPERJUMP SEARCH MODIFICATION
- [x] Hyperjump search exists with sector-based ranking
- [ ] Modify to use sector planes (not Merkle root coordinates) as entry targets
- [ ] Implement sector-plane matching algorithm (X/Y/Z plane detection)
- [ ] Update find-nearest-hyperjump command
- [ ] Test with known Hyperjump coordinates

**Status:** PARTIAL. Has sector ranking but needs sector-plane entry logic.

### 5. ❌ HYPERJUMP ACTION IMPLEMENTATION
- [ ] Implement hyperjump action (kind=3333, A=hyperjump) per DECK-0001
- [ ] Required tags: A, e genesis, e previous, c, C, from_height, from_hj, proof, B, X, Y, Z, S
- [ ] Implement Cantor tree construction with temporal seed (spec §8)
- [ ] Implement verification per spec §8
- [ ] Add hyperjump command to CLI

**Status:** NOT STARTED. Current hyperjump commands may use old spec.

### 6. ❌ TESTING & VALIDATION
- [ ] Create test vectors for all actions
- [ ] Test sector extraction
- [ ] Test Cantor tree construction
- [ ] Test end-to-end Hyperspace traversal

**Status:** NOT STARTED

### 7. ❌ DOCUMENTATION
- [ ] Update CLI README with new commands
- [ ] Document ambiguities/issues encountered
- [ ] Create IMPLEMENTATION_NOTES.md with problems for Arkinox to review

**Status:** NOT STARTED

---

## Current State Analysis

### What Exists

1. **Sidestep Merkle Engine** (`src/cyberspace_core/movement.py`)
   - `merkle_leaf()`, `merkle_parent()` functions
   - `compute_axis_merkle_root_streaming()` 
   - `SidestepProof` dataclass
   - `compute_sidestep_proof()` function

2. **Hyperjump Commands** (`src/cyberspace_cli/cli.py`)
   - `hyperjump show` - display hyperjump info
   - `hyperjump to` - create hyperjump action (may use old spec)
   - `hyperjump next` / `hyperjump prev` - traverse hyperjumps
   - `hyperjump sync` - sync hyperjump anchors from Nostr
   - `hyperjump nearest` - find nearest hyperjump with sector ranking

3. **Sector Logic**
   - `sector()` command shows current sector
   - Sector extraction via `coord >> 30` (NOT de-interleaved per DECK-0001!)
   - Hyperjump ranking by sector distance

### What's Missing

1. **De-interleaving for sector extraction**
   - Current: `sector = coord >> 30` (wrong for interleaved coords)
   - Needed: de-interleave XYZXYZXYZ...P pattern, then extract 55-bit sector

2. **Enter-hyperspace action**
   - No command exists
   - M tag (Merkle root), B tag (block height), axis tag need implementation

3. **Updated hyperjump action**
   - Current implementation may use old spec (pre-PR #14)
   - Need: from_height, from_hj, proof tags for ALL hyperjumps
   - Need: Cantor tree with temporal seed (not current hop proof)

4. **Sector-plane matching**
   - Need to find hyperjups where sector(X) or sector(Y) or sector(Z) matches
   - Current search ranks by sector distance, doesn't match planes

---

## Technical Notes

### Sector Extraction (DECK-0001 vs Current)

**Current CLI:**
```python
sector_bits = 30
sx = x >> sector_bits  # WRONG for interleaved coords
```

**DECK-0001 Spec (§I.2):**
```python
def extract_axis(coord256: int, axis: str) -> int:
    # De-interleave to get 85-bit axis value
    # XYZXYZXYZ...P pattern
    if axis == 'X':
        shift = 3  # X bits at positions 3, 6, 9, ...
    elif axis == 'Y':
        shift = 2  # Y bits at positions 2, 5, 8, ...
    elif axis == 'Z':
        shift = 1  # Z bits at positions 1, 4, 7, ...
    
    result = 0
    for i in range(85):
        bit_pos = shift + (3 * i)
        if coord256 & (1 << bit_pos):
            result |= (1 << i)
    return result

def sector(coord256: int, axis: str) -> int:
    axis_value = extract_axis(coord256, axis)
    return axis_value >> 30  # High 55 bits of 85-bit axis
```

**This is a BREAKING CHANGE** — all sector calculations must use de-interleaved extraction.

### Cantor Tree for Hyperjump (spec §8)

**Leaves:** `[temporal_seed, B_from, B_from+1, ..., B_to]`
- `temporal_seed = int.from_bytes(previous_event_id, "big") % 2^256`
- Pair adjacent leaves using Cantor pairing function
- Unpaired leaf carries forward

**Current hop proof** uses different construction (terrain K + spatial Cantor). Hyperjump action needs entirely new proof mechanism.

---

## Next Immediate Actions

1. **Create branch:** `git checkout -b deck-0001-implementation`
2. **Implement de-interleaving** in `src/cyberspace_core/sector.py` (new file or update existing)
3. **Update all sector extraction** to use de-interleaved method
4. **Add enter-hyperspace command** to CLI
5. **Update hyperjump action** to match DECK-0001 spec
6. **Add benchmark-sidestep** command
7. **Test everything**

---

## Open Questions for Arkinox

1. Should sector extraction be in `src/cyberspace_core/sector.py` or `src/cyberspace_core/coords.py`?

2. How to handle backward compatibility with existing hyperjump events that may use old spec?

3. Should the Cantor tree implementation be in `src/cyberspace_core/cantor.py` (alongside `cantor_pair`)?

4. Cloud compute requirements for high-LCA sidesteps:
   - What's the budget ceiling for cloud PoW?
   - Should we implement automatic cloud job submission when LCA > threshold?

---

## Blockers

None currently. Can begin implementation immediately.

---

## Cron Job Status

**Job ID:** `8f2165d9e916`
**Schedule:** Every 30 minutes
**Status:** Active
**Next run:** 2026-04-16 23:00
**Skills loaded:** cyberspace-protocol, test-driven-development, systematic-debugging
**Delivery:** local (output saved to ~/.hermes/cron/output/)

Cron will continue working on this checklist every 30 minutes until all items complete.
