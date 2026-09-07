"""Unit tests for the HOSAKA client pieces: NIP-98, error mapping, the
verifier against local oracles, and the job record."""

import base64
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from coincurve import PrivateKey, PublicKeyXOnly

from cyberspace_cli import cloud_jobs
from cyberspace_cli.cloud_move import decide_action, spec_sidestep_landings
from cyberspace_cli.cloud_verify import verify_cloud_hop, verify_cloud_sidestep
from cyberspace_cli.hosaka import (
    CloudBusy,
    CloudHeightExceeded,
    CloudUnavailable,
    HosakaClient,
    Limits,
)
from cyberspace_cli.nip98 import nip98_authorization, nip98_event
from cyberspace_core.cantor import int_to_bytes_be_min, sha256
from cyberspace_core.movement import compute_hop_proof, compute_sidestep_proof, find_lca_height

SK = PrivateKey(bytes.fromhex("7f" * 32))
SK_HEX = SK.secret.hex()
PK_HEX = SK.public_key.format(compressed=True)[1:].hex()
PREV = "ab" * 32


def dsha(n: int) -> str:
    return sha256(sha256(int_to_bytes_be_min(n))).hex()


class TestNip98(unittest.TestCase):
    def test_event_is_bound_and_signed(self):
        url = "https://api.example/api/v1/hop?x=1"
        ev = nip98_event(SK_HEX, PK_HEX, url, "post")
        self.assertEqual(ev["kind"], 27235)
        tags = dict((t[0], t[1]) for t in ev["tags"])
        self.assertEqual(tags["u"], url)
        self.assertEqual(tags["method"], "POST")
        self.assertEqual(len(tags["nonce"]), 16)
        serialized = json.dumps([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]], separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(ev["id"], hashlib.sha256(serialized.encode()).hexdigest())
        self.assertTrue(PublicKeyXOnly(bytes.fromhex(PK_HEX)).verify(bytes.fromhex(ev["sig"]), bytes.fromhex(ev["id"])))
        # two events for the same request are different events (no replay)
        self.assertNotEqual(ev["id"], nip98_event(SK_HEX, PK_HEX, url, "post", created_at=ev["created_at"])["id"])

    def test_header_round_trips(self):
        header = nip98_authorization(SK_HEX, PK_HEX, "https://api.example/api/v1/balance", "GET")
        self.assertTrue(header.startswith("Nostr "))
        ev = json.loads(base64.b64decode(header[6:]))
        self.assertEqual(ev["pubkey"], PK_HEX)

    def test_mismatched_pubkey_refused(self):
        with self.assertRaises(ValueError):
            nip98_event(SK_HEX, "00" * 32, "https://x/y", "GET")


class _Resp:
    def __init__(self, body, status=200):
        self._body = json.dumps(body).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestClientErrors(unittest.TestCase):
    def _client(self):
        return HosakaClient("https://api.example", SK_HEX, PK_HEX)

    def _http_error(self, code, body):
        import urllib.error
        import io

        return urllib.error.HTTPError("https://api.example/x", code, "err", {}, io.BytesIO(json.dumps(body).encode()))

    def test_maps_height_busy_and_unavailable(self):
        c = self._client()
        cases = [
            (400, {"detail": {"error": "height_exceeds_hosaka_cap", "hint": "too tall"}}, CloudHeightExceeded),
            (429, {"detail": {"error": "service_busy"}}, CloudBusy),
            (503, {"detail": {"error": "payments_unavailable"}}, CloudUnavailable),
        ]
        for code, body, exc in cases:
            with mock.patch("urllib.request.urlopen", side_effect=self._http_error(code, body)):
                with self.assertRaises(exc):
                    c.limits()

    def test_signed_request_carries_authorization_for_exact_url(self):
        c = self._client()
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["token"] = req.get_header("X-job-token")
            return _Resp({"status": "computing"})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            c.start_job("j1")
            ev = json.loads(base64.b64decode(seen["auth"][6:]))
            self.assertEqual(dict((t[0], t[1]) for t in ev["tags"])["u"], "https://api.example/api/v1/jobs/j1/start")
            c.get_job("j1", "tok")
            self.assertEqual(seen["token"], "tok")
            self.assertIsNone(seen["auth"])


class TestDecisions(unittest.TestCase):
    def test_decide_action(self):
        lim = Limits(25, 29, 1000, 1000, 10**9, 3600)
        self.assertEqual(decide_action((20, 0, 0), lim), "hop")
        self.assertEqual(decide_action((26, 0, 0), lim), "sidestep")
        with self.assertRaises(CloudHeightExceeded):
            decide_action((30, 0, 0), lim)

    def test_spec_landings(self):
        v1 = 0b101_0111  # inside a block of 2^4 at bits 0..3
        # crossing up at h=5 (bit 4): first leaf of the upper child
        self.assertEqual(spec_sidestep_landings(v1, v1 + 16), (0b110_0000,))
        # crossing down: first leaf of the lower child, or its last leaf
        v = 0b110_0011
        self.assertEqual(spec_sidestep_landings(v, v - 4), (0b100_0000, 0b101_1111))


