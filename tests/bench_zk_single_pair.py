"""Benchmarks for single Cantor pair ZK proof."""

import pytest
from cyberspace_core.zk_cantor import prove_single_cantor_pair, verify_single_cantor_pair


class TestSinglePairBenchmark:
    """Benchmark single Cantor pair ZK proof."""

    def test_proof_generation_time(self, benchmark):
        """Benchmark proof generation time."""

        def generate():
            return prove_single_cantor_pair(42, 17)

        result = benchmark(generate)
        z, proof = result

    def test_verification_time(self, benchmark):
        """Benchmark proof verification time."""
        z, proof = prove_single_cantor_pair(42, 17)

        def verify():
            return verify_single_cantor_pair(z, proof)

        result = benchmark(verify)
        assert result is True

    def test_full_cycle_performance(self, benchmark):
        """Benchmark prove + verify full cycle."""

        def full_cycle():
            z, proof = prove_single_cantor_pair(100, 200)
            return verify_single_cantor_pair(z, proof)

        result = benchmark(full_cycle)
        assert result is True
