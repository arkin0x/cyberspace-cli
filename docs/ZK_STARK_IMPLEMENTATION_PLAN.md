# ZK-STARK Proofs for Cyberspace - Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Integrate ZK-STARK proofs into cyberspace-cli for fast Cantor tree verification while preserving work equivalence.

**Architecture:** Mock ZK proof system with production-ready interfaces. Circuit arithmetization complete. Phase 2 will integrate actual STARK backend (plonky3 or cairo-lang).

**Tech Stack:** Python 3.10+, existing cyberspace-core, mock STARK backend (to be replaced with plonky3/cairo-lang in Phase 2)

---

### Task 1: Run existing benchmarks and document baseline performance

**Objective:** Measure current circuit execution performance for various tree heights.

**Files:**
- Execute: `scripts/benchmark_zk_circuit.py`
- Log: `logs/zk-stark-2026-04-18-baseline.md`

**Step 1: Run benchmark script**

```bash
cd ~/repos/cyberspace-cli
python scripts/benchmark_zk_circuit.py
```

**Step 2: Capture output and write baseline log**

Expected output format:
```
Height | Leaves      | Constraints     | Time (ms) | M Constraints/s
     5 |         32 |             155 |       0.08 |            1.90
    10 |      1,024 |           5,115 |       2.23 |            2.30
    15 |     32,768 |         163,835 |      81.28 |            2.02
    20 |  1,048,576 |       5,242,875 |    3,387.00 |            1.55
```

**Step 3: Commit**

```bash
git add logs/zk-stark-2026-04-18-baseline.md
git commit -m "docs: add ZK-STARK baseline performance measurements"
```

---

### Task 2: Extend zk_cantor tests to cover full treeproofs

**Objective:** Ensure comprehensive test coverage for `prove_cantor_tree()` and `verify_cantor_tree()`.

**Files:**
- Modify: `tests/test_zk_cantor.py:1-50`
- Test: `tests/test_zk_cantor.py`

**Step 1: Add tests for hyperspace traversal pattern**

```python
def test_hyperspace_traversal_proof_single_block():
    """Test hyperjump proof for single-block traversal"""
    import os
    prev_id = os.urandom(32)
    from_height, to_height = 1606, 1607
    
    root, proof = prove_hyperspace_traversal(prev_id, from_height, to_height)
    
    assert proof.leaf_count == 3  # temporal_seed + 2 block heights
    assert verify_hyperspace_traversal(root, prev_id, from_height, to_height, proof)
```

**Step 2: Add test for multi-block traversal**

```python
def test_hyperspace_traversal_proof_multi_block():
    """Test hyperjump proof for 10-block traversal"""
    import os
    prev_id = os.urandom(32)
    from_height, to_height = 850000, 850010
    
    root, proof = prove_hyperspace_traversal(prev_id, from_height, to_height)
    
    assert proof.leaf_count == 12  # temporal_seed + 11 block heights
    assert verify_hyperspace_traversal(root, prev_id, from_height, to_height, proof)
```

**Step 3: Run tests**

```bash
cd ~/repos/cyberspace-cli
python -m pytest tests/test_zk_cantor.py -v
```

Expected: All tests pass (existing + new)

**Step 4: Commit**

```bash
git add tests/test_zk_cantor.py
git commit -m "test: add hyperspace traversal ZK proof tests"
```

---

### Task 3: Create cyberspace verify-zk CLI command skeleton

**Objective:** Add CLI command for standalone ZK proof verification.

**Files:**
- Create: `src/cyberspace_cli/commands/verify_zk.py`
- Modify: `src/cyberspace_cli/cli.py` (add command registration)

**Step 1: Create verify_zk command module**

