# ZK-STARK Proofs Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Implement ZK-STARK proofs for Cyberspace Cantor tree verification to enable lightweight client verification while preserving thermodynamic work requirements.

**Architecture:** Add winterfell-based STARK proof generation alongside existing Cantor proofs. Prover does full Cantor work + STARK overhead; verifier checks STARK in milliseconds.

**Tech Stack:** Python, winterfell (ZK-STARK library), pytest (testing), cyberspace-cli existing infrastructure

---

## Session 4-8: Minimal PoC (Single Cantor Pair)

### Task 1: Set Up Development Environment

**Objective:** Create feature branch (no external dependencies for PoC)

**Files:**
- Create: `feature/zk-stark-proofs` (git branch)

**Step 1: Create feature branch**

```bash
cd ~/repos/cyberspace-cli
git checkout -b feature/zk-stark-proofs
git commit -m "chore: create feature branch for ZK-STARK proofs"
```

**Note:** No external ZK library dependencies for PoC. We'll implement a mock/simulation backend that demonstrates the interface pattern. Production can swap in cairo-lang or Rust backend.

**Step 2: Commit**

```bash
git commit --allow-empty -m "chore: start ZK-STARK feature branch (mock implementation)"
```

---

### Task 2: Create ZK Cantor Module Skeleton

**Objective:** Create new module with stub implementations

**Files:**
- Create: `src/cyberspace_core/zk_cantor.py`

**Step 1: Create module with stubs**

```python
"""ZK-STARK proofs for Cantor tree verification.

This module provides zero-knowledge proofs for Cyberspace Cantor tree
computations using the winterfell STARK backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ZKCantorProof:
    """A ZK-STARK proof of correct Cantor tree computation."""
    
    root: int                    # The Cantor tree root (public)
    leaf_count: int              # Number of leaves (public)
    stark_proof: bytes           # The STARK proof object (serialized)
    constraint_count: int        # Number of AIR constraints
    
    
def prove_single_cantor_pair(x: int, y: int) -> Tuple[int, ZKCantorProof]:
    """Generate ZK proof for a single Cantor pairing: π(x, y) = z.
    
    This is the minimal PoC: prove correct computation of one Cantor pair.
    
    Args:
        x: First input to Cantor pairing
        y: Second input to Cantor pairing
        
    Returns:
        Tuple of (result, proof) where result = π(x, y)
    """
    raise NotImplementedError("Task 3: implement this")


def verify_single_cantor_pair(z: int, proof: ZKCantorProof) -> bool:
    """Verify ZK proof for a single Cantor pairing.
    
    Args:
        z: The claimed result of Cantor pairing
        proof: The ZK proof to verify
        
    Returns:
        True if proof is valid, False otherwise
    """
    raise NotImplementedError("Task 4: implement this")
```

**Step 2: Commit**

```bash
git add src/cyberspace_core/zk_cantor.py
git commit -m "feat(zk): add zk_cantor module skeleton with stubs"
```

---

### Task 3: Implement Single Cantor Pair AIR (Algebraic Intermediate Representation)

**Objective:** Define AIR constraints for Cantor pairing function

**Files:**
- Modify: `src/cyberspace_core/zk_cantor.py:40-80` (add AIR implementation)

**Step 1: Write failing test first**

Create: `tests/test_zk_cantor.py`

```python
"""Tests for ZK-STARK Cantor proofs."""

import pytest
from cyberspace_core.cantor import cantor_pair
from cyberspace_core.zk_cantor import prove_single_cantor_pair, verify_single_cantor_pair


class TestSingleCantorPair:
    """Test single Cantor pair ZK proof."""
    
    def test_prove_and_verify_small_numbers(self):
        """Test ZK proof for π(3, 5) = 28."""
        x, y = 3, 5
        expected_z = cantor_pair(x, y)  # Should be 28
        
        # Generate proof
        z, proof = prove_single_cantor_pair(x, y)
        
        # Verify result is correct
        assert z == expected_z
        
        # Verify proof
        assert verify_single_cantor_pair(z, proof) is True
        
    def test_verify_fails_with_wrong_result(self):
        """Test that verification fails with incorrect result."""
        x, y = 3, 5
        z, proof = prove_single_cantor_pair(x, y)
        
        # Tamper with result
        wrong_z = z + 1
        
        # Verification should fail
        assert verify_single_cantor_pair(wrong_z, proof) is False
```

