"""DECK-0001 section 5, ride openings version 2: per-block leaves, the padded
root, the re-roll price (one height-16 Cantor tree per attempt) with samples
drawn from G, the absence of a zero-length ride and the exemption list, against the
spec's decks/hyperjump-reference.py vectors.

Real block hashes come from Bitcoin; like the reference, these tests use
synthetic ones chosen so every block has a small height."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import cyberspace_core.grandfathered as grandfathered
from cyberspace_cli.nostr_event import new_event
from cyberspace_core.cantor import sha256
from cyberspace_core.grandfathered import GRANDFATHERED_V1_HYPERJUMPS, is_grandfathered
from cyberspace_core.movement import encode_nonce, meets_price
from cyberspace_core.ride import (
    GRIND_HEIGHT,
    HYPERSPACE_GRIND_DOMAIN,
    HYPERSPACE_SAMPLE_DOMAIN,
    K_LINE,
    PAD_LEAF,
    SAMPLES,
    attempts_required,
    decode_ride_openings,
    encode_ride_openings,
    find_ride_nonce,
    grind_attempt,
    line_terrain_k,
    merkle_levels,
    path_of,
    prove_ride,
    ride_depth,
    ride_leaf,
    sample_indices,
    verify_ride,
    verify_ride_event,
)

LISTED = json.loads((Path(__file__).parent / "fixtures" / "grandfathered_events.json").read_text())
ZERO = bytes(32)
RANGE = bytes(range(32))
LO, HI = 900000, 900040
_hashes: dict = {}


def synthetic_block_hash(b: int) -> bytes:
    """The reference's stand-in: sha256(b"CYBERSPACE_TEST_BLOCK" || be64(b) || be32(j))
    for the smallest j that gives the block a height K + 6 <= 10."""
    if b not in _hashes:
        j = 0
        while True:
            h = sha256(b"CYBERSPACE_TEST_BLOCK" + b.to_bytes(8, "big") + j.to_bytes(4, "big"))
            if line_terrain_k(h) + K_LINE <= 10:
                _hashes[b] = h
                break
            j += 1
    return _hashes[b]


def no_block_data(b: int) -> bytes:
    raise AssertionError(f"block {b} was asked for, but a listed ride's leaves are not recomputed")


@pytest.fixture(scope="module")
def golden():
    return prove_ride(ZERO, LO, HI, synthetic_block_hash)


class TestGoldenVectors:
    """The values decks/hyperjump-reference.py prints at arkin0x/cyberspace 7f724d5."""

    def test_constants(self):
        assert (SAMPLES, GRIND_HEIGHT, K_LINE) == (32, 16, 6)
        assert HYPERSPACE_GRIND_DOMAIN == b"CYBERSPACE_HYPERSPACE_GRIND_V1"
        assert HYPERSPACE_SAMPLE_DOMAIN == b"CYBERSPACE_HYPERSPACE_SAMPLE_V2"

    def test_one_attempt(self):
        assert grind_attempt(ZERO, ZERO, 0).hex() == "4bac0e5bb9c3bd5058732e2715457c036f87144879e923cdd2a54eab31303707"

    def test_one_leaf(self):
        assert ride_leaf(ZERO, 900001, synthetic_block_hash(900001)).hex() == "ffde7ee869b9b0c4a780f2ac0f481e257070e96294e0a5ead72486857f24633a"

    def test_forty_blocks(self, golden):
        root, nonce, openings = golden
        assert root.hex() == "83187e3a539d79fa9d218843f37d25912b9fb7fbe3d198948d74063e0193a8f3"
        assert nonce == 0 and attempts_required(HI - LO) == 2
        G = grind_attempt(ZERO, root, nonce)
        assert G.hex() == "1ba2e1b836822a7d2263d6e4d83df1d6eb9b70cfa6f77c29ff79d4c09926b08e"
        assert sample_indices(G, HI - LO)[0] == 21
        assert len(openings) == SAMPLES and all(len(p) == ride_depth(HI - LO) == 6 for p in openings)

    def test_one_block(self):
        root, nonce, openings = prove_ride(RANGE, LO, LO + 1, synthetic_block_hash)
        assert root.hex() == "20ef123bafc81ad21a14ffc1d5ffe3be7481ff142a60c5021c0875ac6d2953f0" and nonce == 0
        G = grind_attempt(RANGE, root, nonce)
        assert G.hex() == "e1a04954bdc47c37af1eee22123da22faa2716529b1199fc2e91a9682197ef5f"
        assert sample_indices(G, 1) == [0] * SAMPLES
        assert encode_ride_openings(openings) == ":" * (SAMPLES - 1)


class TestLevel1:
    def test_an_honest_ride_passes(self, golden):
        assert verify_ride(ZERO, LO, HI, synthetic_block_hash, *golden) == []

    def test_a_proof_is_bound_to_its_chain_position(self, golden):
        assert verify_ride(RANGE, LO, HI, synthetic_block_hash, *golden)

    def test_a_nonce_that_misses_the_price_is_rejected(self, golden):
        root, _, openings = golden
        # nonce 2 is the first after 0 whose G has its top bit set, so G x 2 >= 2^256
        assert not meets_price(grind_attempt(ZERO, root, 2), 2)
        failures = verify_ride(ZERO, LO, HI, synthetic_block_hash, root, 2, openings)
        assert len(failures) == 1 and failures[0].startswith("mn:") and "re-roll price" in failures[0]

    def test_a_version_1_proof_is_rejected(self, golden):
        # version 1 drew the samples from the root under the V1 sample domain
        root, nonce, _ = golden
        levels = merkle_levels([ride_leaf(ZERO, b, synthetic_block_hash(b)) for b in range(LO + 1, HI + 1)])
        v1_idx = [int.from_bytes(sha256(b"CYBERSPACE_HYPERSPACE_SAMPLE_V1" + root + i.to_bytes(4, "big")), "big") % (HI - LO) for i in range(SAMPLES)]
        assert verify_ride(ZERO, LO, HI, synthetic_block_hash, root, nonce, [path_of(levels, i) for i in v1_idx])

    def test_a_fabricated_leaf_is_caught_when_sampled(self, golden):
        leaves = [ride_leaf(ZERO, b, synthetic_block_hash(b)) for b in range(LO + 1, HI + 1)]
        G = grind_attempt(ZERO, golden[0], 0)
        skip = sample_indices(G, HI - LO)[0]
        leaves[skip] = sha256(b"fabricated")
        levels = merkle_levels(leaves)
        forged_root = levels[-1][0]
        nonce = find_ride_nonce(ZERO, forged_root, HI - LO, workers=1)
        idx = sample_indices(grind_attempt(ZERO, forged_root, nonce), HI - LO)
        failures = verify_ride(ZERO, LO, HI, synthetic_block_hash, forged_root, nonce, [path_of(levels, i) for i in idx])
        assert bool(failures) == (skip in idx)

    def test_there_is_no_zero_length_ride(self):
        with pytest.raises(ValueError):
            prove_ride(ZERO, LO, LO, synthetic_block_hash)
        assert verify_ride(ZERO, LO, LO, no_block_data, PAD_LEAF, 0, []) == ["B: equals from_height; there is no zero-length ride (5.6)"]

    def test_attempts(self):
        assert [attempts_required(n) for n in (1, 32, 33, 40, 320000)] == [1, 1, 2, 2, 10000]
        assert [ride_depth(n) for n in (0, 1, 2, 3, 4, 5, 40)] == [0, 0, 1, 2, 2, 3, 6]

    def test_the_nonce_search_resumes(self, golden):
        seen = []
        # nonce 1 meets the price for this root; a search resumed at 1 finds it
        assert find_ride_nonce(ZERO, golden[0], HI - LO, start=1, workers=1, on_progress=seen.append) == 1
        assert seen == []

    def test_mp_encoding(self, golden):
        openings = golden[2]
        mp = encode_ride_openings(openings)
        assert mp.count(":") == SAMPLES - 1 and decode_ride_openings(mp, HI - LO) == openings
        assert decode_ride_openings(mp, 64) == openings                    # 40 and 64 both pad to depth 6
        assert decode_ride_openings(mp, 65) is None                        # depth 7
        assert decode_ride_openings(mp.upper(), HI - LO) is None
        assert decode_ride_openings(":".join(mp.split(":")[:-1]), HI - LO) is None
        assert decode_ride_openings("", 0) is None and decode_ride_openings(":", 0) is None


PREV_HEX = ZERO.hex()


def _ride_event(lo, hi, root, *, mn="default", mp=None, **extra):
    """A hyperjump event from lo to hi carrying the given proof; mn=None drops the tag."""
    tags = [
        ["A", "hyperjump"], ["e", "22" * 32, "", "genesis"], ["e", PREV_HEX, "", "previous"],
        ["c", "33" * 32], ["C", "44" * 32], ["from_height", str(lo)], ["B", str(hi)],
        ["proof", root.hex()], ["mp", "" if mp is None else mp],
    ]
    if mn is not None:
        tags.append(["mn", mn])
    for name, value in extra.items():
        tags = [[name, value] if t[0] == name else t for t in tags]
    return new_event(pubkey_hex="11" * 32, created_at=1790000000, kind=3333, tags=tags, content="")


class TestRideEvent:
    def test_a_version_2_ride_verifies(self, golden):
        root, nonce, openings = golden
        ev = _ride_event(LO, HI, root, mn=encode_nonce(nonce), mp=encode_ride_openings(openings))
        assert verify_ride_event(ev, synthetic_block_hash) == []
        # a ride runs either way along the line: from_height above B is the same blocks
        ev = _ride_event(HI, LO, root, mn=encode_nonce(nonce), mp=encode_ride_openings(openings))
        assert verify_ride_event(ev, synthetic_block_hash) == []

    def test_a_zero_length_ride_is_invalid(self):
        assert verify_ride_event(_ride_event(LO, LO, PAD_LEAF, mn="0" * 16), no_block_data) == ["B: equals from_height; there is no zero-length ride (5.6)"]

    def test_malformed_tags_are_rejected(self, golden):
        root, nonce, openings = golden
        good = dict(mn=encode_nonce(nonce), mp=encode_ride_openings(openings))
        assert verify_ride_event(_ride_event(LO, HI, root, **{**good, "mn": "0" * 15}), no_block_data) == ["mn: not exactly 16 lowercase hex characters"]
        assert verify_ride_event(_ride_event(LO, HI, root, **{**good, "mp": good["mp"][64:]}), no_block_data)
        assert verify_ride_event(_ride_event(LO, HI, root, **good, B="９００"), no_block_data) == ["B: missing or not a base-10 block height"]
        assert verify_ride_event({"tags": [["A", "hop"]]}, no_block_data) == ["A: not a hyperjump"]

    def test_an_unlisted_ride_without_mn_is_rejected(self, golden):
        ev = _ride_event(LO, HI, golden[0], mn=None, mp=encode_ride_openings(golden[2]))
        assert verify_ride_event(ev, no_block_data) == ["mn: missing; a ride without mn not listed in decks/grandfathered-v1-hyperjumps.txt (5.8)"]


class TestGrandfathered:
    def test_the_embedded_list(self):
        assert len(GRANDFATHERED_V1_HYPERJUMPS) == 16
        assert all(len(i) == 64 and all(c in "0123456789abcdef" for c in i) for i in GRANDFATHERED_V1_HYPERJUMPS)

    @pytest.mark.parametrize("ev", LISTED["rides"], ids=[e["id"][:12] for e in LISTED["rides"]])
    def test_listed_rides_are_accepted_without_block_data(self, ev):
        # includes a client-data-bug ride whose root does not match the chain:
        # exempted by decision, its root and openings are not recomputed. The
        # exemption covers the root and openings only, so the listed
        # zero-length ride is invalid under 5.6 like any other.
        assert not any(t[0] == "mn" for t in ev["tags"])
        assert is_grandfathered(ev, GRANDFATHERED_V1_HYPERJUMPS)
        tags = {t[0]: t[1] for t in ev["tags"]}
        expected = ["B: equals from_height; there is no zero-length ride (5.6)"] if tags["from_height"] == tags["B"] else []
        assert verify_ride_event(ev, no_block_data) == expected

    def test_the_listed_zero_length_ride_is_in_the_fixture(self):
        assert any(e["id"].startswith("17f65f44") for e in LISTED["rides"])

    def test_a_borrowed_id_is_not_listed(self):
        ev = json.loads(json.dumps(LISTED["rides"][1]))
        ev["tags"] = [["B", "146152"] if t[0] == "B" else t for t in ev["tags"]]
        assert not is_grandfathered(ev, GRANDFATHERED_V1_HYPERJUMPS)
        assert verify_ride_event(ev, no_block_data) == ["mn: missing; a ride without mn not listed in decks/grandfathered-v1-hyperjumps.txt (5.8)"]

    def test_a_listed_ride_still_has_its_tags_checked(self, monkeypatch):
        broken = _ride_event(LO, HI, sha256(b"any root"), mn=None, from_height="")
        monkeypatch.setattr(grandfathered, "GRANDFATHERED_V1_HYPERJUMPS", frozenset({broken["id"]}))
        assert verify_ride_event(broken, no_block_data) == ["from_height: missing or not a base-10 block height"]