```python
"""Verify ZK-STARK proofs for Cantor tree computations."""

import typer
import json
from pathlib import Path

from cyberspace_core.zk_cantor import verify_cantor_tree, verify_hyperspace_traversal


app = typer.Typer()


@app.command()
def cantor(
    event_file: str = typer.Option(..., "--event", help="Nostr event JSON file"),
    proof_file: str = typer.Option(..., "--proof", help="ZK proof JSON file"),
):
    """Verify ZK proof for a Cantor tree movement."""
    event_path = Path(event_file)
    proof_path = Path(proof_file)
    
    if not event_path.exists():
        typer.echo(f"Error: Event file not found: {event_file}")
        raise typer.Exit(1)
    
    if not proof_path.exists():
        typer.echo(f"Error: Proof file not found: {proof_file}")
        raise typer.Exit(1)
    
    with open(event_path) as f:
        event = json.load(f)
    
    with open(proof_path) as f:
        proof_data = json.load(f)
    
    # Extract leaves from event (would be in tags)
    leaves = event.get('tags', {}).get('zk-leaves', [])
    root = int(event.get('tags', {}).get('proof', '0'), 16)
    
    # Convert proof data back to ZKCantorProof
    from cyberspace_core.zk_cantor import ZKCantorProof
    proof = ZKCantorProof(
        root=root,
        leaf_count=proof_data['leaf_count'],
        stark_proof=bytes.fromhex(proof_data['stark_proof']),
        constraint_count=proof_data['constraint_count'],
    )
    
    if verify_cantor_tree(root, leaves, proof):
        typer.echo("✓ ZK proof is valid")
        raise typer.Exit(0)
    else:
        typer.echo("✗ ZK proof is invalid")
        raise typer.Exit(1)


@app.command()
def hyperjump(
    event_file: str = typer.Option(..., "--event", help="Nostr event JSON file"),
    proof_file: str = typer.Option(..., "--proof", help="ZK proof JSON file"),
):
    """Verify ZK proof for a hyperspace traversal."""
    event_path = Path(event_file)
    proof_path = Path(proof_file)
    
    if not event_path.exists():
        typer.echo(f"Error: Event file not found: {event_file}")
        raise typer.Exit(1)
    
    if not proof_path.exists():
        typer.echo(f"Error: Proof file not found: {proof_file}")
        raise typer.Exit(1)
    
    with open(event_path) as f:
        event = json.load(f)
    
    with open(proof_path) as f:
        proof_data = json.load(f)
    
    # Extract hyperjump parameters
    from_height = int(event.get('tags', {}).get('from_height', '0'))
    to_height = int(event.get('tags', {}).get('B', '0'))
    prev_event_id = bytes.fromhex(event.get('tags', {}).get('prev', ''))
    root = int(event.get('tags', {}).get('proof', '0'), 16)
    
    from cyberspace_core.zk_cantor import ZKCantorProof
    proof = ZKCantorProof(
        root=root,
        leaf_count=proof_data['leaf_count'],
        stark_proof=bytes.fromhex(proof_data['stark_proof']),
        constraint_count=proof_data['constraint_count'],
    )
    
    if verify_hyperspace_traversal(root, prev_event_id, from_height, to_height, proof):
        typer.echo("✓ Hyperspace ZK proof is valid")
        raise typer.Exit(0)
    else:
        typer.echo("✗ Hyperspace ZK proof is invalid")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
```

**Step 2: Register command in main CLI**

In `src/cyberspace_cli/cli.py`, add:

```python
from cyberspace_cli.commands import verify_zk

# ... add to main app ...
app.add_typer(verify_zk.app, name="verify-zk")
```

**Step 3: Test command**

```bash
cd ~/repos/cyberspace-cli
cyberspace verify-zk --help
```

Expected: Shows cantor and hyperjump subcommands

**Step 4: Commit**

```bash
git add src/cyberspace_cli/commands/verify_zk.py src/cyberspace_cli/cli.py
git commit -m "feat: add cyberspace verify-zk command skeleton"
```

---

### Task 4: Add ZK proof generation to hyperjump action builder

**Objective:** Extend hyperjump event creation to optionally include ZK proof tags.

**Files:**
- Modify: `src/cyberspace_cli/nostr_event.py` (add ZK proof generation)
- Test: `tests/test_hyperjump_updated.py`

**Step 1: Add make_hyperjump_event_zk function**

```python
def make_hyperjump_event_zk(
    pubkey_hex: str,
    created_at: int,
    genesis_event_id: str,
    previous_event_id: str,
    prev_coord_hex: str,
    coord_hex: str,
    to_height: int,
    from_height: int,
    from_hj_hex: str,
    prove_zk: bool = False,
) -> dict:
    """Create hyperjump event with optional ZK proof.
    
    If prove_zk=True, includes ZK proof tags for fast verification.
    """
    from cyberspace_core.cantor import compute_temporal_seed, build_hyperspace_proof
    from cyberspace_core.zk_cantor import prove_hyperspace_traversal
    
    # Compute temporal seed and Cantor proof
    prev_id_bytes = bytes.fromhex(previous_event_id)
    temporal_seed = compute_temporal_seed(prev_id_bytes)
    leaves = [temporal_seed, from_height] + list(range(from_height, to_height + 1))
    cantor_root = build_hyperspace_proof(leaves)
    
    # Build base tags
    tags = [
        ["A", "hyperjump"],
        ["e", genesis_event_id, "", "genesis"],
        ["e", previous_event_id, "", "previous"],
        ["c", prev_coord_hex],
        ["C", coord_hex],
        ["B", str(to_height)],
        ["from_height", str(from_height)],
        ["from_hj", from_hj_hex],
        ["proof", format(cantor_root, 'x')],  # Standard Cantor root
    ]
    
    # Optionally add ZK proof
    if prove_zk:
        zk_root, zk_proof = prove_hyperspace_traversal(
            prev_id_bytes, from_height, to_height
        )
        
        # Add ZK proof tags
        tags.extend([
            ["zk", "1"],  # ZK proof present flag
            ["zk-proof", zk_proof.stark_proof.hex()],
            ["zk-root", format(zk_proof.root, 'x')],
            ["zk-leaves", str(zk_proof.leaf_count)],
        ])
    
    return {
        "kind": 3333,
        "content": "",
        "tags": tags,
        "pubkey": pubkey_hex,
        "created_at": created_at,
    }
```