**Step 2: Run test to verify failure**

```bash
cd ~/repos/cyberspace-cli
PYTHONPATH=src python3 -m pytest tests/test_zk_cantor.py::TestSingleCantorPair::test_prove_and_verify_small_numbers -v
```

Expected: FAIL — `NotImplementedError`

**Step 3: Implement AIR and prover**

Read winterfell documentation first:
```python
from winterfell import Air, AirContext, ConstraintSystem, Field
```

Implement the AIR (detailed implementation will depend on winterfell API after experimentation).

**Step 4: Run test to verify pass**

```bash
PYTHONPATH=src python3 -m pytest tests/test_zk_cantor.py::TestSingleCantorPair::test_prove_and_verify_small_numbers -v
```

Expected: PASS

**Step 5: Run all ZK tests**

```bash
PYTHONPATH=src python3 -m pytest tests/test_zk_cantor.py -v
```

Expected: All tests pass

**Step 6: Commit**

```bash
git add src/cyberspace_core/zk_cantor.py tests/test_zk_cantor.py
git commit -m "feat(zk): implement single Cantor pair AIR and prover"
```

---

### Task 4: Add Benchmark for Single Pair Proof

**Objective:** Measure proof generation time, verification time, and proof size

**Files:**
- Create: `tests/bench_zk_single_pair.py`

**Step 1: Write benchmark test**

```python
"""Benchmarks for single Cantor pair ZK proof."""

import pytest
import time
from cyberspace_core.zk_cantor import prove_single_cantor_pair, verify_single_cantor_pair


class TestSinglePairBenchmark:
    """Benchmark single Cantor pair ZK proof."""
    
    def test_proof_generation_time(self, benchmark):
        """Benchmark proof generation time."""
        def generate():
            return prove_single_cantor_pair(42, 17)
        
        result = benchmark(generate)
        z, proof = result
        
        print(f"\nProof generation time: {benchmark.stats.mean*1000:.2f}ms")
        print(f"Proof size: {len(proof.stark_proof)} bytes")
        print(f"Constraints: {proof.constraint_count}")
        
    def test_verification_time(self, benchmark):
        """Benchmark proof verification time."""
        z, proof = prove_single_cantor_pair(42, 17)
        
        def verify():
            return verify_single_cantor_pair(z, proof)
        
        result = benchmark(verify)
        assert result is True
        
        print(f"\nVerification time: {benchmark.stats.mean*1000:.2f}ms")
```

**Step 2: Run benchmarks**

```bash
PYTHONPATH=src python3 -m pytest tests/bench_zk_single_pair.py -v --benchmark
```

**Step 3: Document results**

Add results to `logs/zk-stark-2026-04-17.md`:

```markdown
### Benchmark Results (Single Pair)

- Proof generation time: X ms
- Verification time: Y ms
- Proof size: Z bytes
- Constraint count: N

Comparison to standard Cantor:
- Standard computation: ~200 ns (negligible)
- ZK overhead: X ms (acceptable for PoC)
```

**Step 4: Commit**

```bash
git add tests/bench_zk_single_pair.py logs/
git commit -m "test(zk): add benchmarks for single pair proof"
```

---

## Session 9-15: Full Tree Implementation

### Task 5: Extend to Full Cantor Tree

**Objective:** Support ZK proofs for entire Cantor trees (not just single pairs)

