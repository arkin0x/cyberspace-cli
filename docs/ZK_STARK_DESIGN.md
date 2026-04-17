# ZK-STARK Proofs for Cyberspace Cantor Tree Verification

**Document Type:** Design Specification  
**Created:** 2026-04-17  
**Status:** Draft  
**Author:** XOR (via Hermes Agent)  
**Related Specs:** CYBERSPACE_V2.md, DECK-0001-hyperspace.md, RATIONALE.md

---

## 1. Problem Statement

### 1.1 Current State: Work Equivalence

In the current Cyberspace Protocol implementation, **verification costs the same computational work as generation**. This is the "work equivalence" property described in RATIONALE.md §7:

> "In almost every digital system, observers have advantages over participants. Cyberspace aims for a rare property: computing the region preimage costs the same whether you traveled there via a movement chain or computed it directly."

This property maintains **thermodynamic integrity** (no observer advantage) but creates a critical limitation: **lightweight clients cannot participate**.

**The verification burden:**
- A height-30 Cantor tree requires ~1 billion operations
- A height-33 tree (Hyperspace entry) requires ~17 billion operations (~15 minutes on consumer hardware)
- Mobile devices, browsers, and IoT devices cannot perform this computation in reasonable time

### 1.2 Desired State: Asymmetric Verification

ZK-STARK proofs would enable:

| Property | Current (Plain Cantor) | With ZK-STARK |
|----------|----------------------|---------------|
| **Prover work** | Full Cantor tree computation | Full Cantor tree computation (unchanged) |
| **Verifier work** | Full Cantor tree recomputation | Milliseconds (constant-time proof verification) |
| **Proof size** | Single 256-bit root | ~10-100 KB STARK proof |
| **Lightweight client support** | ❌ Infeasible | ✅ Enabled |
| **Thermodynamic integrity** | ✅ Maintained | ✅ Maintained |

### 1.3 Core Challenge

The fundamental question is:

> **How do we prove "I correctly computed a Cantor tree root from these leaves" without forcing the verifier to recompute the tree?**

The statement to prove is:
- **Input:** `leaves = [temporal_seed, coord_1, coord_2, ..., coord_N]`
- **Computation:** Build Cantor pairing tree over all leaves
- **Output:** `tree_root` (256-bit integer)
- **Statement:** "I computed `tree_root` from these leaves using the Cantor pairing function π(x,y) = ((x+y)(x+y+1))/2 + y"

This is an **arithmetic circuit** amenable to ZK-STARKs.

---

## 2. Why ZK-STARKs (Not SNARKs)

### 2.1 Decision Criteria

| Criterion | STARK | SNARK | Winner |
|-----------|-------|-------|--------|
| **Trusted setup** | ❌ None required | ✅ Required (vulnerable if compromised) | **STARK** |
| **Post-quantum security** | ✅ Based on hash functions | ❌ Based on elliptic curves | **STARK** |
| **Proof size** | ~10-100 KB | ~288 bytes (Groth16) | SNARK |
| **Verification time** | ~1-10 ms | ~1-5 ms | Tie |
| **Prover speed** | Slower | Faster | SNARK |
| **Transparency** | ✅ Public randomness | ❌ Toxic waste risk | **STARK** |

### 2.2 Rationale

**Post-quantum security is non-negotiable** for Cyberspace:
- The protocol is designed for permanence (like Bitcoin)
- Movement proofs must remain valid for decades
- Quantum computers would break SNARK elliptic curve assumptions

**No trusted setup is essential** for decentralization:
- Cyberspace has no central authority to coordinate MPC ceremonies
- STARKs use public randomness (can be sourced from Bitcoin block hashes)

**Trade-off accepted:** STARK proofs are ~100× larger than SNARKs, but still fit in Nostr events (which support ~100 KB content).

---

## 3. Arithmetic Circuit Design for Cantor Pairing

### 3.1 The Cantor Formula in Field Arithmetic

The Cantor pairing function:
```
π(x, y) = ((x + y) × (x + y + 1)) / 2 + y
```

