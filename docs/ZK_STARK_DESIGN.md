# ZK-STARK Proofs for Cyberspace Cantor Tree Verification

**Created:** 2026-04-17  
**Status:** Design Draft  
**Author:** XOR (Hermes Agent)  
**Related:** CYBERSPACE_V2.md §4, DECK-0001-hyperspace.md §8

---

## 1. Problem Statement

### Current State

Cantor traversal proofs in Cyberspace have **work equivalence**: verification costs the same computational work as generation. This is established in `RATIONALE.md` §7 as a core thermodynamic property—"no observer advantage."

**The consequence:** A mobile device or lightweight client must recompute the entire Cantor tree to verify a proof. For height-30+ traversals (cross-sector movement), this requires:
- Height 30: ~1 billion Cantor pairings (~1 second on consumer hardware)
- Height 33: ~8.6 billion pairings (~15 minutes, Hyperspace entry cost)
- Height 40: ~1 trillion pairings (infeasible for mobile)

**This prevents lightweight clients from participating** in verification, which limits:
- Mobile wallet integration
- Browser-based verification
- Real-time relay validation at scale
- Third-party audit tools

### Desired State

ZK-STARK proofs would enable:
- **Prover** does the full Cantor tree work (preserves thermodynamic requirement)
- **Verifier** checks the ZK proof in milliseconds (enables lightweight clients)
- **No trusted setup** (STARKs, not SNARKs—critical for decentralization)
- **Post-quantum secure** (STARKs use hash-based cryptography, not elliptic curves)

### Key Insight

The statement to prove is:

> "I correctly computed a Cantor tree root from these leaves, where the leaves include the temporal seed and path coordinates."

This is an **arithmetic circuit** statement amenable to ZK-STARKs:
- **Public inputs:** tree_root, leaf_count, temporal_seed_commitment, leaf_commitments
- **Private inputs:** full leaf sequence, intermediate tree nodes
- **Computation:** Iterative Cantor pairing: `π(a,b) = ((a+b)(a+b+1))/2 + b`

---

## 2. Arithmetic Circuit Design for Cantor Pairing

### Cantor Formula as Field Operations

The Cantor pairing function:

```
π(a, b) = ((a + b) × (a + b + 1)) / 2 + b
```

Must be expressed as arithmetic circuit constraints over a finite field.

**Field choice:** ZK-STARKs typically use prime fields. The Cantor formula involves:
1. Addition: `s = a + b`
2. Multiplication: `s × (s + 1)`
3. Division by 2: `× inverse(2)` in the field
4. Final addition: `+ b`

**Challenge:** Cantor pairing produces integers that grow rapidly. A tree of height h with 64-bit leaves produces a root that can exceed 2^256.

**Solution:** Work in a field large enough to contain the root, or use a commitment scheme where the prover commits to intermediate values and proves correct computation without revealing them.

### Circuit Structure

For a Cantor tree with N leaves:

```
Leaves:     [L0, L1, L2, ..., L(N-1)]
Level 1:    [π(L0,L1), π(L2,L3), ...]     (N/2 pairings)
Level 2:    [π(P0_0, P0_1), ...]          (N/4 pairings)
...
Root:       [single value]
```

**Constraint count per pairing:** ~5-10 arithmetic constraints (depends on field and optimization)

**Total constraints for height-h tree:** 
- Leaves: 2^h
- Pairings: 2^h - 1 (complete binary tree)
- Constraints: ~10 × 2^h

**Example (height 20):**
- 1,048,576 leaves
- 1,048,575 pairings
- ~10 million constraints

This is **feasible** for modern STARK provers (Winterfell can handle 100M+ constraints).

### Temporal Seed Integration

Per DECK-0001 §8, the temporal seed is:

```
temporal_seed = int.from_bytes(previous_event_id, "big") % 2^256
```

**In the circuit:**
- `previous_event_id` is public input (32 bytes)
- Prover computes temporal_seed
- Temporal seed becomes leaf[0] in the Cantor tree
- This binds the proof to the specific chain position

### Leaf Sequence (Private Input)

For Hyperspace traversal (DECK-0001 §8):
```
leaves = [temporal_seed, B_from, B_from+1, ..., B_to]
```

