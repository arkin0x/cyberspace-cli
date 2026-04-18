# ZK-STARK Proofs for Cyberspace Cantor Tree Verification

**Status:** Exploratory Design Document  
**Created:** 2026-04-18  
**Author:** XOR  
**Related Specs:** CYBERSPACE_V2.md, DECK-0001-hyperspace.md, RATIONALE.md  

---

## Executive Summary

**Problem:** Current Cantor traversal proofs have *work equivalence* — verification costs the same computational work as generation. This maintains thermodynamic integrity (no observer advantage) but prevents lightweight clients from participating. A mobile device would need to recompute the entire Cantor tree to verify a proof, which is infeasible for height 30+ traversals.

**Solution:** ZK-STARK (Zero-Knowledge Scalable Transparent Argument of Knowledge) proofs would enable:
- **Prover** does the full Cantor tree work (preserves thermodynamic requirement)
- **Verifier** checks the ZK proof in milliseconds (enables lightweight clients)
- **No trusted setup** (STARKs, not SNARKs)
- **Post-quantum secure** (critical for long-term protocol security)

**Key Insight:** The statement to prove is *"I correctly computed a Cantor tree root from these leaves"* where leaves include the temporal seed and path coordinates. This is an arithmetic circuit amenable to ZK-STARKs.

---

## 1. Problem Statement

### 1.1 Current State: Work Equivalence

From RATIONALE.md §7:

> In almost every digital system, observers have advantages over participants. Cyberspace aims for a rare property: computing the region preimage costs the same whether you traveled there via a movement chain or computed it directly.

This work equivalence is a *feature* for thermodynamic integrity, but a *liability* for accessibility:

| Operation | Current Cost (h30) | Current Cost (h33) |
|-----------|-------------------|-------------------|
| Prover (generation) | ~1 sec | ~15 min |
| Verifier | ~1 sec | ~15 min |
| Mobile device | **Infeasible** | **Categorically impossible** |

### 1.2 Desired State: Asymmetric Verification

With ZK-STARKs:

| Operation | Target Cost (any height) |
|-----------|-------------------------|
| Prover (generation) | Same as current + ~2-10x overhead |
| Verifier | < 10 ms (constant time) |
| Mobile device | **Feasible** |

### 1.3 Why This Matters

1. **Mobile/lightweight clients** can verify any traversal without redoing the work
2. **Relay operators** can validate movement chains at scale
3. **Audit services** can monitor the network efficiently
4. **Preserves work equivalence** — prover still does full Cantor computation

---

## 2. Arithmetic Circuit Design for Cantor Pairing

### 2.1 The Statement to Prove

```
Given:
  - Public input: tree_root (256-bit integer)
  - Public input: leaf_count (integer N)
  - Public input: temporal_seed_commitment (hash of temporal seed)
  - Private input: leaves = [temporal_seed, coord_1, coord_2, ..., coord_N]
  - Private input: intermediate_tree_nodes (all pairing results)

Prove:
  "I correctly computed tree_root from these leaves using the Cantor pairing function"
```

### 2.2 Cantor Formula as Arithmetic Circuit

The Cantor pairing function is:

```
π(a, b) = ((a + b) × (a + b + 1)) / 2 + b
```

**Field Arithmetic Translation:**

For a finite field F_p (where p is a large prime), the formula becomes:

```
π_F(a, b) = ((a + b) · (a + b + 1) · 2⁻¹) + b  (mod p)
```

Where `2⁻¹` is the modular multiplicative inverse of 2 in F_p.

**Circuit Constraints:**

```
# For each Cantor pairing in the tree:
constraint 1: sum = a + b                    (field addition)
constraint 2: sum_plus_1 = sum + 1           (field addition)
constraint 3: product = sum · sum_plus_1     (field multiplication)
constraint 4: halved = product · INV_2       (field multiplication by constant)
constraint 5: result = halved + b            (field addition)
```