**Files:**
- Modify: `src/cyberspace_core/zk_cantor.py` — add `prove_cantor_tree()` and `verify_cantor_tree()`
- Create: `tests/test_zk_cantor_tree.py`

**Step 1: Write failing test for tree proof**

```python
def test_prove_cantor_tree_height_3():
    """Test ZK proof for height-3 Cantor tree (8 leaves)."""
    leaves = [1, 2, 3, 4, 5, 6, 7, 8]
    
    # Compute expected root using standard Cantor
    from cyberspace_core.cantor import build_hyperspace_proof
    expected_root = build_hyperspace_proof(leaves)
    
    # Generate ZK proof
    root, proof = prove_cantor_tree(leaves)
    
    # Verify root matches
    assert root == expected_root
    
    # Verify ZK proof
    assert verify_cantor_tree(root, leaves, proof) is True
```

**Step 2: Implement tree AIR**

This requires extending the AIR to handle iterative tree construction. Implementation details depend on winterfell capabilities for iterative computations.

**Step 3: Verify test passes**

```bash
PYTHONPATH=src python3 -m pytest tests/test_zk_cantor_tree.py -v
```

**Step 4: Commit**

---

### Task 6: Integrate Temporal Seed

**Objective:** Add temporal seed to ZK proofs (per DECK-0001 §8)

**Files:**
- Modify: `src/cyberspace_core/zk_cantor.py` — add temporal seed handling
- Modify: `tests/test_zk_cantor_tree.py` — add temporal seed tests

**Step 1: Write test with temporal seed**

```python
def test_prove_with_temporal_seed():
    """Test ZK proof with temporal seed binding."""
    import os
    prev_event_id = os.urandom(32)
    
    from cyberspace_core.cantor import compute_temporal_seed
    temporal_seed = compute_temporal_seed(prev_event_id)
    
    path_heights = [1606, 1607]  # Example: 1-block hyperjump
    leaves = [temporal_seed] + path_heights
    
    # Generate and verify proof
    root, proof = prove_cantor_tree(leaves)
    assert verify_cantor_tree(root, leaves, proof) is True
```

**Step 2: Implement**

Ensure temporal seed is properly incorporated as first leaf in ZK proof.

**Step 3: Commit**

---

### Task 7: Add CLI verify-zk Command

**Objective:** Add `cyberspace verify-zk` command for fast verification

**Files:**
- Modify: `src/cyberspace_cli/cli.py` — add verify-zk subcommand
- Create: `tests/test_cli_verify_zk.py`

**Step 1: Write failing test**

```python
def test_verify_zk_command():
    """Test cyberspace verify-zk command."""
    # Create a test event with ZK proof
    # Run: cyberspace verify-zk <event_id>
    # Assert: "ZK proof valid (verified in Xms)"
```

**Step 2: Implement CLI command**

```python
@click.command()
@click.argument('event_id')
def verify_zk(event_id):
    """Verify ZK-STARK proof for a movement event (fast path)."""
    from cyberspace_core.zk_cantor import verify_cantor_tree_zk
    import time
    
    # Load event
    # Extract ZK proof
    # Verify
    # Print timing
```

**Step 3: Test manually**

```bash
cyberspace verify-zk <test_event_id>
```

**Step 4: Commit**

---

### Task 8: Performance Comparison

**Objective:** Benchmark ZK vs standard verification

**Files:**
- Create: `tests/bench_zk_vs_standard.py`

**Step 1: Write benchmark comparing both methods**

```python
def test_zk_vs_standard_verification(benchmark):
    """Compare ZK verification time vs standard Cantor verification."""
    # Standard: recompute full Cantor tree
    # ZK: verify STARK proof
    
    # Print comparison:
    # Standard: X ms
    # ZK: Y ms
    # Speedup: X/Y = Z×
```

**Step 2: Run and document**

```bash
PYTHONPATH=src python3 -m pytest tests/bench_zk_vs_standard.py -v --benchmark
```

