import unittest

from cyberspace_core.coords import gps_to_dataspace_coord
from cyberspace_core.cantor import sha256, sha256_int_hex
from cyberspace_core.movement import compute_movement_proof_xyz
from cyberspace_cli.nostr_event import make_hop_event, make_spawn_event


class TestVectors(unittest.TestCase):
    def test_cantor_coord_input_accepts_missing_leading_zeros(self) -> None:
        # This mirrors `cyberspace cantor --from-coord/--to-coord` parsing behavior.
        # A coordinate may be provided without leading zeros; it must normalize to 32 bytes.
        from cyberspace_cli.parsing import normalize_hex_32

        self.assertEqual(normalize_hex_32("0x1"), "0" * 63 + "1")
        self.assertEqual(normalize_hex_32("1"), "0" * 63 + "1")

    def test_cantor_coord_vector_close_points(self) -> None:
        # Golden vector for `cyberspace cantor --from-coord/--to-coord`.
        # Two nearby points in xyz so LCA heights are small.
        from cyberspace_cli.parsing import normalize_hex_32
        from cyberspace_core.coords import coord_to_xyz
        from cyberspace_core.movement import compute_axis_cantor, find_lca_height
        from cyberspace_core.cantor import cantor_pair, sha256, sha256_int_hex

        # These are 256-bit coords with leading zeros omitted on purpose.
        from_coord = "0x2b50e80"
        to_coord = "0x2b50e88"

        from_hex = normalize_hex_32(from_coord)
        to_hex = normalize_hex_32(to_coord)

        self.assertEqual(from_hex, "0000000000000000000000000000000000000000000000000000000002b50e80")
        self.assertEqual(to_hex, "0000000000000000000000000000000000000000000000000000000002b50e88")

        c1 = int.from_bytes(bytes.fromhex(from_hex), "big")
        c2 = int.from_bytes(bytes.fromhex(to_hex), "big")

        x1, y1, z1, p1 = coord_to_xyz(c1)
        x2, y2, z2, p2 = coord_to_xyz(c2)

        self.assertEqual((x1, y1, z1, p1), (100, 200, 300, 0))
        self.assertEqual((x2, y2, z2, p2), (101, 200, 300, 0))

        self.assertEqual(find_lca_height(x1, x2), 1)
        self.assertEqual(find_lca_height(y1, y2), 0)
        self.assertEqual(find_lca_height(z1, z2), 0)

        cx = compute_axis_cantor(x1, x2)
        cy = compute_axis_cantor(y1, y2)
        cz = compute_axis_cantor(z1, z2)

        self.assertEqual(cx, 20402)
        self.assertEqual(cy, 200)
        self.assertEqual(cz, 300)

        combined = cantor_pair(cantor_pair(cx, cy), cz)
        encryption_key = sha256_int_hex(combined)
        discovery_id = sha256(bytes.fromhex(encryption_key)).hex()

        self.assertEqual(encryption_key, "4e02171a1986de2299e3abe37a00b419d853da9bcab7139d76189f5506b138f6")
        self.assertEqual(discovery_id, "b3e3141659d48d3f7e39a684ab9f193badc11497ea6c3d0f89fefd8e9dbc85c5")
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

    def test_large_cantor_encryption_and_discovery_ids(self) -> None:
        # Regression vector: this produces a huge combined Cantor number.
        # We intentionally assert on the 1-hash and 2-hash values (stable, fixed-size).
        from cyberspace_core.movement import compute_axis_cantor
        from cyberspace_core.cantor import cantor_pair, sha256, sha256_int_hex

        cx = compute_axis_cantor(0, 800)
        cy = compute_axis_cantor(0, 900)
        cz = compute_axis_cantor(0, 1000)
        combined = cantor_pair(cantor_pair(cx, cy), cz)

        encryption_key = sha256_int_hex(combined)
        discovery_id = sha256(bytes.fromhex(encryption_key)).hex()

        self.assertEqual(encryption_key, "d1ed6818770b37a3d68c97fd65cd07d3af24a705ef8eb681fea99172b8eadf0d")
        self.assertEqual(discovery_id, "7b67be1e49962882683bc3b3a1be728136754c9fbe9b9a75c4a3e2a629c2d97a")

    def test_axis_cantor_refuses_huge_height(self) -> None:
        from cyberspace_core.movement import compute_axis_cantor

        # 0 -> 2^30 implies an LCA height of 31, which is intentionally too large
        # for a single hop under a small max_compute_height.
        with self.assertRaises(ValueError):
            compute_axis_cantor(0, 1 << 30, max_compute_height=20)

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