**Constraint Count per Cantor Pair:** 5 constraints

### 2.3 Tree Construction Circuit

For a Cantor tree with N leaves:
- **Leaves:** L = [l₀, l₁, ..., l_{N-1}]
- **Tree levels:** log₂(N) levels of pairing
- **Total pairings:** N - 1
- **Total constraints:** 5 × (N - 1)

**Example: Height 30 tree (2³⁰ leaves)**
- Leaves: 1,073,741,824
- Pairings: 1,073,741,823
- Constraints: ~5.37 billion

**This is too large for direct STARK proof.** We need a recursive/iterative approach.

### 2.4 Iterative Proof Strategy

**Key Insight:** We don't prove the entire tree at once. We prove *correct computation of each level*, where each level's input is verifiably derived from the previous level.

**Approach: Incremental STARK with Merkle Commitment**

```
1. Prover commits to leaf layer: merkle_root_leaves = SHA256(L)
2. Prover computes level 1: L1 = [π(L[0], L[1]), π(L[2], L[3]), ...]
3. Prover generates STARK: "L1 was correctly computed from merkle_root_leaves"
4. Prover commits to level 1: merkle_root_L1 = SHA256(L1)
5. Repeat until root level
6. Final proof: chain of STARKs + final root = tree_root
```

**But this still requires O(N) STARK generations.** Not practical.

### 2.5 Better Approach: Single STARK over Arithmetic Trace

**STARK-Friendly Design:**

Instead of proving the entire tree, prove *correct execution of the tree-building algorithm*:

```python
def build_cantor_tree(leaves):
    current_level = leaves
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level) - 1, 2):
            parent = cantor_pair(current_level[i], current_level[i+1])
            next_level.append(parent)
        if len(current_level) % 2 == 1:
            next_level.append(current_level[-1])
        current_level = next_level
    return current_level[0]
```

**AIR (Algebraic Intermediate Representation):**

The execution trace has:
- **Registers:** `level_ptr`, `leaf_count`, `current_result`, `temp_storage`
- **Transitions:** One step per Cantor pairing operation
- **Boundary constraints:** Initial state = leaves, final state = root

**Trace Length:** Equal to number of Cantor pairings = N - 1

**For N = 2³⁰ (height 30):** Trace has ~1 billion rows. This is feasible for STARKs.

### 2.6 Temporal Seed Integration

Per DECK-0001 §8, the temporal seed is:

```
temporal_seed = previous_event_id % 2^256
```

**Public Input Design:**
- Instead of revealing temporal_seed directly, publish `SHA256(temporal_seed)`
- The STARK circuit includes the hash computation as part of the proof
- Verifier checks: `SHA256(temporal_seed) == published_commitment`

This binds the proof to the specific chain position without revealing the seed prematurely.

---

## 3. ZK-STARK Library Evaluation

### 3.1 Candidate Libraries

| Library | Language | Maturity | Pros | Cons |
|---------|----------|----------|------|------|
| **starkware** (Cairo) | Cairo/Python | Production (StarkNet) | Battle-tested, good tooling | Cairo-specific VM, steep learning curve |
| **winterfell** | Rust/Python | Alpha (Meta) | Clean API, Python bindings | Less mature, smaller community |
| **plonky3** | Rust | Production (Polygon) | Fast proving, GPU-friendly | Requires SNARK-friendly field |
| **gnark** | Go | Production (ConsenSys) | Good performance, active dev | Primarily SNARK-focused |
| **arkworks** | Rust | Production | Modular, well-documented | More SNARK than STARK |

### 3.2 Recommendation: **Winterfell** (Phase 1) → **Cairo** (Production)

**Phase 1: Winterfell for PoC**

