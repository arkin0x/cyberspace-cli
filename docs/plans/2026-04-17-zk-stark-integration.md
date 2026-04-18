# ZK-STARK Proofs Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Integrate ZK-STARK proof generation and verification into cyberspace-cli, enabling lightweight clients to verify Cantor traversal proofs in milliseconds.

**Architecture:** Pluggable backend design with mock PoC implementation already complete. Phase 1 adds CLI commands and user workflows. Phase 2 integrates real STARK backend (winterfell).

**Tech Stack:** Python 3.11+, cyberspace-cli existing stack, ZK-STARK backend (mock now, winterfell/plonky3 later).

---

## Current State (As of 2026-04-17)

### ✅ Completed
- Core ZK proof interface (`zk_cantor.py`)
- Mock STARK backend (PoC)
- Unit tests (7/8 passing)
- Design specification (`ZK_STARK_DESIGN.md`)

### ❌ Missing
- CLI commands (`verify-zk`, `bench-zk`, `zk-prove`)
- `--zk` flag for `cyberspace move`
- Real STARK backend integration
- Production benchmarks

---

## Phase 1: CLI Integration (Tasks 1-20)

### Task 1: Create ZK Verification CLI Command

**Objective:** Add `cyberspace verify-zk` command to verify ZK proofs from event files.

**Files:**
- Create: `src/cyberspace_cli/commands/verify_zk.py`
- Modify: `src/cyberspace_cli/cli.py:45-67` (command registration)

**Step 1: Write failing test**

```python
# tests/test_verify_zk_cli.py
import subprocess
import json
import tempfile
from pathlib import Path

def test_verify_zk_command_exists():
    """Test that verify-zk command is recognized."""
    result = subprocess.run(
        ["cyberspace", "verify-zk", "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "Verify ZK-STARK proof" in result.stdout
```

**Step 2: Run test to verify failure**

Run: `pytest tests/test_verify_zk_cli.py::test_verify_zk_command_exists -v`
Expected: FAIL — ModuleNotFoundError: No module named 'cyberspace_cli.commands.verify_zk'

**Step 3: Write minimal implementation**

```python
# src/cyberspace_cli/commands/verify_zk.py
"""Verify ZK-STARK proofs for Cyberspace movement events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cyberspace_core.zk_cantor import verify_cantor_tree, verify_hyperspace_traversal


def cmd_verify_zk(args: argparse.Namespace) -> int:
    """Verify a ZK-STARK proof from an event file."""
    
    # Load event
    try:
        with open(args.event_file, 'r') as f:
            event = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading event file: {e}", file=sys.stderr)
        return 1
    
    # Extract proof tag
    zk_tag = None
    proof_tag = None
    for tag in event.get("tags", []):
        if tag[0] == "zk":
            zk_tag = tag[1]
        if tag[0] == "proof":
            proof_tag = tag[1]
    
    if not zk_tag:
        print("Error: No 'zk' tag found in event", file=sys.stderr)
        return 1
    
    if not proof_tag:
        print("Error: No 'proof' tag found in event", file=sys.stderr)
        return 1
    
    print(f"✓ Found zk tag: {len(zk_tag)} chars")
    print(f"✓ Found proof tag: {proof_tag[:16]}...")
    print("✓ Event structure valid")
    print("\nNote: Mock backend enabled - cryptographic verification not performed")
    print("Production backend will verify STARK proof soundness")
    
    return 0


def register_verify_zk(subparsers):
    """Register verify-zk command."""
    parser = subparsers.add_parser(
        "verify-zk",
        help="Verify ZK-STARK proof for a movement event"
    )
    parser.add_argument(
        "--event-file",
        required=True,
        type=Path,
        help="Path to JSON event file"
    )
    parser.set_defaults(func=cmd_verify_zk)
```

**Step 4: Register command in CLI**

```python
# src/cyberspace_cli/cli.py
# Find the subparsers section and add:

from cyberspace_cli.commands.verify_zk import register_verify_zk

def main():
    # ... existing setup ...
    
    register_verify_zk(subparsers)
    
    # ... rest of CLI ...
```

**Step 5: Run test to verify pass**

Run: `pytest tests/test_verify_zk_cli.py::test_verify_zk_command_exists -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cyberspace_cli/commands/verify_zk.py src/cyberspace_cli/cli.py tests/test_verify_zk_cli.py
git commit -m "feat: add cyberspace verify-zk command"
```

---

### Task 2: Add Event Content Parsing to verify-zk

**Objective:** Parse and decode ZK proof from event, reconstruct proof object.

**Files:**
- Modify: `src/cyberspace_cli/commands/verify_zk.py:25-45`

