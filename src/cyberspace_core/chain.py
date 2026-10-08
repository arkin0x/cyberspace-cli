"""The chain rules of CYBERSPACE_V2.md section 8.12, revision
2026-09-28-virtual-brackets with the rulings folded in on 2026-10-07 and
clarified on 2026-10-08: which movement chains are valid and where an
identity stands.

A verifier holds whatever kind 3333 events relays gave it for one pubkey, in
no particular order. It first discards every event that is not authentic
(8.7.3): an event whose id is not its NIP-01 hash, whose sig is not a valid
signature of that id by its pubkey (8.2), or whose pubkey is not the
identity's. A discarded event is treated as if it never existed, so a branch
that runs through one is cut off and the chain ends at the event before it.
Nobody can end another identity's chain by posting a forged event.

It then resolves the authentic events into the active chain (8.7.3) by
links, created_at and ids alone: the newest spawn, valid or not, then forward
through e previous links among the events whose e genesis names that spawn,
the branch signed first continuing at a fork. Resolution comes before
validity, so an earlier invalid branch beats a later valid one.

It then walks the active chain from the spawn and checks every event in
order. The first event that breaks a rule makes the chain invalid from that
event, the walk stops there, and the identity stands frozen at its last valid
position: the position the chain would give it if it ended at the last valid
event (3.2, 8.7.3), or the spawn coordinate when the spawn itself is invalid.

What the walk checks:

- Every event carries exactly one A tag (8.8).
- Recognized actions (8.9) are the base actions (spawn, hop, sidestep,
  enter-virtual, exit-virtual) and the actions of every mandatory DECK
  (DECK-0001: enter-hyperspace, hyperjump). Each carries the sector tags X,
  Y, Z and S exactly once, equal to the values computed from its C (10).
  Outside a bracket each starts where the chain carries it: its c equals the
  C of the nearest recognized action before it (continuity). Hops,
  sidesteps, boardings and rides have their proofs checked in full at Level
  1, each seeded by the id its e previous tag names.
- An action the verifier does not recognize is skipped (8.9): it is checked
  only for being authentic, linked and carrying one A tag, so it neither
  moves the identity nor stands in for the action before the next one. A
  skipped action that changed the position leaves the next recognized
  action's c mismatched.
- A virtual bracket (8.11) is opaque and checked as a unit. Its
  enter-virtual action does not move the identity (C equals c), and its game
  p tag and region tag are checked for form only; the base position need not
  lie in or near the region. Inside it every name that rule 3 does not
  reserve is a virtual action, checked only for its links and its one A tag;
  its c, C and sector tags belong to the game. The exit names the open entry
  and its C restores the entry's c; its c is not checked. Continuity resumes
  after the exit, and the exit stands in for the action before its entry
  when a later rule looks back (rule 8).
- Rides follow DECK-0001 section 4.3: a hyperjump looks back (through skipped
  actions and closed brackets) to an enter-hyperspace, whose first ride
  departs from the station within the declared as_of bound, or to a
  hyperjump, whose B it departs from. No ride has length zero (5.6). Rides
  need Bitcoin's block data, supplied as a Line (cyberspace_core.hyperspace).

This CLI implements no optional DECK, so its recognized actions are exactly
the base and DECK-0001 actions. The golden vectors in
vectors/chain-rules-2026-09-28-virtual-brackets.json lock every verdict this
module gives, for the TypeScript ports to check against.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cyberspace_core.coords import AXIS_BITS, coord_to_xyz
from cyberspace_core.hyperspace import Line, verify_enter_hyperspace_event
from cyberspace_core.movement import DEFAULT_MAX_COMPUTE_HEIGHT, verify_hop_event, verify_sidestep_event
from cyberspace_core.ride import verify_ride_event
from cyberspace_core.sector import coord_to_sector_id

CHAIN_RULES_REVISION = "2026-09-28-virtual-brackets"

MOVEMENT_KIND = 3333

# 8.8: the base actions.
BASE_ACTIONS = frozenset({"spawn", "hop", "sidestep", "enter-virtual", "exit-virtual"})
# 8.9, 8.12: the actions of every mandatory DECK. At this revision that is DECK-0001 alone.
MANDATORY_DECK_ACTIONS = frozenset({"enter-hyperspace", "hyperjump"})
RECOGNIZED_ACTIONS = BASE_ACTIONS | MANDATORY_DECK_ACTIONS
# 8.11.4 rule 3: every action of the base protocol or of a mandatory DECK is
# reserved inside a bracket. A spawn is never inside one (it starts a new
# chain) and an exit-virtual closes it, so these are the names that make an
# event inside a bracket invalid.
NOT_IN_BRACKET = RECOGNIZED_ACTIONS - {"spawn", "exit-virtual"}

# 8.11.1: a region's height is an integer in [0, 85].
REGION_MAX_HEIGHT = AXIS_BITS

# The reason a chain is invalid, one code per rule. The codes, not the
# free-text detail, are what the golden vectors lock.
REASONS: Dict[str, str] = {
    "no-spawn": "no authentic spawn event for this pubkey, so there is no chain (8.7.3 rule 1)",
    "a-tag": "the event carries no A tag, or more than one (8.8)",
    "malformed": "a tag the chain rules read is missing or ill-formed: e genesis, e previous or e entry missing or repeated; c or C missing, repeated or not a 32-byte lowercase hex coordinate; from_height or B missing or not a base-10 height (the first of each is read)",
    "sector-tags": "a recognized action's X, Y, Z or S tag is missing, repeated, or not the value computed from its C (10)",
    "spawn-coordinate": "the spawn's C is not its pubkey (8.3)",
    "c-mismatch": "c is not the C of the nearest recognized action before it (8.9 item 2, continuity)",
    "hop-proof": "the hop's proof does not verify (8.7.1), including a missing or ill-formed proof tag",
    "sidestep-proof": "the sidestep does not verify at Level 1 (8.7.2), including its geometry, height tags, price and openings",
    "enter-hyperspace-moved": "an enter-hyperspace's C is not its c (DECK-0001 3.1)",
    "enter-hyperspace-proof": "the entry proof does not verify (DECK-0001 3.2)",
    "hyperjump-predecessor": "the action a hyperjump looks back to is neither enter-hyperspace nor hyperjump (DECK-0001 4.3)",
    "hyperjump-zero-length": "a ride whose B equals its from_height; there is no zero-length ride (DECK-0001 5.2, 5.6)",
    "hyperjump-as-of": "the first ride after boarding has no as_of tag, or as_of is not a height on the line, or is below B (DECK-0001 4.2, 4.3)",
    "hyperjump-station": "the first ride after boarding does not depart from the station (DECK-0001 4.2, 4.3)",
    "hyperjump-from-height": "a later ride does not depart from the previous ride's B (DECK-0001 4.3)",
    "hyperjump-stop": "the ride's C is not the stop coordinate of B, or B is not a height on the line (DECK-0001 5.5 Level 1 step 2)",
    "hyperjump-proof": "the ride's proof does not verify at Level 1 (DECK-0001 5.5, 5.8), including ill-formed proof, mp or mn tags",
    "enter-virtual-moved": "an enter-virtual's C is not its c; entering a game does not move the identity (8.11.1)",
    "region": "the enter-virtual's region tag is missing, repeated or ill-formed: H not canonical in [0, 85], or the base not aligned (8.11.1)",
    "game-tag": "the enter-virtual does not carry exactly one p tag marked game holding a 32-byte lowercase hex pubkey (8.11.1)",
    "base-action-in-bracket": "an action of the base protocol or of a mandatory DECK inside an open bracket (8.11.4 rule 3)",
    "exit-without-bracket": "an exit-virtual when no bracket is open (8.11.4 rule 6)",
    "exit-wrong-entry": "an exit-virtual whose e entry names anything but the open enter-virtual (8.11.4 rule 6)",
    "exit-position": "an exit-virtual whose C is not the c of its enter-virtual (8.11.4 rule 2)",
}


class LineRequired(Exception):
    """A ride is on the chain and the verifier was given no Line. Rides are
    mandatory (8.9), so a chain with one cannot be judged without Bitcoin's
    block data; this is a missing input, not a verdict."""


@dataclass(frozen=True)
class Region:
    """8.11.1: the aligned cube of height H at base (bx, by, bz) on plane P.

    The base verifier checks a region for form only and never asks whether
    anything lies inside it (8.11.1, 8.11.5). `contains` is the containment
    test of 8.11.1, for games and clients that give the region a meaning."""

    bx: int
    by: int
    bz: int
    plane: int
    height: int

    def contains(self, coord_hex: str) -> bool:
        x, y, z, p = coord_to_xyz(int(coord_hex, 16))
        h = self.height
        return p == self.plane and x >> h == self.bx >> h and y >> h == self.by >> h and z >> h == self.bz >> h


@dataclass(frozen=True)
class ChainVerdict:
    """What a verifier says about one identity's events.

    `position` is where the identity stands, valid or not. For a valid chain
    it is the C of the last recognized action (8.9 item 5), or the c of the
    enter-virtual left open at the head (8.11.4 rule 7), whose id is then
    `open_bracket`; `head` is the id of the last event of the active chain,
    which may be a skipped action. For an invalid chain it is the last valid
    position (3.2, 8.7.3): the position the chain would give the identity if
    it ended at the last valid event before `invalid_at`, or the spawn
    coordinate when the spawn itself is invalid. The chain is frozen there
    until the identity respawns. `invalid_index` counts from the spawn at 0,
    and `reason` is a code in REASONS."""

    valid: bool
    chain: Tuple[str, ...] = ()
    position: Optional[str] = None
    head: Optional[str] = None
    open_bracket: Optional[str] = None
    skipped: Tuple[str, ...] = ()
    reason: Optional[str] = None
    invalid_at: Optional[str] = None
    invalid_index: Optional[int] = None
    detail: str = ""
    revision: str = CHAIN_RULES_REVISION

    def expected(self) -> Dict[str, Any]:
        """The fields the golden vectors lock, in their JSON shape."""
        if self.valid:
            return {
                "valid": True,
                "chain": list(self.chain),
                "position": self.position,
                "head": self.head,
                "open_bracket": self.open_bracket,
                "skipped": list(self.skipped),
            }
        return {
            "valid": False,
            "chain": list(self.chain),
            "position": self.position,
            "reason": self.reason,
            "invalid_at": self.invalid_at,
            "invalid_index": self.invalid_index,
        }


# ---------------------------------------------------------------- tags

def _tags(event: Dict[str, Any]) -> List[List[str]]:
    return [t for t in (event.get("tags") or []) if isinstance(t, list) and len(t) >= 2 and all(isinstance(s, str) for s in t)]


def _values(event: Dict[str, Any], name: str) -> List[str]:
    return [t[1] for t in _tags(event) if t[0] == name]


def _e(event: Dict[str, Any], marker: str) -> List[str]:
    """The ids of the e tags with this marker: ["e", <id>, <relay>, <marker>]."""
    return [t[1] for t in _tags(event) if t[0] == "e" and len(t) >= 4 and t[3] == marker]


def _action(event: Dict[str, Any]) -> Optional[str]:
    values = _values(event, "A")
    return values[0] if len(values) == 1 else None


def _is_hex32(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _decimal(value: Optional[str]) -> Optional[int]:
    """A base-10 height as rides write it (DECK-0001 5.2), else None."""
    return int(value) if isinstance(value, str) and value.isascii() and value.isdigit() else None


def event_id(event: Dict[str, Any]) -> str:
    """8.2: the NIP-01 id, sha256 of [0, pubkey, created_at, kind, tags, content]."""
    payload = [0, event.get("pubkey"), event.get("created_at"), event.get("kind"), event.get("tags"), event.get("content")]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def signature_ok(event: Dict[str, Any]) -> bool:
    """8.2: sig is a BIP-340 Schnorr signature of the id by the pubkey."""
    from coincurve import PublicKeyXOnly

    try:
        return PublicKeyXOnly(bytes.fromhex(event["pubkey"])).verify(bytes.fromhex(event["sig"]), bytes.fromhex(event["id"]))
    except (KeyError, TypeError, ValueError):
        return False


def nip01_shape_ok(event: Any) -> bool:
    """NIP-01's shape: id, pubkey, sig and content are strings, created_at
    and kind are integers, and tags is an array of arrays of strings. An
    event of any other shape is not a valid NIP-01 event, whatever its id
    hashes to, and resolution must never meet one: fork resolution compares
    created_at, and a tag holding a null would otherwise vanish from it."""
    if not isinstance(event, dict):
        return False
    if not all(isinstance(event.get(k), str) for k in ("id", "pubkey", "sig", "content")):
        return False
    if not all(isinstance(event.get(k), int) and not isinstance(event.get(k), bool) for k in ("created_at", "kind")):
        return False
    tags = event.get("tags")
    return isinstance(tags, list) and all(isinstance(t, list) and all(isinstance(v, str) for v in t) for t in tags)


def is_authentic(event: Any, pubkey: str) -> bool:
    """8.7.3: a valid NIP-01 event (the shape of nip01_shape_ok, its id the
    hash of its canonical serialization, its sig a valid signature of that
    id) by the identity itself, of the movement kind. Anything else is
    discarded before resolution, wherever the reader got it. A string that
    cannot be encoded as UTF-8, such as a lone surrogate, has no canonical
    serialization, so such an event is discarded too rather than stopping
    the verifier."""
    if not (nip01_shape_ok(event) and event["kind"] == MOVEMENT_KIND and event["pubkey"] == pubkey):
        return False
    try:
        if event_id(event) != event["id"]:
            return False
    except UnicodeEncodeError:
        return False
    return signature_ok(event)


def sector_tags_ok(event: Dict[str, Any], coord_hex: str) -> bool:
    """Section 10: X, Y, Z and S each exactly once, equal to the values
    computed from C (base-10 with no sign or leading zeros, S as
    "<sx>-<sy>-<sz>"). Comparing with the computed strings checks the format
    and the values at once."""
    sid, _ = coord_to_sector_id(coord=int(coord_hex, 16))
    want = {"X": str(sid.sx), "Y": str(sid.sy), "Z": str(sid.sz), "S": sid.tag()}
    return all(_values(event, name) == [value] for name, value in want.items())


def parse_region(event: Dict[str, Any]) -> Tuple[Optional[Region], str]:
    """8.11.1: the one region tag ["region", <coord_hex>, <H>], with H written
    canonically in [0, 85] and the base aligned (the low H bits of each axis
    zero). Returns (region, "") or (None, why). A check of form only."""
    tags = [t for t in _tags(event) if t[0] == "region"]
    if len(tags) != 1:
        return None, f"expected exactly one region tag, found {len(tags)}"
    tag = tags[0]
    if len(tag) < 3:
        return None, "region tag has no height"
    coord_hex, h_text = tag[1], tag[2]
    if not _is_hex32(coord_hex):
        return None, "region base is not a 32-byte lowercase hex coordinate"
    if not (h_text.isascii() and h_text.isdigit() and (h_text == "0" or not h_text.startswith("0"))):
        return None, f"region height {h_text!r} is not a canonical decimal"
    h = int(h_text)
    if h > REGION_MAX_HEIGHT:
        return None, f"region height {h} is above {REGION_MAX_HEIGHT}"
    bx, by, bz, plane = coord_to_xyz(int(coord_hex, 16))
    if any(v & ((1 << h) - 1) for v in (bx, by, bz)):
        return None, f"region base is not aligned to height {h}"
    return Region(bx, by, bz, plane, h), ""


def game_tag_ok(event: Dict[str, Any]) -> bool:
    """8.11.1, 8.11.5: exactly one ["p", <game_pubkey>, <relay_hint>, "game"],
    the pubkey 32 bytes of lowercase hex. The relay hint may be empty. The
    game is never contacted: this is a check of form only."""
    games = [t for t in _tags(event) if t[0] == "p" and len(t) >= 4 and t[3] == "game"]
    return len(games) == 1 and _is_hex32(games[0][1])


# ---------------------------------------------------------------- resolving (8.7.3)

def resolve_active_chain(events: Iterable[Dict[str, Any]], pubkey: str) -> List[Dict[str, Any]]:
    """8.7.3: the identity's active chain, spawn first, from events in any order.

    Every event that is not authentic is discarded first and treated as if
    it never existed, so a branch through one is cut off: the event that
    names it as previous is never reached, and the chain ends at the event
    before it. Then, by links, created_at and ids alone, with no proof or tag
    checked:

    1. The newest spawn by created_at, the larger id when they tie, whether
       or not it is valid.
    2. Only events whose e genesis names that spawn take part; the rest are an
       older chain's history.
    3. From the spawn, follow e previous links forward.
    4. At a fork the event with the smallest created_at continues the chain,
       the smaller id when they tie, even if it is invalid and a later
       branch is valid; the other branches are dropped.
    5. The chain ends at the first event that nothing names as previous.

    A spawn names no previous event, so an event whose A is spawn is never a
    link: it starts a chain of its own wherever it was published. The first
    e tag with each marker is the one followed."""
    mine: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        if is_authentic(ev, pubkey) and ev["id"] not in mine:
            mine[ev["id"]] = ev
    spawns = [ev for ev in mine.values() if _values(ev, "A")[:1] == ["spawn"]]
    if not spawns:
        return []
    spawn = max(spawns, key=lambda ev: (ev.get("created_at", 0), ev["id"]))
    children: Dict[str, List[Dict[str, Any]]] = {}
    for ev in mine.values():
        if _values(ev, "A")[:1] == ["spawn"]:
            continue
        genesis, previous = _e(ev, "genesis")[:1], _e(ev, "previous")[:1]
        if genesis == [spawn["id"]] and previous:
            children.setdefault(previous[0], []).append(ev)
    chain = [spawn]
    while True:
        nxt = children.get(chain[-1]["id"])
        if not nxt:
            return chain
        chain.append(min(nxt, key=lambda ev: (ev.get("created_at", 0), ev["id"])))


# ---------------------------------------------------------------- verifying

@dataclass
class _Bracket:
    entry_id: str
    base: str  # the entry's c, which its C repeats: the identity's position while the bracket is open (rule 1)
    lookback: Dict[str, Any]  # the action before the entry, which the exit stands for (rule 8)


@dataclass
class _Walk:
    line: Optional[Line]
    max_compute_height: int
    position: str = ""
    lookback: Dict[str, Any] = field(default_factory=dict)  # the recognized action that stands before the next one
    bracket: Optional[_Bracket] = None
    skipped: List[str] = field(default_factory=list)

    def held(self) -> str:
        """The identity's position as the chain gives it so far: the base
        position while a bracket is open (rule 7), else the C of the last
        recognized action (8.9 item 5)."""
        return self.bracket.base if self.bracket else self.position

    def step(self, index: int, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """Check one event; returns (reason, detail) when it breaks a rule."""
        action = _action(event)
        if action is None:
            return "a-tag", f"expected exactly one A tag, found {len(_values(event, 'A'))}"
        if index == 0:
            return self._spawn(event)
        if self.bracket is not None:
            return self._inside(event, action)
        if action not in RECOGNIZED_ACTIONS:
            # 8.9: authentic, linked and one A tag, all already established; otherwise as if absent.
            self.skipped.append(event["id"])
            return None
        return self._outside(event, action)

    @staticmethod
    def _links(event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        for marker in ("genesis", "previous"):
            if len(_e(event, marker)) != 1:
                return "malformed", f"e {marker}: expected exactly one"
        return None

    @staticmethod
    def _coord(event: Dict[str, Any], name: str) -> Tuple[str, Optional[Tuple[str, str]]]:
        values = _values(event, name)
        if len(values) != 1 or not _is_hex32(values[0]):
            return "", ("malformed", f"{name}: expected exactly one 32-byte lowercase hex coordinate")
        return values[0], None

    def _spawn(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        C, bad = self._coord(event, "C")
        if bad:
            return bad
        if C != event.get("pubkey"):
            return "spawn-coordinate", "the spawn's C is not its pubkey"
        if not sector_tags_ok(event, C):
            return "sector-tags", "the spawn's sector tags are not X, Y, Z and S once each, computed from C"
        self.position = C
        self.lookback = event
        return None

    def _inside(self, event: Dict[str, Any], action: str) -> Optional[Tuple[str, str]]:
        """8.11.5 steps 2 and 3: a virtual action, checked only for its links
        (which resolution guarantees) and its one A tag, or the exit."""
        b = self.bracket
        assert b is not None
        if action in NOT_IN_BRACKET:
            return "base-action-in-bracket", f"{action} inside the bracket opened by {b.entry_id}"
        if action != "exit-virtual":
            return None
        bad = self._links(event)
        if bad:
            return bad
        entries = _e(event, "entry")
        if len(entries) != 1:
            return "malformed", "e entry: expected exactly one"
        if entries[0] != b.entry_id:
            return "exit-wrong-entry", f"e entry names {entries[0]}, the open bracket is {b.entry_id}"
        C, bad = self._coord(event, "C")
        if bad:
            return bad
        if C != b.base:
            return "exit-position", "the exit's C is not the c of its enter-virtual"
        if not sector_tags_ok(event, C):
            return "sector-tags", "the exit's sector tags are not X, Y, Z and S once each, computed from C"
        # Rule 2: the base position is restored and continuity resumes from it;
        # rule 8: the exit stands for the action before the entry.
        self.position = C
        self.lookback = b.lookback
        self.bracket = None
        return None

    def _outside(self, event: Dict[str, Any], action: str) -> Optional[Tuple[str, str]]:
        if action == "exit-virtual":
            return "exit-without-bracket", "no bracket is open"
        bad = self._links(event)
        if bad:
            return bad
        c, bad = self._coord(event, "c")
        if bad:
            return bad
        C, bad = self._coord(event, "C")
        if bad:
            return bad
        if c != self.position:
            return "c-mismatch", "c is not the C of the nearest recognized action before it"
        if not sector_tags_ok(event, C):
            return "sector-tags", "sector tags are not X, Y, Z and S once each, computed from C"
        if action == "enter-virtual":
            if C != c:
                return "enter-virtual-moved", "C is not c; entering a game does not move the identity"
            region, why = parse_region(event)
            if region is None:
                return "region", why
            if not game_tag_ok(event):
                return "game-tag", "expected exactly one p tag marked game holding a 32-byte lowercase hex pubkey"
            # Rule 1: the position is held at c; position and look-back stay as they are until the exit.
            self.bracket = _Bracket(event["id"], c, self.lookback)
            return None
        if action == "hop":
            failures = verify_hop_event(event, max_compute_height=self.max_compute_height)
            if failures:
                return "hop-proof", "; ".join(failures)
        elif action == "sidestep":
            failures = verify_sidestep_event(event)
            if failures:
                return "sidestep-proof", "; ".join(failures)
        elif action == "enter-hyperspace":
            if C != c:
                return "enter-hyperspace-moved", "C is not c; boarding does not move the identity"
            failures = verify_enter_hyperspace_event(event)
            if failures:
                return "enter-hyperspace-proof", "; ".join(failures)
        elif action == "hyperjump":
            bad = self._ride(event, C)
            if bad:
                return bad
        self.position = C
        self.lookback = event
        return None

    def _ride(self, event: Dict[str, Any], C: str) -> Optional[Tuple[str, str]]:
        """DECK-0001 5.6 and 4.3 against the action this ride looks back to,
        then the stop of B and the ride's proof (5.5 Level 1)."""
        if self.line is None:
            raise LineRequired(f"hyperjump {event['id']} needs the line's block data")
        line = self.line
        from_height, to_height = _decimal(next(iter(_values(event, "from_height")), None)), _decimal(next(iter(_values(event, "B")), None))
        if from_height is None or to_height is None:
            return "malformed", "from_height and B: expected base-10 block heights"
        if from_height == to_height:
            return "hyperjump-zero-length", "B equals from_height; every ride passes at least one block"
        before = _action(self.lookback)
        if before not in ("enter-hyperspace", "hyperjump"):
            return "hyperjump-predecessor", f"the action before this ride is {before}"
        if before == "enter-hyperspace":
            as_of = _decimal(next(iter(_values(event, "as_of")), None))
            if as_of is None or as_of > line.tip or as_of < to_height:
                return "hyperjump-as-of", "the first ride needs as_of, a height on the line and at least B"
            station = line.station(_values(self.lookback, "C")[0], as_of)
            if from_height != station:
                return "hyperjump-station", f"from_height {from_height} but the station within {as_of} is {station}"
        else:
            previous_b = _decimal(_values(self.lookback, "B")[0])
            if from_height != previous_b:
                return "hyperjump-from-height", f"from_height {from_height} but the previous ride ended at {previous_b}"
        stop = line.stop(to_height)
        if stop is None or stop.coord_hex != C:
            return "hyperjump-stop", f"C is not the stop coordinate of block {to_height}"
        failures = verify_ride_event(event, line.block_hash)
        if failures:
            return "hyperjump-proof", "; ".join(failures)
        return None