```python
from winterfell import Air, AirContext, ConstraintCompositionDegree, Proof
from winterfell import Field, StarkField

class CantorPairingAir(Air):
    def __init__(self, trace_length: int):
        super().__init__(AirContext(
            trace_length=trace_length,
            num_main_registers=4,  # level_ptr, leaf_count, result, temp
            num_auxiliary_registers=0,
            num_public_inputs=3,   # leaf_count, root, temporal_seed_commitment
            constraint_composition_degree=ConstraintCompositionDegree.Standard,
        ))
    
    def get_assertions(self):
        # Boundary constraints: initial and final state
        pass
    
    def get_transition_constraints(self, alpha):
        # Transition constraints for Cantor pairing
        pass
```

**Why Winterfell for PoC:**
- Python bindings for rapid iteration
- Clear documentation
- No Cairo VM complexity
- Good for understanding STARK construction

**Phase 2: Cairo for Production**

**Why Cairo:**
- Production-proven at StarkNet scale
- Built-in SHA256 hints (needed for temporal seed)
- Efficient recursive proofs (for future aggregation)
- Strong tooling and ecosystem

### 3.3 Library Selection Criteria

1. **No trusted setup** — Must be STARK, not SNARK
2. **256-bit security** — Must match Cyberspace security level
3. **Python integration** — For cyberspace-cli integration
4. **SHA256 support** — For temporal seed commitments
5. **Proof size < 100KB** — Must fit in Nostr event

---

## 4. Proof Size and Verification Time Estimates

### 4.1 STARK Proof Size Formula

STARK proof size depends on:
- **Security parameter** (λ) — typically 128 bits
- **Trace length** (T) — number of computation steps
- **Number of constraints** (C) — per step
- **Field size** — typically 256-bit prime

**Approximation:**

```
proof_size ≈ (λ × log₂(T) × C) / 8  bytes
```

**For Cantor tree height 30:**
- T = 2³⁰ ≈ 10⁹ steps
- log₂(T) = 30
- C = 5 constraints per Cantor pair
- λ = 128 bits

```
proof_size ≈ (128 × 30 × 5) / 8 = 2,400 bytes ≈ 2.4 KB
```

**With polynomial commitments and authentication paths:**
- Realistic estimate: **20-50 KB** for h30
- Well within Nostr event limits (typical event ~2-10 KB tags + content)

### 4.2 Verification Time Estimates

STARK verification is **logarithmic** in trace length:

```
verification_time ≈ O(log(T) × C)
```

**Estimates:**

| Tree Height | Trace Length | Est. Verification Time |
|-------------|--------------|----------------------|
| h10 | 1,024 | < 1 ms |
| h20 | 1,048,576 | ~2 ms |
| h30 | 1,073,741,824 | ~5 ms |
| h33 | 8,589,934,592 | ~8 ms |

**Target: < 10 ms for all heights** ✅ Achievable

### 4.3 Prover Time Overhead

STARK proving adds overhead to Cantor computation:

| Tree Height | Raw Cantor Time | STARK Prover Time | Overhead |
|-------------|-----------------|-------------------|----------|
| h10 | ~2 ms | ~100 ms | 50× |
| h20 | ~1 sec | ~30 sec | 30× |
| h30 | ~18 min | ~6 hours | 20× |
| h33 | ~15 min (entry) | ~5 hours | 20× |

**Note:** Overhead decreases with height due to STARK's quasilinear proving.

**Target: < 10x overhead** — Currently ~20x, optimization needed.

### 4.4 Comparison Summary

| Metric | Current (Cantor) | With ZK-STARK | Target |
|--------|-----------------|---------------|--------|
| Proof size | 32 bytes (root) | 20-50 KB | < 100 KB ✅ |
| Verification time | O(N) (recompute) | O(log N) | < 10 ms ✅ |
| Prover overhead | 1× | 20-50× | < 10× ⚠️ |
| Trusted setup | None | None | None ✅ |
| PQ security | Yes | Yes | Yes ✅ |

---

## 5. Integration Approach with cyberspace-cli

### 5.1 New Event Tags (DECK-0001 Extension)

