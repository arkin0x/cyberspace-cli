"""Residue openings, version 2 of the hop proof (CYBERSPACE_V2 5.9 to 5.13,
8.4, 8.7.1, 8.8), against the spec's golden vectors and its reference.

tests/fixtures/hop_residue_v2.json is the spec's hop-residue-vectors.json and
tests/fixtures/hop-residue-reference.py its hop-residue-reference.py, both
copied unchanged from arkin0x/cyberspace at SPEC_COMMIT; their SHA-256 are
asserted below. The vectors are not normative: where they disagree with the
text of CYBERSPACE_V2.md, the text is right."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
from pathlib import Path
from typing import Any, Dict, List

import pytest

import cyberspace_core.grandfathered as grandfathered
import cyberspace_core.residue as R
from cyberspace_cli.cloud_verify import cloud_hop_from_result, verify_cloud_hop
from cyberspace_cli.nostr_event import make_hop_event, new_event
from cyberspace_core.coords import coord_to_xyz, xyz_to_coord
from cyberspace_core.movement import compute_hop_proof, verify_hop_event, verify_hop_event_v1, verify_hop_tags

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
VECTORS_PATH = FIXTURES / "hop_residue_v2.json"
REFERENCE_PATH = FIXTURES / "hop-residue-reference.py"

# arkin0x/cyberspace master: #83 added the vectors; #50 (8b45430) is the reference they were written from.
SPEC_COMMIT = "06c287332651f99b75e609b7b098e165993750fd"
REFERENCE_COMMIT = "8b45430af330f6e93ee763716d33868706cc2879"
VECTORS_SHA256 = "29b2222d3768b173b82887d9fb992cda23044ef84cfcfca48dd049766c7c4d33"
REFERENCE_SHA256 = "cb42f244b998762adbae4007ea86106eea7685d88cfe847a28adcc92b504a86d"

DOC = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
PROVER = {v["name"]: v for v in DOC["prover"]}
GOLDEN = PROVER["golden-5.7"]
PUB = "11" * 32
GENESIS = "22" * 32


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


REF = _load("hop_residue_reference", REFERENCE_PATH)
GEN = _load("gen_grandfathered", ROOT / "scripts" / "gen_grandfathered.py")


def _hop(v: Dict[str, Any]):
    return bytes.fromhex(v["previous_event_id"]), int(v["c"], 16), int(v["C"], 16)


def _tags(v: Dict[str, Any]) -> List[List[str]]:
    """A hop's tags from a vector: a tag missing from the vector's tags is missing from the event."""
    tags = [["A", "hop"], ["e", GENESIS, "", "genesis"], ["e", v["previous_event_id"], "", "previous"], ["c", v["c"]], ["C", v["C"]]]
    return tags + [[name, v["tags"][name]] for name in ("proof", "mn", "mp") if name in v["tags"]]


def _event(v: Dict[str, Any]) -> Dict[str, Any]:
    return new_event(pubkey_hex=PUB, created_at=1790000000, kind=3333, tags=_tags(v))


def _be64s(values) -> bytes:
    return b"".join(int(x).to_bytes(8, "big") for x in values)


@pytest.fixture(scope="module")
def residues() -> Dict[str, List[int]]:
    """Every residue of every prover vector, computed once."""
    out = {}
    for name, v in PROVER.items():
        prev, c, C = _hop(v)
        out[name] = R.hop_residues(prev, R.hop_geometry(prev, c, C), workers=1)
    return out


class TestFixtures:
    def test_copied_unchanged(self):
        assert hashlib.sha256(VECTORS_PATH.read_bytes()).hexdigest() == VECTORS_SHA256
        assert hashlib.sha256(REFERENCE_PATH.read_bytes()).hexdigest() == REFERENCE_SHA256

    def test_provenance(self):
        p = DOC["provenance"]
        assert p["spec_commit"] == REFERENCE_COMMIT
        assert p["reference_sha256"] == REFERENCE_SHA256
        assert p["chain_rules_revision"] == "2026-10-08-residue-openings"

    def test_constants(self):
        c = DOC["constants"]
        for name in ("HOP_RESIDUE_PRIME_DOMAIN", "HOP_RESIDUE_LEAF_DOMAIN", "HOP_RESIDUE_GRIND_DOMAIN", "HOP_RESIDUE_SAMPLE_DOMAIN"):
            assert getattr(R, name) == c[name].encode() == getattr(REF, name)
        for name in ("HOP_SAMPLES", "RESIDUE_BLOCK", "PRIME_BITS", "WIDTH_DIVISOR", "HOP_GRIND_HEIGHT"):
            assert getattr(R, name) == c[name]
        assert list(R.SMALL_ODD_PRIMES) == c["SMALL_ODD_PRIMES"]
        assert [str(b) for b in R.HOP_REROLL_BUDGET] == c["HOP_REROLL_BUDGET"]  # decimal strings (format)
        assert R.PAD_LEAF.hex() == c["PAD_LEAF"]


class TestSingle:
    @pytest.mark.parametrize("v", DOC["single"], ids=lambda v: v["function"])
    def test_value(self, v):
        a = v["arguments"]
        prev = bytes.fromhex(a["previous_event_id"])
        if v["function"] == "hop_prime":
            assert str(R.derive_prime(prev, a["j"])) == v["value"] == str(R.hop_prime(prev, a["j"]))
        elif v["function"] == "compute_subtree_cantor mod p_0":
            p0 = R.hop_prime(prev, 0)
            assert str(R.residue_root(int(a["base"]), a["height"], p0)) == v["value"]
            assert str(R.residue_tree(int(a["base"]), a["height"], p0)) == v["value"]
        elif v["function"] == "leaf_hash":
            assert R.leaf_hash(prev, a["block"], [int(r) for r in a["residues"]]).hex() == v["value"]
        elif v["function"] == "attempt":
            assert R.attempt(prev, bytes.fromhex(a["seal"]), a["nonce"]).hex() == v["value"]
        else:
            raise AssertionError(f"unknown function {v['function']}")

    def test_index_above_2_32_does_not_wrap(self):
        prev = bytes(range(32))
        assert R.hop_prime(prev, (1 << 32) + 1) != R.hop_prime(prev, 1)
        with pytest.raises(ValueError):
            R.derive_prime(prev, 1 << 64)


class TestProver:
    @pytest.mark.parametrize("name", list(PROVER))
    def test_geometry(self, name):
        v = PROVER[name]
        prev, c, C = _hop(v)
        g = R.hop_geometry(prev, c, C)
        assert [(str(b), h) for b, h in g.axes] == [(a["base"], a["height"]) for a in v["axes"]]
        assert (g.temporal, g.h_max, g.m, g.depth, str(g.attempts)) == ((int(v["t_base"]), v["K"]), v["h_max"], v["m"], v["depth"], v["A"])
        assert g.m // R.RESIDUE_BLOCK == v["blocks"]
        assert coord_to_xyz(c) == tuple(int(v["from"][k]) for k in ("x", "y", "z")) + (v["from"]["plane"],)
        assert coord_to_xyz(C) == tuple(int(v["to"][k]) for k in ("x", "y", "z")) + (v["to"]["plane"],)

    @pytest.mark.parametrize("name", list(PROVER))
    def test_primes_and_roots(self, name):
        v = PROVER[name]
        prev, c, C = _hop(v)
        g = R.hop_geometry(prev, c, C)
        primes = R.hop_primes(prev, g.m, workers=1)
        assert [str(p) for p in primes[:8]] == v["primes_first_8"] and str(primes[-1]) == v["prime_last"]
        assert hashlib.sha256(_be64s(primes)).hexdigest() == v["primes_sha256"]
        p0 = primes[0]
        roots = [R.residue_root(b, h, p0) for b, h in g.axes] + [R.residue_root(*g.temporal, p0)]
        assert [str(r) for r in roots] == [v["roots_mod_p0"][k] for k in ("x", "y", "z", "t")]
        assert str(R.combine_residues(*roots, p0)) == v["roots_mod_p0"]["hop_n"] == str(R.hop_residue(g, p0))

    @pytest.mark.parametrize("name", list(PROVER))
    def test_residues_seal_attempt_draw(self, name, residues):
        v = PROVER[name]
        prev, c, C = _hop(v)
        rs = residues[name]
        assert [str(r) for r in rs[:8]] == v["residues_first_8"]
        assert hashlib.sha256(_be64s(rs)).hexdigest() == v["residues_sha256"]
        assert str(rs[0]) == v["roots_mod_p0"]["hop_n"]
        seal, levels = R.seal_levels(prev, rs)
        assert levels[0][0].hex() == v["leaf_0"] and seal.hex() == v["seal"]
        a = R.attempt_detail(prev, seal, v["nonce"])
        want = v["attempt"]
        assert (a.seed.hex(), str(a.g_base), str(a.r_g), a.G.hex()) == (want["seed"], want["g_base"], want["r_g"], want["G"])
        assert a.G.hex() == v["G"] and R.meets_price(a.G, int(v["A"]))
        assert R.attempt(prev, seal, 0).hex() == v["attempt_nonce_0"]
        assert all(not R.meets_price(R.attempt(prev, seal, n), int(v["A"])) for n in range(v["nonce"]))
        assert R.sample_indices(a.G, v["m"]) == v["indices"]

    @pytest.mark.parametrize("name", list(PROVER))
    def test_tags_byte_identical(self, name):
        v = PROVER[name]
        proof = R.prove_hop(*_hop(v), workers=1)
        assert (proof.proof, proof.mn, proof.mp) == (v["tags"]["proof"], v["tags"]["mn"], v["tags"]["mp"])
        assert len(proof.mp) == v["mp_length"] == R.mp_length(v["depth"])
        assert hashlib.sha256(proof.mp.encode()).hexdigest() == v["mp_sha256"]
        assert proof.nonce == v["nonce"] and proof.G.hex() == v["G"]

    @pytest.mark.parametrize("name", ["golden-5.7", "multi-axis-earth", "into-plane-1"])
    def test_every_backend_gives_the_same_residues(self, name, residues):
        prev, c, C = _hop(PROVER[name])
        g = R.hop_geometry(prev, c, C)
        backends = ["int", "decimal"] + (["gmpy2"] if R.HAS_GMPY2 else [])
        for backend in backends:
            assert R.hop_residues(prev, g, backend=backend, workers=1) == residues[name], backend
        with pytest.raises(ValueError):
            R.hop_residues(prev, g, backend="float")

    def test_parallel_paths_give_the_sequential_answers(self, monkeypatch):
        prev, c, C = _hop(GOLDEN)
        g = R.hop_geometry(prev, c, C)
        monkeypatch.setattr(R, "PARALLEL_PRIMES", 1)
        monkeypatch.setattr(R, "PARALLEL_ATTEMPTS", 1)
        assert R.hop_primes(prev, g.m, workers=3) == R.hop_primes(prev, g.m, workers=1)
        assert R.find_nonce(prev, bytes.fromhex(GOLDEN["seal"]), g.attempts, workers=3) == GOLDEN["nonce"]


class TestChecks:
    """The 16 Level 1 checks of the 5.7 hop, one at a time."""

    @pytest.mark.parametrize("s", DOC["checks"]["samples"], ids=lambda s: f"sample-{s['i']}")
    def test_sample(self, s):
        v = PROVER[DOC["checks"]["hop"]]
        prev, c, C = _hop(v)
        g = R.hop_geometry(prev, c, C)
        assert s["index"] == v["indices"][s["i"]]
        assert (s["block"], s["position"]) == divmod(s["index"], R.RESIDUE_BLOCK)
        p = R.hop_prime(prev, s["index"])
        assert str(p) == s["prime"] and str(R.hop_residue(g, p)) == s["residue"]
        block = [int(r) for r in s["block_residues"]]
        assert block[s["position"]] == int(s["residue"])
        leaf = R.leaf_hash(prev, s["block"], block)
        siblings = [bytes.fromhex(x) for x in s["siblings"]]
        assert leaf.hex() == s["leaf"] and len(siblings) == v["depth"]
        assert R.verify_path(leaf, s["block"], siblings, bytes.fromhex(v["seal"]))
        assert s["mp_offset"] == s["i"] * R.opening_width(v["depth"])
        opening = R.decode_openings(v["tags"]["mp"], v["depth"])[s["i"]]  # type: ignore[index]
        assert opening == (block, siblings)


VERIFIER = DOC["verifier"]


class TestVerifier:
    @pytest.mark.parametrize("v", VERIFIER, ids=lambda v: v["name"])
    def test_first_failure(self, v):
        prev, c, C = _hop(v)
        t = v["tags"]
        got = R.verify_hop_proof(prev, c, C, t.get("proof"), t.get("mn"), t.get("mp"), workers=1)
        want = v["first_failure"]
        if v["expected"] == "accept":
            assert got == [] and want is None
        else:
            assert len(got) == 1
            assert (got[0].step, got[0].sample) == (want["step"], want.get("sample"))

    @pytest.mark.parametrize("v", VERIFIER, ids=lambda v: v["name"])
    def test_all_failures_agree(self, v):
        prev, c, C = _hop(v)
        t = v["tags"]
        every = R.verify_hop_proof(prev, c, C, t.get("proof"), t.get("mn"), t.get("mp"), all_failures=True, workers=1)
        assert (every == []) == (v["expected"] == "accept")
        if every:
            want = v["first_failure"]
            assert (every[0].step, every[0].sample) == (want["step"], want.get("sample"))

    @pytest.mark.parametrize("v", VERIFIER, ids=lambda v: v["name"])
    def test_event_verdict(self, v):
        failures = verify_hop_event(_event(v))
        assert (failures == []) == (v["expected"] == "accept"), failures

    @pytest.mark.parametrize("v", VERIFIER, ids=lambda v: v["name"])
    def test_reference_agrees(self, v):
        prev, c, C = _hop(v)
        t = v["tags"]
        if "mn" in t and "mp" in t:
            assert REF.verify_hop(prev, c, C, t["proof"], t["mn"], t["mp"]) == (v["expected"] == "accept")

    def test_parallel_samples_give_the_same_failure(self, monkeypatch):
        monkeypatch.setattr(R, "PARALLEL_VERIFY_HEIGHT", 0)
        for name in ("golden-accepted", "middle-sibling-flipped", "last-sampled-residue-flipped"):
            v = next(x for x in VERIFIER if x["name"] == name)
            prev, c, C = _hop(v)
            t = v["tags"]
            got = R.verify_hop_proof(prev, c, C, t["proof"], t["mn"], t["mp"], workers=2)
            want = v["first_failure"]
            assert [(f.step, f.sample) for f in got] == ([] if want is None else [(want["step"], want.get("sample"))])

    def test_two_failures_are_both_reported(self):
        prev, c, C = _hop(GOLDEN)
        openings = R.decode_openings(GOLDEN["tags"]["mp"], GOLDEN["depth"])
        idx = GOLDEN["indices"]
        for s in (2, 9):
            openings[s][0][idx[s] % 8] ^= 1  # type: ignore[index]
        mp = R.encode_openings(openings)  # type: ignore[arg-type]
        every = R.verify_hop_proof(prev, c, C, GOLDEN["tags"]["proof"], GOLDEN["tags"]["mn"], mp, all_failures=True, workers=1)
        steps = {(f.step, f.sample) for f in every}
        assert ("residue", 2) in steps and ("residue", 9) in steps and ("path", 2) in steps
        assert (every[0].step, every[0].sample) == ("residue", 2)

    def test_too_tall_raises_after_form_and_price(self):
        prev, c, C = _hop(GOLDEN)
        t = GOLDEN["tags"]
        with pytest.raises(R.HopTooTall):
            R.verify_hop_proof(prev, c, C, t["proof"], t["mn"], t["mp"], max_height=12)
        assert R.verify_hop_proof(prev, c, C, t["proof"], "0" * 16, t["mp"], max_height=12)[0].step == "price"


class TestCodec:
    @pytest.mark.parametrize("mn", ["0x00000000000057", "+000000000000057", "0000_00000000057", " 000000000000057",
                                    "000000000000057 ", "000000000000005G", "00000000000000AB", "57", "0" * 17, "", None, 87])
    def test_mn_rejects_what_int_accepts(self, mn):
        assert R.decode_nonce(mn) is None

    def test_mn_round_trip(self):
        assert R.decode_nonce("0000000000000057") == 87 == R.decode_nonce(R.encode_nonce(87))
        with pytest.raises(ValueError):
            R.encode_nonce(1 << 64)

    @pytest.mark.parametrize("proof", ["AB" * 32, "ab" * 31, "ab" * 33, "0x" + "ab" * 31, "ab" * 31 + " a", "ab" * 31 + "a\n"])
    def test_seal_rejects(self, proof):
        assert R.decode_seal(proof) is None

    def test_mp_width_is_exact(self):
        mp, depth = GOLDEN["tags"]["mp"], GOLDEN["depth"]
        assert R.decode_openings(mp, depth) is not None
        for bad in (mp[:-1], mp + "0", mp[:100] + "_" + mp[101:], mp[:100] + " " + mp[101:], mp.upper()):
            assert R.decode_openings(bad, depth) is None
        assert R.decode_openings(mp, depth - 1) is None and R.decode_openings(mp, depth + 1) is None


class TestPricesAndSizes:
    def test_budgets(self):
        for row in DOC["prices"]["budgets"] + DOC["prices"]["reference_printed_budgets"]:
            assert str(R.reroll_budget(row["h"])) == row["B"] == str(REF.reroll_budget(row["h"]))

    def test_attempts(self):
        for row in DOC["prices"]["attempts"]:
            assert str(R.reroll_attempts(row["heights"])) == row["A"]

    def test_sizes(self):
        for row in DOC["sizes"]:
            m = R.residue_count(row["h_max"])
            assert (m, R.merkle_depth(m), R.mp_length(R.merkle_depth(m))) == (row["m"], row["depth"], row["mp_length"])


class TestEngines:
    def test_packed_engine_equals_the_tree(self):
        rng = random.Random(5)
        for _ in range(60):
            h = rng.randrange(0, 15)
            base = (rng.getrandbits(85) >> h) << h
            p = R.hop_prime(bytes(range(32)), rng.randrange(1 << 40))
            want = R.residue_tree(base, h, p)
            assert R.residue_root(base, h, p) == want == R.residue_engine(base, h, p) == REF.residue_tree(base, h, p)
            assert R.residue_root(base, h, p) == REF.compute_subtree_cantor(base, h) % p

    def test_every_level_k(self, monkeypatch):
        p = R.hop_prime(bytes(32), 3)
        base = 1 << 84
        want = R.residue_tree(base, 13, p)
        for k in range(1, 6):
            monkeypatch.setattr(R, "_packed_level", lambda h, k=k: k)
            assert R.residue_root(base, 13, p) == want, k

    def test_lane_reduction_boundary(self, monkeypatch):
        # more nodes than REDUCE_EVERY, and an odd modulus just below 2^62 (above
        # every hop prime), so the lanes come as close to their bound as they can
        p = (1 << 62) - 57
        monkeypatch.setattr(R, "_packed_level", lambda h: 3)
        for h in (10, 12):
            base = (1 << 85) - (1 << h)
            assert R.residue_root(base, h, p) == R.residue_tree(base, h, p)


class TestDifferential:
    """The spec's reference, imported by path: random small hops come out byte
    identical, and random mutations get the same verdict."""

    @staticmethod
    def _random_hop(rng):
        prev = rng.getrandbits(256).to_bytes(32, "big")
        x, y, z = (rng.getrandbits(85) for _ in range(3))
        moved = []
        for v in (x, y, z):
            h = rng.choice([0, 0, 1, 2, 3, 5, 7, 9])
            moved.append(v ^ (rng.randrange(1, 1 << h) if h else 0) & ((1 << 85) - 1))
        plane1, plane2 = rng.randrange(2), rng.randrange(2)
        return prev, xyz_to_coord(x, y, z, plane=plane1), xyz_to_coord(*moved, plane=plane2)

    def test_random_hops_byte_identical(self):
        rng = random.Random(3333)
        for _ in range(12):
            prev, c, C = self._random_hop(rng)
            mine = R.prove_hop(prev, c, C, workers=1)
            assert (mine.proof, mine.mn, mine.mp) == REF.prove(prev, c, C)
            assert R.audit_hop_proof(prev, c, C, mine.proof, mine.mn, mine.mp, workers=1) == []

    def test_random_mutations_verdict_equal(self):
        rng = random.Random(84)
        alphabet = "0123456789abcdefABCDEF x+_g"
        for _ in range(4):
            prev, c, C = self._random_hop(rng)
            proof, mn, mp = REF.prove(prev, c, C)
            for _ in range(30):
                tags = [proof, mn, mp]
                k = rng.randrange(3)
                s = tags[k]
                kind = rng.randrange(4)
                if kind == 0 and s:
                    i = rng.randrange(len(s))
                    s = s[:i] + rng.choice(alphabet) + s[i + 1:]
                elif kind == 1:
                    s = s[:-1] if s else s
                elif kind == 2:
                    s = s + rng.choice(alphabet)
                else:
                    s = s.upper()
                tags[k] = s
                mine = R.verify_hop_proof(prev, c, C, *tags, workers=1) == []
                assert mine == REF.verify_hop(prev, c, C, *tags), (k, kind)
            other = rng.getrandbits(256).to_bytes(32, "big")
            assert (R.verify_hop_proof(other, c, C, proof, mn, mp, workers=1) == []) == REF.verify_hop(other, c, C, proof, mn, mp)


class TestLevel2:
    def test_a_list_wrong_off_the_samples_passes_level_1_and_fails_level_2(self):
        v = PROVER["multi-axis-earth"]
        prev, c, C = _hop(v)
        g = R.hop_geometry(prev, c, C)
        true = R.hop_residues(prev, g, workers=1)
        for j in range(0, g.m, 37):
            mixed = list(true)
            mixed[j] += 1
            seal, levels = R.seal_levels(prev, mixed)
            nonce = R.find_nonce(prev, seal, g.attempts, workers=1)
            idx = R.sample_indices(R.attempt(prev, seal, nonce), g.m)
            if j in idx:
                continue
            tags = R.encode_tags(seal, nonce, [R.open_block(levels, mixed, i // 8) for i in idx])
            assert R.verify_hop_proof(prev, c, C, *tags, workers=1) == []
            assert [f.step for f in R.audit_hop_proof(prev, c, C, *tags, workers=1)] == ["seal"]
            return
        raise AssertionError("every trial sampled its wrong residue")


def _signed_v1_hop(content: str = "") -> Dict[str, Any]:
    v = GOLDEN
    tags = _tags({**v, "tags": {"proof": "ed9d09ca697b2da29c9d042207ac8ef7aab40f6dde550e6467452aa0e2e8cac6"}})
    return new_event(pubkey_hex=PUB, created_at=1790000000, kind=3333, tags=tags, content=content)


class TestGrandfatheredV1:
    @pytest.mark.parametrize("v", DOC["grandfathered_v1"], ids=lambda v: v["name"])
    def test_vector(self, v):
        listed = frozenset(eid for eid, _ in GEN.parse_list(v["grandfathered_v1_hops"]))
        failures = verify_hop_tags(_tags(v), event_id=v["event_id"], listed=listed)
        assert (failures == []) == (v["expected"] == "accept"), failures

    def test_the_section_5_7_version_1_proof_still_holds(self):
        x1, y1, z1, _ = coord_to_xyz(int(GOLDEN["c"], 16))
        x2, y2, z2, plane = coord_to_xyz(int(GOLDEN["C"], 16))
        v1 = compute_hop_proof(x1, y1, z1, x2, y2, z2, plane=plane, previous_event_id_hex=GOLDEN["previous_event_id"])
        assert v1.proof_hash == "ed9d09ca697b2da29c9d042207ac8ef7aab40f6dde550e6467452aa0e2e8cac6"
        assert REF.proof_hash_v1(bytes(32), int(GOLDEN["c"], 16), int(GOLDEN["C"], 16)) == v1.proof_hash
        assert verify_hop_event_v1(_signed_v1_hop()) == []

    def test_the_embedded_list_is_empty_until_the_census(self):
        assert grandfathered.GRANDFATHERED_V1_HOPS == frozenset()
        assert verify_hop_event(_signed_v1_hop()) == ["proof: a version 1 hop (no mn and no mp tag) not listed in grandfathered-v1-hops.txt (5.13)"]

    def test_listing_is_by_the_nip01_id(self, monkeypatch):
        ev = _signed_v1_hop()
        monkeypatch.setattr(grandfathered, "GRANDFATHERED_V1_HOPS", frozenset({ev["id"]}))
        assert verify_hop_event(ev) == []
        borrowed = dict(_signed_v1_hop(content="x"), id=ev["id"])  # a listed id on other content
        assert verify_hop_event(borrowed) != []
        no_id = {k: val for k, val in ev.items() if k != "id"}
        assert verify_hop_event(no_id) != []
        assert verify_hop_tags(ev["tags"], event_id=None, listed=frozenset({ev["id"]})) != []

    def test_a_listed_hop_is_still_checked_for_the_rest(self):
        listed = frozenset({"ab" * 32})
        base = _tags({**GOLDEN, "tags": {"proof": "ed" * 32}})
        assert verify_hop_tags(base, event_id="ab" * 32, listed=listed) == []
        assert verify_hop_tags(base + [["mn", "00000000000000AB"]], event_id="ab" * 32, listed=listed) != []
        assert verify_hop_tags(base + [["mp", "00"]], event_id="ab" * 32, listed=listed) != []
        assert verify_hop_tags(base + [["mn", "0" * 16], ["mn", "0" * 16]], event_id="ab" * 32, listed=listed) != []
        upper = [t if t[0] != "proof" else ["proof", "ED" * 32] for t in base]
        assert verify_hop_tags(upper, event_id="ab" * 32, listed=listed) != []
        bad_c = [t if t[0] != "c" else ["c", "zz"] for t in base]
        assert verify_hop_tags(bad_c, event_id="ab" * 32, listed=listed) != []


class TestListFormat:
    A, B = "ab" * 32, "cd" * 32

    def test_comments_empty_lines_and_commentary(self):
        text = f"# header\n\n{self.A} the 5.7 movement\n#{self.B}\n{self.B}\t audited\n"
        assert GEN.parse_list(text) == [(self.A, "the 5.7 movement"), (self.B, "audited")]
        assert GEN.parse_list("") == [] and GEN.parse_list("# only a comment") == []

    @pytest.mark.parametrize("text", [
        f" {'ab' * 32}\n",            # leading whitespace
        f" # {'ab' * 32}\n",          # an indented # is not a comment
        "   \n",                     # whitespace-only line
        "\t\n",
        f"{'ab' * 32}\r\n",           # CR
        "# comment\r\n",
        f"{'ab' * 32}c\n",            # 65 hex characters
        f"{'ab' * 32}x note\n",       # no separator after the id
        f"{'AB' * 32}\n",             # uppercase
        f"{'ab' * 31}\n",             # too short
        f"0x{'ab' * 31}\n",
        f"{'ab' * 32}\n{'ab' * 32} again\n",  # duplicate
    ])
    def test_strict(self, text):
        with pytest.raises(ValueError):
            GEN.parse_list(text)

    def test_the_spec_lists_parse(self):
        hops_text = (FIXTURES.parent.parent / "src" / "cyberspace_core" / "grandfathered.py").read_text()
        assert "grandfathered-v1-hops.txt (0 ids)" in hops_text
        assert grandfathered.SPEC_COMMIT == SPEC_COMMIT


class TestBuilder:
    def _proof(self):
        return R.prove_hop(*_hop(PROVER["multi-axis-earth"]), workers=1)

    def _event(self, proof, **kw):
        v = PROVER["multi-axis-earth"]
        args = dict(pubkey_hex=PUB, created_at=1790000000, genesis_event_id=GENESIS, previous_event_id=v["previous_event_id"],
                    prev_coord_hex=v["c"], coord_hex=v["C"], proof_hex=proof.proof, nonce_hex=proof.mn, openings_hex=proof.mp)
        args.update(kw)
        return make_hop_event(**args)

    def test_proof_mn_mp_exactly_once_after_proof(self):
        proof = self._proof()
        ev = self._event(proof)
        names = [t[0] if t[0] != "e" else f"e:{t[3]}" for t in ev["tags"]]
        assert names == ["A", "e:genesis", "e:previous", "c", "C", "proof", "mn", "mp", "X", "Y", "Z", "S"]
        assert [t[1] for t in ev["tags"] if t[0] in ("proof", "mn", "mp")] == [proof.proof, proof.mn, proof.mp]
        assert verify_hop_event(ev) == []

    def test_version_1_shape_and_refusals(self):
        proof = self._proof()
        v1 = self._event(proof, nonce_hex=None, openings_hex=None)
        assert not any(t[0] in ("mn", "mp") for t in v1["tags"])
        with pytest.raises(ValueError):
            self._event(proof, openings_hex=None)
        with pytest.raises(ValueError):
            self._event(proof, nonce_hex="0x" + proof.mn[2:])
        with pytest.raises(ValueError):
            self._event(proof, proof_hex=proof.proof.upper())
        with pytest.raises(ValueError):
            self._event(proof, openings_hex=proof.mp.upper())

    def test_a_second_copy_of_a_read_tag_is_rejected(self):
        proof = self._proof()
        ev = self._event(proof)
        for name in ("proof", "mn", "mp"):
            twice = new_event(pubkey_hex=PUB, created_at=1790000000, kind=3333,
                              tags=ev["tags"] + [[name, next(t[1] for t in ev["tags"] if t[0] == name)]])
            assert any("exactly once" in f for f in verify_hop_event(twice)), name


class TestCloudVersion2:
    def _result(self):
        v = PROVER["multi-axis-earth"]
        prev, c, C = _hop(v)
        (x1, y1, z1, _), (x2, y2, z2, plane) = coord_to_xyz(c), coord_to_xyz(C)
        proof = R.prove_hop(prev, c, C, workers=1)
        res = {"seal": proof.proof, "mn": proof.mn, "mp": proof.mp, "K": proof.terrain_k, "max_height": proof.geometry.h_max}
        return res, (x1, y1, z1, x2, y2, z2), dict(plane=plane, previous_event_id_hex=v["previous_event_id"], local_ceiling=8)

    def test_accepts_and_builds_a_version_2_hop(self):
        res, xyz, kw = self._result()
        assert verify_cloud_hop(res, *xyz, **kw) == []
        hop = cloud_hop_from_result({"id": "job", "result": res, "cost_msats": 1000}, *xyz, plane=kw["plane"])
        assert (hop.proof, hop.mn, hop.mp) == (res["seal"], res["mn"], res["mp"])
        assert hop.terrain_k == res["K"] and hop.lookup_id == ""

    def test_rejects(self):
        res, xyz, kw = self._result()
        depth = R.hop_geometry(bytes.fromhex(kw["previous_event_id_hex"]), *[xyz_to_coord(*xyz[i:i + 3], plane=kw["plane"]) for i in (0, 3)]).depth
        openings = R.decode_openings(res["mp"], depth)
        openings[0][0][0] ^= 1  # type: ignore[index]
        flipped = dict(res, mp=R.encode_openings(openings))  # type: ignore[arg-type]
        assert verify_cloud_hop(flipped, *xyz, **kw)
        assert any(f.startswith("mp") for f in verify_cloud_hop({k: val for k, val in res.items() if k != "mp"}, *xyz, **kw))
        assert any(f.startswith("K") for f in verify_cloud_hop(dict(res, K=res["K"] + 1), *xyz, **kw))
        assert verify_cloud_hop(res, *xyz, **dict(kw, previous_event_id_hex="cd" * 32))
        assert verify_cloud_hop(dict(res, mn="0x" + res["mn"][2:]), *xyz, **kw)
        assert verify_cloud_hop(dict(res, seal=res["seal"].upper()), *xyz, **kw)


class TestMoveCommand:
    """The move command's own hops: version 2, each read tag once, accepted by
    this verifier and by the spec's reference. The cloud is off and every
    socket connection fails the test, so nothing reaches HOSAKA."""

    def test_move_to_and_toward_write_verifiable_version_2_hops(self, tmp_path, monkeypatch):
        import contextlib
        import io
        import socket

        def no_network(*args, **kwargs):
            raise AssertionError(f"network access from a test: {args[1:] or kwargs}")

        monkeypatch.setattr(socket.socket, "connect", no_network)
        monkeypatch.setattr(socket, "create_connection", no_network)

        from cyberspace_cli import chains
        from cyberspace_cli.cli import move
        from cyberspace_cli.nostr_event import make_spawn_event
        from cyberspace_cli.state import STATE_VERSION, CyberspaceState, save_state

        monkeypatch.setenv("CYBERSPACE_HOME", str(tmp_path))
        c0 = xyz_to_coord(100, 200, 300, plane=0).to_bytes(32, "big").hex()
        genesis = make_spawn_event(pubkey_hex=PUB, created_at=1700000000, coord_hex=c0)
        chains.create_new_chain("t", genesis, overwrite=False)
        save_state(CyberspaceState(version=STATE_VERSION, privkey_hex="22" * 32, pubkey_hex=PUB, coord_hex=c0,
                                   active_chain_label="t", targets=[], active_target_label=""))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            move(to="140,201,300", by=None, toward=None, max_lca_height=8, max_hops=0, no_cloud=True)
            move(to=None, by=None, toward="180,230,310", max_lca_height=6, max_hops=0, no_cloud=True)
        events = chains.read_events("t")
        assert len(events) >= 3, out.getvalue()
        for prev, ev in zip(events, events[1:]):
            names = [t[0] for t in ev["tags"]]
            assert [names.count(n) for n in ("proof", "mn", "mp")] == [1, 1, 1]
            assert names.index("proof") + 1 == names.index("mn") and names.index("mn") + 1 == names.index("mp")
            assert verify_hop_event(ev) == []
            tag = {t[0]: t[1] for t in ev["tags"]}
            assert tag["c"] == (prev["tags"] and {t[0]: t[1] for t in prev["tags"]}.get("C"))
            assert REF.verify_hop(bytes.fromhex(prev["id"]), int(tag["c"], 16), int(tag["C"], 16), tag["proof"], tag["mn"], tag["mp"])


class TestCloudVersion1StillWorks:
    """Until HOSAKA switches (at once, with no result carrying both shapes), a
    result without seal, mn and mp is a version 1 result and builds a version 1 hop."""

    def test_version_1_result(self):
        from cyberspace_core.cantor import int_to_bytes_be_min, sha256

        x1, y1, z1, x2, y2, z2 = 1000, 2000, 3000, 1000 + (1 << 9), 2000, 3001
        prev = "ab" * 32
        proof = compute_hop_proof(x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=prev, max_compute_height=12)

        def env(n):
            secret = sha256(int_to_bytes_be_min(n))
            return {"public_proof": sha256(secret).hex(), "secret_key": secret.hex()}

        res = {"hop_n": env(proof.hop_n), "region_n": env(proof.region_n), "cantor_x": env(proof.cantor_x),
               "cantor_y": env(proof.cantor_y), "cantor_z": env(proof.cantor_z), "cantor_t": env(proof.cantor_t),
               "K": proof.terrain_k, "max_height": max(R.find_lca_height(a, b) for a, b in ((x1, x2), (y1, y2), (z1, z2)))}
        assert verify_cloud_hop(res, x1, y1, z1, x2, y2, z2, plane=0, previous_event_id_hex=prev, local_ceiling=12) == []
        hop = cloud_hop_from_result({"id": "job", "result": res}, x1, y1, z1, x2, y2, z2, plane=0)
        assert (hop.proof, hop.mn, hop.mp) == (proof.proof_hash, None, None)
        assert hop.lookup_id == res["region_n"]["public_proof"] and hop.terrain_k == proof.terrain_k
        ev = make_hop_event(pubkey_hex=PUB, created_at=1, genesis_event_id=GENESIS, previous_event_id=prev,
                            prev_coord_hex=xyz_to_coord(x1, y1, z1).to_bytes(32, "big").hex(),
                            coord_hex=xyz_to_coord(x2, y2, z2).to_bytes(32, "big").hex(),
                            proof_hex=hop.proof, nonce_hex=hop.mn, openings_hex=hop.mp)
        assert not any(t[0] in ("mn", "mp") for t in ev["tags"])
        assert verify_hop_event_v1(ev) == []
