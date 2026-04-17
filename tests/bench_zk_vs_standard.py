"""Benchmarks comparing ZK-STARK verification vs standard Cantor verification."""

import time
from cyberspace_core.cantor import build_hyperspace_proof
from cyberspace_core.zk_cantor import prove_cantor_tree, verify_cantor_tree


class TestZKVsStandardBenchmark:
    """Benchmark ZK-STARK vs standard Cantor verification."""

    def test_comparison_by_tree_size(self):
        """Compare verification times for different tree sizes."""
        print("\n" + "="*70)
        print("ZK-STARK vs Standard Cantor Verification Comparison")
        print("="*70)
        
        for tree_size in [4, 8, 16, 32]:
            leaves = list(range(1, tree_size + 1))
            
            # Standard verification: recompute full Cantor tree
            start = time.perf_counter()
            standard_root = build_hyperspace_proof(leaves)
            standard_time = time.perf_counter() - start
            
            # ZK: Generate proof
            start = time.perf_counter()
            zk_root, proof = prove_cantor_tree(leaves)
            proof_gen_time = time.perf_counter() - start
            
            # ZK verification
            start = time.perf_counter()
            is_valid = verify_cantor_tree(zk_root, leaves, proof)
            zk_verify_time = time.perf_counter() - start
            
            print(f"\nTree size: {tree_size} leaves")
            print(f"  Standard Cantor compute: {standard_time*1000:.3f}ms")
            print(f"  ZK proof generation:     {proof_gen_time*1000:.3f}ms")
            print(f"  ZK verification:         {zk_verify_time*1000:.3f}ms")
            print(f"  Proof size:              {len(proof.stark_proof)} bytes")
            print(f"  Constraint count:        {proof.constraint_count}")
            print(f"  Overhead factor:         {proof_gen_time/standard_time:.1f}x")
            assert is_valid
            assert standard_root == zk_root
        
        print("\n" + "="*70)

    def test_zk_verification_performance(self):
        """Document ZK verification performance across tree sizes."""
        print("\n" + "-"*70)
        print("ZK Verification Performance by Tree Size")
        print("-"*70)
        
        sizes = [8, 16, 32, 64]
        
        for size in sizes:
            leaves = list(range(1, size + 1))
            root, proof = prove_cantor_tree(leaves)
            
            # Multiple verification runs for averaging
            times = []
            for _ in range(100):
                start = time.perf_counter()
                verify_cantor_tree(root, leaves, proof)
                times.append(time.perf_counter() - start)
            
            avg_time = sum(times) / len(times)
            print(f"  {size:3d} leaves: {avg_time*1000:.3f}ms avg (proof: {len(proof.stark_proof)} bytes)")

    def test_proof_generation_overhead(self):
        """Measure the overhead of ZK proof generation vs standard computation."""
        print("\n" + "-"*70)
        print("ZK Proof Generation Overhead Analysis")
        print("-"*70)
        
        leaves = list(range(1, 16))
        
        # Standard: just compute Cantor root
        standard_times = []
        for _ in range(100):
            start = time.perf_counter()
            build_hyperspace_proof(leaves)
            standard_times.append(time.perf_counter() - start)
        
        # ZK: compute root + generate proof
        zk_times = []
        for _ in range(100):
            start = time.perf_counter()
            prove_cantor_tree(leaves)
            zk_times.append(time.perf_counter() - start)
        
        std_avg = sum(standard_times) / len(standard_times)
        zk_avg = sum(zk_times) / len(zk_times)
        
        print(f"\n  Standard Cantor (15 leaves): {std_avg*1000:.3f}ms avg")
        print(f"  ZK proof generation:         {zk_avg*1000:.3f}ms avg")
        print(f"  Overhead factor:             {zk_avg/std_avg:.1f}x")
        print(f"  Absolute overhead:           {(zk_avg-std_avg)*1000:.3f}ms")
        print(f"\n  Note: Mock implementation - production STARK will have higher overhead")
        print(f"        but enables O(1) verification vs O(N) for standard.")
