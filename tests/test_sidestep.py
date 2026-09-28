"""Sidestep version 3 (CYBERSPACE_V2 section 6): seeded trees, the re-roll
price, openings drawn from G, Level 1 verification and the version 2
exemption list, against the spec's sidestep-reference.py vectors."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from functools import partial
from pathlib import Path

import pytest

import cyberspace_core.grandfathered as grandfathered
import cyberspace_core.merkle_engine as merkle_engine
from cyberspace_cli.nostr_event import make_sidestep_event, new_event
from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256
from cyberspace_core.coords import xyz_to_coord
from cyberspace_core.grandfathered import GRANDFATHERED_V2_SIDESTEPS, SPEC_COMMIT, is_grandfathered
from cyberspace_core.merkle_engine import parallel_first, parallel_merkle_root, parallel_merkle_tree
from cyberspace_core.movement import (
    AXIS_BYTE,
    SIDESTEP_DOMAIN,
    SIDESTEP_GRIND_DOMAIN,
    SIDESTEP_SAMPLE_DOMAIN,
    SIDESTEP_SAMPLES,
    SidestepProof,
    _nonce_meets_price,
    compute_axis_merkle_root,
    compute_axis_merkle_root_streaming,
    compute_sidestep_proof,
    decode_nonce,
    decode_openings,
    encode_nonce,
    encode_openings,
    find_lca_height,
    find_nonce,
    grind_hash,
    leaf_hasher,
    meets_price,
    merkle_leaf,
    merkle_parent,
    reroll_attempts,
    sample_indices,
    seed_prefix,
    verify_axis_openings,
    verify_merkle_inclusion,
    verify_sidestep_event,
    verify_sidestep_openings,
)

FIXTURES = Path(__file__).parent / "fixtures"
VECTORS = json.loads((FIXTURES / "sidestep_v3.json").read_text())
LISTED = json.loads((FIXTURES / "grandfathered_events.json").read_text())
ZERO = bytes(32)
RANGE = bytes(range(32))
PREFIX = seed_prefix(RANGE, 2)
GOLDEN_BASE = (0x1234567 >> 12) << 12
GOLDEN_SRC = (5, 7, GOLDEN_BASE + (1 << 11) - 1)
GOLDEN_DST = (5, 7, GOLDEN_BASE + (1 << 11))


def _roots(proof):
    return [proof.merkle_x, proof.merkle_y, proof.merkle_z]


class TestSeedAndLeaf:
    def test_prefix_layout(self):
        assert SIDESTEP_DOMAIN == b"CYBERSPACE_SIDESTEP_V2" and len(SIDESTEP_DOMAIN) == 22
        for v in VECTORS["axis_roots"]:
            assert seed_prefix(bytes.fromhex(v["prev"]), v["axis"]).hex() == v["prefix"]
        with pytest.raises(ValueError):
            seed_prefix(bytes(31), 0)

    def test_leaf_is_the_seeded_hash_and_resumes_from_the_midstate(self):
        leaf = leaf_hasher(PREFIX)
        for value in (0, 1, 255, 256, 1 << 84):
            assert leaf(value) == merkle_leaf(PREFIX, value) == sha256(PREFIX + int_to_bytes_be_min(value))

    def test_leaf_depends_on_seed_and_axis(self):
        assert merkle_leaf(PREFIX, 5) != merkle_leaf(seed_prefix(ZERO, 2), 5)
        assert merkle_leaf(PREFIX, 5) != merkle_leaf(seed_prefix(RANGE, 0), 5)


class TestGoldenVectors:
    """The values sidestep-reference.py prints at arkin0x/cyberspace 7f724d5."""

    def test_constants(self):
        assert SIDESTEP_GRIND_DOMAIN == b"CYBERSPACE_SIDESTEP_GRIND_V1" and len(SIDESTEP_GRIND_DOMAIN) == 28
        assert SIDESTEP_SAMPLE_DOMAIN == b"CYBERSPACE_SIDESTEP_SAMPLE_V2"
        assert SIDESTEP_SAMPLES == 8
        # 164 bytes, three SHA-256 blocks, the nonce inside the first
        assert len(SIDESTEP_GRIND_DOMAIN) + 8 + 32 + 3 * 32 == 164 and len(SIDESTEP_GRIND_DOMAIN) + 8 <= 64

    def test_axis_roots_unchanged_from_version_2(self):
        assert compute_axis_merkle_root(seed_prefix(ZERO, 0), 0, 0).root.hex() == "803e23af5b006f6542e43cb30a70e0229916586105eb230e5d8796984d5b0901"
        assert compute_axis_merkle_root(seed_prefix(ZERO, 2), GOLDEN_BASE, GOLDEN_BASE + (1 << 4)).root.hex() == "202ede33045254297d335033c68b2fa05e6a47be1756abe7fee8caeedd89dcd6"
        assert compute_axis_merkle_root(seed_prefix(RANGE, 1), 1 << 40, (1 << 40) + (1 << 8)).root.hex() == "badf31e4bf617b2cddaa7f5b560ead66ed34198523a2b8ae4f45b624103cda92"

    def test_the_crossing(self):
        proof = compute_sidestep_proof(*GOLDEN_SRC, *GOLDEN_DST, plane=0, previous_event_id_hex=ZERO.hex())
        assert proof.lca_heights == (0, 0, 12)
        assert reroll_attempts(proof.lca_heights) == 512
        assert proof.nonce == 175 and encode_nonce(proof.nonce) == "00000000000000af"
        G = grind_hash(ZERO, _roots(proof), proof.nonce)
        assert G.hex() == "0067d4a60e171a3f6007da903f999c0eb441115369fa2d07f9424af4dd5f985a"
        assert sample_indices(G, AXIS_BYTE["z"], 12)[0] == 2113
        # searched upward from 0: every smaller nonce misses the price
        assert not any(meets_price(grind_hash(ZERO, _roots(proof), n), 512) for n in range(175))


class TestReferenceVectors:
    @pytest.mark.parametrize("v", VECTORS["axis_roots"], ids=[v["name"] for v in VECTORS["axis_roots"]])
    def test_axis_root(self, v):
        tree = compute_axis_merkle_root(seed_prefix(bytes.fromhex(v["prev"]), v["axis"]), int(v["v1"]), int(v["v2"]))
        assert (tree.root.hex(), tree.base, tree.height) == (v["root"], v["base"], v["height"])

    @pytest.mark.parametrize("v", VECTORS["crossings"], ids=[v["name"] for v in VECTORS["crossings"]])
    def test_crossing(self, v):
        prev = bytes.fromhex(v["prev"])
        proof = compute_sidestep_proof(*v["src"], *v["dst"], plane=0, previous_event_id_hex=v["prev"])
        assert list(proof.lca_heights) == v["heights"]
        assert [r.hex() for r in _roots(proof)] == v["roots"]
        assert reroll_attempts(proof.lca_heights) == v["attempts"]
        assert proof.nonce == v["nonce"] and encode_nonce(proof.nonce) == v["mn"]
        G = grind_hash(prev, _roots(proof), proof.nonce)
        assert G.hex() == v["G"]
        assert [sample_indices(G, AXIS_BYTE[a], h) for a, h in zip("xyz", v["heights"])] == v["samples"]
        assert ":".join(encode_openings(proof.openings[a]) for a in "xyz") == v["mp"]
        assert verify_sidestep_openings(prev, v["src"], v["dst"], _roots(proof), proof.nonce, proof.openings) == []


class TestPrice:
    def test_attempts(self):
        assert reroll_attempts((0, 0, 0)) == 1
        assert reroll_attempts((0, 0, 1)) == 1
        assert reroll_attempts((0, 0, 12)) == 512
        assert reroll_attempts((11, 0, 6)) == 264          # 2112 leaves: exact, not a power of two
        assert reroll_attempts((85, 85, 85)) == 3 << 82

    def test_meets_price_is_the_integer_threshold(self):
        top = (1 << 256) // 512
        assert meets_price((top - 1).to_bytes(32, "big"), 512)
        assert not meets_price(top.to_bytes(32, "big"), 512)
        assert meets_price(b"\xff" * 32, 1)

    def test_a_nonce_that_misses_the_price_is_rejected(self):
        proof = compute_sidestep_proof(*GOLDEN_SRC, *GOLDEN_DST, plane=0, previous_event_id_hex=ZERO.hex())
        bad = next(n for n in range(1000) if not meets_price(grind_hash(ZERO, _roots(proof), n), 512))
        failures = verify_sidestep_openings(ZERO, GOLDEN_SRC, GOLDEN_DST, _roots(proof), bad, proof.openings)
        assert failures and failures[0].startswith("mn:")

    def test_a_version_2_proof_is_rejected(self):
        # version 2 drew the samples from M_axis under the V1 sample domain
        proof = compute_sidestep_proof(*GOLDEN_SRC, *GOLDEN_DST, plane=0, previous_event_id_hex=ZERO.hex())
        prefix = seed_prefix(ZERO, 2)
        tree = compute_axis_merkle_root(prefix, GOLDEN_SRC[2], GOLDEN_DST[2])
        v2_idx = [int.from_bytes(sha256(b"CYBERSPACE_SIDESTEP_SAMPLE_V1" + tree.root + bytes([2]) + i.to_bytes(4, "big")), "big") % (1 << 12) for i in range(8)]
        v2_openings = {"x": [], "y": [], "z": tree.paths([GOLDEN_DST[2] - GOLDEN_BASE] + v2_idx)}
        for nonce in (0, proof.nonce):
            assert verify_sidestep_openings(ZERO, GOLDEN_SRC, GOLDEN_DST, _roots(proof), nonce, v2_openings)

    def test_parallel_search_finds_the_sequential_nonce(self):
        proof = compute_sidestep_proof(*GOLDEN_SRC, *GOLDEN_DST, plane=0, previous_event_id_hex=ZERO.hex())
        check = partial(_nonce_meets_price, ZERO, tuple(_roots(proof)), 512)
        assert parallel_first(check, chunk=16, workers=3) == 175
        assert parallel_first(check, start=176, chunk=64, workers=2) == next(n for n in range(176, 10**5) if check(n))
        assert find_nonce(ZERO, _roots(proof), 512, workers=1) == 175

    def test_nonce_encoding(self):
        assert encode_nonce(0) == "0" * 16 and encode_nonce(175) == "00000000000000af" and encode_nonce((1 << 64) - 1) == "f" * 16
        assert decode_nonce("00000000000000af") == 175 and decode_nonce("f" * 16) == (1 << 64) - 1
        for bad in ("00000000000000AF", "0000000000000af", "000000000000000af", "000000000000000g",
                    " 00000000000000a", "0000000_0000000a", "+00000000000000a", None, 175):
            assert decode_nonce(bad) is None, bad
        with pytest.raises(OverflowError):
            encode_nonce(1 << 64)
        with pytest.raises(ValueError):
            grind_hash(ZERO, [ZERO] * 3, 1 << 64)


class TestStreaming:
    def _levels(self, base, height):
        level = [merkle_leaf(PREFIX, base + i) for i in range(1 << height)]
        out = [level]
        while len(level) > 1:
            level = [merkle_parent(level[i], level[i + 1]) for i in range(0, len(level), 2)]
            out.append(level)
        return out

    def _path(self, levels, index):
        siblings = []
        for depth in range(len(levels) - 1):
            siblings.append(levels[depth][index ^ 1])
            index >>= 1
        return siblings

    @pytest.mark.parametrize("height", [1, 2, 3, 5])
    def test_every_path_is_its_leafs_path(self, height):
        base = 9 << height
        levels = self._levels(base, height)
        tree = compute_axis_merkle_root_streaming(PREFIX, base, height)
        assert tree.root == levels[-1][0] and (tree.base, tree.height) == (base, height)
        assert tree.paths(range(1 << height)) == [self._path(levels, i) for i in range(1 << height)]
        G = sha256(b"any G")
        opened = tree.openings(3 % (1 << height), G, 2)
        assert opened == [self._path(levels, i) for i in [3 % (1 << height)] + sample_indices(G, 2, height)]

    def test_height_zero_and_bad_index(self):
        tree = compute_axis_merkle_root_streaming(PREFIX, 42, 0)
        assert tree.root == merkle_leaf(PREFIX, 42) and tree.openings(0, ZERO, 2) == []
        with pytest.raises(ValueError):
            compute_axis_merkle_root_streaming(PREFIX, 0, 3).paths([8])

    def test_kept_levels_at_h18(self):
        base = 5 << 18
        v1, v2 = base + (1 << 17) - 1, base + (1 << 17)
        tree = compute_axis_merkle_root_streaming(PREFIX, base, 18)
        G = sha256(b"any G")
        assert verify_axis_openings(PREFIX, 2, v1, v2, tree.root, tree.openings(v2 - base, G, 2), G)


class TestParallelEngine:
    # Forced past the direct path so the split, the merge and the inner paths
    # are all exercised, with a small tree.
    HEIGHT, BASE, TARGET = 14, 3 << 14, 1 << 13

    def _indices(self):
        return [self.TARGET] + sample_indices(sha256(b"any G"), 2, self.HEIGHT) + [0, (1 << self.HEIGHT) - 1]

    def test_parallel_tree_matches_streaming(self):
        streaming = compute_axis_merkle_root_streaming(PREFIX, self.BASE, self.HEIGHT)
        parallel = parallel_merkle_tree(PREFIX, self.BASE, self.HEIGHT, workers=2)
        assert parallel.root == streaming.root and parallel.paths(self._indices()) == streaming.paths(self._indices())
        assert parallel_merkle_root(PREFIX, self.BASE, self.HEIGHT, workers=2) == streaming.root

    def test_pooled_path_rebuilds_match(self, monkeypatch):
        monkeypatch.setattr(merkle_engine, "PARALLEL_PATH_HEIGHT", 0)
        streaming = compute_axis_merkle_root_streaming(PREFIX, self.BASE, self.HEIGHT)
        parallel = parallel_merkle_tree(PREFIX, self.BASE, self.HEIGHT, workers=2)
        assert parallel.paths(self._indices()) == streaming.paths(self._indices())


class TestToll:
    H, AXIS = 12, 2

    def test_movers_differ_copies_fail_axes_separate(self):
        alice = compute_sidestep_proof(*GOLDEN_SRC, *GOLDEN_DST, plane=0, previous_event_id_hex=ZERO.hex())
        bob = compute_sidestep_proof(*GOLDEN_SRC, *GOLDEN_DST, plane=0, previous_event_id_hex=RANGE.hex())
        assert alice.merkle_z != bob.merkle_z
        assert verify_sidestep_openings(ZERO, GOLDEN_SRC, GOLDEN_DST, _roots(alice), alice.nonce, alice.openings) == []
        assert verify_sidestep_openings(RANGE, GOLDEN_SRC, GOLDEN_DST, _roots(alice), alice.nonce, alice.openings)
        assert compute_axis_merkle_root(seed_prefix(ZERO, 0), *GOLDEN_SRC[2:], GOLDEN_DST[2]).root != alice.merkle_z

    def test_fabricated_tree_fails_the_samples(self):
        # the destination-only check of version 1 passes a tree that was never built...
        alice = seed_prefix(ZERO, self.AXIS)
        v2 = GOLDEN_DST[2]
        fake = [hashlib.sha256(b"forge" + bytes([i])).digest() for i in range(self.H)]
        cur, i = merkle_leaf(alice, v2), v2 - GOLDEN_BASE
        for s in fake:
            cur = merkle_parent(cur, s) if i % 2 == 0 else merkle_parent(s, cur)
            i //= 2
        assert verify_merkle_inclusion(alice, v2, fake, cur, self.H, GOLDEN_BASE)
        # ...and the sampled openings refuse it, even with the price paid
        honest = compute_sidestep_proof(*GOLDEN_SRC, *GOLDEN_DST, plane=0, previous_event_id_hex=ZERO.hex())
        roots = [honest.merkle_x, honest.merkle_y, cur]
        nonce = find_nonce(ZERO, roots, reroll_attempts((0, 0, self.H)))
        failures = verify_sidestep_openings(ZERO, GOLDEN_SRC, GOLDEN_DST, roots, nonce, {"x": [], "y": [], "z": [fake] * (SIDESTEP_SAMPLES + 1)})
        assert failures == ["merkle_z: openings do not prove the seeded tree"]


class TestEncoding:
    def test_round_trip_and_v1_rejection(self):
        v = next(x for x in VECTORS["crossings"] if x["name"] == "zero-xyz-h3-h4-h5")
        for segment, h in zip(v["mp"].split(":"), v["heights"]):
            openings = decode_openings(segment, h)
            assert openings is not None and len(openings) == SIDESTEP_SAMPLES + 1 and encode_openings(openings) == segment
            assert decode_openings(encode_openings(openings[:1]), h) is None
        assert decode_openings("", 0) == [] and decode_openings("zz", 0) is None


class TestSidestepProof:
    def test_full_proof_shape_and_hash(self):
        prev = RANGE.hex()
        proof = compute_sidestep_proof(1023, 100, 479, 1024, 100, 480, plane=0, previous_event_id_hex=prev)
        assert isinstance(proof, SidestepProof)
        assert proof.lca_heights == (11, 0, 6)
        assert len(proof.openings["x"]) == 9 and proof.openings["y"] == [] and len(proof.openings["z"]) == 9
        assert meets_price(grind_hash(RANGE, _roots(proof), proof.nonce), 264)
        assert verify_sidestep_openings(RANGE, (1023, 100, 479), (1024, 100, 480), _roots(proof), proof.nonce, proof.openings) == []
        mx, my, mz = (int.from_bytes(r, "big") for r in _roots(proof))
        assert proof.region_m == cantor_pair(cantor_pair(mx, my), mz)
        assert proof.proof_hash == sha256(sha256(int_to_bytes_be_min(proof.sidestep_n))).hex()
        assert find_lca_height(1023, 1024) == 11

    def test_rejects_bad_previous_id(self):
        with pytest.raises(ValueError):
            compute_sidestep_proof(7, 0, 0, 8, 0, 0, plane=0, previous_event_id_hex="ab" * 31)


PREV_HEX = "5c" * 32


def _event(src, dst, *, prev_hex=PREV_HEX, plane=0, **override):
    """A version 3 sidestep event for the crossing, with any tag overridden
    (None drops it) and its id recomputed."""
    proof = compute_sidestep_proof(*src, *dst, plane=plane, previous_event_id_hex=prev_hex)
    ev = make_sidestep_event(
        pubkey_hex="11" * 32, created_at=1790000000, genesis_event_id="22" * 32, previous_event_id=prev_hex,
        prev_coord_hex=format(xyz_to_coord(*src, plane=plane), "064x"), coord_hex=format(xyz_to_coord(*dst, plane=plane), "064x"),
        proof_hash_hex=proof.proof_hash, merkle_roots_hex=":".join(r.hex() for r in _roots(proof)),
        merkle_proofs_hex=":".join(encode_openings(proof.openings[a]) for a in "xyz"),
        nonce_hex=encode_nonce(proof.nonce), lca_heights=proof.lca_heights,
    )
    if override:
        tags = []
        for t in ev["tags"]:
            if t[0] in override:
                if override[t[0]] is not None:
                    tags.append([t[0], override[t[0]]])
            else:
                tags.append(t)
        ev = new_event(pubkey_hex=ev["pubkey"], created_at=ev["created_at"], kind=ev["kind"], tags=tags, content=ev["content"])
    return ev, proof


class TestSidestepEvent:
    def test_a_version_3_event_verifies(self):
        ev, proof = _event(GOLDEN_SRC, GOLDEN_DST)
        names = [t[0] for t in ev["tags"]]
        assert names.index("mn") == names.index("mp") + 1
        assert dict((t[0], t[1]) for t in ev["tags"])["mn"] == encode_nonce(proof.nonce)
        assert verify_sidestep_event(ev) == []

    def test_multi_axis_event_verifies(self):
        ev, _ = _event((1023, 100, 479), (1024, 100, 480))
        assert verify_sidestep_event(ev) == []

    def test_mn_must_be_well_formed(self):
        with pytest.raises(ValueError):
            make_sidestep_event(
                pubkey_hex="11" * 32, created_at=0, genesis_event_id="22" * 32, previous_event_id=PREV_HEX,
                prev_coord_hex="00" * 32, coord_hex="00" * 32, proof_hash_hex="00" * 32, merkle_roots_hex="",
                merkle_proofs_hex="", nonce_hex="00000000000000AF", lca_heights=(0, 0, 0),
            )
        ev, _ = _event(GOLDEN_SRC, GOLDEN_DST, mn="00000000000000AF")
        assert verify_sidestep_event(ev) == ["mn: not exactly 16 lowercase hex characters"]

    def test_a_nonce_that_misses_the_price_is_rejected(self):
        ev, proof = _event(GOLDEN_SRC, GOLDEN_DST)
        prev = bytes.fromhex(PREV_HEX)
        bad = next(n for n in range(1000) if not meets_price(grind_hash(prev, _roots(proof), n), 512))
        ev, _ = _event(GOLDEN_SRC, GOLDEN_DST, mn=encode_nonce(bad))
        failures = verify_sidestep_event(ev)
        assert failures and failures[0].startswith("mn:") and "re-roll price" in failures[0]

    def test_an_unlisted_version_2_event_is_rejected(self):
        ev, _ = _event(GOLDEN_SRC, GOLDEN_DST, mn=None)
        assert not any(t[0] == "mn" for t in ev["tags"])
        assert verify_sidestep_event(ev) == ["mn: missing; a version 2 sidestep not listed in grandfathered-v2-sidesteps.txt (6.16)"]

    def test_a_version_1_segment_is_rejected(self):
        ev, proof = _event(GOLDEN_SRC, GOLDEN_DST)
        mp = dict((t[0], t[1]) for t in ev["tags"])["mp"]
        x, y, z = mp.split(":")
        ev, _ = _event(GOLDEN_SRC, GOLDEN_DST, mp=f"{x}:{y}:{z[:64 * 12]}")
        assert verify_sidestep_event(ev) == ["mp: axis z segment is malformed, or a version 1 single path (8.5, 6.15)"]

    def test_geometry_heights_and_proof_hash_are_checked(self):
        # two gibsons past the wall: a hop's job, not a sidestep's (6.3)
        ev, _ = _event(GOLDEN_SRC, (5, 7, GOLDEN_DST[2] + 1))
        assert any(f.startswith("geometry: axis z") for f in verify_sidestep_event(ev))
        ev, _ = _event(GOLDEN_SRC, GOLDEN_DST, hz="11")
        assert verify_sidestep_event(ev) == ["hz: tag '11' but the coordinates give 12"]
        ev, _ = _event(GOLDEN_SRC, GOLDEN_DST, proof="ab" * 32)
        assert verify_sidestep_event(ev) == ["proof: does not match the proof hash of the claimed roots (6.8)"]

    def test_a_copied_proof_fails_under_another_previous_event(self):
        ev, _ = _event(GOLDEN_SRC, GOLDEN_DST)
        tags = [["e", "77" * 32, "", "previous"] if t[0] == "e" and t[3:] == ["previous"] else t for t in ev["tags"]]
        copied = new_event(pubkey_hex=ev["pubkey"], created_at=ev["created_at"], kind=ev["kind"], tags=tags, content=ev["content"])
        assert verify_sidestep_event(copied)

    def test_not_a_sidestep(self):
        assert verify_sidestep_event({"tags": [["A", "hop"]]}) == ["A: not a sidestep"]


def _load_generator():
    path = Path(__file__).resolve().parents[1] / "scripts" / "gen_grandfathered.py"
    spec = importlib.util.spec_from_file_location("gen_grandfathered", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGrandfathered:
    def test_the_embedded_list(self):
        assert SPEC_COMMIT == "787cda3bd7c76fbe618b9b72e30ecafa19f05434"
        assert len(GRANDFATHERED_V2_SIDESTEPS) == 36
        assert all(len(i) == 64 and all(c in "0123456789abcdef" for c in i) for i in GRANDFATHERED_V2_SIDESTEPS)
        assert "393b58f707d94d31b3aa11a1326b46e54f9b14ae2864989bbcbe2a210aa76458" in GRANDFATHERED_V2_SIDESTEPS

    @pytest.mark.parametrize("ev", LISTED["sidesteps"], ids=[e["id"][:12] for e in LISTED["sidesteps"]])
    def test_listed_version_2_events_are_accepted(self, ev):
        assert not any(t[0] == "mn" for t in ev["tags"])
        assert is_grandfathered(ev, GRANDFATHERED_V2_SIDESTEPS)
        assert verify_sidestep_event(ev) == []

    def test_a_borrowed_id_is_not_listed(self):
        ev = json.loads(json.dumps(LISTED["sidesteps"][0]))
        ev["content"] += " "
        assert not is_grandfathered(ev, GRANDFATHERED_V2_SIDESTEPS)
        assert verify_sidestep_event(ev) == ["mn: missing; a version 2 sidestep not listed in grandfathered-v2-sidesteps.txt (6.16)"]

    def test_a_listed_event_is_still_checked_for_everything_else(self, monkeypatch):
        # A listed event's roots and openings are not re-checked; its geometry,
        # height tags and proof hash are.
        garbage, _ = _event(GOLDEN_SRC, GOLDEN_DST, mn=None, mp="::" + "ab" * 64 * 12 * 9)
        wrong_proof, _ = _event(GOLDEN_SRC, GOLDEN_DST, mn=None, proof="ab" * 32)
        too_far, _ = _event(GOLDEN_SRC, (5, 7, GOLDEN_DST[2] + 1), mn=None)
        monkeypatch.setattr(grandfathered, "GRANDFATHERED_V2_SIDESTEPS", frozenset({garbage["id"], wrong_proof["id"], too_far["id"]}))
        assert verify_sidestep_event(garbage) == []
        assert verify_sidestep_event(wrong_proof) == ["proof: does not match the proof hash of the claimed roots (6.8)"]
        assert any(f.startswith("geometry:") for f in verify_sidestep_event(too_far))

    def test_the_generator_reads_the_list_format(self):
        gen = _load_generator()
        a, b = "ab" * 32, "cd" * 32
        text = f"# header\n\n{a} pubkey 2026-09-08T04:42:17Z 0,0,19 L2-clean\n# more\n{b}\n"
        assert gen.parse_list(text) == [(a, "pubkey 2026-09-08T04:42:17Z 0,0,19 L2-clean"), (b, "")]
        with pytest.raises(ValueError):
            gen.parse_list(a.upper() + "\n")
        with pytest.raises(ValueError):
            gen.parse_list(f"{a}\n{a} again\n")
        rendered = gen.render("f" * 40, [(a, "note")], [(b, "")])
        namespace: dict = {}
        exec(compile(rendered, "grandfathered.py", "exec"), namespace)
        assert namespace["GRANDFATHERED_V2_SIDESTEPS"] == frozenset({a}) and namespace["GRANDFATHERED_V1_HYPERJUMPS"] == frozenset({b})
        assert namespace["SPEC_COMMIT"] == "f" * 40


class TestMoveCommand:
    def test_move_sidestep_appends_a_version_3_event(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from cyberspace_cli import chains
        from cyberspace_cli.cli import app
        from cyberspace_cli.nostr_event import make_spawn_event
        from cyberspace_cli.state import STATE_VERSION, CyberspaceState, save_state

        monkeypatch.setenv("CYBERSPACE_HOME", str(tmp_path))
        x, y, z = (1 << 13) - 1, 5, 5                     # touching the h14 wall
        c0 = format(xyz_to_coord(x, y, z, plane=0), "064x")
        chains.create_new_chain("s", make_spawn_event(pubkey_hex="11" * 32, created_at=1700000000, coord_hex=c0), overwrite=False)
        save_state(CyberspaceState(version=STATE_VERSION, privkey_hex="22" * 32, pubkey_hex="11" * 32, coord_hex=c0,
                                   active_chain_label="s", targets=[], active_target_label=""))
        r = CliRunner().invoke(app, ["move", "--to", f"{x + 1},{y},{z}", "--sidestep", "--no-cloud"], env={"CYBERSPACE_HOME": str(tmp_path)})
        assert r.exit_code == 0, r.output
        ev = chains.read_events("s")[-1]
        tags = {t[0]: t[1] for t in ev["tags"]}
        assert tags["A"] == "sidestep" and tags["hx"] == "14" and decode_nonce(tags["mn"]) is not None
        assert verify_sidestep_event(ev) == []