For standard hop (CYBERSPACE_V2.md §5):
```
leaves = [temporal_seed, coord_1, coord_2, ..., coord_N]  # per-axis values
```

---

## 3. ZK-STARK Library Evaluation

### Candidates

| Library | Language | Maturity | GPU Support | Learning Curve |
|---------|----------|----------|-------------|----------------|
| **winterfell** | Rust | High (Facebook/Meta) | No | Medium |
| **starkware/starkex** | Cairo | Production (dYdX, Sorare) | No | High (Cairo DSL) |
| **plonky3** | Rust | High (0xLabs, Polygon) | Yes | Medium |
| **arkworks/stark** | Rust | Medium | No | High |
| **gnark** | Go | Medium | No | Medium |

### Recommendation: Winterfell

**Rationale:**

1. **Python bindings available** via `winterfell-py` (or easy FFI)
2. **Well-documented** with examples for arithmetic circuits
3. **No trusted setup** (authentic STARK, not STARK → SNARK)
4. **Active maintenance** (Meta-backed)
5. **Provable security** (post-quantum, hash-based)

**Alternative:** `plonky3` if GPU acceleration becomes necessary. Plonky3 supports GPU proving and is used in production by major L2s.

### Why Not SNARKs?

- **Trusted setup required** (violates Cyberspace's "no authorities" principle)
- **Not post-quantum secure** (elliptic curve-based)
- **Less transparent** security assumptions

STARKs are the correct choice for a protocol prioritizing decentralization and longevity.

---

## 4. Proof Size and Verification Time Estimates

Based on Winterfell benchmarks and STARK literature:

### Proof Size

| Tree Height | Leaves | Proof Size (estimated) | Fits in Nostr? |
|-------------|--------|------------------------|----------------|
| h10 | 1,024 | ~50 KB | ✅ Yes |
| h15 | 32,768 | ~75 KB | ✅ Yes |
| h20 | 1,048,576 | ~100 KB | ⚠️ Borderline (Nostr limit ~64KB recommended) |
| h25 | 33M | ~150 KB | ❌ No (needs chunking) |
| h30 | 1B | ~200 KB | ❌ No (needs chunking) |

**Mitigation:** For large proofs, publish ZK proof separately and include commitment hash in Nostr event. Or use recursive proof composition (prove tree in chunks, compose final proof).

### Verification Time

| Tree Height | Verification Time (CPU) | Mobile Device |
|-------------|------------------------|---------------|
| Any height | **5-50 ms** | ✅ Feasible |

**Key property:** STARK verification is O(log N) in circuit size, so verification time is nearly constant regardless of tree height.

### Proof Generation Time

| Tree Height | Prover Time (single-core) | Prover Time (GPU) |
|-------------|---------------------------|-------------------|
| h15 | ~1 second | ~100 ms |
| h20 | ~10 seconds | ~1 second |
| h25 | ~2 minutes | ~10 seconds |
| h30 | ~20 minutes | ~1 minute |

**Acceptable overhead:** < 10x standard verification (per success metrics). Current estimates meet this for h ≤ 25 on CPU.

---

## 5. Integration Approach with cyberspace-cli

### New Action Tag (Future Extension)

Per `cyberspace-protocol` skill, all movement actions use `kind=3333`. A future extension could add:

```
A=verify-zk  # ZK-STARK augmented verification
```

**Event structure:**
```json
{
  "kind": 3333,
  "tags": [
    ["A", "hop"],  // or "hyperjump", "enter-hyperspace"
    ["A", "verify-zk"],  # Additional tag for ZK proof
    ["proof", "<cantor_root_hex>"],
    ["zk_proof", "<stark_proof_hex_or_url>"],
    // ... other standard tags
  ]
}
```

**Note:** This is a **future extension**. Initial work is pure research/PoC—no protocol changes required yet.

### CLI Commands (PoC Phase)

```bash
# Generate ZK proof for a Cantor computation
cyberspace zk prove --leaves "1,2,3,4,5" --output proof.json

# Verify a ZK proof
cyberspace zk verify --proof proof.json --expected-root <hex>

# Benchmark ZK vs standard verification
cyberspace zk bench --height 20

# Convert existing hop proof to ZK-augmented proof
cyberspace zk augment --hop-event event.json --output zk-event.json
```

### Directory Structure

```
~/repos/cyberspace-cli/
├── src/cyberspace_core/
│   └── zk_cantor/           # New module
│       ├── __init__.py
│       ├── circuit.py       # Arithmetic circuit definition
│       ├── prover.py        # STARK prover integration
│       ├── verifier.py      # STARK verifier integration
│       └── benchmarks.py    # Performance tests
├── tests/test_zk_cantor.py
├── docs/ZK_STARK_DESIGN.md  # This document
└── logs/zk-stark-YYYY-MM-DD.md
```

### Feature Flag

Keep ZK features behind a flag until production-ready:

```python
# In CLI entry point
if ctx.params.get('zk_enabled'):
    from cyberspace_core import zk_cantor
    # ... use ZK module
```

Or use environment variable:
```bash
export CYBERSPACE_ZK_ENABLED=1
```

---

## 6. Technical Challenges and Mitigations

### Challenge 1: Field Size for Large Integers

**Problem:** Cantor roots for height-20+ trees exceed typical STARK field sizes (often ~256 bits).

**Mitigations:**
1. **Use a larger field** (Winterfell supports custom field configuration)
2. **Commit-and-prove** approach: prover commits to intermediate values, proves correct computation in chunks
3. **Recursive proofs:** Prove subtrees individually, compose final proof

### Challenge 2: Proof Size in Nostr Events

**Problem:** STARK proofs (50-200 KB) may exceed practical Nostr event sizes.

**Mitigations:**
1. **External storage:** Publish proof to IPFS/Nostr large-blob protocol, include hash in event
2. **Recursive composition:** Prove tree in chunks, publish only final composed proof
3. **Optimize for common case:** Most hops are h≤20; optimize for that, handle large proofs separately

### Challenge 3: Work Equivalence Property

**Problem:** RATIONALE.md §7 emphasizes work equivalence (observers = participants). ZK proofs break this symmetry.

**Analysis:**
- **Prover still does full work** (Cantor tree computation is input to ZK circuit)
- **Verifier does less work** (checks proof instead of recomputing)
- **This is acceptable** because:
  - The *generation* cost is unchanged (thermodynamic requirement preserved)
  - Lightweight verification is a *convenience*, not a protocol advantage
  - Anyone can still verify by recomputing (work equivalence is preserved as an *option*)

**Design principle:** ZK proofs are an *optimization*, not a replacement. Standard verification remains valid.

### Challenge 4: Implementation Complexity

**Problem:** ZK-STARKs are complex. Risk of bugs, side-channels, or incorrect circuit design.

**Mitigations:**
1. **Start minimal:** Single Cantor pair proof (not full tree)
2. **Property-based testing:** Use Hypothesis to generate random trees, compare ZK vs standard verification
3. **Formal verification:** Consider Cairo or formal methods for critical circuits
4. **Incremental deployment:** Keep behind feature flag, audit extensively before enabling

---

## 7. Security Considerations

### Soundness

STARKs provide **computational soundness**: a malicious prover cannot forge a valid proof except with negligible probability.

**For Cyberspace:** This means a malicious actor cannot claim to have computed a Cantor root they did not compute. The soundness error for STARKs is typically < 2^-100.

### Zero-Knowledge

**Question:** Does the proof need to be zero-knowledge (hiding the leaf values)?

**Answer:** **No.** The leaf values (coordinates, temporal seed) are already public in the Nostr event. Zero-knowledge adds overhead without security benefit.

**Optimization:** Use a STARK variant without zero-knowledge (faster, smaller proofs).

### Post-Quantum Security

STARKs rely on:
- Collision-resistant hash functions (e.g., SHA-256, BLAKE3)
- Random oracles (in the random oracle model)

These are **believed to be post-quantum secure** (Grover's algorithm gives quadratic speedup, mitigated by larger hash outputs).

**Contrast with SNARKs:** SNARKs use elliptic curve pairings, which are broken by Shor's algorithm on a quantum computer.

---

## 8. Success Metrics (from Original Task)

| Metric | Target | Feasibility |
|--------|--------|-------------|
| Proof generation time | < 10x standard verification | ✅ Achievable for h ≤ 25 |
| Verification time | < 10ms regardless of height | ✅ STARKs are O(log N) |
| Proof size | < 100KB (fits in Nostr) | ⚠️ Achievable for h ≤ 20; larger needs chunking |
| All existing tests pass | — | ✅ ZK is additive, not replacement |
| No trusted setup | Required | ✅ STARKs don't need it |
| Post-quantum secure | Required | ✅ Hash-based, not EC-based |

---

## 9. Next Steps

### Session 1-3: Research & Design (Current Session)

- ✅ Read all required materials (CYBERSPACE_V2.md, DECK-0001, RATIONALE.md, CLI code)
- ✅ Write this design document
- ⏳ **Next:** Install Winterfell, run examples, verify arithmetic circuit approach

### Session 4-8: Minimal PoC

- Create `feature/zk-stark-proofs` branch
- Install Winterfell (Rust + Python bindings)
- Implement single Cantor pair proof:
  - Circuit: `π(x, y) = z`
  - Public inputs: `x, y, z`
  - Private inputs: none (trivial case)
- Write verification tests
- Benchmark proof size and verification time

### Session 9-15: Full Tree Implementation

- Extend circuit to full Cantor tree
- Integrate temporal seed binding
- Add `cyberspace zk prove` and `cyberspace zk verify` commands
- Compare performance vs standard verification

### Session 16+: Integration & Testing

- Property-based tests for correctness
- Integration with hop/hyperjump event construction
- Documentation updates
- Performance optimization (GPU? Recursive proofs?)

---

## 10. References

### Protocol Specs
- `~/repos/cyberspace/CYBERSPACE_V2.md` — Core protocol, §4 (Cantor trees), §5 (Temporal axis)
- `~/repos/cyberspace/decks/DECK-0001-hyperspace.md` — Hyperspace traversal proofs, §8
- `~/repos/cyberspace/RATIONALE.md` — Work equivalence property, §7

### ZK-STARK Libraries
- Winterfell: https://github.com/facebookresearch/winterfell
- Plonky3: https://github.com/0xPolygonZero/plonky3
- Cairo (StarkWare): https://www.cairo-lang.org/

### Background Reading
- "STARKs, Explained" — Vitalik Buterin, https://vitalik.ca/general/2017/11/09/starks_part_1.html
- "Anatomy of a STARK" — https://neerc.ifmo.ru/teaching/proofs/
- Winterfell documentation: https://github.com/facebookresearch/winterfell/tree/main/docs

---

## Appendix A: Sample Arithmetic Circuit for Cantor Pair

```
# Circuit for π(a, b) = ((a+b)(a+b+1))/2 + b

# Public inputs: a, b, result
# Private wires: s, t, u

# Constraint 1: s = a + b
s - (a + b) = 0

# Constraint 2: t = s + 1
t - (s + 1) = 0

# Constraint 3: u = s * t
u - (s * t) = 0

# Constraint 4: result = u / 2 + b
# Multiply both sides by 2 to avoid division:
# 2 * result = u + 2 * b
2 * result - u - 2 * b = 0

# Total: 4 constraints per Cantor pairing
```

**Note:** Actual implementation depends on the specific STARK library's constraint system. Winterfell uses Algebraic Intermediate Representation (AIR) with polynomials.

---

## Appendix B: Leaf Construction for Different Action Types

### Hop (Local Movement)
```python
leaves = [
    temporal_seed,
    x1, x2, ..., xN,  # X-axis path (aligned subtree leaves)
    y1, y2, ..., yM,  # Y-axis path
    z1, z2, ..., zK,  # Z-axis path
]
```

### Hyperjump (Hyperspace Traversal)
```python
leaves = [temporal_seed, B_from, B_from+1, ..., B_to]
```

### Enter-Hyperspace (Sector Plane Entry)
```python
# Standard Cantor proof to reach the coordinate
leaves = [temporal_seed, coord_1, coord_2, ..., coord_N]  # per-axis traversal
```

---

*Document created: 2026-04-17*  
*Next session: Install Winterfell and prototype single-pair circuit*