**Step 3: Update design doc with real numbers**

Modify `ZK_STARK_DESIGN.md` §8 with actual benchmarks.

**Step 4: Commit**

---

## Session 16+: Integration & Testing

### Task 9: Add Feature Flag Configuration

**Objective:** Put ZK proofs behind feature flag

**Files:**
- Modify: `src/cyberspace_cli/config.py` — add zk_proofs config section
- Modify: `src/cyberspace_cli/cli.py` — check feature flag before using ZK

**Step 1: Add config structure**

```python
{
    "zk_proofs": {
        "enabled": False,
        "library": "winterfell",
        "publish_mode": "attached",
        "max_proof_size_kb": 100
    }
}
```

**Step 2: Add CLI commands for config**

```bash
cyberspace config set --zk-proofs true
cyberspace config show  # Should display ZK settings
```

**Step 3: Commit**

---

### Task 10: Property-Based Tests

**Objective:** Add hypothesis-based property tests for correctness

**Files:**
- Create: `tests/test_zk_cantor_properties.py`

**Step 1: Write property tests**

```python
from hypothesis import given, strategies as st

@given(st.integers(min_value=0, max_value=1000),
       st.integers(min_value=0, max_value=1000))
def test_zk_proof_soundness(x, y):
    """Property: ZK proof always verifies for correct computation."""
    z, proof = prove_single_cantor_pair(x, y)
    assert verify_single_cantor_pair(z, proof) is True

@given(st.integers(min_value=0, max_value=1000),
       st.integers(min_value=0, max_value=1000))
def test_zk_proof_rejects_wrong_result(x, y):
    """Property: ZK proof never verifies for wrong result."""
    z, proof = prove_single_cantor_pair(x, y)
    wrong_z = z + 1
    assert verify_single_cantor_pair(wrong_z, proof) is False
```

**Step 2: Run property tests**

```bash
PYTHONPATH=src python3 -m pytest tests/test_zk_cantor_properties.py -v
```

**Step 3: Commit**

---

### Task 11: Documentation Updates

**Objective:** Update README and docs with ZK proof usage

**Files:**
- Modify: `README.md` — add ZK proof commands
- Modify: `docs/` — add ZK proof documentation

**Step 1: Add to README**

```markdown
## ZK-STARK Proofs (Experimental)

Verify Cantor proofs in milliseconds using zero-knowledge proofs:

```bash
# Enable ZK proofs
cyberspace config set --zk-proofs true

# Move with ZK proof
cyberspace move --to x,y,z --zk-proof

# Fast verification
cyberspace verify-zk <event_id>
```
```

**Step 2: Add documentation page**

Create: `docs/zk-proofs.md` with user guide.

**Step 3: Commit**

```bash
git commit -m "docs: add ZK-STARK proof documentation"
```

---

### Task 12: Final Review and Cleanup

**Objective:** Ensure all tests pass, code is clean, ready for merge

**Step 1: Run full test suite**

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```

Expected: All tests pass

**Step 2: Run linter**

```bash
flake8 src/cyberspace_core/zk_cantor.py
```

**Step 3: Create pull request**

```bash
git push origin feature/zk-stark-proofs
# Create PR on GitHub
```

**Step 4: Update session log**

Add final session summary to `logs/zk-stark-YYYY-MM-DD.md`.

---

## Verification Checklist

Before marking work complete:

- [ ] Single Cantor pair proof works (prove + verify)
- [ ] Full Cantor tree proof works
- [ ] Temporal seed properly integrated
- [ ] `verify-zk` command implemented
- [ ] All existing tests still pass
- [ ] ZK feature behind flag
- [ ] Benchmarks show < 10ms verification
- [ ] Proof size < 100KB
- [ ] Documentation complete
- [ ] Property-based tests pass

---

*Plan created: 2026-04-17*  
*Based on: ZK_STARK_DESIGN.md v0.1*
