import unittest

from cyberspace_core.coords import gps_to_dataspace_coord
from cyberspace_core.cantor import sha256, sha256_int_hex
from cyberspace_core.movement import compute_movement_proof_xyz
from cyberspace_cli.nostr_event import make_hop_event, make_spawn_event


class TestVectors(unittest.TestCase):
    def test_gps_golden_vectors_subset(self) -> None:
        # Consensus-critical outputs (copied from v2 selftest).
        vectors = [
            (
                "origin_equator_prime",
                "0",
                "0",
                "e040009249248048201201000049208000201009201200000040049201048240",
            ),
            (
                "north_pole",
                "90",
                "0",
                "e020004920020000120820120124900900100024124904920904124120100124",
            ),
            (
                "london",
                "51.5074",
                "-0.1278",
                "c49eeba5feb124bd3ec0f3a132977c8c33edbb111fdfd02cb35cea53075b9846",
            ),
            (
                "nyc",
                "40.7128",
                "-74.0060",
                "c4943fa01bb22b95946ec1605717047a3b79bd717d5d84e35a12cb56df76134a",
            ),
        ]
        for name, lat, lon, expected_hex in vectors:
            got = gps_to_dataspace_coord(lat, lon).to_bytes(32, "big").hex()
            self.assertEqual(got, expected_hex, msg=name)

    def test_movement_proof_doc_example(self) -> None:
        # From CYBERSPACE_V2.md example: (0,0,0) -> (3,2,1)
        proof = compute_movement_proof_xyz(0, 0, 0, 3, 2, 1)
        self.assertEqual(proof.cantor_x, 228)
        self.assertEqual(proof.cantor_y, 228)
        self.assertEqual(proof.cantor_z, 2)
        self.assertEqual(proof.combined, 5452446953)
        self.assertEqual(
            proof.proof_hash,
            "9306cfcf163adfa9a1f34933091a445bbbc77de02a1e504eba9d6bcd5950b414",
        )

        # Location-based encryption lookup id: sha256(sha256(cantor_number))
        encryption_key = sha256_int_hex(proof.combined)
        discovery_id = sha256(bytes.fromhex(encryption_key)).hex()
        self.assertEqual(encryption_key, proof.proof_hash)
        self.assertEqual(
            discovery_id,
            "1247b1caeb69145100d6adbb52943c36d72023b10a0f5f434d41311d0b0b339c",
        )

    def test_nostr_event_id_vectors(self) -> None:
        # These lock our NIP-01 serialization + tag ordering.
        pubkey = "00" * 32
        coord0 = "11" * 32
        coord1 = "22" * 32
        created0 = 1700000000
        created1 = 1700000123

        spawn = make_spawn_event(pubkey_hex=pubkey, created_at=created0, coord_hex=coord0)
        # Expected is derived from current implementation; change requires intentional bump.
        self.assertEqual(spawn["id"], "56a9dd855585a70e69928feb6163c2f72689856d58d823da6c0563d882eb0bba")

        hop = make_hop_event(
            pubkey_hex=pubkey,
            created_at=created1,
            genesis_event_id=spawn["id"],
            previous_event_id=spawn["id"],
            prev_coord_hex=coord0,
            coord_hex=coord1,
            proof_hash_hex="ab" * 32,
        )
        self.assertEqual(hop["id"], "4cda3483928f30e4c3dfd85cb71401f0a439601ef923e19cba57ca86853cc75e")


if __name__ == "__main__":
    unittest.main()
