"""The ride the CLI builds (nostr_event.make_hyperjump_event, DECK-0001 5.2)
carries every tag the chain rules read on a ride (CYBERSPACE_V2 8.8):
from_height, B, as_of on the first ride after boarding, proof, mp and mn.

A chain the CLI builds is accepted by the CLI's own verifier, the builder
writes the tags in the order ONOSENDAI and cyberspace-mcp write them, and the
rides those clients built and signed rebuild here to the same event ids."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from coincurve import PrivateKey

from cyberspace_cli.nostr_event import _sector_tags_from_coord_hex, make_hyperjump_event, make_spawn_event, new_event
from cyberspace_core.chain import CHAIN_RULES_REVISION, event_id, verify_chain
from cyberspace_core.hyperspace import Line, enter_hyperspace_proof
from cyberspace_core.movement import encode_nonce
from cyberspace_core.ride import encode_ride_openings, prove_ride

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "vectors" / f"chain-rules-{CHAIN_RULES_REVISION}.json").read_text(encoding="utf-8"))
LINE = Line.from_blocks(DOC["line"]["blocks"])
SK = PrivateKey(bytes.fromhex(DOC["test_key"]["secret_key"]))
PUB = DOC["test_key"]["pubkey"]
FIXTURES = ROOT / "tests" / "fixtures"
T0 = 1790200000

# DECK-0001 5.2 and its example, ONOSENDAI events.ts and cyberspace-mcp builder.ts hyperjumpTemplate.
RIDE_TAG_ORDER = ["A", "e:genesis", "e:previous", "c", "C", "from_height", "B", "as_of", "proof", "mp", "mn", "X", "Y", "Z", "S"]


def _names(event: Dict[str, Any]) -> List[str]:
    return [f"e:{t[3]}" if t[0] == "e" else t[0] for t in event["tags"]]


def _value(event: Dict[str, Any], name: str) -> Optional[str]:
    return next((t[1] for t in event["tags"] if t[0] == name), None)


def _signed(event: Dict[str, Any]) -> Dict[str, Any]:
    return dict(event, sig=SK.sign_schnorr(bytes.fromhex(event["id"]), bytes(32)).hex())


def _board(genesis: Dict[str, Any], prev: Dict[str, Any], here: str, created_at: int) -> Dict[str, Any]:
    """An enter-hyperspace (DECK-0001 3.1); the CLI has no builder for one yet."""
    tags = [["A", "enter-hyperspace"], ["e", genesis["id"], "", "genesis"], ["e", prev["id"], "", "previous"],
            ["c", here], ["C", here], ["proof", enter_hyperspace_proof(here, bytes.fromhex(prev["id"]))]]
    return _signed(new_event(pubkey_hex=PUB, created_at=created_at, kind=3333, tags=tags + _sector_tags_from_coord_hex(here)))


def _ride(genesis: Dict[str, Any], prev: Dict[str, Any], c: str, from_height: int, to_height: int,
          created_at: int, as_of: Optional[int] = None) -> Dict[str, Any]:
    """A ride the CLI's builder writes, its proof from cyberspace_core.ride seeded by the event before it."""
    lo, hi = min(from_height, to_height), max(from_height, to_height)
    root, nonce, openings = prove_ride(bytes.fromhex(prev["id"]), lo, hi, LINE.block_hash, workers=1)
    return _signed(make_hyperjump_event(
        pubkey_hex=PUB,
        created_at=created_at,
        genesis_event_id=genesis["id"],
        previous_event_id=prev["id"],
        prev_coord_hex=c,
        coord_hex=LINE.stop(to_height).coord_hex,
        from_height=from_height,
        to_height=to_height,
        as_of=as_of,
        proof_hash_hex=root.hex(),
        ride_openings_hex=encode_ride_openings(openings),
        nonce_hex=encode_nonce(nonce),
    ))


