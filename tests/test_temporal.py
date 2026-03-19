"""Tests for the temporal axis (§5.5.2) and 4D hop proof (§5.5.3 / §5.7).

Golden vectors taken from CYBERSPACE_V2.md §5.6.1.
"""

import unittest

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256, sha256_int_hex
from cyberspace_core.movement import (
    HopProof,
    compute_axis_cantor,
    compute_hop_proof,
    compute_movement_proof_xyz,
    compute_subtree_cantor,
)
from cyberspace_core.terrain import terrain_k


class TestTerrainK(unittest.TestCase):
    def test_terrain_k_at_spec_vector_destination(self) -> None:
        """§5.6.1: K = 11 at destination (x2=4104, y2=0, z2=0, plane=0)."""
        k = terrain_k(x=4104, y=0, z=0, plane=0)
        self.assertEqual(k, 11)

    def test_terrain_k_range(self) -> None:
        """K must be in [0, 16] (popcount of 16 bits)."""
        k = terrain_k(x=0, y=0, z=0, plane=0)
        self.assertGreaterEqual(k, 0)
        self.assertLessEqual(k, 16)


class TestTemporalAxis(unittest.TestCase):
    def test_temporal_seed_from_zero_prev_id(self) -> None:
        """§5.5.2.2: t = 0 when previous_event_id is all zeros."""
        prev_id_hex = "0" * 64
        prev_id_int = int(prev_id_hex, 16)
        t = prev_id_int % (1 << 85)
        self.assertEqual(t, 0)

    def test_temporal_cantor_root_spec_vector(self) -> None:
        """§5.6.1: cantor_t = compute_subtree_cantor(0, 11) when t=0 and K=11."""
        t = 0
        k = 11
        t_base = (t >> k) << k
        self.assertEqual(t_base, 0)
        cantor_t = compute_subtree_cantor(t_base, k, max_compute_height=17)

    def test_previous_event_id_must_be_64_chars(self) -> None:
        with self.assertRaises(ValueError):
            compute_hop_proof(
                0, 0, 0,
                1, 0, 0,
                plane=0,
                previous_event_id_hex="0" * 63,
                max_compute_height=20,
            )

    def test_previous_event_id_must_be_lowercase(self) -> None:
        with self.assertRaises(ValueError):
            compute_hop_proof(
                0, 0, 0,
                1, 0, 0,
                plane=0,
                previous_event_id_hex="AA" * 32,
                max_compute_height=20,
            )

    def test_previous_event_id_must_be_hex(self) -> None:
        with self.assertRaises(ValueError):
            compute_hop_proof(
                0, 0, 0,
                1, 0, 0,
                plane=0,
                previous_event_id_hex="gg" * 32,
                max_compute_height=20,
            )


class TestHopProofGoldenVector(unittest.TestCase):
    """Spec §5.6.1: movement (0,0,0) → (4104,0,0), prev_id = zeros."""

    PREV_EVENT_ID_HEX = "0" * 64

    def test_spatial_region_n(self) -> None:
        """region_n = π(π(cantor_x, 0), 0)."""
        cantor_x = compute_axis_cantor(0, 4104, max_compute_height=20)
        cantor_y = compute_axis_cantor(0, 0, max_compute_height=20)
        cantor_z = compute_axis_cantor(0, 0, max_compute_height=20)
        self.assertEqual(cantor_y, 0)
        self.assertEqual(cantor_z, 0)
        region_n = cantor_pair(cantor_pair(cantor_x, cantor_y), cantor_z)

        # Verify via the spatial-only proof function.
        spatial = compute_movement_proof_xyz(0, 0, 0, 4104, 0, 0, max_compute_height=20)
        self.assertEqual(spatial.combined, region_n)

    def test_stable_lookup_id(self) -> None:
        """§5.6.1: lookup_id = sha256(sha256(int_to_bytes_be_min(region_n)))."""
        spatial = compute_movement_proof_xyz(0, 0, 0, 4104, 0, 0, max_compute_height=20)
        region_n = spatial.combined

        location_decryption_key = sha256(int_to_bytes_be_min(region_n))
        lookup_id = sha256(location_decryption_key).hex()
        self.assertEqual(
            lookup_id,
            "8d2463eb22301d97a1f7e33b90e473ba2eec69079f418a72609c3e4d2981669b",
        )

    def test_full_hop_proof_hash(self) -> None:
        """§5.6.1: proof_hash = sha256(sha256(int_to_bytes_be_min(hop_n)))."""
        proof = compute_hop_proof(
            0, 0, 0,
            4104, 0, 0,
            plane=0,
            previous_event_id_hex=self.PREV_EVENT_ID_HEX,
            max_compute_height=20,
        )

        self.assertEqual(proof.terrain_k, 11)
        self.assertEqual(proof.temporal_seed, 0)

        self.assertEqual(
            proof.proof_hash,
            "ed9d09ca697b2da29c9d042207ac8ef7aab40f6dde550e6467452aa0e2e8cac6",
        )

    def test_different_prev_id_produces_different_proof(self) -> None:
        """Different previous_event_id → different proof_hash, even for same spatial move."""
        proof_a = compute_hop_proof(
            0, 0, 0,
            4104, 0, 0,
            plane=0,
            previous_event_id_hex="0" * 64,
            max_compute_height=20,
        )
        proof_b = compute_hop_proof(
            0, 0, 0,
            4104, 0, 0,
            plane=0,
            previous_event_id_hex="ff" * 32,
            max_compute_height=20,
        )

        # Same spatial region.
        self.assertEqual(proof_a.region_n, proof_b.region_n)
        # Different temporal → different hop_n → different proof_hash.
        self.assertNotEqual(proof_a.proof_hash, proof_b.proof_hash)


class TestHopProofSmallMove(unittest.TestCase):
    """Sanity: a tiny move should succeed and produce a valid HopProof."""

    def test_adjacent_hop(self) -> None:
        # Use destination near the spec vector where K is known to be manageable (K=15).
        proof = compute_hop_proof(
            4199, 0, 0,
            4200, 0, 0,
            plane=0,
            previous_event_id_hex="ab" * 32,
            max_compute_height=20,
        )
        self.assertIsInstance(proof, HopProof)
        self.assertEqual(len(proof.proof_hash), 64)
        self.assertEqual(proof.terrain_k, 15)


if __name__ == "__main__":
    unittest.main()