**Step 2: Test ZK tag generation**

```python
def test_hyperjump_with_zk_tags():
    """Test hyperjump event includes ZK tags when requested"""
    event = make_hyperjump_event_zk(
        pubkey_hex="test",
        created_at=123456,
        genesis_event_id="genesis",
        previous_event_id="0" * 64,
        prev_coord_hex="abc123",
        coord_hex="def456",
        to_height=1607,
        from_height=1606,
        from_hj_hex="merkle_root_hex",
        prove_zk=True,
    )
    
    # Check standard tags
    assert any(t[0] == "proof" for t in event["tags"])
    
    # Check ZK tags
    assert any(t[0] == "zk" and t[1] == "1" for t in event["tags"])
    assert any(t[0] == "zk-proof" for t in event["tags"])
    assert any(t[0] == "zk-root" for t in event["tags"])
```

**Step 3: Run tests**

```bash
cd ~/repos/cyberspace-cli
python -m pytest tests/test_hyperjump_updated.py::test_hyperjump_with_zk_tags -v
```

**Step 4: Commit**

```bash
git add src/cyberspace_cli/nostr_event.py tests/test_hyperjump_updated.py
git commit -m "feat: add ZK proof generation to hyperjump events"
```

---

### Task 5: Add feature flag configuration for ZK proofs

**Objective:** Enable/disable ZK proof generation via config.

**Files:**
- Modify: `src/cyberspace_cli/config.py` (add ZK config options)
- Modify: `src/cyberspace_cli/cli.py` (add config commands)

**Step 1: Add ZK config fields**

```python
@dataclass
class CyberspaceConfig:
    # ... existing fields ...
    zk_stark_enabled: bool = False
    zk_verify_incoming: bool = False
    zk_backend: str = "mock"  # "mock" | "plonky3" | "cairo"
```

**Step 2: Add config commands**

```bash
cyberspace config set --zk-stark-enabled true
cyberspace config set --zk-verify-incoming true
cyberspace config show
```

**Step 3: Test config persistence**

```bash
cyberspace config set --zk-stark-enabled true
cyberspace config show | grep zk
# Should show: zk_stark_enabled: true
```

**Step 4: Commit**

```bash
git add src/cyberspace_cli/config.py
git commit -m "feat: add ZK proof configuration flags"
```

---

### Task 6: Write integration test for complete ZK workflow

**Objective:** End-to-end test: spawn → move → hyperjump with ZK → verify.

**Files:**
- Create: `tests/test_zk_integration.py`

**Step 1: Create integration test**

```python
"""Integration test for ZK-STARK proof workflow."""

import unittest
import os
from pathlib import Path

from cyberspace_cli.cli import app
from cyberspace_core.zk_cantor import (
    prove_hyperspace_traversal,
    verify_hyperspace_traversal,
)
from Cyberspace_cli.nostr_event import make_hyperjump_event_zk


class TestZKIntegration(unittest.TestCase):
    def test_complete_hyperjump_zk_workflow(self):
        """Test full hyperjump with ZK proof generation and verification"""
        # Generate proof
        prev_id = os.urandom(32)
        root, proof = prove_hyperspace_traversal(prev_id, 1606, 1607)
        
        # Create event with ZK tags
        event = make_hyperjump_event_zk(
            pubkey_hex="test_pubkey",
            created_at=123456,
            genesis_event_id="genesis",
            previous_event_id=prev_id.hex(),
            prev_coord_hex="c0ffee",
            coord_hex="deadbeef",
            to_height=1607,
            from_height=1606,
            from_hj_hex="merkle_hex",
            prove_zk=True,
        )
        
        # Extract proof from event
        zk_proof_hex = None
        for tag in event["tags"]:
            if tag[0] == "zk-proof":
                zk_proof_hex = tag[1]
                break
        
        self.assertIsNotNone(zk_proof_hex)
        
        # Verify proof
        from cyberspace_core.zk_cantor import ZKCantorProof
        reconstructed_proof = ZKCantorProof(
            root=root,
            leaf_count=proof.leaf_count,
            stark_proof=bytes.fromhex(zk_proof_hex),
            constraint_count=proof.constraint_count,
        )
        
        self.assertTrue(verify_hyperspace_traversal(
            root, prev_id, 1606, 1607, reconstructed_proof
        ))
```