@pytest.fixture(scope="module")
def cli_chain() -> List[Dict[str, Any]]:
    """Spawn, board, ride from the station (2 within as_of 5) to 4, ride on to 6, back to 3."""
    spawn = _signed(make_spawn_event(pubkey_hex=PUB, created_at=T0, coord_hex=PUB))
    board = _board(spawn, spawn, PUB, T0 + 1)
    station = LINE.station(PUB, 5)
    assert station == 2
    first = _ride(spawn, board, PUB, station, 4, T0 + 2, as_of=5)
    later = _ride(spawn, first, LINE.stop(4).coord_hex, 4, 6, T0 + 3)
    back = _ride(spawn, later, LINE.stop(6).coord_hex, 6, 3, T0 + 4)
    return [spawn, board, first, later, back]


class TestTheCliRide:
    def test_the_cli_verifier_accepts_a_chain_of_cli_rides(self, cli_chain):
        verdict = verify_chain(cli_chain, pubkey=PUB, line=LINE)
        assert verdict.valid, (verdict.reason, verdict.detail)
        assert verdict.head == cli_chain[-1]["id"]
        assert verdict.position == LINE.stop(3).coord_hex

    def test_each_prefix_is_valid_and_ends_at_its_stop(self, cli_chain):
        for n, height in ((3, 4), (4, 6)):
            verdict = verify_chain(cli_chain[:n], pubkey=PUB, line=LINE)
            assert verdict.valid, (verdict.reason, verdict.detail)
            assert verdict.position == LINE.stop(height).coord_hex

    def test_tags_the_chain_rules_read_in_the_reference_order(self, cli_chain):
        first, later = cli_chain[2], cli_chain[3]
        assert _names(first) == RIDE_TAG_ORDER
        assert _names(later) == [n for n in RIDE_TAG_ORDER if n != "as_of"]
        assert [_value(first, n) for n in ("from_height", "B", "as_of")] == ["2", "4", "5"]
        assert [_value(later, n) for n in ("from_height", "B")] == ["4", "6"]
        for ride in cli_chain[2:]:
            assert len(_value(ride, "mn")) == 16 and _value(ride, "mp") and len(_value(ride, "proof")) == 64
            assert ride["content"] == ""

    @pytest.mark.parametrize("drop", ["from_height", "proof", "mp", "mn"])
    def test_a_ride_without_a_tag_the_rules_read_is_invalid(self, cli_chain, drop):
        """What the CLI's ride lacked before: the verifier refuses the chain from that ride."""
        spawn, board, first = cli_chain[:3]
        bare = dict(first, tags=[t for t in first["tags"] if t[0] != drop])
        bare = _signed(dict(bare, id=event_id(bare)))
        verdict = verify_chain([spawn, board, bare], pubkey=PUB, line=LINE)
        assert not verdict.valid
        assert verdict.invalid_at == bare["id"]
        assert verdict.reason in ("malformed", "hyperjump-proof")


GOOD = dict(
    pubkey_hex=PUB, created_at=T0, genesis_event_id="11" * 32, previous_event_id="22" * 32,
    prev_coord_hex="33" * 32, coord_hex="44" * 32, from_height=2, to_height=4,
    proof_hash_hex="55" * 32, ride_openings_hex="66" * 32, nonce_hex="0123456789abcdef",
)


class TestTheBuilderRefuses:
    @pytest.mark.parametrize("change", [
        {"to_height": 2},                       # zero-length ride (5.6)
        {"as_of": 3},                           # as_of below B (4.2)
        {"from_height": -1},
        {"to_height": "4"},
        {"as_of": True},
        {"proof_hash_hex": "55" * 31},
        {"proof_hash_hex": "AB" * 32},
        {"ride_openings_hex": ""},
        {"nonce_hex": "0123456789abcde"},
        {"nonce_hex": "0123456789ABCDEF"},
        {"as_of": 4, "from_height": 5},         # the station lies within as_of (4.2)
        {"genesis_event_id": "11" * 31},
        {"previous_event_id": "GG" * 32},
        {"prev_coord_hex": ""},
        {"coord_hex": "44" * 33},
    ], ids=lambda c: next(iter(c)) + "=" + repr(next(iter(c.values()))))
    def test_input_that_would_make_an_invalid_ride(self, change):
        with pytest.raises(ValueError):
            make_hyperjump_event(**dict(GOOD, **change))

    def test_as_of_equal_to_b_is_allowed(self):
        assert _value(make_hyperjump_event(**dict(GOOD, as_of=4)), "as_of") == "4"