**Step 1: Write failing test**

```python
def test_verify_zk_decodes_proof():
    """Test that verify-zk correctly decodes proof from hex."""
    # Create mock event with ZK proof
    event = {
        "kind": 3333,
        "tags": [
            ["A", "hop"],
            ["proof", "abcd1234"],
            ["zk", "7b22726f6f74223a203132337d"]  # Mock hex-encoded proof
        ]
    }
    
    # Save to temp file and test
```

**Step 2: Implement proof decoding**

```python
# Add to verify_zk.py:
import binascii

def _decode_zk_proof(zk_tag_hex: str):
    """Decode ZK proof from hex string."""
    try:
        proof_bytes = binascii.unhexlify(zk_tag_hex)
        return proof_bytes
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"Invalid hex in zk tag: {e}")
```

**Step 3: Integrate with verification**

```python
# In cmd_verify_zk:
try:
    proof_bytes = _decode_zk_proof(zk_tag)
    print(f"✓ Decoded proof: {len(proof_bytes)} bytes")
except ValueError as e:
    print(f"Error decoding proof: {e}", file=sys.stderr)
    return 1
```

**Step 4: Run tests and commit**

```bash
pytest tests/test_verify_zk_cli.py -v
git add src/cyberspace_cli/commands/verify_zk.py
git commit -m "feat: decode ZK proof from hex in verify-zk"
```

---

### Task 3: Implement verify-zk Full Verification Logic

**Objective:** Actually verify the proof using zk_cantor module.

**Files:**
- Modify: `src/cyberspace_cli/commands/verify_zk.py:50-80`

**Step 1: Extract leaves from event**

```python
def _extract_leaves_from_event(event: dict) -> list[int]:
    """Extract leaf values from event tags."""
    leaves = []
    
    # Look for temporal_seed tag
    for tag in event.get("tags", []):
        if tag[0] == "temporal_seed":
            leaves.append(int(tag[1]))
        elif tag[0] == "B":  # Block height (for hyperjump)
            leaves.append(int(tag[1]))
        elif tag[0] == "C":  # Coordinate
            leaves.append(int(tag[1], 16))
    
    return leaves
```

**Step 2: Reconstruct proof object**

```python
from cyberspace_core.zk_cantor import ZKCantorProof

def _reconstruct_proof(event: dict, proof_bytes: bytes) -> ZKCantorProof:
    """Reconstruct ZKCantorProof from event tags."""
    root = int(event["tags"]["proof"], 16)
    leaf_count = len(_extract_leaves_from_event(event))
    
    # Mock constraint count (real backend would include this in proof)
    constraint_count = (leaf_count - 1) * 3
    
    return ZKCantorProof(
        root=root,
        leaf_count=leaf_count,
        stark_proof=proof_bytes,
        constraint_count=constraint_count,
    )
```

**Step 3: Call verification**

```python
# In cmd_verify_zk:
leaves = _extract_leaves_from_event(event)
proof = _reconstruct_proof(event, proof_bytes)

try:
    is_valid = verify_cantor_tree(root, leaves, proof)
    if is_valid:
        print("✓ ZK proof VERIFIED")
        return 0
    else:
        print("✗ ZK proof INVALID", file=sys.stderr)
        return 1
except Exception as e:
    print(f"✗ Verification error: {e}", file=sys.stderr)
    return 1
```

**Step 4: Test and commit**

```bash
pytest tests/test_verify_zk_cli.py::test_verify_zk_full_verification -v
git add src/cyberspace_cli/commands/verify_zk.py
git commit -m "feat: implement full ZK verification logic"
```

---

### Task 4: Add Hyperjump-Specific Verification

**Objective:** Add special handling for hyperjump events with hyperspace_traversal verification.

**Files:**
- Modify: `src/cyberspace_cli/commands/verify_zk.py:85-110`

**Step 1: Write failing test**

```python
def test_verify_zk_hyperjump():
    """Test hyperjump-specific verification path."""
    event = {
        "kind": 3333,
        "tags": [
            ["A", "hyperjump"],
            ["proof", "abcd1234"],
            ["zk", "proof_hex"],
            ["from_height", "1606"],
            ["B", "1607"],
            ["prev", "prev_event_id_hex"]
        ]
    }
```

**Step 2: Detect hyperjump action type**

```python
action_type = None
for tag in event.get("tags", []):
    if tag[0] == "A":
        action_type = tag[1]
        break

if action_type == "hyperjump":
    # Use hyperspace_traversal verification
    return _verify_hyperjump_zk(event, proof_bytes)
else:
    # Use standard tree verification
    return _verify_hop_zk(event, proof_bytes)
```

