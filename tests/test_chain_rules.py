"""The chain rules of CYBERSPACE_V2 section 8.12, revision
2026-09-28-virtual-brackets: active chain resolution (8.7.3), skipping
actions a verifier does not recognize (8.9), virtual brackets (8.11) and the
DECK-0001 ride rules, each locked by the golden vectors in
vectors/chain-rules-2026-09-28-virtual-brackets.json, which the TypeScript
ports load too. Regenerate them with scripts/gen_chain_vectors.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cyberspace_core.chain import (
    CHAIN_RULES_REVISION,
    REASONS,
    LineRequired,
    Region,
    parse_region,
    resolve_active_chain,
    verify_chain,
)
from cyberspace_core.coords import xyz_to_coord
from cyberspace_core.hyperspace import Line

VECTORS_PATH = Path(__file__).resolve().parents[1] / "vectors" / f"chain-rules-{CHAIN_RULES_REVISION}.json"
DOC = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
PUBKEY = DOC["test_key"]["pubkey"]
LINE = Line.from_blocks(DOC["line"]["blocks"])
BY_NAME = {v["name"]: v for v in DOC["vectors"]}


def _has_ride(vector) -> bool:
    return any(t[:2] == ["A", "hyperjump"] for ev in vector["events"] for t in ev["tags"])


@pytest.mark.parametrize("vector", DOC["vectors"], ids=[v["name"] for v in DOC["vectors"]])
def test_vector(vector):
    verdict = verify_chain(vector["events"], pubkey=PUBKEY, line=LINE, check_signatures=True)
    assert verdict.expected() == vector["expected"], verdict.detail
    assert verdict.revision == CHAIN_RULES_REVISION


@pytest.mark.parametrize("vector", [v for v in DOC["vectors"] if not _has_ride(v)], ids=lambda v: v["name"])
def test_vector_in_any_order(vector):
    """Relays return events in no particular order, and 8.7.3 resolves them the same way whatever the order."""
    verdict = verify_chain(list(reversed(vector["events"])), pubkey=PUBKEY, line=LINE, check_signatures=True)
    assert verdict.expected() == vector["expected"]


class TestTheFile:
    def test_revision_and_reasons(self):
        assert DOC["chain_rules_revision"] == CHAIN_RULES_REVISION == "2026-09-28-virtual-brackets"
        assert DOC["reasons"] == REASONS
        assert {v["expected"].get("reason") for v in DOC["vectors"]} - {None} == set(REASONS)

    def test_line(self):
        for block in DOC["line"]["blocks"]:
            assert LINE.stop(block["height"]).coord_hex == block["coord"]
        assert [LINE.station(PUBKEY, bound) for bound in range(8)][2:] == [2, 2, 2, 2, 6, 6]

    def test_open_questions_are_named(self):
        assert sorted(v["name"] for v in DOC["vectors"] if "open_question" in v) == ["bracket-exit-c-mismatch", "ride-zero-length-later"]


class TestVerifier:
    def test_ride_without_line(self):
        with pytest.raises(LineRequired):
            verify_chain(BY_NAME["ride-valid"]["events"], pubkey=PUBKEY)

    def test_signatures_are_checked_only_when_asked(self):
        """Without signature checks the unsigned branch, signed first, wins the fork; with them it is set aside."""
        vector = BY_NAME["unsigned-fork-ignored"]
        spawn, unsigned, real = vector["events"]
        assert verify_chain(vector["events"], pubkey=PUBKEY).chain == (spawn["id"], unsigned["id"])
        assert verify_chain(vector["events"], pubkey=PUBKEY, check_signatures=True).chain == (spawn["id"], real["id"])

    def test_invalid_reports_the_carried_position(self):
        verdict = verify_chain(BY_NAME["bracket-exit-position-mismatch"]["events"], pubkey=PUBKEY)
        assert not verdict.valid and verdict.last_valid_position == PUBKEY

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
            assert verify_chain(ordered, pubkey=PUBKEY, check_signatures=True).expected() == vector["expected"]

    def test_other_kinds_and_authors_are_ignored(self):
        events = BY_NAME["bracket-unclosed"]["events"]
        noise = [dict(events[0], kind=1), dict(events[1], pubkey="00" * 32)]
        assert [e["id"] for e in resolve_active_chain(events + noise, PUBKEY)] == BY_NAME["bracket-unclosed"]["expected"]["chain"]


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