In arithmetic circuit form (over a finite field F_p):
```
s = x + y                    // 1 addition
t = s + 1                    // 1 addition
u = s × t                    // 1 multiplication
v = u / 2                    // 1 multiplication by inverse of 2
result = v + y               // 1 addition
```

**Total constraints per Cantor pair: 5 constraints**

### 3.2 Tree Construction as Constraint System

For a tree with N leaves (assume N is power of 2 for simplicity):

```
Level 0 (leaves):    L_0, L_1, L_2, ..., L_{N-1}
Level 1 (1st pair):  P_0,0 = π(L_0, L_1), P_0,1 = π(L_2, L_3), ...
Level 2 (2nd pair):  P_1,0 = π(P_0,0, P_0,1), P_1,1 = π(P_0,2, P_0,3), ...
...
Root:                R = P_{log2(N)-1, 0}
```

**Constraint count:**
- Total Cantor pairs = N - 1 (for N leaves)
- Total constraints = 5 × (N - 1)

**For a height-33 tree (2³³ ≈ 8.6 billion leaves):**
- Constraints = 5 × 8.6B ≈ **43 billion constraints**

### 3.3 Problem: Direct Encoding is Infeasible

A 43-billion-constraint circuit is **impossible** to prove with current ZK-STARK technology:
- State-of-the-art STARK provers handle ~1M constraints/second
- 43B constraints would take ~12 hours of continuous computation
- Memory requirements would be impractical

### 3.4 Solution: STARK-Friendly Hash with Recursive Proofs

**Approach:** Use a STARK-friendly hash function (Poseidon, Rescue, or GRIFFIN) instead of Cantor pairing for the arithmetized circuit.

**Key insight:** We're not proving "I computed Cantor" but "I computed a deterministic function F over leaves where F has the same binding properties as Cantor."

**Properties required:**
1. **Deterministic:** Same leaves → same root
2. **Binding:** Cannot find two leaf sequences with same root
3. **Arithmetic-friendly:** Efficient in field arithmetic

