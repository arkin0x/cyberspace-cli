"""
High-level Merkle tree computation with optional C acceleration and parallelism.

Provides:
    compute_subtree_root(base, height) -> bytes
    compute_subtree_root_with_proof(base, height) -> (bytes, list[bytes])
    parallel_merkle_root(base, height, workers=None) -> bytes
    parallel_merkle_root_with_proof(base, height, workers=None) -> (bytes, list[bytes])

The C extension (_merkle_engine) is used when available; otherwise falls back
to a pure-Python implementation.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Domain separation constant
# ---------------------------------------------------------------------------

SIDESTEP_DOMAIN = b"CYBERSPACE_SIDESTEP_V1"

# ---------------------------------------------------------------------------
# Try to import the C extension
# ---------------------------------------------------------------------------

_USE_C = False
HAS_C_EXTENSION = False

try:
    from cyberspace_core._merkle_engine import (
        compute_subtree_root as _c_compute_subtree_root,
        compute_subtree_root_with_proof as _c_compute_subtree_root_with_proof,
    )
    _USE_C = True
    HAS_C_EXTENSION = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Pure Python fallback
# ---------------------------------------------------------------------------


def _int_to_bytes_be_min(n: int) -> bytes:
    if n == 0:
        return b"\x00"
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _merkle_leaf(value: int) -> bytes:
    return _sha256(SIDESTEP_DOMAIN + _int_to_bytes_be_min(value))


def _merkle_parent(left: bytes, right: bytes) -> bytes:
    return _sha256(left + right)


def _py_compute_subtree_root(base: int, height: int) -> bytes:
    """Pure Python streaming Merkle root computation."""
    if height == 0:
        return _merkle_leaf(base)

    leaf_count = 1 << height
    # Stack-based streaming: stack[level] = hash or None
    stack: list[bytes | None] = [None] * (height + 1)

    for i in range(leaf_count):
        current = _merkle_leaf(base + i)
        level = 0
        while stack[level] is not None:
            current = _merkle_parent(stack[level], current)
            stack[level] = None
            level += 1
        stack[level] = current

    return stack[height]  # type: ignore[return-value]


def _py_compute_subtree_root_with_proof(
    base: int, height: int
) -> Tuple[bytes, List[bytes]]:
    """Pure Python streaming Merkle root + inclusion proof for leaf 0."""
    if height == 0:
        return _merkle_leaf(base), []

    leaf_count = 1 << height
    stack: list[bytes | None] = [None] * (height + 1)
    proof: list[bytes] = []

    for i in range(leaf_count):
        current = _merkle_leaf(base + i)
        level = 0
        while stack[level] is not None:
            # For leaf 0 inclusion proof: leaf 0 is always on leftmost path.
            # At each level, its ancestor is the left child; sibling is right (current).
            if len(proof) == level:
                proof.append(current)
            current = _merkle_parent(stack[level], current)
            stack[level] = None
            level += 1
        stack[level] = current

    return stack[height], proof  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public API — dispatch to C or Python
# ---------------------------------------------------------------------------


def compute_subtree_root(base: int, height: int) -> bytes:
    """Compute the Merkle root for an aligned subtree [base, base + 2^height)."""
    if _USE_C:
        return _c_compute_subtree_root(base, height)
    return _py_compute_subtree_root(base, height)


def compute_subtree_root_with_proof(
    base: int, height: int
) -> Tuple[bytes, List[bytes]]:
    """Compute Merkle root and inclusion proof for leaf 0."""
    if _USE_C:
        return _c_compute_subtree_root_with_proof(base, height)
    return _py_compute_subtree_root_with_proof(base, height)


def _subtree_root_with_proof_for(
    base: int, height: int, target_index: int
) -> Tuple[bytes, List[bytes]]:
    """Root and inclusion proof for any leaf of a subtree. Leaf 0 keeps the
    accelerated path; other leaves use the streaming reference, which is
    exact and only ever runs on one subtree."""
    if target_index == 0:
        return compute_subtree_root_with_proof(base, height)
    from cyberspace_core.movement import compute_axis_merkle_root_streaming

    return compute_axis_merkle_root_streaming(base, height, target_index=target_index)


# ---------------------------------------------------------------------------
# Worker function for multiprocessing (must be top-level / picklable)
# ---------------------------------------------------------------------------


def _worker_compute_root(args: Tuple[int, int]) -> bytes:
    """Worker: compute subtree root for (base, height)."""
    base, height = args
    return compute_subtree_root(base, height)


# ---------------------------------------------------------------------------
# Parallel Merkle computation
# ---------------------------------------------------------------------------


def _merge_roots_serial(roots: List[bytes], levels: int) -> bytes:
    """Merge a list of 2^levels subtree roots into a single root."""
    current = roots
    for _ in range(levels):
        next_level = []
        for j in range(0, len(current), 2):
            next_level.append(_merkle_parent(current[j], current[j + 1]))
        current = next_level
    assert len(current) == 1
    return current[0]


def parallel_merkle_root(
    base: int,
    height: int,
    workers: Optional[int] = None,
) -> bytes:
    """Compute Merkle root using multiple processes.

    Splits the tree of height h into 2^split_depth subtrees of height
    (h - split_depth), computes each in parallel, then merges serially.

    Parameters
    ----------
    base : int
        Aligned subtree base value.
    height : int
        Tree height (2^height leaves).
    workers : int, optional
        Number of worker processes. Defaults to CPU count.

    Returns
    -------
    bytes
        32-byte Merkle root.
    """
    if workers is None:
        workers = os.cpu_count() or 4

    # For small trees, just compute directly
    if height <= 12:
        return compute_subtree_root(base, height)

    # Choose split depth: enough subtrees to keep workers busy
    # but not so many that overhead dominates.
    # At least workers tasks, at most 256.
    split_depth = min(8, height)
    # Ensure we have at least `workers` subtrees
    while (1 << split_depth) < workers and split_depth < height:
        split_depth += 1
    split_depth = min(split_depth, height)

    sub_height = height - split_depth
    num_subtrees = 1 << split_depth

    # Build task list
    tasks = []
    for i in range(num_subtrees):
        sub_base = base + (i << sub_height) if sub_height > 0 else base + i
        tasks.append((sub_base, sub_height))

    # Parallel computation
    with multiprocessing.Pool(processes=workers) as pool:
        roots = pool.map(_worker_compute_root, tasks)

    # Merge subtree roots serially (small: 2^split_depth nodes)
    return _merge_roots_serial(roots, split_depth)


def parallel_merkle_root_with_proof(
    base: int,
    height: int,
    workers: Optional[int] = None,
    target_index: int = 0,
) -> Tuple[bytes, List[bytes]]:
    """Compute Merkle root and the inclusion proof for one leaf, using parallelism.

    CYBERSPACE_V2 6.10 wants the destination leaf's path, so callers pass
    target_index = v2 - base. The proof is collected as:
    1. The inner proof inside the subtree that holds the target leaf.
    2. The sibling subtree roots along the target's path at the upper levels.

    Parameters
    ----------
    base : int
        Aligned subtree base value.
    height : int
        Tree height (2^height leaves).
    workers : int, optional
        Number of worker processes.

    Returns
    -------
    (bytes, list[bytes])
        (root, inclusion_proof) where inclusion_proof has `height` entries.
    """
    if workers is None:
        workers = os.cpu_count() or 4

    if not 0 <= target_index < (1 << height):
        raise ValueError(f"target_index {target_index} outside subtree of {1 << height} leaves")

    # For small trees, compute directly
    if height <= 12:
        return _subtree_root_with_proof_for(base, height, target_index)

    split_depth = min(8, height)
    while (1 << split_depth) < workers and split_depth < height:
        split_depth += 1
    split_depth = min(split_depth, height)

    sub_height = height - split_depth
    num_subtrees = 1 << split_depth

    # Build task list
    tasks = []
    for i in range(num_subtrees):
        sub_base = base + (i << sub_height) if sub_height > 0 else base + i
        tasks.append((sub_base, sub_height))

    # The subtree holding the target leaf is computed with its inner proof.
    sub_index = target_index >> sub_height
    inner_target = target_index & ((1 << sub_height) - 1)
    inner_root, inner_proof = _subtree_root_with_proof_for(
        tasks[sub_index][0], tasks[sub_index][1], inner_target
    )

    # Compute the other subtrees in parallel
    remaining_tasks = [t for k, t in enumerate(tasks) if k != sub_index]
    if remaining_tasks:
        with multiprocessing.Pool(processes=workers) as pool:
            remaining_roots = pool.map(_worker_compute_root, remaining_tasks)
        all_roots = remaining_roots[:sub_index] + [inner_root] + remaining_roots[sub_index:]
    else:
        all_roots = [inner_root]

    # Merge the upper tree, collecting the sibling of the target's ancestor
    # at every level; the ancestor's index halves per level.
    upper_proof: list[bytes] = []
    current_level = all_roots
    idx = sub_index
    for _ in range(split_depth):
        upper_proof.append(current_level[idx ^ 1])
        idx >>= 1
        next_level = []
        for j in range(0, len(current_level), 2):
            next_level.append(_merkle_parent(current_level[j], current_level[j + 1]))
        current_level = next_level

    assert len(current_level) == 1
    root = current_level[0]

    full_proof = inner_proof + upper_proof
    assert len(full_proof) == height, (
        f"Expected {height} proof entries, got {len(full_proof)}"
    )

    return root, full_proof
