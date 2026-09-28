#!/usr/bin/env python3
"""Regenerate tests/fixtures/sidestep_v3.json from the spec's sidestep-reference.py.

    python scripts/gen_sidestep_vectors.py --spec /path/to/cyberspace --ref origin/master

The reference (stdlib only) is loaded from the given git ref, not from the
working tree, and its commit is recorded in the fixture. For each crossing it
records what a version 3 prover publishes: the three axis roots, A, the nonce
(and its mn tag), G, the sampled indices and the exact mp tag value. The
per-axis root vectors are unchanged from version 2 and kept as they were.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import types
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sidestep_v3.json"
ZERO, RANGE = bytes(32), bytes(range(32))
GOLDEN_BASE = (0x1234567 >> 12) << 12

# (name, previous_event_id, axis byte, v1, v2): roots only, unchanged from version 2.
AXIS_ROOTS = [
    ("trivial", ZERO, 0, 0, 0),
    ("zero-z-h5", ZERO, 2, GOLDEN_BASE, GOLDEN_BASE + (1 << 4)),
    ("range-y-h9", RANGE, 1, 1 << 40, (1 << 40) + (1 << 8)),
    ("range-x-h7-down", RANGE, 0, 1000, 959),
    ("range-z-h1", RANGE, 2, 5, 4),
]

# (name, previous_event_id, src, dst): every crossing obeys section 6.3.
CROSSINGS = [
    ("golden-z-h12", ZERO, (5, 7, GOLDEN_BASE + (1 << 11) - 1), (5, 7, GOLDEN_BASE + (1 << 11))),
    ("range-x-h11-z-h6", RANGE, (1023, 100, 479), (1024, 100, 480)),
    ("range-y-h9-down", RANGE, (3, (1 << 40) + 256, 4), (3, (1 << 40) + 255, 4)),
    ("range-z-h1", RANGE, (9, 9, 4), (9, 9, 5)),
    ("zero-xyz-h3-h4-h5", ZERO, (3, 7, 15), (4, 8, 16)),
]


def load_reference(spec: Path, ref: str):
    commit = subprocess.run(["git", "-C", str(spec), "rev-parse", f"{ref}^{{commit}}"], check=True, capture_output=True, text=True).stdout.strip()
    source = subprocess.run(["git", "-C", str(spec), "show", f"{commit}:sidestep-reference.py"], check=True, capture_output=True, text=True).stdout
    module = types.ModuleType("sidestep_reference")
    exec(compile(source, "sidestep-reference.py", "exec"), module.__dict__)
    return commit, module


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--spec", type=Path, required=True, help="local clone of arkin0x/cyberspace")
    parser.add_argument("--ref", default="origin/master")
    args = parser.parse_args()
    commit, ref = load_reference(args.spec, args.ref)

    axis_roots = []
    for name, prev, axis, v1, v2 in AXIS_ROOTS:
        base, h = ref.axis_geometry(v1, v2)
        prefix = ref.seed_prefix(prev, axis)
        axis_roots.append({
            "name": name, "prev": prev.hex(), "axis": axis, "v1": v1, "v2": v2, "base": base, "height": h,
            "prefix": prefix.hex(), "root": ref.merkle_root_streaming(prefix, base, h).hex(),
        })

    crossings = []
    for name, prev, src, dst in CROSSINGS:
        heights = [ref.axis_geometry(a, b)[1] for a, b in zip(src, dst)]
        roots, nonce, openings = ref.prove_sidestep(prev, src, dst)
        G = ref.grind_hash(prev, roots, nonce)
        assert ref.verify_sidestep(prev, src, dst, roots, nonce, openings)
        crossings.append({
            "name": name, "prev": prev.hex(), "src": list(src), "dst": list(dst), "heights": heights,
            "roots": [r.hex() for r in roots], "attempts": ref.reroll_attempts(heights),
            "nonce": nonce, "mn": nonce.to_bytes(8, "big").hex(), "G": G.hex(),
            "samples": [ref.sample_indices(G, ax, h) if h else [] for ax, h in zip(ref.AXES, heights)],
            "mp": ":".join("".join(s.hex() for path in paths for s in path) for paths in openings),
        })

    OUT.write_text(json.dumps({
        "source": f"arkin0x/cyberspace {commit} sidestep-reference.py",
        "regenerate": "python scripts/gen_sidestep_vectors.py --spec /path/to/cyberspace --ref origin/master",
        "axis_roots": axis_roots,
        "crossings": crossings,
    }, indent=1) + "\n")
    print(f"{OUT}: {len(axis_roots)} axis roots, {len(crossings)} crossings, from {commit}")


if __name__ == "__main__":
    main()