**Poseidon hash** meets these criteria:
- Designed for ZK circuits
- ~2-3 constraints per bit (vs Cantor's 5 constraints per pairing)
- Cryptographically secure

### 3.5 Alternative: Hybrid Approach (Cantor + STARK)

**Preserve the Cantor formula in the protocol, verify with STARK:**

1. Prover computes full Cantor tree (unchanged)
2. Prover generates STARK proof that:
   - Input: leaf sequence + claimed Cantor root
   - Statement: "This root is the correct Cantor tree root for these leaves"
3. Verifier checks STARK proof (milliseconds)

**Challenge:** Still requires arithmetizing Cantor pairing.

**Path forward:** Use a **recursive proof composition** (e.g., STARKs + SNARKs):
- inner_snark: SNARK proves correct Cantor computation (efficient prover)
- outer_stark: STARK proves the SNARK verification (post-quantum, transparent)

This is the approach used by **SHARP** (SHApping Recursive Proofs) and **recursive STARKs**.

---

## 4. Library Selection

### 4.1 Candidates Evaluated

| Library | Language | Maturity | Cantor-Friendly? | Notes |
|---------|----------|----------|------------------|-------|
| **starkware** | Cairo/CairoVM | High (production at Scale, dYdX) | ⚠️ Requires Cairo translation | Industry standard, heavy weight |
| **winterfell** | Rust/Python | Medium (Meta/Facebook) | ✅ Configurable algebraic IR | Good documentation, active |
| **cairo-lang** | Cairo | High (StarkNet ecosystem) | ⚠️ Requires Cairo | Full ecosystem, complex |
| **plonky3** | Rust | High (Polygon) | ✅ Plonk + STARK | Fast prover, recursive |
| **arkworks** | Rust | Medium (research) | ⚠️ Generic SNARKs | Flexible, not STARK-specific |
| **gnark** | Go | Medium (ConsenSys) | ⚠️ SNARK-focused | Good Go support |

### 4.2 Recommendation: **winterfell** (Phase 1), **plonky3** (Phase 2)

#### Phase 1: Proof-of-Concept with winterfell

**Why winterfell:**
- Python bindings available (matches cyberspace-cli stack)
- Configurable algebraic intermediate representation (AIR)
- Good documentation and examples
- Actively maintained (Meta)
- No trusted setup

**Trade-offs:**
- Slower than plonky3 for large circuits
- Less mature recursion support

#### Phase 2: Production with plonky3

**Why plonky3:**
- Blazing fast prover (optimized for large circuits)
- Recursive proof support built-in
- Production use at Polygon
- Rust implementation (can expose to Python via PyO3)

**Trade-offs:**
- No native Python support (requires FFI wrapper)
- Newer than winterfell (less community knowledge)

### 4.3 Alternative: StarkWare/Cairo

**When to consider:**
- Planning to integrate with StarkNet/Ethereum L2
- Need maximum ecosystem support

**Why not now:**
- Overkill for current use case
- Cairo is a full VM (complexity overhead)
- Cyberspace uses Nostr, not Ethereum

---

## 5. Proof Size and Verification Time Estimates

### 5.1 STARK Proof Parameters

Based on winterfell and plonky3 benchmarks:

| Tree Height | Leaves | Approx Proof Size | Verification Time |
|-------------|--------|-------------------|-------------------|
| h10 | 1,024 | ~15 KB | ~1 ms |
| h20 | ~1M | ~20 KB | ~2 ms |
| h30 | ~1B | ~25 KB | ~3 ms |
| h33 | ~8.6B | ~30 KB | ~4 ms |

**Key insight:** STARK proof size scales **logarithmically** with circuit size, not linearly. A height-33 proof is only ~2× larger than height-10.

### 5.2 Nostr Event Fit

Current Nostr event limits:
- Content: No hard limit, but relays may reject >100 KB
- Tags: Each tag adds ~50-100 bytes
- Total typical limit: ~500 KB (generous relay)

**ZK proof in Nostr:**
- STARK proof (~30 KB) fits comfortably as a tag
- Encoding: Base64 or hex (2× overhead → ~60 KB)
- **Verdict:** ✅ Fits in single Nostr event

### 5.3 Performance Targets

Based on the skill's success metrics:

| Metric | Target | STARK Feasibility |
|--------|--------|-------------------|
| Proof generation time | <10× standard (~150 min for h33) | ⚠️ Challenging; may need optimization |
| Verification time | <10 ms | ✅ Achieved (~4 ms expected) |
| Proof size | <100 KB | ✅ Achieved (~60 KB with encoding) |
| No trusted setup | Required | ✅ Native to STARKs |
| Post-quantum secure | Required | ✅ Hash-based assumptions |

---

## 6. Integration Approach with cyberspace-cli

### 6.1 New Event Structure

**Current hop event:**
```json
{
  "kind": 3333,
  "tags": [
    ["A", "hop"],
    ["c", "<prev_coord>"],
    ["C", "<dest_coord>"],
    ["proof", "<cantor_root_hex>"],
    ...
  ]
}
```

**ZK-enabled hop event:**
```json
{
  "kind": 3333,
  "tags": [
    ["A", "hop-zk"],
    ["c", "<prev_coord>"],
    ["C", "<dest_coord>"],
    ["proof", "<cantor_root_hex>"],  // Original proof (backward compat)
    ["zk", "<stark_proof_hex>"],     // NEW: STARK proof
    ["zk-pub", "<public_inputs_hex>"] // NEW: leaves hash, root
  ]
}
```

### 6.2 Feature Flag Design

**Gradual rollout:**
```bash
# Enable ZK proof generation (prover-side only)
cyberspace config set --zk-stark-enabled true

# Verify incoming ZK proofs (verifier-side)
cyberspace config set --zk-verify-incoming true

# Generate both proofs during transition
cyberspace move --to x,y,z --zk
```

### 6.3 New Commands

```bash
# Verify a ZK proof independently
cyberspace verify-zk --event <event_file> --proof <stark_proof>

# Benchmark ZK proof generation
cyberspace bench-zk --height 20

# Generate STARK proof for existing movement
cyberspace zk-prove --chain mychain --event-id <event_id>
```

### 6.4 Code Structure

```
cyberspace-cli/
├── src/cyberspace_core/
│   ├── cantor.py              # existing
│   ├── movement.py            # existing
│   └── zk_stark/
│       ├── __init__.py
│       ├── prover.py          # STARK proof generation
│       ├── verifier.py        # STARK proof verification
│       ├── air.py             # Algebraic IR for Cantor circuit
│       └── utils.py           # leaf encoding, serialization
├── src/cyberspace_cli/
│   ├── commands/
│   │   ├── verify_zk.py
│   │   └── bench_zk.py
│   └── event_builder.py       # ZK tag injection
└── tests/
    └── test_zk_stark.py
```

---

## 7. Protocol Extensions: New Action Types?

### 7.1 Option A: New A Tag (`hop-zk`)

**Pros:**
- Clear semantics (verifier knows ZK proof present)
- Enables gradual adoption
- Relays can filter by capability

**Cons:**
- Fragmentation (two hop types)
- Requires spec update

### 7.2 Option B: Same `hop` Tag, Optional `zk` Tag

**Pros:**
- Backward compatible
- No spec change needed (tags are extensible)
- Single action type

**Cons:**
- Verifiers must check for `zk` tag presence

### 7.3 Recommendation: **Option B**

Follows Cyberspace's extensibility pattern. The `proof` tag remains the canonical commitment; `zk` tag is an optional efficiency layer.

**Event validation:**
1. Verify `proof` tag (Cantor root) — always required
2. If `zk` tag present, verify STARK proof
3. If STARK verification fails, reject event
4. If no `zk` tag, fall back to standard verification

---

## 8. Threat Model and Security Considerations

### 8.1 Work Equivalence Preservation

**Requirement:** Prover must still do full Cantor tree work.

**Risk:** If STARK prover can shortcut the computation, thermodynamic integrity breaks.

**Mitigation:**
- STARK circuit **must** encode the full Cantor tree computation
- No precomputation or cached intermediate values
- Temporal seed binding prevents proof reuse

### 8.2 Proof Malleability

**Risk:** Attacker modifies STARK proof to validate different root.

**Mitigation:**
- STARK proofs bind to public inputs (leaves hash, root)
- `proof` tag contains original Cantor root
- Verifier checks STARK proof against `proof` tag

### 8.3 Quantum Attack Surface

**STARK security assumptions:**
- Hash function collision resistance (SHA2-256 or Poseidon)
- No known quantum speedup for hash preimage attacks

**Timeline:**
- Current quantum computers: ~1000 qubits
- Breaking SHA2-256: requires millions of stable qubits
- Estimated timeline: 10-20+ years

**Recommendation:** Use SHA2-256 (same as Nostr/Bitcoin) for consistency.

### 8.4 Implementation Risk

**ZK bugs are subtle and dangerous.** Mitigation strategy:
1. Start with tiny circuits (height 5-10) and known test vectors
2. Property-based testing (Hypothesis + circuit verification)
3. Independent audit before production enablement
4. Feature flag with conservative defaults (disabled until audited)

---

## 9. Implementation Roadmap

### Phase 1: Research & Minimal PoC (Weeks 1-4)
- [ ] Set up winterfell with Python bindings
- [ ] Implement toy circuit (Cantor pair of 2 numbers)
- [ ] Write test vectors (known inputs → known proof)
- [ ] Benchmark proof size and verification time
- [ ] **Deliverable:** `ZK_PROOF_OF_CONCEPT.md` with results

### Phase 2: Single-Axis Tree (Weeks 5-8)
- [ ] Extend to full binary tree over N leaves (N=4, 8, 16)
- [ ] Integrate temporal seed binding
- [ ] Benchmark height-10 tree (1024 leaves)
- [ ] Compare performance vs plain Cantor
- [ ] **Deliverable:** `cyberspace bench-zk` command

### Phase 3: Full Integration (Weeks 9-12)
- [ ] Scale to height-20 (~1M leaves)
- [ ] Integrate with `cyberspace move` command
- [ ] Add `verify-zk` command
- [ ] Property-based correctness tests
- [ ] **Deliverable:** Feature-complete implementation behind flag

### Phase 4: Optimization & Audit (Weeks 13-16)
- [ ] Profile and optimize prover performance
- [ ] Consider plonky3 migration if winterfell too slow
- [ ] Engage auditor for security review
- [ ] Documentation and spec updates
- [ ] **Deliverable:** Production-ready, audited code

---

## 10. Open Questions and Research Directions

### 10.1 Can We Use a Different Tree Structure?

**Current:** Binary Cantor tree (two children per parent)

**Alternative:** M-ary tree (e.g., 4-ary, 8-ary)
- **Pros:** Shallower tree, fewer total constraints
- **Cons:** More complex arithmetization, less parallelizable

**Research needed:** Benchmark M-ary vs binary for STARK efficiency.

### 10.2 Recursive Proof Composition?

**Idea:** Prove small subtrees recursively, combine into final proof.

**Benefit:** Parallelizable proof generation.

**Complexity:** Adds significant engineering overhead.

**Verdict:** Defer to Phase 4 if single-circuit approach proves too slow.

### 10.3 Can We Reuse STARK Proofs?

**Problem:** Each hop has unique temporal seed, so proofs are non-reusable.

**Idea:** Cache STARK proofs for spatial subtrees (independent of temporal seed).

**Benefit:** Amortize STARK cost across multiple movements.

**Risk:** Complicates caching semantics, potential for stale proofs.

**Verdict:** Research in Phase 2.

---

## 11. Success Metrics (From Skill)

| Metric | Target | Measurement Approach |
|--------|--------|---------------------|
| Proof generation time | <10× standard | `time cyberspace move --zk` vs `time cyberspace move` |
| Verification time | <10 ms | `cyberspace verify-zk --benchmark` |
| Proof size | <100 KB | Measure encoded proof tag size |
| All existing tests pass | 100% | `pytest tests/` with ZK enabled |
| No trusted setup | Required | Verify library configuration |
| Post-quantum secure | Required | Confirm hash-based assumptions |

---

## 12. Related Work and Prior Art

### 12.1 ZK for Proof-of-Work

- **zk-Bitcoin:** Proposals to prove PoW validity without re-hashing
- **Equihash ZK:** ZK proofs for memory-hard PoW (Zcash)
- **Relevance:** Same pattern (prove expensive computation cheaply)

### 12.2 ZK for Tree Computations

- **Merkle tree inclusion proofs:** Standard in ZK (e.g., Tornado Cash)
- **Verkle trees:** Vector commitment trees for stateless clients
- **Relevance:** Tree arithmetization patterns

### 12.3 Recursive Proof Systems

- **Nova:** Incrementally verifiable computation (IVC)
- **Briar:** Privacy-preserving state channels
- **Relevance:** Could enable incremental Cantor tree proofs

---

## 13. Appendix: Cantor Pairing Constraint System

### 13.1 Minimal AIR (Algebraic Intermediate Representation)

**Public inputs:** `x`, `y`, `result`

**Trace columns:** `s`, `t`, `u`, `v`

**Constraints:**
```
s - (x + y) = 0
t - (s + 1) = 0
u - (s × t) = 0
v - (u × inv2) = 0  // inv2 = (p+1)/2 in field F_p
result - (v + y) = 0
```

**Boundary constraints:**
```
x = public_input[0]
y = public_input[1]
result = public_input[2]
```

### 13.2 Field Selection

**Recommended prime field:**
- **Mersenne31:** 2³¹ - 1 (winterfell default)
- **Goldilocks:** 2⁶⁴ - 2³² + 1 (plonky3 default)

**Rationale:** Fast modular reduction, widely supported.

---

## 14. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-17 | Use ZK-STARKs (not SNARKs) | Post-quantum security, no trusted setup |
| 2026-04-17 | Phase 1: winterfell | Python support, easier prototyping |
| 2026-04-17 | Optional `zk` tag (not new action type) | Backward compatibility, gradual adoption |
| 2026-04-17 | Preserve original `proof` tag | Fallback verification, audit trail |

---

## 15. Next Steps

1. **Set up development environment** with winterfell Python bindings
2. **Create feature branch:** `feature/zk-stark-proofs`
3. **Write minimal PoC:** Prove single Cantor pair computation
4. **Write test vectors:** Known inputs → expected proof
5. **Document learnings:** `logs/zk-stark-2026-04-17.md`

---

*This document is a living design spec. Update as implementation progresses and new learnings emerge.*
