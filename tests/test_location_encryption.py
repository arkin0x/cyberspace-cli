import unittest
from cyberspace_core.location_encryption import derive_region_keys_from_region_n
from cyberspace_core.movement import compute_movement_proof_xyz


class TestLocationEncryption(unittest.TestCase):
    def test_lookup_id_matches_spec_vector_region(self) -> None:
        # CYBERSPACE_V2 §5.6.1: lookup_id from the known spatial region_n vector.
        spatial = compute_movement_proof_xyz(0, 0, 0, 4104, 0, 0, max_compute_height=20)
        _decryption_key, lookup_id_hex = derive_region_keys_from_region_n(spatial.combined)
        self.assertEqual(
            lookup_id_hex,
            "8d2463eb22301d97a1f7e33b90e473ba2eec69079f418a72609c3e4d2981669b",
        )


if __name__ == "__main__":
    unittest.main()
