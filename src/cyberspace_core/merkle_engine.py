"""Parallel Merkle engine for version 2 sidesteps (CYBERSPACE_V2 section 6).

Splits a tall tree into 2^split_depth subtrees, builds them across worker
processes, and merges their roots. Every leaf is hashed under the seed
prefix of section 6.4, so each worker resumes from the prefix's SHA-256
state and a leaf costs one compression (6.5).

The openings (6.10) are assembled after the root is known: for each of the
nine opened leaves, the inner path comes from a single-target streaming
pass over its own subtree, and the upper siblings from the merged levels.

The C extension that predates this revision hashes leaves under the v1
domain with no seed, so it is not used; it can return once it takes the
prefix.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
from typing import Callable, List, Optional, Tuple

from cyberspace_core.cantor import int_to_bytes_be_min

HAS_C_EXTENSION = False


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _leaf_hasher(prefix: bytes) -> Callable[[int], bytes]:
    if len(prefix) != 64:
        raise ValueError("seed prefix must be exactly one SHA-256 block")
    mid = hashlib.sha256(prefix)

    def leaf(value: int) -> bytes:
        h = mid.copy()
        h.update(int_to_bytes_be_min(value))
        return h.digest()

    return leaf


def _merkle_parent(left: bytes, right: bytes) -> bytes:
    return _sha256(left + right)


def compute_subtree_root(prefix: bytes, base: int, height: int) -> bytes:
    """Streaming root of the subtree [base, base + 2^height) under the seed."""
    leaf = _leaf_hasher(prefix)
    if height == 0:
        return leaf(base)
    stack: list = [None] * (height + 1)
    for i in range(1 << height):
        current = leaf(base + i)
        level = 0
        while stack[level] is not None:
            current = _merkle_parent(stack[level], current)
            stack[level] = None
            level += 1
        stack[level] = current
    return stack[height]


def _stream_with_path(prefix: bytes, base: int, height: int, target: int) -> Tuple[bytes, List[bytes]]:
    """Root of the subtree at `base` and the path of its leaf at `target`."""
    leaf = _leaf_hasher(prefix)
    if height == 0:
        return leaf(base), []
    stack: List[Tuple[bytes, int]] = []
    siblings: List[Optional[bytes]] = [None] * height
    for i in range(1 << height):
        current, level = leaf(base + i), 0
        while stack and stack[-1][1] == level:
            left, _ = stack.pop()
            if (target >> (level + 1)) == (i >> (level + 1)):
                siblings[level] = left if (target >> level) & 1 else current
            current = _merkle_parent(left, current)
            level += 1
        stack.append((current, level))
    assert len(stack) == 1 and all(s is not None for s in siblings)
    return stack[0][0], siblings  # type: ignore[return-value]


def _worker_compute_root(args: Tuple[bytes, int, int]) -> bytes:
    prefix, base, height = args
    return compute_subtree_root(prefix, base, height)


def _split_depth(height: int, workers: int) -> int:
    depth = min(8, height)
    while (1 << depth) < workers and depth < height:
        depth += 1
    return min(depth, height)


def _merge_levels(roots: List[bytes]) -> List[List[bytes]]:
    """Every level of the tree over `roots`, the roots first, the top last."""
    levels = [roots]
    current = roots
    while len(current) > 1:
        current = [_merkle_parent(current[j], current[j + 1]) for j in range(0, len(current), 2)]
        levels.append(current)
    return levels


def parallel_merkle_root(prefix: bytes, base: int, height: int, workers: Optional[int] = None) -> bytes:
    """The root alone, across processes."""
    if workers is None:
        workers = os.cpu_count() or 4
    if height <= 12:
        return compute_subtree_root(prefix, base, height)
    split = _split_depth(height, workers)
    sub = height - split
    tasks = [(prefix, base + (i << sub), sub) for i in range(1 << split)]
    with multiprocessing.Pool(processes=workers) as pool:
        roots = pool.map(_worker_compute_root, tasks)
    return _merge_levels(roots)[-1][0]


def parallel_merkle_root_with_proof(
    prefix: bytes,
    base: int,
    height: int,
    workers: Optional[int] = None,
    target_index: int = 0,
    axis_byte: Optional[int] = None,
) -> Tuple[bytes, List[List[bytes]]]:
    """Root and openings (6.10) for the subtree at `base`: the path of the
    leaf at target_index (the destination), then the eight sampled paths at
    positions drawn from the root."""
    from cyberspace_core.movement import compute_axis_merkle_root_streaming, sample_indices

    if not 0 <= target_index < (1 << height):
        raise ValueError(f"target_index {target_index} outside subtree of {1 << height} leaves")
    if axis_byte is None:
        raise ValueError("axis_byte is needed to draw the sampled openings")
    if workers is None:
        workers = os.cpu_count() or 4
    if height <= 12:
        return compute_axis_merkle_root_streaming(prefix, base, height, target_index=target_index, axis_byte=axis_byte)

    split = _split_depth(height, workers)
    sub = height - split
    tasks = [(prefix, base + (i << sub), sub) for i in range(1 << split)]
    with multiprocessing.Pool(processes=workers) as pool:
        roots = pool.map(_worker_compute_root, tasks)
    levels = _merge_levels(roots)
    root = levels[-1][0]

    def path_for(index: int) -> List[bytes]:
        sub_index = index >> sub
        inner_root, inner = _stream_with_path(prefix, base + (sub_index << sub), sub, index & ((1 << sub) - 1))
        assert inner_root == roots[sub_index]
        upper = []
        idx = sub_index
        for level in range(split):
            upper.append(levels[level][idx ^ 1])
            idx >>= 1
        return inner + upper

    openings = [path_for(target_index)] + [path_for(i) for i in sample_indices(root, axis_byte, height)]
    return root, openings
