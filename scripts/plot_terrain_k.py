#!/usr/bin/env python3

# Usage: 
# source .venv/bin/activate
# PYTHONPATH=src python3 scripts/plot_terrain_k.py \
#   --size 512 \
#   --step 1 \
#   --base-x 0 --base-y 0 \
#   --z 0 --plane 0 \
#   --cell-bits 3,5,7,9 \
#   --out-dir out/terrain-k/demo_3579

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

# In headless environments, force a non-interactive backend.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from cyberspace_core.cantor import sha256
from cyberspace_core.coords import xyz_to_coord
from cyberspace_core.terrain import TERRAIN_DOMAIN_V1


def _aligned(v: int, cell_bits: int) -> int:
    if cell_bits <= 0:
        return v
    return (v >> cell_bits) << cell_bits


def _fmt_cell_size(bits: int) -> str:
    """Format the implied cell width (= 2^bits axis-units).

    For small sizes, print exactly. For huge sizes, print an approximate scientific
    notation to keep plot titles readable.
    """

    if bits < 0:
        raise ValueError("bits must be >= 0")

    n = 1 << bits

    # Exact for small-ish sizes; approximate for huge sizes.
    if bits <= 30:
        return f"2^{bits}={n}"
    if bits <= 60:
        return f"2^{bits}={n:,}"

    return f"2^{bits}≈{float(n):.3e}"


def _terrain_byte(*, x: int, y: int, z: int, plane: int, cell_bits: int, cache: dict[tuple[int, int, int, int, int], int]) -> int:
    bx = _aligned(x, cell_bits)
    by = _aligned(y, cell_bits)
    bz = _aligned(z, cell_bits)

    key = (cell_bits, bx, by, bz, plane)
    if key in cache:
        return cache[key]

    coord = xyz_to_coord(bx, by, bz, plane=plane)
    coord_bytes = coord.to_bytes(32, "big")
    digest = sha256(TERRAIN_DOMAIN_V1 + bytes([cell_bits]) + coord_bytes)
    b0 = digest[0]
    cache[key] = b0
    return b0


def terrain_k_grid(
    *,
    base_x: int,
    base_y: int,
    size: int,
    step: int,
    z: int,
    plane: int,
    cell_bits: tuple[int, int, int, int],
) -> np.ndarray:
    k = np.zeros((size, size), dtype=np.uint8)

    cache: dict[tuple[int, int, int, int, int], int] = {}

    for iy in range(size):
        y = base_y + iy * step
        for ix in range(size):
            x = base_x + ix * step

            word = 0
            for bits in cell_bits:
                b0 = _terrain_byte(x=x, y=y, z=z, plane=plane, cell_bits=bits, cache=cache)
                word = (word << 8) | b0

            k[iy, ix] = int(word).bit_count()

    return k


def expected_binomial_counts(*, n: int, total: int) -> np.ndarray:
    # p=0.5
    out = np.zeros(n + 1, dtype=np.float64)
    denom = 2**n
    for k in range(n + 1):
        out[k] = total * (math.comb(n, k) / denom)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Plot a deterministic Cyberspace terrain K field (0..32).")
    p.add_argument("--size", type=int, default=512, help="Grid width/height in pixels.")
    p.add_argument("--step", type=int, default=1, help="Axis step per pixel.")
    p.add_argument("--base-x", type=int, default=0, help="X origin (u85 int) for the plotted window.")
    p.add_argument("--base-y", type=int, default=0, help="Y origin (u85 int) for the plotted window.")
    p.add_argument("--z", type=int, default=0, help="Fixed Z slice (u85 int).")
    p.add_argument("--plane", type=int, default=0, choices=[0, 1], help="Plane bit (0=dataspace, 1=ideaspace).")
    p.add_argument(
        "--cell-bits",
        type=str,
        default="3,7,9,11",
        help="Four comma-separated cell sizes (bits). Example: 3,7,9,11",
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default="./out",
        help="Output directory for PNGs.",
    )

    args = p.parse_args()

    bits = tuple(int(s.strip(), 0) for s in (args.cell_bits.split(",") if args.cell_bits else []) if s.strip())
    if len(bits) != 4:
        raise SystemExit("--cell-bits must contain exactly 4 integers")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    k = terrain_k_grid(
        base_x=int(args.base_x),
        base_y=int(args.base_y),
        size=int(args.size),
        step=int(args.step),
        z=int(args.z),
        plane=int(args.plane),
        cell_bits=bits,  # type: ignore[arg-type]
    )

    total = int(k.size)
    hist = np.bincount(k.reshape(-1), minlength=33)[:33]

    mean = float(k.mean())
    std = float(k.std())

    cell_sizes = ", ".join(_fmt_cell_size(b) for b in bits)

    title = (
        f"terrain K (popcount32)  size={args.size} step={args.step} "
        f"base=({args.base_x},{args.base_y},{args.z}) plane={args.plane}\n"
        f"cell_bits={bits}  cell_sizes=[{cell_sizes}] (axis units per cell)\n"
        f"mean={mean:.3f} std={std:.3f}"
    )

    # --- Heatmap ---
    plt.figure(figsize=(8, 7), dpi=150)
    plt.imshow(k, origin="lower", interpolation="nearest", cmap="terrain", vmin=0, vmax=32)
    plt.colorbar(label="K")
    plt.title(title)
    plt.xlabel("x offset")
    plt.ylabel("y offset")
    heat_path = out_dir / "terrain_k_heatmap.png"
    plt.tight_layout()
    plt.savefig(heat_path)
    plt.close()

    # --- Histogram ---
    exp = expected_binomial_counts(n=32, total=total)

    xs = np.arange(33)

    plt.figure(figsize=(9, 5), dpi=150)
    plt.bar(xs, hist, alpha=0.85, label="observed")
    plt.plot(xs, exp, color="#cc0000", linewidth=2.0, label="expected binomial(n=32,p=0.5)")
    plt.title("K distribution\n" + f"cell_bits={bits}  cell_sizes=[{cell_sizes}] (axis units per cell)")
    plt.xlabel("K")
    plt.ylabel("count")
    plt.legend()
    plt.grid(True, alpha=0.2)

    hist_path = out_dir / "terrain_k_hist.png"
    plt.tight_layout()
    plt.savefig(hist_path)
    plt.close()

    # Summary to stdout for quick inspection.
    print(title)
    print(f"out: {heat_path}")
    print(f"out: {hist_path}")
    print("hist (K:count):")
    for kk, c in enumerate(hist.tolist()):
        if c:
            print(f"{kk:02d}: {c}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
