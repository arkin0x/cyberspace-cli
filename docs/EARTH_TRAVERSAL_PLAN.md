# Earth Traversal Plan via Hyperspace Network

**Date:** 2026-04-17  
**Goal:** Navigate from current spawn location to Earth coordinates using DECK-0001 Hyperspace mechanics

---

## Objective

**Target:** Earth coordinates (real-world GPS → Cyberspace coord)  
**Method:** Use Hyperspace network for efficient long-distance traversal  
**Spec:** DECK-0001-hyperspace.md (PR #14)

---

## Assumptions & Constraints

### Known
1. ✅ DECK-0001 fully implemented in cyberspace-cli (PR #11)
2. ✅ Sector-plane entry reduces cost from h≈84 to h≈33
3. ✅ Hyperjumps indexed on Nostr (kind 321 events)
4. ✅ ~940,000+ Bitcoin blocks = ~940,000 Hyperjumps (2.8M entry planes)

### Unknown (Research Needed)
1. ❓ Earth's current GPS coordinates
2. ❓ Earth's Cyberspace coord256 (needs GPS → coord conversion)
3. ❓ Current spawn/position in Cyberspace
4. ❓ Hyperjump index completeness (how many blocks indexed?)
5. ❓ Nearest enterable Hyperjump to current position
6. ❓ Nearest Earth-proximate Hyperjump

---

## Plan Phases

### Phase 1: Target Acquisition (Day 1)

**Goal:** Determine Earth's Cyberspace coordinates

#### Steps:

1. **Get GPS coordinates for "Earth" (Nick's location)**
   - Use real-world GPS (phone, online tool)
   - Or use predefined "Earth" coord if already established
   
2. **Convert GPS to Cyberspace coord256**
   - Need: GPS → coord256 conversion algorithm
   - Question: Is there an established mapping?
   - If not: Propose a standard (e.g., GPS → Hilbert curve → coord256)

3. **Store as "Earth target"**
   ```bash
   cyber target set earth <coord_hex>
   ```

**Deliverables:**
- Earth's GPS coordinates
- Earth's Cyberspace coord256
- Stored target config

---

### Phase 2: Hyperjump Indexing (Day 1-2)

**Goal:** Build complete local index of available Hyperjumps

#### Steps:

1. **Sync all Hyperjump anchors from Nostr**
   ```bash
   cyber hyperjump sync --all
   ```
   
2. **Verify index completeness**
   ```bash
   cyber hyperjump count  # Should approach 940,000+
   cyber hyperjump latest  # Most recent block height
   ```

3. **Index metadata**
   - Block height
   - Merkle root (coordinate)
   - Sector values (X, Y, Z)
   - Plane (0 or 1)
   
4. **Create searchable database**
   - SQLite with sector indexes
   - Fast sector-plane lookups

**Expected Duration:** 2-4 hours (depends on relay performance)

**Deliverables:**
- Complete local Hyperjump index
- Searchable database with sector indexing

---

### Phase 3: Route Planning (Day 2)

**Goal:** Find optimal path via Hyperspace network

#### Steps:

1. **Find nearest enterable Hyperjump (current position)**
   ```bash
   cyber hyperjump enterable --radius 100
   ```
   - Searches for Hyperjumps where any sector (X, Y, or Z) matches current position
   - Returns ranked list by accessibility

2. **Find Earth-proximate Hyperjump**
   ```bash
   cyber hyperjump nearest --target <earth_coord> --radius 100
   ```
   - Finds Hyperjump closest to Earth coord
   - May need to search multiple sectors

3. **Compute hyperspace path**
   - Path: Current → Enterable_HJ → [Hyperspace traversal] → Earth_HJ → Earth
   - Need: Hyperjump-to-Hyperjump pathfinding algorithm
   - Consider: Block height proximity (cheaper to traverse adjacent blocks)

4. **Evaluate alternatives**
   - Multiple entry points (try top 5 nearest)
   - Multiple exit points (try top 5 nearest to Earth)
   - Compute total cost for each route
   - Select optimal (lowest PoW cost)

**Algorithm:**
```python
def find_optimal_route(current_coord, earth_coord):
    # Find candidate entry hyperjumps
    entry_candidates = find_enterable_hyperjumps(current_coord, radius=100)
    
    # Find candidate exit hyperjumps (near Earth)
    exit_candidates = find_nearest_hyperjumps(earth_coord, radius=100)
    
    # Evaluate all entry/exit pairs
    best_route = None
    best_cost = infinity
    
    for entry_hj in entry_candidates[:10]:
        for exit_hj in exit_candidates[:10]:
            # Cost = entry proof + hyperspace traversal + exit hop
            entry_cost = estimate_entry_cost(current_coord, entry_hj)
            traversal_cost = estimate_traversal_cost(entry_hj, exit_hj)
            exit_cost = estimate_exit_cost(exit_hj, earth_coord)
            
            total_cost = entry_cost + traversal_cost + exit_cost
            
            if total_cost < best_cost:
                best_cost = total_cost
                best_route = (entry_hj, exit_hj, total_cost)
    
    return best_route
```

**Deliverables:**
- Optimal entry Hyperjump (with sector plane)
- Optimal exit Hyperjump
- Estimated total cost (PoW height)
- Step-by-step route plan

---

### Phase 4: Pre-Traverse Setup (Day 3)

**Goal:** Prepare for traversal execution

#### Steps:

1. **Benchmark local compute capacity**
   ```bash
   cyber benchmark-hop
   cyber benchmark-sidestep
   ```
   - Determine max feasible LCA for local compute
   - Identify which steps need cloud fallback

2. **Set up cloud compute (if needed)**
   - Configure Modal integration
   - Test with h=28-30 proof
   - Set budget limits

3. **Verify spawn chain validity**
   ```bash
   cyber chain verify
   ```
   - Ensure current chain is valid
   - Check for any equivocation issues

4. **Prepare state**
   ```bash
   cyber state save pre-traverse-backup
   ```
   - Snapshot current position and chain
   - enables rollback if needed

**Deliverables:**
- Benchmark results (max local LCA)
- Cloud compute configured
- State backup created
- Ready-to-execute traversal plan

---

### Phase 5: Execution - Sector Plane Entry (Day 3)

**Goal:** Enter Hyperspace via chosen entry Hyperjump

#### Steps:

1. **Move to sector plane entry point**
   ```bash
   cyber move --toward <entry_plane_coord> --max-lca 22
   ```
   - Navigate to coordinate on sector plane
   - May involve multiple hops
   - Use benchmark results to optimize

2. **Verify sector match**
   ```bash
   cyber hyperjump show <merkle_root>
   cyber sector  # Compare with Hyperjump sector
   ```

3. **Execute enter-hyperspace action**
   ```bash
   cyber enter-hyperspace \
     --merkle <entry_hj_merkle> \
     --block-height <entry_hj_block> \
     --axis <X|Y|Z>
   ```
   - Publishes kind=3333, A=enter-hyperspace event
   - Includes Cantor proof for sector-plane entry
   - Validates sector match per DECK-0001 §I.3

4. **Confirm entry**
   ```bash
   cyber state  # Should show "on Hyperspace network"
   cyber chain latest  # Verify enter-hyperspace event published
   ```

**Expected Duration:** 15-30 minutes (depends on entry LCA height)

**Deliverables:**
- Successfully entered Hyperspace network
- Position at entry Hyperjump (block height B_entry)

---

### Phase 6: Execution - Hyperspace Traversal (Day 3-4)

**Goal:** Traverse from entry Hyperjump to exit Hyperjump via Hyperspace

#### Steps:

1. **Compute traversal path**
   - Path: B_entry → B_entry+1 → ... → B_exit
   - Block height difference: ΔB = |B_exit - B_entry|
   - Proof: Cantor tree over [temporal_seed, B_entry, ..., B_exit]

2. **Execute hyperjump action**
   ```bash
   cyber hyperjump to \
     --merkle <exit_hj_merkle> \
     --block-height <exit_hj_block>
   ```
   - Publishes kind=3333, A=hyperjump event
   - Includes Cantor tree proof per DECK-0001 §8
   - Tags: from_height, from_hj, proof, B (to_height)

3. **Verify arrival**
   ```bash
   cyber state  # Position = exit_hj Merkle root coord
   cyber chain latest  # Verify hyperjump event
   ```

**Expected Duration:**
- ΔB < 1000 blocks: ~1-10ms (negligible)
- ΔB = 10,000 blocks: ~10-100ms
- ΔB = 100,000 blocks: ~0.1-1s
- ΔB = 1,000,000 blocks: ~1-10s

**Deliverables:**
- Successfully traversed Hyperspace
- Position at exit Hyperjump (Merkle root coordinate)

---

### Phase 7: Execution - Exit to Cyberspace (Day 4)

**Goal:** Exit Hyperspace and reach final Earth coordinates

#### Steps:

1. **Determine exit strategy**
   - Exit at exit_hj Merkle root coordinate (exact)
   - Then hop/sidestep to Earth coord

2. **Execute exit hop/sidestep**
   ```bash
   cyber move --toward <earth_coord> --max-lca 22 --sidestep-if-needed
   ```
   - If LCA ≤22: Standard hop
   - If LCA >22: Sidestep with Merkle proof
   - If LCA >28: Cloud compute fallback

3. **Verify arrival at Earth**
   ```bash
   cyber state  # Position = Earth coord
   cyber distance --to-earth  # Should be ~0
   ```

4. **Publish arrival proof**
   ```bash
   cyber chain export --to-earth  # Export complete journey chain
   ```

**Expected Duration:** Depends on final hop distance (LCA height)

**Deliverables:**
- ✅ **ARRIVED AT EARTH**
- Complete traversal chain documented
- Journey proof exported

---

## Risk Analysis & Mitigation

### Risk 1: Incomplete Hyperjump Index
**Probability:** Medium  
**Impact:** Cannot find optimal entry/exit points  
**Mitigation:**
- Sync from multiple relays
- Allow partial index with larger search radius
- Fallback: Search by block height proximity

### Risk 2: Entry/Exit LCA Too High
**Probability:** Medium  
**Impact:** Cannot afford PoW cost  
**Mitigation:**
- Use cloud compute (Modal)
- Search wider radius for better entry/exit points
- Accept suboptimal route

### Risk 3: Hyperspace Traversal Cost Underestimated
**Probability:** Low  
**Impact:** Traversal takes longer than expected  
**Mitigation:**
- Cantor tree is O(n) pairings, well-understood
- Benchmark beforehand
- Budget extra time

### Risk 4: Chain Equivocation
**Probability:** Low  
**Impact:** Invalid chain, must restart  
**Mitigation:**
- Careful chain management
- State backups at each phase
- Verify before each action

### Risk 5: Hyperjump Orphaned
**Probability:** Very Low (Bitcoin finality)  
**Impact:** Referenced block invalid  
**Mitigation:**
- Use confirmed blocks (6+ confirmations)
- Validate against deepest chain

---

## Success Criteria

✅ **Phase 1:** Earth coord256 determined and stored  
✅ **Phase 2:** Complete Hyperjump index (940k+ events)  
✅ **Phase 3:** Optimal route computed with cost estimate  
✅ **Phase 4:** Benchmarks complete, cloud configured  
✅ **Phase 5:** Successfully entered Hyperspace  
✅ **Phase 6:** Successfully traversed to exit Hyperjump  
✅ **Phase 7:** Arrived at Earth coordinates  

**Overall Success:** Chain of events from spawn → Earth, all valid, total cost within budget

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| 1. Target Acquisition | 1-2 hours | GPS coordinates |
| 2. Hyperjump Indexing | 2-4 hours | Relay performance |
| 3. Route Planning | 2-4 hours | Phases 1-2 complete |
| 4. Pre-Traverse Setup | 1-2 hours | Benchmarks |
| 5. Sector Plane Entry | 30min-2 hours | Depends on entry LCA |
| 6. Hyperspace Traversal | <1 minute | Depends on ΔB |
| 7. Exit to Earth | 30min-4 hours | Depends on exit LCA |

**Total Estimate:** 8-16 hours (1-2 days)  
**Critical Path:** Phases 2-3 (indexing + route planning)

---

## Tools & Commands Reference

```bash
# Target management
cyber target set earth <coord>
cyber target show earth

# Hyperjump indexing
cyber hyperjump sync --all
cyber hyperjump count
cyber hyperjump latest

# Route planning
cyber hyperjump enterable --radius 100
cyber hyperjump nearest --target <coord> --radius 100

# Benchmarks
cyber benchmark-hop
cyber benchmark-sidestep

# Movement
cyber move --toward <coord> [--max-lca 22] [--sidestep-if-needed]

# Enter Hyperspace
cyber enter-hyperspace --merkle <M> --block-height <B> --axis <X|Y|Z>

# Traverse Hyperspace
cyber hyperjump to --merkle <M> --block-height <B>
cyber hyperjump next  # Move to next block

# State management
cyber state
cyber state save <name>
cyber chain verify
cyber chain export --to-earth
```

---

## Open Questions for Arkinox

1. **Earth GPS coordinates:** What are the exact GPS coords for "Earth" (your location)?

2. **GPS → Cyberspace mapping:** Is there an established algorithm for GPS → coord256 conversion? If not, shall I propose one?

3. **Current position:** What's your current spawn/position in Cyberspace? (Need starting coord)

4. **Budget:** What's the max acceptable PoW cost for this journey?
   - Suggestion: $10-50 cloud compute budget if needed

5. **Timeline:** Any urgency, or can this be methodical (1-2 day timeline ok)?

6. **Public vs Private:** Should this journey be public (announced on Nostr) or private?

---

## Next Actions

**Once you provide:**
1. Earth GPS coordinates
2. Current Cyberspace position
3. Budget confirmation

**I will:**
1. Convert GPS → coord256 (or propose mapping)
2. Start Phase 2 (Hyperjump indexing)
3. Begin executing the traversal plan

**Estimated start:** Immediately upon receiving answers

---

## Summary

**Plan:** 7 phases from target acquisition → Earth arrival  
**Method:** Hyperspace network via DECK-0001 mechanics  
**Cost:** Mostly local compute, cloud fallback for h>28  
**Time:** 1-2 days total  
**Risk:** Low-Medium (well-understood mechanics, fallbacks available)

**Ready to execute as soon as you provide Earth coords and current position!** 🚀
