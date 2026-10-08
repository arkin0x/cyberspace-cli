"""The chain rules of CYBERSPACE_V2 section 8.12, revision
2026-09-28-virtual-brackets with the rulings of 2026-10-07 and 2026-10-08:
authentic events only and active chain resolution (8.7.3), frozen chains at
their last valid position (3.2), one A tag (8.8), skipping actions a verifier
does not recognize (8.9), opaque virtual brackets (8.11), sector tags (10)
and the DECK-0001 ride rules, each locked by the golden vectors in
vectors/chain-rules-2026-09-28-virtual-brackets.json, which the TypeScript
ports load too. Regenerate them with scripts/gen_chain_vectors.py."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from coincurve import PrivateKey

from cyberspace_core.chain import (
    CHAIN_RULES_REVISION,
    REASONS,
    LineRequired,
    event_id,
    Region,
    is_authentic,
    parse_region,
    resolve_active_chain,
    sector_tags_ok,
    verify_chain,
)
from cyberspace_core.coords import xyz_to_coord
from cyberspace_core.hyperspace import Line

VECTORS_PATH = Path(__file__).resolve().parents[1] / "vectors" / f"chain-rules-{CHAIN_RULES_REVISION}.json"
DOC = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
PUBKEY = DOC["verify_with"]["identity"]
LINE = Line.from_blocks(DOC["line"]["blocks"])
BY_NAME = {v["name"]: v for v in DOC["vectors"]}


def _has_ride(vector) -> bool:
    return any(t[:2] == ["A", "hyperjump"] for ev in vector["events"] for t in ev["tags"])


@pytest.mark.parametrize("vector", DOC["vectors"], ids=[v["name"] for v in DOC["vectors"]])
def test_vector(vector):
    verdict = verify_chain(vector["events"], pubkey=PUBKEY, line=LINE)
    assert verdict.expected() == vector["expected"], verdict.detail
    assert verdict.revision == CHAIN_RULES_REVISION


@pytest.mark.parametrize("vector", [v for v in DOC["vectors"] if not _has_ride(v)], ids=lambda v: v["name"])
def test_vector_in_any_order(vector):
    """Relays return events in no particular order, and 8.7.3 resolves them the same way whatever the order."""
    verdict = verify_chain(list(reversed(vector["events"])), pubkey=PUBKEY, line=LINE)
    assert verdict.expected() == vector["expected"]


class TestTheFile:
    def test_revision_and_reasons(self):
        assert DOC["chain_rules_revision"] == CHAIN_RULES_REVISION == "2026-09-28-virtual-brackets"
        assert DOC["test_key"]["pubkey"] == PUBKEY
        assert DOC["reasons"] == REASONS
        assert {v["expected"].get("reason") for v in DOC["vectors"]} - {None} == set(REASONS)

    def test_line(self):
        for block in DOC["line"]["blocks"]:
            assert LINE.stop(block["height"]).coord_hex == block["coord"]
        assert [LINE.station(PUBKEY, bound) for bound in range(8)][2:] == [2, 2, 2, 2, 6, 6]

    def test_no_open_questions_remain(self):
        """The rulings of 2026-10-07 and 2026-10-08 answered every reading the first vectors left open."""
        assert not [v["name"] for v in DOC["vectors"] if "open_question" in v]

    def test_every_invalid_verdict_names_a_position(self):
        for v in DOC["vectors"]:
            if not v["expected"]["valid"] and v["expected"]["reason"] != "no-spawn":
                assert v["expected"]["position"], v["name"]


class TestVerifier:
    def test_ride_without_line(self):
        with pytest.raises(LineRequired):
            verify_chain(BY_NAME["ride-valid"]["events"], pubkey=PUBKEY)

    def test_authenticity(self):
        spawn, unsigned, real = BY_NAME["unsigned-fork-ignored"]["events"]
        assert is_authentic(spawn, PUBKEY) and is_authentic(real, PUBKEY)
        assert not is_authentic(unsigned, PUBKEY)  # its sig signs another id
        assert not is_authentic(dict(real, sig=""), PUBKEY)  # unsigned local events are discarded too (8.2)
        assert not is_authentic(real, DOC["other_key"]["pubkey"])

    def test_an_unsigned_chain_resolves_to_nothing(self):
        events = [dict(e, sig="") for e in BY_NAME["bracket-valid-then-hop"]["events"]]
        assert verify_chain(events, pubkey=PUBKEY).reason == "no-spawn"

    def test_a_fork_behind_a_cut_off_is_never_reached(self):
        """Two authentic events that both name a discarded event are cut off with it; they make no fork."""
        vector = BY_NAME["forged-event-cuts-branch"]
        spawn, hop, forged, after = vector["events"]
        twin = dict(after, created_at=after["created_at"] + 1)
        identity = PrivateKey(bytes.fromhex(DOC["test_key"]["secret_key"]))
        twin["id"] = event_id(twin)
        twin["sig"] = identity.sign_schnorr(bytes.fromhex(twin["id"]), bytes(32)).hex()
        assert verify_chain(vector["events"] + [twin], pubkey=PUBKEY).expected() == vector["expected"]

    def test_sector_tags(self):
        spawn = BY_NAME["spawn-only"]["events"][0]
        assert sector_tags_ok(spawn, PUBKEY)
        assert not sector_tags_ok(BY_NAME["spawn-sector-tags-wrong"]["events"][0], PUBKEY)

    def test_pubkey_is_inferred_from_one_author(self):
        events = BY_NAME["bracket-valid-then-hop"]["events"]
        assert verify_chain(events).expected() == BY_NAME["bracket-valid-then-hop"]["expected"]
        with pytest.raises(ValueError):
            verify_chain(events + [dict(events[0], pubkey="00" * 32)])

    def test_a_forged_copy_of_an_id_loses_in_either_order(self):
        vector = BY_NAME["bracket-valid-then-hop"]
        events = vector["events"]
        forged = dict(events[2], tags=events[2]["tags"] + [["x", "forged"]])
        for ordered in ([forged] + events, events + [forged]):
            assert verify_chain(ordered, pubkey=PUBKEY).expected() == vector["expected"]

    def test_other_kinds_and_authors_are_ignored(self):
        """Properly signed noise: a kind 1 copy of the first hop by the identity
        and a copy by another author, each signed one second before the real
        hop, so each would fork the chain, and kill it, if kind or author were
        not checked."""
        vector = BY_NAME["bracket-unclosed"]
        events = vector["events"]
        hop = events[1]
        identity = PrivateKey(bytes.fromhex(DOC["test_key"]["secret_key"]))
        other = PrivateKey(sha256(b"CYBERSPACE_CHAIN_VECTORS_OTHER_KEY").digest())
        assert other.public_key_xonly.format().hex() == DOC["other_key"]["pubkey"]

        def signed(key, kind):
            ev = dict(hop, pubkey=key.public_key_xonly.format().hex(), kind=kind, created_at=hop["created_at"] - 1)
            ev["id"] = event_id(ev)
            ev["sig"] = key.sign_schnorr(bytes.fromhex(ev["id"]), bytes(32)).hex()
            return ev

        noise = [signed(identity, 1), signed(other, 3333)]
        assert all(event_id(e) == e["id"] for e in noise)
        resolution = resolve_active_chain(events + noise, PUBKEY)
        assert [e["id"] for e in resolution.chain] == vector["expected"]["chain"] and not resolution.fork
        # the control: the same noise as a kind 3333 event by the identity does make a fork
        control = signed(identity, 3333)
        resolution = resolve_active_chain(events + [control], PUBKEY)
        assert resolution.fork == tuple(sorted((control["id"], hop["id"]))) and [e["id"] for e in resolution.chain] == [events[0]["id"]]


class TestRegion:
    def _event(self, coord_hex: str, h: str):
        return {"tags": [["region", coord_hex, h]]}

    def test_height_zero_is_one_point(self):
        base = xyz_to_coord(5, 6, 7, 1)
        region, _ = parse_region(self._event(format(base, "064x"), "0"))
        assert region == Region(5, 6, 7, 1, 0)
        assert region.contains(format(base, "064x"))
        assert not region.contains(format(xyz_to_coord(5, 6, 8, 1), "064x"))

    def test_height_85_is_a_whole_plane(self):
        region, _ = parse_region(self._event("00" * 32, "85"))
        assert region.contains(format(xyz_to_coord((1 << 85) - 1, 3, 9, 0), "064x"))
        assert not region.contains(format(xyz_to_coord(0, 0, 0, 1), "064x"))

    @pytest.mark.parametrize("h", ["", "-1", "+3", "03", "86", "1.0", "x"])
    def test_height_must_be_canonical(self, h):
        assert parse_region(self._event("00" * 32, h))[0] is None

    def test_base_must_be_aligned_on_every_axis(self):
        for x, y, z in ((1 << 2, 0, 0), (0, 1 << 2, 0), (0, 0, 1 << 2)):
            assert parse_region(self._event(format(xyz_to_coord(x, y, z, 0), "064x"), "3"))[0] is None
        assert parse_region(self._event(format(xyz_to_coord(1 << 3, 0, 0, 0), "064x"), "3"))[0] is not None