def verify_chain(
    events: Iterable[Dict[str, Any]],
    *,
    pubkey: Optional[str] = None,
    line: Optional[Line] = None,
    max_compute_height: int = DEFAULT_MAX_COMPUTE_HEIGHT,
) -> ChainVerdict:
    """Discard inauthentic events, resolve the identity's active chain
    (8.7.3) and verify it under the chain rules of revision
    CHAIN_RULES_REVISION.

    `pubkey` defaults to the one pubkey among the kind 3333 events. Every
    event must be signed: an unsigned or wrongly signed event is not
    authentic and is discarded even if it was never published (8.2), so an
    unsigned local chain resolves to no chain at all. `line` supplies
    Bitcoin's block data for rides, and LineRequired is raised when a ride is
    met without it. A hop taller than `max_compute_height` raises ValueError.
    Neither exception is a verdict: the rules cannot be applied without the
    data or the work."""
    events = list(events)
    if pubkey is None:
        pubkeys = {ev.get("pubkey") for ev in events if isinstance(ev, dict) and ev.get("kind") == MOVEMENT_KIND}
        if len(pubkeys) != 1:
            raise ValueError(f"expected the events of one pubkey, found {len(pubkeys)}; pass pubkey=")
        pubkey = pubkeys.pop()
    chain = resolve_active_chain(events, pubkey)  # type: ignore[arg-type]
    ids = tuple(ev["id"] for ev in chain)
    if not chain:
        return ChainVerdict(valid=False, reason="no-spawn", detail=REASONS["no-spawn"])
    walk = _Walk(line, max_compute_height)
    for index, event in enumerate(chain):
        before = walk.held() or pubkey  # an invalid spawn leaves the identity at its spawn coordinate (3.2)
        failure = walk.step(index, event)
        if failure:
            reason, detail = failure
            assert reason in REASONS, reason
            return ChainVerdict(
                valid=False, chain=ids, position=before, reason=reason, invalid_at=event["id"], invalid_index=index, detail=detail,
            )
    return ChainVerdict(
        valid=True,
        chain=ids,
        position=walk.held(),
        head=ids[-1],
        open_bracket=walk.bracket.entry_id if walk.bracket else None,
        skipped=tuple(walk.skipped),
    )