class TestVerifierAgainstOracles(unittest.TestCase):
    """Build a cloud-shaped result from the local reference computation and
    check that the verifier accepts it and rejects every mutation."""

    def _hop_result(self, x1, y1, z1, x2, y2, z2):
        proof = compute_hop_proof(x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=PREV, max_compute_height=12)

        def env(n):
            secret = sha256(int_to_bytes_be_min(n))
            return {"public_proof": sha256(secret).hex(), "secret_key": secret.hex(), "size_bytes": len(int_to_bytes_be_min(n))}

        heights = [find_lca_height(x1, x2), find_lca_height(y1, y2), find_lca_height(z1, z2)]
        return {
            "hop_n": env(proof.hop_n), "region_n": env(proof.region_n),
            "cantor_x": env(proof.cantor_x), "cantor_y": env(proof.cantor_y), "cantor_z": env(proof.cantor_z),
            "cantor_t": env(proof.cantor_t), "K": proof.terrain_k, "max_height": max(heights),
        }, proof

    def test_hop_accepts_reference_and_rejects_mutations(self):
        x1, y1, z1 = 1000, 2000, 3000
        x2, y2, z2 = 1000 + (1 << 9), 2000, 3001
        res, proof = self._hop_result(x1, y1, z1, x2, y2, z2)
        ok = verify_cloud_hop(res, x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=PREV, local_ceiling=12)
        self.assertEqual(ok, [])
        # below the local ceiling the axis root is recomputed and compared
        bad = json.loads(json.dumps(res)); bad["cantor_x"]["public_proof"] = "00" * 32; bad["cantor_x"]["secret_key"] = None
        self.assertTrue(any("cantor_x" in f for f in verify_cloud_hop(bad, x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=PREV, local_ceiling=12)))
        bad = json.loads(json.dumps(res)); bad["K"] = res["K"] + 1
        self.assertTrue(any(f.startswith("K") for f in verify_cloud_hop(bad, x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=PREV, local_ceiling=12)))
        bad = json.loads(json.dumps(res)); bad["cantor_t"]["public_proof"] = dsha(proof.cantor_t + 1); bad["cantor_t"]["secret_key"] = None
        self.assertTrue(any("cantor_t" in f for f in verify_cloud_hop(bad, x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=PREV, local_ceiling=12)))
        # a different previous event changes the temporal root
        self.assertTrue(verify_cloud_hop(res, x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex="cd" * 32, local_ceiling=12))
        # secret_key must hash to public_proof
        bad = json.loads(json.dumps(res)); bad["region_n"]["secret_key"] = "11" * 32
        self.assertTrue(any("region_n" in f for f in verify_cloud_hop(bad, x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=PREV, local_ceiling=12)))

    def test_sidestep_accepts_reference_and_rejects_mutations(self):
        x1, y1, z1 = (1 << 20) + 5, 44, 44
        x2 = (((x1 >> 6) << 6) + (1 << 5))   # first leaf of the upper child at h=6
        proof = compute_sidestep_proof(x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex=PREV)
        res = {
            "proof_hash": proof.proof_hash,
            "merkle_x": proof.merkle_x.hex(), "merkle_y": proof.merkle_y.hex(), "merkle_z": proof.merkle_z.hex(),
            "openings": {a: [[s.hex() for s in path] for path in proof.openings[a]] for a in ("x", "y", "z")},
            "lca_heights": list(proof.lca_heights), "bases": [(x1 >> 6) << 6, 44, 44],
            "terrain_k": proof.terrain_k, "region_m_hex": format(proof.region_m, "x"),
        }
        self.assertEqual(verify_cloud_sidestep(res, x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex=PREV), [])
        bad = json.loads(json.dumps(res)); bad["openings"]["x"][3][0] = "ff" * 32
        self.assertTrue(any("merkle_x" in f for f in verify_cloud_sidestep(bad, x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex=PREV)))
        bad = json.loads(json.dumps(res)); bad["merkle_y"] = "ee" * 32
        self.assertTrue(any("merkle_y" in f for f in verify_cloud_sidestep(bad, x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex=PREV)))
        bad = json.loads(json.dumps(res)); bad["proof_hash"] = "dd" * 32
        self.assertTrue(any("proof_hash" in f for f in verify_cloud_sidestep(bad, x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex=PREV)))
        # a v1 result, the destination path alone, is rejected (6.15)
        bad = json.loads(json.dumps(res)); bad["openings"]["x"] = res["openings"]["x"][:1]
        self.assertTrue(any("merkle_x" in f for f in verify_cloud_sidestep(bad, x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex=PREV)))
        # a tree built under another chain position is rejected under ours (6.4)
        theirs = compute_sidestep_proof(x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex="cd" * 32)
        bad = json.loads(json.dumps(res)); bad["merkle_x"] = theirs.merkle_x.hex(); bad["openings"]["x"] = [[s.hex() for s in p] for p in theirs.openings["x"]]
        self.assertTrue(any("merkle_x" in f for f in verify_cloud_sidestep(bad, x1, y1, z1, x2, y1, z1, plane=0, previous_event_id_hex=PREV)))


class TestCloudJobs(unittest.TestCase):
    def test_record_update_pending(self):
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("CYBERSPACE_HOME")
            os.environ["CYBERSPACE_HOME"] = td
            try:
                cloud_jobs.record({"job_id": "a", "state": "awaiting_payment", "action": "hop"})
                cloud_jobs.record({"job_id": "b", "state": "computing", "action": "sidestep"})
                self.assertEqual({j["job_id"] for j in cloud_jobs.pending()}, {"a", "b"})
                cloud_jobs.update("a", state="appended", event_id="e1")
                self.assertEqual([j["job_id"] for j in cloud_jobs.pending()], ["b"])
                self.assertEqual(cloud_jobs.get("a")["event_id"], "e1")
                self.assertIsNone(cloud_jobs.get("zzz"))
            finally:
                if old is None:
                    os.environ.pop("CYBERSPACE_HOME", None)
                else:
                    os.environ["CYBERSPACE_HOME"] = old


if __name__ == "__main__":
    unittest.main()
