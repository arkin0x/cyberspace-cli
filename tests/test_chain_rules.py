"""The chain rules of CYBERSPACE_V2 section 8.12, locked by one golden
vector file per revision, which the other ports load too:

- vectors/chain-rules-2026-10-08-residue-openings.json, the current revision:
  hop proofs of version 2, residue openings (5.9 to 5.13), with the version 1
  hops on its own test list standing in for grandfathered-v1-hops.txt;
- vectors/chain-rules-2026-09-28-virtual-brackets.json, the previous
  revision with the rulings of 2026-10-07 and 2026-10-08, whose hops are
  version 1, checked with verify_chain(revision=PREVIOUS_REVISION).

Both lock authentic events only and active chain resolution (8.7.3), frozen
chains at their last valid position (3.2), one A tag (8.8), skipping actions
a verifier does not recognize (8.9), opaque virtual brackets (8.11), sector
tags (10) and the DECK-0001 ride rules. Regenerate them with
scripts/gen_chain_vectors.py (add --revision 2026-09-28-virtual-brackets for
the previous file)."""

from __future__ import annotations

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import pytest
from coincurve import PrivateKey

from cyberspace_core.chain import (
    CHAIN_RULES_REVISION,
    PREVIOUS_REVISION,
    REASONS,
    REASONS_BY_REVISION,
    REVISIONS,
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

ROOT = Path(__file__).resolve().parents[1]
DOCS = {r: json.loads((ROOT / "vectors" / f"chain-rules-{r}.json").read_text(encoding="utf-8")) for r in REVISIONS}
DOC = DOCS[CHAIN_RULES_REVISION]
PUBKEY = DOC["verify_with"]["identity"]
LINE = Line.from_blocks(DOC["line"]["blocks"])
BY_NAME = {v["name"]: v for v in DOC["vectors"]}
OLD_BY_NAME = {v["name"]: v for v in DOCS[PREVIOUS_REVISION]["vectors"]}
# The test list of the current file, in place of grandfathered-v1-hops.txt when the vectors run.
LISTED = frozenset(DOC["grandfathered_v1_hops"]["ids"])
LISTED_BY_REVISION = {CHAIN_RULES_REVISION: LISTED, PREVIOUS_REVISION: None}


def _has_ride(vector) -> bool:
    return any(t[:2] == ["A", "hyperjump"] for ev in vector["events"] for t in ev["tags"])


def _cases(only=lambda v: True):
    return [pytest.param(r, v, id=f"{r}:{v['name']}") for r in REVISIONS for v in DOCS[r]["vectors"] if only(v)]


def _verify(revision, events):
    return verify_chain(events, pubkey=PUBKEY, line=LINE, revision=revision, listed_v1_hops=LISTED_BY_REVISION[revision])


@pytest.mark.parametrize("revision,vector", _cases())
def test_vector(revision, vector):
    verdict = _verify(revision, vector["events"])
    assert verdict.expected() == vector["expected"], verdict.detail
    assert verdict.revision == revision


@pytest.mark.parametrize("revision,vector", _cases(lambda v: not _has_ride(v)))
def test_vector_in_any_order(revision, vector):
    """Relays return events in no particular order, and 8.7.3 resolves them the same way whatever the order."""
    verdict = _verify(revision, list(reversed(vector["events"])))
    assert verdict.expected() == vector["expected"]


class TestTheFiles:
    @pytest.mark.parametrize("revision", REVISIONS)
    def test_revision_and_reasons(self, revision):
        doc = DOCS[revision]
        assert doc["chain_rules_revision"] == revision
        assert doc["test_key"] == DOC["test_key"] and doc["test_key"]["pubkey"] == PUBKEY
        assert doc["line"] == DOC["line"]
        assert doc["reasons"] == REASONS_BY_REVISION[revision]
        assert {v["expected"].get("reason") for v in doc["vectors"]} - {None} == set(doc["reasons"])

    def test_the_current_revision(self):
        assert CHAIN_RULES_REVISION == "2026-10-08-residue-openings" and PREVIOUS_REVISION == "2026-09-28-virtual-brackets"
        assert REASONS == REASONS_BY_REVISION[CHAIN_RULES_REVISION]
        assert set(REASONS) == set(REASONS_BY_REVISION[PREVIOUS_REVISION])
        assert DOC["spec"]["commit"] == "06c287332651f99b75e609b7b098e165993750fd"

    def test_line(self):
        for block in DOC["line"]["blocks"]:
            assert LINE.stop(block["height"]).coord_hex == block["coord"]
        assert [LINE.station(PUBKEY, bound) for bound in range(8)][2:] == [2, 2, 2, 2, 6, 6]

    @pytest.mark.parametrize("revision", REVISIONS)
    def test_no_open_questions_remain(self, revision):
        """The rulings of 2026-10-07 and 2026-10-08 answered every reading the first vectors left open."""
        assert not [v["name"] for v in DOCS[revision]["vectors"] if "open_question" in v]

    @pytest.mark.parametrize("revision", REVISIONS)
    def test_every_invalid_verdict_names_a_position(self, revision):
        for v in DOCS[revision]["vectors"]:
            if not v["expected"]["valid"] and v["expected"]["reason"] != "no-spawn":
                assert v["expected"]["position"], v["name"]


def _hops(event_list):
    """The events whose one A tag is hop."""
    return [e for e in event_list if isinstance(e.get("tags"), list)
            and [t[1:2] for t in e["tags"] if isinstance(t, list) and t[:1] == ["A"]] == [["hop"]]]


def _tag(event, name):
    return next(t[1] for t in event["tags"] if t[0] == name)


class TestResidueOpenings:
    """What the current revision changed: hop proofs of version 2 (5.9 to 5.13)."""

    def test_only_the_previous_revision_changed(self):
        """Every vector of the previous revision is in the current file under the same name, with the same verdict
        apart from event ids: the same validity, reason, index, position and chain length."""
        def shape(v):
            e = v["expected"]
            return (e["valid"], e.get("reason"), e.get("invalid_index"), e["position"], len(e["chain"]),
                    len(e.get("skipped", [])), e.get("open_bracket") is None)

        assert set(OLD_BY_NAME) <= set(BY_NAME)
        assert {n: shape(v) for n, v in OLD_BY_NAME.items()} == {n: shape(BY_NAME[n]) for n in OLD_BY_NAME}

    def test_every_authentic_hop_is_version_2_unless_the_vector_says_otherwise(self):
        """Hops carry proof, mn and mp; the exceptions are the listed version 1 hops, and the vectors named
        hop-version-1-unlisted, hop-mn-missing and hop-mp-missing."""
        for v in DOC["vectors"]:
            for e in _hops(v["events"]):
                if not is_authentic(e, PUBKEY) or e["id"] in LISTED:
                    continue
                names = [t[0] for t in e["tags"]]
                if v["name"] in ("hop-version-1-unlisted", "hop-mn-missing", "hop-mp-missing") and e["id"] == v["expected"]["invalid_at"]:
                    continue
                assert "mn" in names and "mp" in names, v["name"]

    def test_every_hop_on_a_valid_chain_verifies_with_the_spec_reference(self):
        """An oracle independent of this verifier: the spec's hop-residue-reference.py (tests/fixtures, pinned in
        tests/test_hop_residue.py) checks every unlisted hop that a valid vector's chain carries."""
        spec = importlib.util.spec_from_file_location("hop_residue_reference", ROOT / "tests" / "fixtures" / "hop-residue-reference.py")
        ref = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ref)  # type: ignore[union-attr]
        checked = 0
        for v in DOC["vectors"]:
            if not v["expected"]["valid"]:
                continue
            by_id = {e["id"]: e for e in v["events"]}
            for e in _hops([by_id[i] for i in v["expected"]["chain"]]):
                if e["id"] in LISTED:
                    continue
                prev = next(t[1] for t in e["tags"] if t[0] == "e" and t[3] == "previous")
                assert ref.verify_hop(bytes.fromhex(prev), int(_tag(e, "c"), 16), int(_tag(e, "C"), 16),
                                      _tag(e, "proof"), _tag(e, "mn"), _tag(e, "mp")), v["name"]
                checked += 1
        assert checked == 28  # every unlisted hop on the chain of a valid vector

    def test_the_previous_revisions_vectors_are_not_vectors_of_this_one(self):
        """8.12: a verifier of this revision rejects the unlisted version 1 hops of the previous file, and a verifier
        of the previous revision rejects the version 2 hops of the current one."""
        for revision, vector in ((CHAIN_RULES_REVISION, OLD_BY_NAME["bracket-valid-then-hop"]),
                                 (PREVIOUS_REVISION, BY_NAME["bracket-valid-then-hop"])):
            verdict = verify_chain(vector["events"], pubkey=PUBKEY, revision=revision)
            assert (verdict.valid, verdict.reason, verdict.invalid_index) == (False, "hop-proof", 1)

    def test_without_the_test_list_a_listed_hop_is_an_unlisted_one(self):
        """The embedded grandfathered-v1-hops.txt is empty until the census, so the vectors need their own list."""
        vector = BY_NAME["hop-version-1-listed"]
        verdict = verify_chain(vector["events"], pubkey=PUBKEY)
        assert (verdict.valid, verdict.reason, verdict.invalid_index) == (False, "hop-proof", 1)
        assert "grandfathered-v1-hops.txt" in verdict.detail

    def test_the_test_list_is_exactly_the_listed_hops(self):
        listed_vectors = {v["name"] for v in DOC["vectors"] for e in v["events"] if e.get("id") in LISTED}
        assert listed_vectors == {n for n in BY_NAME if n.startswith("hop-version-1-listed")}
        listed_events = [e for v in DOC["vectors"] for e in v["events"] if e.get("id") in LISTED]
        assert {e["id"] for e in listed_events} == LISTED
        assert all(_hops([e]) == [e] and is_authentic(e, PUBKEY) for e in listed_events)

    def test_an_unknown_revision_is_refused(self):
        with pytest.raises(ValueError, match="unknown chain rules revision"):
            verify_chain(BY_NAME["spawn-only"]["events"], pubkey=PUBKEY, revision="2026-01-01-nothing")


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