**Step 3: Implement hyperjump verification**

```python
from cyberspace_core.zk_cantor import verify_hyperspace_traversal

def _verify_hyperjump_zk(event: dict, proof_bytes: bytes) -> int:
    """Verify ZK proof for hyperjump event."""
    # Extract from_height, to_height
    from_height = to_height = None
    for tag in event.get("tags", []):
        if tag[0] == "from_height":
            from_height = int(tag[1])
        elif tag[0] == "B":
            to_height = int(tag[1])
    
    if from_height is None or to_height is None:
        print("Error: Missing from_height or B tag", file=sys.stderr)
        return 1
    
    # Extract previous event ID
    prev_id_hex = None
    for tag in event.get("tags", []):
        if tag[0] == "prev":
            prev_id_hex = tag[1]
            break
    
    if not prev_id_hex:
        print("Error: Missing prev tag", file=sys.stderr)
        return 1
    
    prev_event_id = binascii.unhexlify(prev_id_hex)
    root = int(event["tags"]["proof"], 16)
    proof = _reconstruct_proof(event, proof_bytes)
    
    try:
        is_valid = verify_hyperspace_traversal(
            root, prev_event_id, from_height, to_height, proof
        )
        if is_valid:
            print(f"✓ Hyperjump ZK proof VERIFIED (blocks {from_height}→{to_height})")
            return 0
        else:
            print("✗ Hyperjump ZK proof INVALID", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"✗ Verification error: {e}", file=sys.stderr)
        return 1
```

**Step 4: Test and commit**

```bash
pytest tests/test_verify_zk_cli.py::test_verify_zk_hyperjump -v
git add src/cyberspace_cli/commands/verify_zk.py
git commit -m "feat: add hyperjump-specific ZK verification"
```

---

### Task 5: Create benchmark-zk CLI Command

**Objective:** Add `cyberspace bench-zk` command to benchmark ZK proof generation.

**Files:**
- Create: `src/cyberspace_cli/commands/bench_zk.py`
- Modify: `src/cyberspace_cli/cli.py:68-70` (register command)

**Complete task following TDD pattern** (similar to Tasks 1-4)

...

[PLAN CONTINUES - Truncated for brevity, full plan would have 20 tasks covering:]

### Tasks 6-20 Outline

6. **Add --zk flag to move command** - Enable ZK proof generation during movement
7. **Implement zk-prove command** - Generate ZK proofs for existing events
8. **Add ZK configuration options** - Config flags for enabling/disabling ZK features
9. **Write integration tests** - End-to-end ZK workflow tests
10. **Add progress indicators** - Show ZK proof generation progress for large trees
11. **Add proof size reporting** - Display proof size estimates
12. **Add verification timing** - Benchmark verification time
13. **Write user documentation** - Update README.md with ZK features
14. **Add help text** - Document --zk flag and new commands
15. **Add error handling** - Graceful handling of ZK backend failures
16. **Add logging** - Verbose mode for debugging ZK operations
17. **Add serialization helpers** - Encode/decode ZK proofs for Nostr events
18. **Write CLI manual pages** - Man pages for verify-zk, bench-zk, zk-prove
19. **Add CI/CD tests** - Ensure ZK tests run in CI pipeline
20. **Phase 1 review** - Verify all success metrics met

---

## Phase 2: Real STARK Backend (Tasks 21-40)

### Tasks 21-40 Outline

21. Set up winterfell Python environment
22. Implement winterfell backend for single pair
23. Write test vectors for winterfell backend
24. Benchmark winterfell vs mock
25. Implement Cantor tree backend in winterfell
26. Optimize constraint system
27. Add backend switching mechanism
28. Add backend configuration
29. Implement real proof serialization
30. Implement real proof verification
31. Add cryptographic soundness tests
32. Benchmark full tree proofs
33. Profile memory usage
34. Profile CPU usage
35. Optimize for height-33 proofs
36. Write migration guide (mock → winterfell)
37. Add fallback to mock backend
38. Security review checklist
39. Phase 2 review
40. Prepare for audit

---

## Success Metrics

- ✅ `cyberspace verify-zk` command works
- ✅ `cyberspace bench-zk` command works
- ✅ `cyberspace move --zk` generates proofs
- ✅ Verification time <10 ms (mock)
- ✅ All existing tests pass
- ✅ Mock → winterfell migration path defined

---

## Execution Instructions

**"Plan complete. Ready to execute using subagent-driven-development — dispatching fresh subagent per task with two-stage review (spec compliance then code quality). Proceeding with Phase 1, Task 1."**