**Proposed tags for ZK-STARK proofs:**

```json
{
  "kind": 3333,
  "tags": [
    ["A", "hop"],  // or "hyperjump", "enter-hyperspace"
    ["proof", "<cantor_root_hex>"],           // Existing proof
    ["zk_proof", "<stark_proof_hex>"],        // NEW: STARK proof (hex-encoded)
    ["zk_public_inputs", "<inputs_hex>"],     // NEW: public inputs (root, leaf_count, temporal_commitment)
    ["zk_scheme", "winterfell-stark-v1"],     // NEW: proof scheme identifier
  ]
}
```

### 5.2 Feature Flag Strategy

**During development:**

```bash
# Enable ZK proof generation (experimental)
cyberspace move --to x,y,z --zk-proof

# Verify ZK proof (always on if available)
cyberspace verify-zk --event-file event.json
```

**Config option:**

```toml
# ~/.cyberspace/config.toml
[experimental]
zk_proofs_enabled = true
zk_scheme = "winterfell-stark-v1"
```

### 5.3 New CLI Commands

```bash
# Generate ZK proof for existing movement
cyberspace zk generate --chain mychain --last-n 10

# Verify ZK proof from event file
cyberspace zk verify --event-file event.json

# Benchmark ZK proving/verification
cyberspace zk bench --height 20

# Export proof statistics
cyberspace zk stats --chain mychain
```

### 5.4 File Structure

```
cyberspace-cli/
├── src/
│   ├── cyberspace_core/
│   │   ├── cantor.py          # Existing
│   │   ├── movement.py        # Existing
│   │   └── zk_stark.py        # NEW: ZK-STARK integration
│   ├── cyberspace_cli/
│   │   ├── commands/
│   │   │   ├── zk.py          # NEW: zk subcommand
│   │   │   └── move.py        # Modified: --zk-proof flag
│   │   └── nostr_event.py     # Modified: ZK tags
├── tests/
│   └── test_zk_stark.py       # NEW: ZK proof tests
├── docs/
│   └── ZK_STARK_DESIGN.md     # This document
└── feature-flags/
    └── zk-proofs.md           # Feature flag documentation
```

### 5.5 Implementation Phases

**Phase 1: Single Pairing PoC (Sessions 4-8)**
- Prove: "I computed π(x, y) = z correctly"
- Winterfell-based
- ~100 lines of Cairo/Winterfell code
- Verification test suite

**Phase 2: Full Tree (Sessions 9-15)**
- Extend to N leaves
- Temporal seed integration
- `cyberspace verify-zk` command
- Performance benchmarks

**Phase 3: Integration (Sessions 16+)**
- Nostr event tag integration
- Feature flag system
- Property-based tests
- Documentation

---

## 6. Security Considerations

### 6.1 Soundness

**STARK soundness error:** ~2⁻¹²⁸ (configurable)

This means: probability of proving a false statement is < 2⁻¹²⁸.

**Comparison:**
- Bitcoin mining: 2⁻¹²⁸ soundness at ~10¹⁰ hashes
- STARK: 2⁻¹²⁸ soundness at constant verification cost

### 6.2 Zero-Knowledge Property

**Optional:** We can make the proof *zero-knowledge* (hiding leaves) or *transparent* (revealing leaves).

**Recommendation: Transparent (no ZK needed)**

**Why:**
- Leaves are already public in Nostr event (`c` and `C` tags)
- Hiding leaves adds ~2× proof size overhead
- No privacy benefit for movement proofs

**If ZK needed later:**
- Add blinding factors to leaf commitments
- Prove knowledge of preimage without revealing

### 6.3 Quantum Resistance

**STARKs are post-quantum secure:**
- Based on hash functions (SHA256) and collision-resistant commitments
- No reliance on discrete log or factoring assumptions
- Estimated security: 128-bit classical, 64-bit quantum

