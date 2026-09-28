"""Parallel Merkle engine for sidesteps (CYBERSPACE_V2 section 6).

Splits a tall tree into 2^split_depth subtrees, builds them across worker
processes, and merges their roots. Every leaf is hashed under the seed
prefix of section 6.4, so each worker resumes from the prefix's SHA-256
state and a leaf costs one compression (6.5).

Version 3 draws the sampled openings from G, which needs every axis root and
the re-roll nonce first (6.10), so the engine returns the tree after the root
pass and hands out paths afterwards: for each opened leaf, the inner path
comes from a single-target streaming pass over its own subtree, and the upper
siblings from the merged levels. parallel_first spreads the nonce search, of
a sidestep or of a ride, over the same kind of pool.

The C extension that predates version 2 hashes leaves under the v1 domain
with no seed, so it is not used; it can return once it takes the prefix.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
from typing import Callable, List, Optional, Sequence, Tuple

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


def _worker_path(args: Tuple[bytes, int, int, int]) -> Tuple[bytes, List[bytes]]:
    prefix, base, height, target = args
    return _stream_with_path(prefix, base, height, target)


# Below this subtree height a path is rebuilt faster in this process than a
# pool can be started for it.
PARALLEL_PATH_HEIGHT = 16


def parallel_merkle_tree(prefix: bytes, base: int, height: int, workers: Optional[int] = None):
    """The root pass for the subtree at `base` across processes (6.5), as an
    AxisTree whose paths are assembled on request once G is known: each
    path's lower siblings from a pass over its own subtree, the upper ones
    from the merged levels."""
    from cyberspace_core.movement import AxisTree, compute_axis_merkle_root_streaming

    if workers is None:
        workers = os.cpu_count() or 4
    if height <= 12:
        return compute_axis_merkle_root_streaming(prefix, base, height)

    split = _split_depth(height, workers)
    sub = height - split
    tasks = [(prefix, base + (i << sub), sub) for i in range(1 << split)]
    with multiprocessing.Pool(processes=workers) as pool:
        roots = pool.map(_worker_compute_root, tasks)
    levels = _merge_levels(roots)

    def paths(indices: Sequence[int]) -> List[List[bytes]]:
        for index in indices:
            if not 0 <= index < (1 << height):
                raise ValueError(f"index {index} outside subtree of {1 << height} leaves")
        jobs = [(prefix, base + ((i >> sub) << sub), sub, i & ((1 << sub) - 1)) for i in indices]
        if sub >= PARALLEL_PATH_HEIGHT and len(jobs) > 1:
            with multiprocessing.Pool(processes=min(workers, len(jobs))) as pool:
                inner = pool.map(_worker_path, jobs)
        else:
            inner = [_worker_path(job) for job in jobs]
        out = []
        for index, (inner_root, inner_path) in zip(indices, inner):
            assert inner_root == roots[index >> sub]
            upper, idx = [], index >> sub
            for level in range(split):
                upper.append(levels[level][idx ^ 1])
                idx >>= 1
            out.append(inner_path + upper)
        return out

    return AxisTree(levels[-1][0], base, height, paths)


def _scan(args: Tuple[Callable[[int], bool], int, int]) -> Optional[int]:
    check, lo, hi = args
    for n in range(lo, hi):
        if check(n):
            return n
    return None


def parallel_first(
    check: Callable[[int], bool],
    *,
    start: int = 0,
    chunk: int,
    workers: Optional[int] = None,
    on_progress: Optional[Callable[[int], None]] = None,
) -> int:
    """The smallest n >= start with check(n), searched across processes, a
    batch of `workers` consecutive chunks at a time; it is the n a sequential
    search from `start` finds. `check` must pickle (a module-level function,
    or a functools.partial of one). on_progress receives the count of values
    tried after each batch that found nothing."""
    if workers is None:
        workers = os.cpu_count() or 4
    lo = start
    with multiprocessing.Pool(processes=workers) as pool:
        while lo < 1 << 64:
            hits = [n for n in pool.map(_scan, [(check, lo + i * chunk, lo + (i + 1) * chunk) for i in range(workers)]) if n is not None]
            if hits:
                return min(hits)
            lo += workers * chunk
            if on_progress is not None:
                on_progress(lo - start)
    raise ValueError("no value below 2^64 passed the check")
