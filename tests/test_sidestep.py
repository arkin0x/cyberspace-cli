"""Sidestep version 2 (CYBERSPACE_V2 section 6): seeded trees, openings,
Level 1 verification, against the spec's reference vectors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cyberspace_core.cantor import cantor_pair, int_to_bytes_be_min, sha256
from cyberspace_core.merkle_engine import parallel_merkle_root, parallel_merkle_root_with_proof
from cyberspace_core.movement import (
    AXIS_BYTE,
    SIDESTEP_DOMAIN,
    SIDESTEP_SAMPLES,
    SidestepProof,
    compute_axis_merkle_root,
    compute_axis_merkle_root_streaming,
    compute_sidestep_proof,
    decode_openings,
    encode_openings,
    find_lca_height,
    leaf_hasher,
    merkle_leaf,
    merkle_parent,
    sample_indices,
    seed_prefix,
    verify_axis_openings,
    verify_merkle_inclusion,
)

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "sidestep_v2.json").read_text())
ZERO = bytes(32)
RANGE = bytes(range(32))
PREFIX = seed_prefix(RANGE, 2)


class TestSeedAndLeaf:
    def test_prefix_layout(self):
        assert SIDESTEP_DOMAIN == b"CYBERSPACE_SIDESTEP_V2" and len(SIDESTEP_DOMAIN) == 22
        for v in VECTORS:
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


class TestReferenceVectors:
    @pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
    def test_root_samples_openings(self, v):
        prefix = seed_prefix(bytes.fromhex(v["prev"]), v["axis"])
        root, openings, h = compute_axis_merkle_root(prefix, v["axis"], int(v["v1"]), int(v["v2"]))
        assert h == v["height"] and root.hex() == v["root"]
        assert sample_indices(root, v["axis"], h) == v["samples"]
        assert [[s.hex() for s in p] for p in openings] == v["openings"]
        assert verify_axis_openings(prefix, v["axis"], int(v["v1"]), int(v["v2"]), root, openings)


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
    def test_every_opening_is_its_leafs_path(self, height):
        base = 9 << height
        levels = self._levels(base, height)
        for target in range(1 << height):
            root, openings = compute_axis_merkle_root_streaming(PREFIX, base, height, target_index=target, axis_byte=2)
            assert root == levels[-1][0] and openings[0] == self._path(levels, target)
            for idx, path in zip(sample_indices(root, 2, height), openings[1:]):
                assert path == self._path(levels, idx)

    def test_height_zero_and_bad_targets(self):
        root, openings = compute_axis_merkle_root_streaming(PREFIX, 42, 0)
        assert root == merkle_leaf(PREFIX, 42) and openings == []
        with pytest.raises(ValueError):
            compute_axis_merkle_root_streaming(PREFIX, 0, 3, target_index=8, axis_byte=2)

    def test_kept_levels_at_h18(self):
        base = 5 << 18
        v1, v2 = base + (1 << 17) - 1, base + (1 << 17)
        root, openings = compute_axis_merkle_root_streaming(PREFIX, base, 18, target_index=v2 - base, axis_byte=2)
        assert verify_axis_openings(PREFIX, 2, v1, v2, root, openings)


class TestParallelEngine:
    def test_parallel_root_and_openings_match_streaming(self):
        # Forced past the direct path so the split, the merge and the inner
        # paths are all exercised, with a small tree.
        height, base = 14, 3 << 14
        target = (1 << 13)
        root_s, openings_s = compute_axis_merkle_root_streaming(PREFIX, base, height, target_index=target, axis_byte=2)
        root_p, openings_p = parallel_merkle_root_with_proof(PREFIX, base, height, workers=2, target_index=target, axis_byte=2)
        assert root_p == root_s and openings_p == openings_s
        assert parallel_merkle_root(PREFIX, base, height, workers=2) == root_s


class TestToll:
    H, AXIS = 12, 2
    base = (0x1234567 >> 12) << 12
    v1, v2 = base + (1 << 11) - 1, base + (1 << 11)

    def test_movers_differ_copies_fail_axes_separate(self):
        alice, bob = seed_prefix(ZERO, self.AXIS), seed_prefix(RANGE, self.AXIS)
        ra, oa, _ = compute_axis_merkle_root(alice, self.AXIS, self.v1, self.v2)
        rb, _, _ = compute_axis_merkle_root(bob, self.AXIS, self.v1, self.v2)
        assert ra != rb
        assert verify_axis_openings(alice, self.AXIS, self.v1, self.v2, ra, oa)
        assert not verify_axis_openings(bob, self.AXIS, self.v1, self.v2, ra, oa)
        assert compute_axis_merkle_root(seed_prefix(ZERO, 0), 0, self.v1, self.v2)[0] != ra

    def test_fabricated_tree_fails_the_samples(self):
        alice = seed_prefix(ZERO, self.AXIS)
        fake = [hashlib.sha256(b"forge" + bytes([i])).digest() for i in range(self.H)]
        cur, i = merkle_leaf(alice, self.v2), self.v2 - self.base
        for s in fake:
            cur = merkle_parent(cur, s) if i % 2 == 0 else merkle_parent(s, cur)
            i //= 2
        assert verify_merkle_inclusion(alice, self.v2, fake, cur, self.H, self.base)
        assert not verify_axis_openings(alice, self.AXIS, self.v1, self.v2, cur, [fake] * (SIDESTEP_SAMPLES + 1))


class TestEncoding:
    def test_round_trip_and_v1_rejection(self):
        v = next(x for x in VECTORS if x["name"] == "zero-z-h5")
        openings = [[bytes.fromhex(s) for s in p] for p in v["openings"]]
        seg = encode_openings(openings)
        assert decode_openings(seg, v["height"]) == openings
        assert decode_openings(encode_openings(openings[:1]), v["height"]) is None
        assert decode_openings("", 0) == [] and decode_openings("zz", 0) is None


class TestSidestepProof:
    def test_full_proof_shape_and_hash(self):
        prev = RANGE.hex()
        proof = compute_sidestep_proof(1023, 100, 479, 1024, 100, 480, plane=0, previous_event_id_hex=prev)
        assert isinstance(proof, SidestepProof)
        assert proof.lca_heights == (11, 0, 6)
        assert len(proof.openings["x"]) == 9 and proof.openings["y"] == [] and len(proof.openings["z"]) == 9
        for axis, v1, v2 in (("x", 1023, 1024), ("z", 479, 480)):
            root = getattr(proof, f"merkle_{axis}")
            assert verify_axis_openings(seed_prefix(RANGE, AXIS_BYTE[axis]), AXIS_BYTE[axis], v1, v2, root, proof.openings[axis])
        mx, my, mz = (int.from_bytes(getattr(proof, f"merkle_{a}"), "big") for a in "xyz")
        assert proof.region_m == cantor_pair(cantor_pair(mx, my), mz)
        assert proof.proof_hash == sha256(sha256(int_to_bytes_be_min(proof.sidestep_n))).hex()
        assert find_lca_height(1023, 1024) == 11

    def test_rejects_bad_previous_id(self):
        with pytest.raises(ValueError):
            compute_sidestep_proof(7, 0, 0, 8, 0, 0, plane=0, previous_event_id_hex="ab" * 31)
