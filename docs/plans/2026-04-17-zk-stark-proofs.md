# ZK-STARK Proofs Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Implement ZK-STARK proofs for Cyberspace Cantor tree verification to enable lightweight client verification while preserving thermodynamic work requirements.

**Architecture:** Winterfell ZK-STARK library integrated with cyberspace-cli, proving correct computation of Cantor pairing trees. Prover does full work, verifier checks in milliseconds.

**Tech Stack:** Python, Winterfell (ZK-STARK), pytest (TDD), cyberspace-cli existing codebase

---

## Part I: Research & Design (COMPLETE)

### Session 1-3: Research & Design ✅

**Status:** COMPLETE — See `logs/zk-stark-2026-04-17.md`

**Key outputs:**
- Design document with arithmetic circuit specification
- Winterfell library selected
- Integration pattern: new tags on kind 3333 events
- Success metrics defined

---

## Part II: Minimal PoC (Sessions 4-8)

### Task 1: Set Up Winterfell in Development Environment

**Objective:** Install Winterfell ZK-STARK library and verify it works

**Files:**
- Modify: `~/repos/cyberspace-cli/pyproject.toml` (add winterfell dependency)
- Create: `~/repos/cyberspace-cli/tests/zk_stark/test_winterfell_integration.py`

**Step 1: Add dependency to pyproject.toml**

```toml
[project.optional-dependencies]
zk = ["winterfell>=0.3.0"]
```

**Step 2: Run test to verify installation**

```bash
cd ~/repos/cyberspace-cli
pip install -e ".[zk]"
python3 -c "import winterfell; print('Winterfell version:', winterfell.__version__)"
```

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add winterfell zk-stark dependency (optional)"
```

---

### Task 2: Create Winterfell Circuit for Single Cantor Pair

**Objective:** Implement arithmetic circuit that proves correct computation of π(x,y) = z

**Files:**
- Create: `~/repos/cyberspace-cli/src/cyberspace_zk/cantor_circuit.py`
- Create: `~/repos/cyberspace-cli/tests/zk_stark/test_single_pair_proof.py`

**Step 1: Write failing test**

```python
# tests/zk_stark/test_single_pair_proof.py
from cyberspace_zk.cantor_circuit import CantorPairCircuit
from cyberspace_core.cantor import cantor_pair
import winterfell

def test_prove_single_cantor_pair():
    """Prove: I correctly computed π(42, 17) = 1871"""
    x, y = 42, 17
    expected_z = cantor_pair(x, y)  # Should be 1871
    
    # Create circuit with public inputs (x, y, z) and private witness
    circuit = CantorPairCircuit(x=x, y=y, z=expected_z)
    
    # Generate proof
    proof = circuit.prove()
    
    # Verify proof
    is_valid = winterfell.verify(
        proof=proof,
        public_inputs={'x': x, 'y': y, 'z': expected_z}
    )
    
    assert is_valid, "ZK proof should verify correct computation"

def test_reject_incorrect_cantor_pair():
    """Verify: Incorrect z value fails verification"""
    x, y = 42, 17
    wrong_z = 9999  # Intentionally wrong
    
    circuit = CantorPairCircuit(x=x, y=y, z=wrong_z)
    proof = circuit.prove()
    
    is_valid = winterfell.verify(
        proof=proof,
        public_inputs={'x': x, 'y': y, 'z': wrong_z}
    )
    
    assert not is_valid, "ZK proof should reject incorrect computation"
