#!/usr/bin/env python3
"""Benchmark Cantor tree circuit execution for ZK-STARK sizing.

This measures the execution trace generation time (what the prover would do)
and constraint counts for various tree heights.
"""

import time
from cyberspace_core.zk_stark.circuit import (
    cantor_tree_circuit,
    verify_tree_constraints,
    count_constraints,
)


def benchmark_tree_height(height: int, num_runs: int = 3) -> dict:
    """Benchmark Cantor tree circuit for a given height.
    
    Args:
        height: Tree height (2^height leaves)
        num_runs: Number of runs to average
        
    Returns:
        Dictionary with benchmark results
    """
    num_leaves = 2 ** height
    leaves = list(range(num_leaves))
    
    # Warm-up
    _ = cantor_tree_circuit(leaves[:min(100, num_leaves)])
    
    # Benchmark
    times = []
    for _ in range(num_runs):
        start = time.perf_counter()
        tree = cantor_tree_circuit(leaves)
        end = time.perf_counter()
        times.append(end - start)
    
    avg_time = sum(times) / len(times)
    constraints = count_constraints(num_leaves)
    
    return {
        "height": height,
        "num_leaves": num_leaves,
        "num_pairings": constraints["num_pairings"],
        "total_constraints": constraints["total_constraints"],
        "avg_execution_time_sec": avg_time,
        "constraints_per_second": constraints["total_constraints"] / avg_time if avg_time > 0 else 0,
    }


def main():
    print("=" * 80)
    print("CANTOR TREE CIRCUIT BENCHMARK - ZK-STARK PROOF-OF-CONCEPT")
    print("=" * 80)
    print()
    
    # Test realistic heights for Cyberspace
    test_heights = [5, 8, 10, 12, 15, 18, 20]
    
    results = []
    for height in test_heights:
        print(f"Benchmarking height {height} ({2**height:,} leaves)...")
        try:
            result = benchmark_tree_height(height)
            results.append(result)
            print(f"  ✓ Execution: {result['avg_execution_time_sec']*1000:.2f} ms")
            print(f"  ✓ Constraints: {result['total_constraints']:,}")
            if result['avg_execution_time_sec'] > 0:
                print(f"  ✓ Throughput: {result['constraints_per_second']/1e6:.2f}M constraints/sec")
        except MemoryError:
            print(f"  ✗ Memory error (too many leaves)")
            break
        print()
    
    # Summary table
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'Height':>6} | {'Leaves':>12} | {'Constraints':>15} | {'Time (ms)':>10} | {'M Constraints/s':>15}")
    print("-" * 80)
    
    for r in results:
        time_ms = r['avg_execution_time_sec'] * 1000
        m_constraints_sec = r['constraints_per_second'] / 1e6
        print(f"{r['height']:>6} | {r['num_leaves']:>12,} | {r['total_constraints']:>15,} | {time_ms:>10.2f} | {m_constraints_sec:>15.2f}")
    
    print()
    print("=" * 80)
    print("STARK PROOF SIZE ESTIMATES (Based on Winterfell/Plonky3 benchmarks)")
    print("=" * 80)
    
    for r in results:
        # STARK proof size scales logarithmically
        # Approximate: 15KB base + 0.5KB per log2(constraints)
        import math
        log_constraints = math.log2(r['total_constraints']) if r['total_constraints'] > 0 else 0
        estimated_proof_size_kb = 15 + 0.5 * log_constraints
        estimated_verify_time_ms = 1 + 0.1 * log_constraints
        
        print(f"Height {r['height']:2d}: ~{estimated_proof_size_kb:5.1f} KB proof, ~{estimated_verify_time_ms:4.1f} ms verification")
    
    print()
    print("=" * 80)
    print("NOTES")
    print("=" * 80)
    print("""
- These benchmarks measure Python execution trace generation
- Actual STARK prover would be 10-100x slower (proof generation overhead)
- STARK verification would be ~1-10ms regardless of tree height
- For production: use Rust-based prover (Winterfell/Plonky3) via PyO3 bindings
- Constraint counts assume 5 constraints per Cantor pairing
    """)


if __name__ == "__main__":
    main()