class TestInterop:
    def _rebuild(self, ride: Dict[str, Any], nonce_hex: str) -> Dict[str, Any]:
        """The ride rebuilt by the CLI's builder from the values its own tags carry."""
        e = {t[3]: t[1] for t in ride["tags"] if t[0] == "e"}
        as_of = _value(ride, "as_of")
        return make_hyperjump_event(
            pubkey_hex=ride["pubkey"],
            created_at=ride["created_at"],
            genesis_event_id=e["genesis"],
            previous_event_id=e["previous"],
            prev_coord_hex=_value(ride, "c"),
            coord_hex=_value(ride, "C"),
            from_height=int(_value(ride, "from_height")),
            to_height=int(_value(ride, "B")),
            as_of=int(as_of) if as_of is not None else None,
            proof_hash_hex=_value(ride, "proof"),
            ride_openings_hex=_value(ride, "mp"),
            nonce_hex=nonce_hex,
        )

    @pytest.mark.parametrize("ride_id", [
        "f8b9a187f1969c235e4b17c292a3a8d152b7e455431c08c94ff11bb74bca5190",
        "43628b3880fb004f3f1236f298152fd093e3e0f3740fb4029b9ed9716249ae5c",
    ], ids=lambda i: i[:8])
    def test_onosendai_rides_rebuild_byte_for_byte(self, ride_id):
        """Two rides the reference client, ONOSENDAI, published and signed
        (fetched from wss://cyberspace.nostr1.com; DECK-0001 5.8 lists them
        because they predate mn). With the builder's mn taken out, the CLI
        writes the same tags with the same values in the same order, so the
        same event id."""
        rides = json.loads((FIXTURES / "grandfathered_events.json").read_text(encoding="utf-8"))["rides"]
        ride = next(r for r in rides if r["id"] == ride_id)
        built = self._rebuild(ride, "0" * 16)
        built["tags"] = [t for t in built["tags"] if t[0] != "mn"]
        assert built["tags"] == ride["tags"]
        assert event_id(built) == ride["id"]

    def test_cyberspace_mcp_rides_rebuild_and_verify(self):
        """A chain built, proved and signed by cyberspace-mcp's own code
        (tests/fixtures/mcp_rides.json). The CLI's prover reaches the same
        root, openings and nonce, its builder rebuilds each ride to the same
        id (the MCP's signEvent adds a client tag, which no rule reads), and
        its verifier accepts the chain."""
        doc = json.loads((FIXTURES / "mcp_rides.json").read_text(encoding="utf-8"))
        events = doc["events"]
        for ride in events[2:]:
            frm, to = int(_value(ride, "from_height")), int(_value(ride, "B"))
            previous = next(t[1] for t in ride["tags"] if t[0] == "e" and t[3] == "previous")
            root, nonce, openings = prove_ride(bytes.fromhex(previous), min(frm, to), max(frm, to), LINE.block_hash, workers=1)
            assert [root.hex(), encode_ride_openings(openings), encode_nonce(nonce)] == [_value(ride, n) for n in ("proof", "mp", "mn")]
            built = self._rebuild(ride, _value(ride, "mn"))
            built["tags"].append(["client", "cyberspace-mcp"])
            assert built["tags"] == ride["tags"]
            assert event_id(built) == ride["id"]
        verdict = verify_chain(events, pubkey=PUB, line=LINE)
        assert verdict.valid, (verdict.reason, verdict.detail)
        assert verdict.position == LINE.stop(6).coord_hex
