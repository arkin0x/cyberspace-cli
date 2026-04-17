# DECK-0001 Implementation Notes

**Implementation branch:** `deck-0001-implementation`
**Spec reference:** `~/repos/cyberspace/decks/DECK-0001-hyperspace.md` (PR #14, commit d4cd829)
**Started:** 2026-04-16 22:30
**Author:** XOR

---

## Session 1: 2026-04-16 (Evening)

### Work Completed

#### 1. ✅ Sector extraction with de-interleaving (DECK-0001 §I.2)

**File:** `src/cyberspace_core/sector.py`

**Functions added:**
- `extract_axis_from_coord256(coord256, axis)` - De-interleaves 256-bit coord to get 85-bit axis value
- `sector_from_coord256(coord256, axis)` - Extracts 55-bit sector from axis value
- `extract_hyperjump_sectors(merkle_root_hex)` - Gets (sx, sy, sz) from Merkle root
- `coord_matches_hyperjump_plane(coord256, merkle_root_hex, axis)` - Sector-plane entry check

**Key insight:** Existing sector extraction was WRONG for interleaved coordinates:
```python
# OLD (WRONG):
sector = coord >> 30  # Treats coord as raw integer

# NEW (DECK-0001 compliant):
axis_value = extract_axis_from_coord256(coord, 'X')  # De-interleave XYZ pattern
sector = axis_value >> 30  # High 55 bits of 85-bit axis
```

**Impact:** This is a BREAKING CHANGE. All hyperjump sector calculations must be updated to use de-interleaved extraction. Current hyperjump search/ranking will give wrong results.

---

### Work In Progress

#### 2. ⚠️ Enter-hyperspace action implementation

**Not yet started.** Will implement:
- Command: `cyber hyperjump enter` or `cyber enter-hyperspace`
- Event kind: 3333, A=enter-hyperspace
- Required tags: A, e genesis, e previous, c, C, M, B, axis, proof, X, Y, Z, S
- Optional: e hyperjump-anchor

**Questions:**
- Should this be under `hyperjump enter-hyperspace` subcommand or top-level `enter-hyperspace`?
- Should M tag validation verify the Merkle root corresponds to a valid Bitcoin block?

---

#### 3. ⚠️ Hyperjump action update (DECK-0001 spec)

**Current state:** CLI has `hyperjump to/next/prev` commands using pre-DECK-0001 spec

**Needs update:**
- Add `from_height` and `from_hj` as REQUIRED tags
- Add `proof` tag (Cantor tree with temporal seed) to ALL hyperjumps
- Update verification to use spec §8 Cantor tree construction

**Breaking change:** Existing hyperjump events without these tags will be invalid under new spec.

---

### Ambiguities & Spec Issues Found

#### 1. Sector extraction breaking change
**Issue:** Current CLI uses `coord >> 30` for sector extraction (wrong for interleaved coords)
**Impact:** All hyperjump sector rankings are incorrect
**Resolution:** Must update all sector extraction calls to use `sector_from_coord256()`
**Arkinox decision needed:** Should we add a migration/compatibility flag for old events?

#### 2. Cantor tree temporal seed derivation
**Spec says:** `temporal_seed = int.from_bytes(previous_event_id, "big") % 2^256`
**Question:** Is `previous_event_id` the `prev` tag event ID or the `e` previous-tagged event ID?
**My assumption:** They're the same (the previous movement event in the chain)
**Clarification needed:** Confirm this is correct interpretation

#### 3. Verification step ordering
**Spec §8 has 7 verification steps** but doesn't specify:
- Should Bitcoin block validation happen before or after proof verification?
- If proof verification fails, should we still validate the hyperjump coordinates?

**Decision:** I'll implement in order: 1) extract data, 2) validate Bitcoin blocks, 3) verify proof

#### 4. Error handling for orphaned blocks
**Scenario:** Hyperjump references block that gets orphaned
**Spec:** Says "valid Bitcoin block" but doesn't specify chain depth
**Decision:** Will validate against deepest chain at verification time, no depth requirement
**Arkinox:** Should we add a minimum confirmation depth (e.g., 6 blocks)?

---

### Cloud Compute Research (Preliminary)

**Problem:** High-LCA sidesteps (h>25) exceed local compute capacity

**Initial findings:**
- Modal.com: GPU cloud, serverless, pay-per-use (~$0.000029/GB-s for A100)
- Lambda Labs: Dedicated GPU instances ($0.50-2/hr for A100/H100)
- RunPod: Similar to Lambda, community cloud option

**Estimated costs for h=35 sidestep:**
- 2³⁵ operations ≈ 34 billion Cantor pairings
- On A100: ~10⁹ pairings/sec → ~34 seconds
- Cost: ~$0.001-0.01 per sidestep (depending on provider)

**Next steps:**
- Benchmark local machine's Cantor pairing throughput
- Determine LCA threshold where cloud becomes cheaper than time cost
- Implement cloud job submission interface (Modal likely easiest)

---

### Files Changed (Session 1)

```
src/cyberspace_core/sector.py
  ✅ Added: extract_axis_from_coord256()
  ✅ Added: sector_from_coord256()
  ✅ Added: extract_hyperjump_sectors()
  ✅ Added: coord_matches_hyperjump_plane()

IMPLEMENTATION_STATUS.md (new)
  ✅ Created: Comprehensive checklist
  ✅ Documented: Current state analysis

IMPLEMENTATION_NOTES.md (new)
  ✅ Created: This file
```

---

### Next Steps (Session 2)

1. **Write tests** for sector extraction functions
2. **Update existing code** to use de-interleaved sector extraction
3. **Implement enter-hyperspace action** command
4. **Research cloud providers** more deeply (Modal, Lambda, RunPod)
5. **Benchmark local compute** for Cantor pairing performance

---

### TODO: Questions for Arkinox

1. **Sector breaking change:** Add migration flag for old hyperjump events, or hard break?

2. **Temporal seed source:** Confirm `previous_event_id` = `prev` tag event ID (not some other source)

3. **Orphaned block handling:** Require minimum confirmation depth? (e.g., 6 blocks)

4. **Cloud compute:** What's acceptable cost ceiling for automated cloud fallback?

5. **Command naming:** Prefer `cyber enter-hyperspace` or `cyber hyperjump enter`?

---

## Cron Job Status

**Active.** Runs every 30 minutes.
**Job ID:** `8f2165d9e916`
**Next run:** 2026-04-16 23:00
**Delivery:** local files (`~/.hermes/cron/output/`)

Cron will:
- Check `IMPLEMENTATION_STATUS.md` for progress
- Continue down the checklist
- Update this file with new findings/issues