**Step 2: Run integration test**

```bash
cd ~/repos/cyberspace-cli
python -m pytest tests/test_zk_integration.py -v
```

**Step 3: Commit**

```bash
git add tests/test_zk_integration.py
git commit -m "test: add ZK-STARK integration test"
```

---

### Task 7: Update ZK_STARK_DESIGN.md with implementation status

**Objective:** Document current implementation state and next steps.

**Files:**
- Modify: `docs/ZK_STARK_DESIGN.md` (add implementation status section)

**Step 1: Add implementation status**

```markdown
## 16. Implementation Status (2026-04-18)

### Phase 1 Complete: Arithmetic Circuit & Mock Backend ✅

**Completed:**
- ✅ Arithmetic circuit design (5 constraints per Cantor pair)
- ✅ Circuit execution trace generation `zk_stark/circuit.py`
- ✅ Mock ZK proof system `zk_cantor.py`
- ✅ Test suite (14 passing tests)
- ✅ Benchmark infrastructure
- ✅ CLI command skeleton `cyberspace verify-zk`
- ✅ Hyperjump ZK tag generation
- ✅ Feature flag configuration

**Performance Measurements:**
| Height | Leaves | Constraints | Execution Time | Throughput |
|--------|--------|-------------|----------------|------------|
| h10 | 1K | 5K | 2.23 ms | 2.30M c/s |
| h15 | 32K | 163K | 81.28 ms | 2.02M c/s |
| h20 | 1M | 5.2M | 3,387 ms | 1.55M c/s |

### Phase 2: Production STARK Backend (Not Started)

**TODO:**
- [ ] Select production backend (plonky3 vs cairo-lang)
- [ ] Implement Rust wrapper with PyO3 bindings
- [ ] Replace mock proofs with real STARK proofs
- [ ] Optimize prover performance
- [ ] Security audit

### Phase 3: Production Deployment (Not Started)

**TODO:**
- [ ] Enable by default for all hyperjump actions
- [ ] Relay compatibility testing
- [ ] Documentation updates
- [ ] Deprecation path for non-ZK proofs
```

**Step 2: Commit**

```bash
git add docs/ZK_STARK_DESIGN.md
git commit -m "docs: update ZK_STARK_DESIGN with Phase 1 completion status"
```

---

### Task 8: Run full test suite and verify no regressions

**Objective:** Ensure ZK implementation doesn't break existing functionality.

**Files:**
- All tests in `tests/`

**Step 1: Run full test suite**

```bash
cd ~/repos/cyberspace-cli
python -m pytest tests/ -v --tb=short 2>&1 | tee test-results-2026-04-18.md
```

**Step 2: Verify all tests pass**

Expected: All pre-existing tests still pass, new ZK tests pass

**Step 3: Commit test results**

```bash
git add test-results-2026-04-18.md
git commit -m "ci: full test suite pass with ZK-STARK integration"
```

---

## Success Verification

After completing all tasks:

```bash
# 1. Check all tests pass
python -m pytest tests/ -q
# Expected: All tests pass

# 2. Verify ZK proof generation works
cyberspace verify-zk --help
# Expected: Shows cantor and hyperjump subcommands

# 3. Check config flags exist
cyberspace config show
# Expected: Shows zk_stark_enabled, zk_verify_incoming

# 4. Verify benchmarks run
python scripts/benchmark_zk_circuit.py
# Expected: Shows performance table
```

**Deliverables:**
- ✅ Mock ZK proof system with production-ready interfaces
- ✅ CLI commands for verification
- ✅ Test coverage for all ZK functionality
- ✅ Feature flags for gradual rollout
- ✅ Documentation of implementation status

---

*Plan created: 2026-04-18 for cron job execution*
*Next phase: Phase 2 - Production STARK backend integration (plonky3/cairo-lang)*