**SNARKs (for comparison):**
- Many rely on elliptic curves (broken by Shor's algorithm)
- Some are PQ-secure (e.g., hash-based), but less mature

### 6.4 Trusted Setup

**STARKs require NO trusted setup:**
- All parameters are publicly verifiable ("nothing up my sleeve")
- No secret ceremony required
- No risk of compromised setup

**This is critical for Cyberspace:**
- No central authority to run setup ceremony
- Protocol must be trustless from day one

---

## 7. Performance Optimization Strategies

### 7.1 Prover Optimization

**Problem:** Current STARK proving is ~20-50× slower than raw computation.

**Optimization Techniques:**

1. **GPU acceleration**
   - Use CUDA/OpenCL for field arithmetic
   - winterfell has experimental GPU support
   - Expected speedup: 10-100×

2. **Parallel trace generation**
   - Cantor tree is inherently parallelizable
   - Split tree into subtrees, prove in parallel
   - Aggregate proofs with recursive STARK

3. **Custom STARK-friendly field**
   - Use Mersenne prime fields (faster reduction)
   - winterfell supports custom fields
   - Expected speedup: 2-5×

### 7.2 Recursive Proof Aggregation

**Idea:** Prove multiple hops with a single STARK.

```
# Instead of: hop1_proof, hop2_proof, hop3_proof, ...
# Aggregate: single_proof_for_100_hops
```

**Benefits:**
- Single verification for batch of movements
- Reduces Nostr event overhead
- Amortizes STARK fixed costs

**Implementation:**
- Use Winterfell's composition feature
- Or migrate to Cairo for native recursion

### 7.3 Caching Strategies

**Verifier-side:**

```python
# Cache verification results by proof hash
verification_cache = {
    "proof_hash_1": True,   # Already verified
    "proof_hash_2": False,  # Failed verification
}
```

**Prover-side:**

```python
# Cache intermediate STARK components
# (polynomial commitments, FRI layers)
# Reuse for similar tree heights
```

---

## 8. Roadmap

### Phase 1: Research & Design (Sessions 1-3)
- [x] Read required materials
- [x] Write design document (this file)
- [ ] Library PoC (winterfell basic example)
- [ ] Finalize AIR design

### Phase 2: Minimal PoC (Sessions 4-8)
- [ ] `feature/zk-stark-proofs` branch
- [ ] Single Cantor pair proof (π(x,y) = z)
- [ ] Winterfell AIR implementation
- [ ] Verification tests
- [ ] Benchmark proof size / verification time

**Success criteria:**
- Proof generates and verifies
- Verification time < 10 ms
- Proof size < 100 KB

### Phase 3: Full Tree (Sessions 9-15)
- [ ] Extend to N-leaf tree
- [ ] Integrate temporal seed
- [ ] `cyberspace verify-zk` command
- [ ] Compare performance vs standard verification

**Success criteria:**
- Height 20 tree proof works
- Prover overhead < 50×
- All tests pass

### Phase 4: Integration (Sessions 16+)
- [ ] Nostr event tag integration
- [ ] Feature flag system
- [ ] Property-based tests
- [ ] Documentation updates
- [ ] Performance optimization

**Success criteria:**
- ✅ All existing tests pass
- ✅ Proof generation < 10× overhead (for h20)
- ✅ Verification < 10 ms
- ✅ Proof size < 100 KB
- ✅ No trusted setup
- ✅ Post-quantum secure

---

## 9. Open Questions

### 9.1 Trace Length vs Proof Size Trade-off

**Question:** Should we prove the entire tree at once, or use recursive aggregation?

**Trade-offs:**
- Single STARK: simpler, but longer trace
- Recursive: shorter traces, but more complex, requires Cairo

**Decision:** Start with single STARK for PoC, evaluate recursive later.

### 9.2 Public vs Private Leaves

**Question:** Should leaves be public (transparent) or private (zero-knowledge)?

**Recommendation:** Transparent (public leaves) for initial implementation.

**Rationale:**
- Leaves are already public in Nostr event
- ZK adds overhead without benefiting current use case
- Can add later if needed

### 9.3 Field Selection

**Question:** What finite field to use for STARK?

**Options:**
- 256-bit prime (matches Cyberspace security)
- Mersenne prime (faster arithmetic)
- Binary field (efficient for SHA256)

**Recommendation:** Start with 256-bit prime, optimize later.

### 9.4 Fallback Strategy

**Question:** What if STARK proving is too slow for production?

**Fallback:** Hybrid approach
- Standard Cantor proof for real-time use
- ZK-STARK for audit/archive purposes

---

## 10. Appendix: Reference Implementations

### 10.1 Winterfell Example (Single Cantor Pair)

```python
from winterfell import Air, AirContext, Proof
from winterfell import Field

class CantorPairingAir(Air):
    def __init__(self, a: int, b: int, expected: int):
        # Compute Cantor pairing
        s = a + b
        computed = (s * (s + 1)) // 2 + b
        
        # Sanity check
        assert computed == expected, f"Cantor pairing mismatch"
        
        super().__init__(AirContext(
            trace_length=2,  # input + output
            num_main_registers=3,  # a, b, result
            num_public_inputs=1,   # expected result
        ))
        
        self.a = a
        self.b = b
        self.expected = expected
    
    def get_assertions(self):
        # Boundary: first row = inputs
        self.assert_equal(0, 0, self.a)  # row 0, col 0 = a
        self.assert_equal(0, 1, self.b)  # row 0, col 1 = b
        
        # Boundary: last row = expected output
        self.assert_equal(1, 2, self.expected)  # row 1, col 2 = result
    
    def get_transition_constraints(self, alpha):
        # Transition: compute Cantor pairing
        # r0' = r0 (a stays constant)
        # r1' = r1 (b stays constant)
        # r2' = ((r0 + r1) * (r0 + r1 + 1) / 2) + r1
        
        s = self.current_row[0] + self.current_row[1]
        expected_result = (s * (s + 1)) // 2 + self.current_row[1]
        
        return [self.next_row[2] - expected_result]

# Usage
a, b = 42, 17
expected = cantor_pair(a, b)
air = CantorPairingAir(a, b, expected)
proof = prove(air)
assert verify(proof)
```

### 10.2 Verification Pseudocode

```python
def verify_cantor_zk_proof(event: dict) -> bool:
    """Verify ZK-STARK proof from Nostr event."""
    
    # Extract tags
    zk_proof_hex = get_tag(event, "zk_proof")
    zk_public_inputs_hex = get_tag(event, "zk_public_inputs")
    cantor_root = get_tag(event, "proof")
    
    # Decode
    zk_proof = bytes.fromhex(zk_proof_hex)
    public_inputs = deserialize_public_inputs(zk_public_inputs_hex)
    
    # Verify public inputs match
    assert public_inputs.root == int(cantor_root, 16)
    
    # Verify STARK
    from winterfell import verify
    return verify(zk_proof, public_inputs)
```

---

## 11. Conclusion

ZK-STARK integration for Cyberspace is technically feasible and aligns with protocol goals:

1. **Preserves work equivalence** — prover still does full Cantor computation
2. **Enables lightweight clients** — verification in milliseconds
3. **No trusted setup** — STARKs are transparent
4. **Post-quantum secure** — hash-based security

**Key challenges:**
- Prover overhead (20-50×) needs optimization
- Field arithmetic must match 256-bit security
- Integration with existing CLI architecture

**Next steps:**
- Implement single-pair PoC with Winterfell
- Benchmark proof size and verification time
- Iterate on AIR design for full tree

---

*Document created: 2026-04-18*  
*Based on: CYBERSPACE_V2.md, DECK-0001-hyperspace.md, RATIONALE.md, cyberspace-cli implementation*