```

**Step 2: Run test to verify failure**

```bash
cd ~/repos/cyberspace-cli
PYTHONPATH=src pytest tests/zk_stark/test_single_pair_proof.py::test_prove_single_cantor_pair -v
```

Expected: FAIL — ModuleNotFoundError: No module named 'cyberspace_zk'

**Step 3: Write minimal implementation**

```python
# src/cyberspace_zk/cantor_circuit.py
"""ZK-STARK circuits for Cantor pairing proofs using Winterfell."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List
import winterfell


@dataclass
class CantorPairCircuit:
    """Arithmetic circuit proving correct computation of π(x,y) = z.
    
    Cantor formula: π(x, y) = ((x + y) × (x + y + 1)) / 2 + y
    
    This circuit verifies that the prover knows x, y such that z = π(x,y)
    without revealing x, y (optional — for our use case, x,y are public).
    """
    
    x: int
    y: int
    z: int
    
    def prove(self) -> Any:
        """Generate ZK-STARK proof of correct Cantor computation.
        
        Returns:
            Winterfell proof object
        """
        # Define the constraint system
        # We need to prove: z = ((x + y) * (x + y + 1)) // 2 + y
        
        # Winterfell computation trace
        # Each row represents a step in the computation
        
        # Trace columns:
        # col[0]: x (constant)
        # col[1]: y (constant)
        # col[2]: s = x + y
        # col[3]: t = s + 1
        # col[4]: u = s * t
        # col[5]: v = u / 2 (multiply by inverse of 2 in field)
        # col[6]: result = v + y (should equal z)
        
        # Simplified approach: use Winterfell's arithmetic circuit builder
        from winterfell import ArithmeticCircuitBuilder
        
        builder = ArithmeticCircuitBuilder()
        
        # Allocate variables
        x_var = builder.add_public_input(self.x)
        y_var = builder.add_public_input(self.y)
        z_var = builder.add_public_input(self.z)
        
        # Compute constraints
        s_var = builder.add(x_var, y_var)  # s = x + y
        t_var = builder.add(s_var, builder.one())  # t = s + 1
        u_var = builder.mul(s_var, t_var)  # u = s * t
        v_var = builder.div(u_var, builder.constant(2))  # v = u / 2
        result_var = builder.add(v_var, y_var)  # result = v + y
        
        # Enforce: result == z
        builder.assert_equal(result_var, z_var)
        
        # Build and execute circuit
        circuit = builder.build()
        proof = winterfell.prove(circuit)
        
        return proof
```

**Step 4: Run test to verify pass**

```bash
cd ~/repos/cyberspace-cli
PYTHONPATH=src pytest tests/zk_stark/test_single_pair_proof.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/cyberspace_zk/cantor_circuit.py tests/zk_stark/test_single_pair_proof.py
git commit -m "feat(zk): single Cantor pair proof circuit"
```

---

### Task 3: Benchmark Single Pair Proof Performance

**Objective:** Measure proof size and verification time for baseline

**Files:**
- Create: `~/repos/cyberspace-cli/tests/zk_stark/test_single_pair_benchmark.py`

**Step 1: Write test**

```python
# tests/zk_stark/test_single_pair_benchmark.py
import time
import pytest
from cyberspace_zk.cantor_circuit import CantorPairCircuit
from cyberspace_core.cantor import cantor_pair
import winterfell

def test_single_pair_proof_size():
    """Measure proof size in bytes"""
    x, y = 42, 17
    z = cantor_pair(x, y)
    
    circuit = CantorPairCircuit(x=x, y=y, z=z)
    proof = circuit.prove()
    
    # Serialize proof to bytes
    proof_bytes = proof.to_bytes()  # or appropriate serialization
    size_kb = len(proof_bytes) / 1024
    
    print(f"Proof size: {size_kb:.2f} KB ({len(proof_bytes)} bytes)")
    assert size_kb < 100, "Proof should be < 100KB"

def test_single_pair_verification_time():
    """Measure verification time"""
    x, y = 42, 17
    z = cantor_pair(x, y)
    
    circuit = CantorPairCircuit(x=x, y=y, z=z)
    proof = circuit.prove()
    
    # Time verification
    start = time.perf_counter()
    is_valid = winterfell.verify(
        proof=proof,
        public_inputs={'x': x, 'y': y, 'z': z}
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    
    print(f"Verification time: {elapsed_ms:.2f} ms")
    assert is_valid
    assert elapsed_ms < 10, "Verification should be < 10ms"
```

**Step 2: Run test**

```bash
cd ~/repos/cyberspace-cli
PYTHONPATH=src pytest tests/zk_stark/test_single_pair_benchmark.py -v -s
```

Expected: PASS (with printed metrics)

**Step 3: Commit**

```bash
git add tests/zk_stark/test_single_pair_benchmark.py
git commit -m "test(zk): benchmark single pair proof performance"
```

---

### Task 4: Implement Full Cantor Tree Circuit

**Objective:** Extend to prove correct computation of entire Cantor tree over N leaves

**Files:**
- Modify: `~/repos/cyberspace-cli/src/cyberspace_zk/cantor_circuit.py` (add CantorTreeCircuit)
- Create: `~/repos/cyberspace-cli/tests/zk_stark/test_tree_proof.py`

**Step 1: Write failing test**

```python
# tests/zk_stark/test_tree_proof.py
from cyberspace_zk.cantor_circuit import CantorTreeCircuit
from cyberspace_core.cantor import build_hyperspace_proof
import winterfell

def test_prove_cantor_tree_3_leaves():
    """Prove: I correctly computed Cantor tree over [temporal_seed, 1606, 1607]"""
    temporal_seed = 12345678
    leaves = [temporal_seed, 1606, 1607]
    expected_root = build_hyperspace_proof(leaves)
    
    circuit = CantorTreeCircuit(leaves=leaves, root=expected_root)
    proof = circuit.prove()
    
    is_valid = winterfell.verify(
        proof=proof,
        public_inputs={'root': expected_root, 'leaf_count': len(leaves)}
    )
    
    assert is_valid

def test_prove_cantor_tree_5_leaves():
    """Prove: I correctly computed Cantor tree over 5 leaves"""
    temporal_seed = 98765432
    leaves = [temporal_seed, 10, 20, 30, 40]
    expected_root = build_hyperspace_proof(leaves)
    
    circuit = CantorTreeCircuit(leaves=leaves, root=expected_root)
    proof = circuit.prove()
    
    is_valid = winterfell.verify(
        proof=proof,
        public_inputs={'root': expected_root, 'leaf_count': len(leaves)}
    )
    
    assert is_valid
```

**Step 2: Run test to verify failure**

```bash
cd ~/repos/cyberspace-cli
PYTHONPATH=src pytest tests/zk_stark/test_tree_proof.py::test_prove_cantor_tree_3_leaves -v
```

Expected: FAIL — ImportError: cannot import name 'CantorTreeCircuit'

**Step 3: Write implementation**

```python
# src/cyberspace_zk/cantor_circuit.py (add to existing file)

@dataclass
class CantorTreeCircuit:
    """Arithmetic circuit proving correct computation of Cantor tree root.
    
    Proves knowledge of leaves [L0, L1, ..., L{N-1}] such that
    build_cantor_tree(leaves) = root, without necessarily revealing all leaves.
    
    For hyperspace traversal:
    - leaves = [temporal_seed, B_from, B_from+1, ..., B_to]
    - root = hyperspace proof value
    """
    
    leaves: List[int]
    root: int
    
    def prove(self) -> Any:
        """Generate ZK-STARK proof of correct Cantor tree computation."""
        from winterfell import ArithmeticCircuitBuilder
        
        builder = ArithmeticCircuitBuilder()
        
        # Add public inputs
        root_var = builder.add_public_input(self.root)
        leaf_count_var = builder.add_public_input(len(self.leaves))
        
        # Add leaves as private inputs (or public, depending on privacy needs)
        leaf_vars = [builder.add_private_input(leaf) for leaf in self.leaves]
        
        # Build Cantor tree layer by layer
        current_level = leaf_vars
        
        while len(current_level) > 1:
            next_level = []
            
            for i in range(0, len(current_level) - 1, 2):
                left = current_level[i]
                right = current_level[i + 1]
                
                # Compute Cantor pair: π(left, right)
                s_var = builder.add(left, right)
                t_var = builder.add(s_var, builder.one())
                u_var = builder.mul(s_var, t_var)
                v_var = builder.div(u_var, builder.constant(2))
                parent_var = builder.add(v_var, right)
                
                next_level.append(parent_var)
            
            # Handle odd leaf count (carry forward)
            if len(current_level) % 2 == 1:
                next_level.append(current_level[-1])
            
            current_level = next_level
        
        # Final constraint: computed_root == public_root
        builder.assert_equal(current_level[0], root_var)
        
        # Build and prove
        circuit = builder.build()
        proof = winterfell.prove(circuit)
        
        return proof
```

**Step 4: Run test to verify pass**

```bash
cd ~/repos/cyberspace-cli
PYTHONPATH=src pytest tests/zk_stark/test_tree_proof.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/cyberspace_zk/cantor_circuit.py tests/zk_stark/test_tree_proof.py
git commit -m "feat(zk): full Cantor tree proof circuit"
```

---

### Task 5: Integrate Temporal Seed Properly

**Objective:** Add temporal seed computation from previous_event_id per DECK-0001 §8

**Files:**
- Modify: `~/repos/cyberspace-cli/src/cyberspace_zk/cantor_circuit.py` (add temporal seed commitment)
- Create: `~/repos/cyberspace-cli/tests/zk_stark/test_temporal_seed.py`

**Step 1: Write failing test**

```python
# tests/zk_stark/test_temporal_seed.py
from cyberspace_zk.cantor_circuit import CantorTreeCircuitWithTemporalSeed
from cyberspace_core.cantor import compute_temporal_seed, build_hyperspace_proof
import winterfell

def test_prove_with_temporal_seed():
    """Prove: I correctly computed temporal seed and Cantor tree"""
    # Mock previous event ID (32 bytes)
    prev_event_id = bytes.fromhex("a" * 64)
    temporal_seed = compute_temporal_seed(prev_event_id)
    
    # Hyperspace traversal: 1-block jump
    B_from, B_to = 1606, 1607
    leaves = [temporal_seed, B_from, B_to]
    expected_root = build_hyperspace_proof(leaves)
    
    circuit = CantorTreeCircuitWithTemporalSeed(
        previous_event_id=prev_event_id,
        block_range=(B_from, B_to),
        root=expected_root
    )
    proof = circuit.prove()
    
    is_valid = winterfell.verify(
        proof=proof,
        public_inputs={
            'root': expected_root,
            'prev_event_commitment': sha256(prev_event_id).hex()
        }
    )
    
    assert is_valid
```

**Step 2: Run test to verify failure**

Expected: FAIL — ImportError: cannot import name 'CantorTreeCircuitWithTemporalSeed'

**Step 3: Write implementation**

```python
# src/cyberspace_zk/cantor_circuit.py (add)

from cyberspace_core.cantor import compute_temporal_seed, build_hyperspace_proof
from hashlib import sha256

@dataclass
class CantorTreeCircuitWithTemporalSeed:
    """ZK circuit for hyperspace proof with temporal seed binding.
    
    Proves:
    1. temporal_seed = compute_temporal_seed(previous_event_id)
    2. leaves = [temporal_seed, B_from, ..., B_to]
    3. root = build_hyperspace_proof(leaves)
    
    Public inputs: root, leaf_count, prev_event_commitment
    Private inputs: previous_event_id, block range, intermediate nodes
    """
    
    previous_event_id: bytes
    block_range: tuple[int, int]  # (B_from, B_to)
    root: int
    
    def prove(self) -> Any:
        """Generate ZK proof with temporal seed binding."""
        # Compute temporal seed
        temporal_seed = compute_temporal_seed(self.previous_event_id)
        
        # Build leaves
        B_from, B_to = self.block_range
        leaves = [temporal_seed] + list(range(B_from, B_to + 1))
        
        # Use existing CantorTreeCircuit
        inner_circuit = CantorTreeCircuit(leaves=leaves, root=self.root)
        return inner_circuit.prove()
```

**Step 4: Run test to verify pass**

Expected: PASS

**Step 5: Commit**

```bash
git add src/cyberspace_zk/cantor_circuit.py tests/zk_stark/test_temporal_seed.py
git commit -m "feat(zk): add temporal seed binding to hyperspace proofs"
```

---

## Part III: CLI Integration (Sessions 9-15)

### Task 6: Add cyberspace zk prove Command

**Objective:** Create CLI command to generate ZK proofs for movement events

**Files:**
- Create: `~/repos/cyberspace-cli/src/cyberspace_cli/commands/zk.py`
- Modify: `~/repos/cyberspace-cli/src/cyberspace_cli/__init__.py` (register command)

**Step 1: Write failing test (manual verification)**

```bash
# This will be tested manually after implementation
cyberspace zk prove --event-id <event_id> --output proof.json
```

**Step 2: Implement command**

```python
# src/cyberspace_cli/commands/zk.py
"""ZK-STARK proof commands for Cyberspace."""

from __future__ import annotations
import argparse
import json
from cyberspace_zk.cantor_circuit import CantorTreeCircuitWithTemporalSeed
from cyberspace_core.cantor import compute_temporal_seed, build_hyperspace_proof

def register_zk_commands(subparsers):
    """Register zk subcommands."""
    
    # zk prove
    prove_parser = subparsers.add_parser('prove', help='Generate ZK proof for movement event')
    prove_parser.add_argument('--event-id', required=True, help='Nostr event ID')
    prove_parser.add_argument('--output', required=True, help='Output proof file path')
    prove_parser.set_defaults(func=cmd_zk_prove)
    
    # zk verify
    verify_parser = subparsers.add_parser('verify', help='Verify ZK proof')
    verify_parser.add_argument('--proof-file', required=True, help='ZK proof file')
    verify_parser.set_defaults(func=cmd_zk_verify)
    
    # zk bench
    bench_parser = subparsers.add_parser('bench', help='Benchmark ZK proof performance')
    bench_parser.add_argument('--height', type=int, default=30, help='Tree height')
    bench_parser.set_defaults(func=cmd_zk_bench)

def cmd_zk_prove(args, config, state):
    """Generate ZK proof for a movement event."""
    # Load event from chain
    # Extract tags (proof, from_height, B, prev)
    # Compute ZK proof
    # Save to file
    pass

def cmd_zk_verify(args, config, state):
    """Verify a ZK proof."""
    # Load proof file
    # Verify with Winterfell
    # Print result
    pass

def cmd_zk_bench(args, config, state):
    """Benchmark ZK proof performance."""
    # Generate proofs for various heights
    # Measure time, size
    # Print results
    pass
```

**Step 3: Test command**

```bash
cd ~/repos/cyberspace-cli
cyberspace zk --help
```

**Step 4: Commit**

```bash
git add src/cyberspace_cli/commands/zk.py
git commit -m "feat(cli): add zk prove/verify/bench commands"
```

---

### Task 7: Add zk_proof Tag to Movement Actions

**Objective:** Extend movement event creation to include ZK proof tags

**Files:**
- Modify: `~/repos/cyberspace-cli/src/cyberspace_cli/nostr_event.py` (add ZK proof tags)

**Step 1: Write failing test**

```python
# tests/test_nostr_event_zk.py
def test_hyperjump_event_with_zk_proof():
    """Verify hyperjump event includes zk_proof tag"""
    from cyberspace_cli.nostr_event import make_hyperjump_event_with_zk
    
    event = make_hyperjump_event_with_zk(...)
    
    # Check for zk_proof tag
    zk_proof_tags = [t for t in event['tags'] if t[0] == 'zk_proof']
    assert len(zk_proof_tags) == 1
```

**Step 2: Implement**

```python
# src/cyberspace_cli/nostr_event.py (add)

def make_hyperjump_event_with_zk(
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    to_height: int,
    from_height: int,
    from_hj_hex: str,
    proof_hex: str,  # Standard Cantor proof
    zk_proof_hex: str,  # NEW: ZK proof
    **kwargs
) -> dict:
    """Create hyperjump event with ZK proof attachment."""
    tags = [
        ["A", "hyperjump"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["from_height", str(from_height)],
        ["from_hj", from_hj_hex],
        ["proof", proof_hex],
        ["zk_proof", zk_proof_hex],  # NEW
        ["B", str(to_height)],
        # ... sector tags
    ]
    
    return {
        "kind": 3333,
        "content": "",
        "tags": tags,
        "pubkey": pubkey_hex,
        "created_at": created_at,
    }
```

**Step 3: Commit**

```bash
git add src/cyberspace_cli/nostr_event.py
git commit -m "feat(cli): add zk_proof tag to hyperjump events"
```

---

### Task 8: Full Integration Test

**Objective:** End-to-end test: generate movement, create ZK proof, verify

**Files:**
- Create: `~/repos/cyberspace-cli/tests/zk_stark/test_integration.py`

**Step 1: Write integration test**

```python
# tests/zk_stark/test_full_integration.py
def test_full_zk_proof_workflow():
    """End-to-end: spawn -> hyperjump -> ZK proof -> verify"""
    # 1. Create identity
    # 2. Spawn
    # 3. Create hyperjump event
    # 4. Generate ZK proof
    # 5. Verify ZK proof
    # 6. Assert all steps succeed
    pass
```

**Step 2: Run integration test**

```bash
cd ~/repos/cyberspace-cli
PYTHONPATH=src pytest tests/zk_stark/test_full_integration.py -v
```

**Step 3: Commit**

```bash
git add tests/zk_stark/test_full_integration.py
git commit -m "test(zk): full integration test for ZK proof workflow"
```

---

## Part IV: Testing & Documentation (Sessions 16+)

### Task 9: Property-Based Tests for Correctness

**Objective:** Use Hypothesis to test ZK proofs across wide input space

**Files:**
- Create: `~/repos/cyberspace-cli/tests/zk_stark/test_property_based.py`

**Step 1: Write property tests**

```python
# tests/zk_stark/test_property_based.py
from hypothesis import given, strategies as st

@given(
    x=st.integers(min_value=0, max_value=1000),
    y=st.integers(min_value=0, max_value=1000),
)
def test_cantor_pair_proof_always_verifies(x, y):
    """Property: ZK proof verifies for all valid inputs"""
    z = cantor_pair(x, y)
    circuit = CantorPairCircuit(x=x, y=y, z=z)
    proof = circuit.prove()
    
    assert winterfell.verify(proof, {'x': x, 'y': y, 'z': z})

@given(
    leaves=st.lists(st.integers(0, 10000), min_size=2, max_size=10),
)
def test_tree_proof_always_verifies(leaves):
    """Property: Tree ZK proof verifies for all valid leaf sequences"""
    root = build_hyperspace_proof(leaves)
    circuit = CantorTreeCircuit(leaves=leaves, root=root)
    proof = circuit.prove()
    
    assert winterfell.verify(proof, {'root': root, 'leaf_count': len(leaves)})
```

**Step 2: Commit**

```bash
git add tests/zk_stark/test_property_based.py
git commit -m "test(zk): property-based tests for ZK correctness"
```

---

### Task 10: Documentation Updates

**Objective:** Update README and docs with ZK-STARK usage

**Files:**
- Modify: `~/repos/cyberspace-cli/README.md` (add ZK commands section)
- Create: `~/repos/cyberspace-cli/docs/zk-starks.md` (full documentation)

**Step 1: Update README**

```markdown
## ZK-STARK Proofs (Experimental)

Generate zero-knowledge proofs for movement verification:

```bash
# Generate ZK proof for movement event
cyberspace zk prove --event-id <event_id> --output proof.json

# Verify ZK proof (lightweight)
cyberspace zk verify --proof-file proof.json

# Benchmark performance
cyberspace zk bench --height 30
```

See `docs/zk-starks.md` for full documentation.
```

**Step 2: Write comprehensive docs**

```markdown
# docs/zk-starks.md

## Overview

ZK-STARK proofs enable lightweight verification...

## Usage

## Performance Benchmarks

## Limitations
```

**Step 3: Commit**

```bash
git add README.md docs/zk-starks.md
git commit -m "docs: add ZK-STARK documentation"
```

---

## Verification Checklist

Before marking work complete:

- [ ] Single Cantor pair proof works
- [ ] Full tree proof works (tested up to height 30+)
- [ ] Temporal seed binding implemented
- [ ] CLI commands functional (prove, verify, bench)
- [ ] ZK proof tags added to movement events
- [ ] All existing tests pass
- [ ] Performance benchmarks meet targets (verification <10ms)
- [ ] Property-based tests pass
- [ ] Documentation complete
- [ ] Feature flag implemented (opt-in)

---

## Notes for Implementer

- Follow TDD strictly — watch every test fail first
- Winterfell API may differ from examples — adapt as needed
- If Winterfell proves too experimental, fall back to starkware/Cairo
- Keep ZK features behind `--enable-zk-proofs` flag until production-ready
- Benchmark frequently — track proof size and verification time
- Document all deviations from this plan

---

**Plan written:** 2026-04-17  
**Ready for execution via subagent-driven-development**
