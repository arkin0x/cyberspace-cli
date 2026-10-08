"""The chain rules of CYBERSPACE_V2.md section 8.12, revision
2026-09-28-virtual-brackets with the rulings folded in on 2026-10-07 and
2026-10-08: which movement chains are valid and where an identity stands.

A verifier holds whatever kind 3333 events relays gave it for one pubkey, in
no particular order. It first discards every event that is not authentic
(8.7.3): an event that is not NIP-01 in shape, whose id is not its NIP-01
hash, whose sig is not a valid signature of that id by its pubkey (8.2),
whose pubkey is not the identity's, or whose kind is not 3333. A discarded
event is treated as if it never existed, so a branch that runs through one
is cut off and the chain ends at the event before it, and a discarded event
can never make a fork. Nobody can end another identity's chain by posting a
forged event.

It then resolves the authentic events into the active chain (8.7.3) by links
alone: the newest spawn, valid or not (any A tag equal to spawn makes an event
a spawn), then forward through e previous links among the events whose e
genesis names that spawn. A fork is fatal: when two or more of those events
name the same event as previous, whatever their actions and whichever is
valid or earlier, the whole chain is invalid from the spawn and the identity
stands at its spawn coordinate. Forks are found from the links before any
proof is checked.

It then walks the active chain from the spawn and checks every event in
order. The first event that breaks a rule makes the chain invalid from that
event, the walk stops there, and the identity stands frozen at its last valid
position: the position the chain would give it if it ended at the last valid
event (3.2, 8.7.3), or the spawn coordinate when the spawn itself is invalid.

Every tag a chain rule reads must appear exactly once with a well-formed
value. A tag counts by its name alone, so a bare ["A"] is an A tag (with no
value, and invalid) and a second copy of any read tag is invalid, whatever
its value. Tags no rule reads are free. Resolution follows the first copy of
each e tag; validity then rejects a second copy.

What the walk checks:

- Every event carries exactly one A tag with a non-empty value (8.8), and
  every event but the spawn exactly one e genesis and one e previous tag.
- Recognized actions (8.9) are the base actions (spawn, hop, sidestep,
  enter-virtual, exit-virtual) and the actions of every mandatory DECK
  (DECK-0001: enter-hyperspace, hyperjump). Each carries its C, the tags its
  rules read, and the sector tags X, Y, Z and S, each exactly once, the sector
  tags equal to the values computed from C (10). Outside a bracket each
  starts where the chain carries it: its c equals the C of the nearest
  recognized action before it (continuity). Hops, sidesteps, boardings and
  rides have their proofs checked in full at Level 1, each seeded by the id
  its e previous tag names.
- An action the verifier does not recognize is skipped (8.9): it is checked
  only for being authentic, linked (one e genesis, one e previous) and
  carrying one A tag, so it neither moves the identity nor stands in for the
  action before the next one. A skipped action that changed the position
  leaves the next recognized action's c mismatched.
- A virtual bracket (8.11) is opaque and checked as a unit. Its
  enter-virtual action does not move the identity (C equals c), and its game
  p tag and region tag are checked for form only; the base position need not
  lie in or near the region. Inside it every name that rule 3 does not
  reserve is a virtual action, checked only for its links and its one A tag;
  every other tag on it belongs to the game. The exit names the open entry
  (one e entry tag) and its C restores the entry's c; its c is never read.
  Continuity resumes after the exit, and the exit stands in for the action
  before its entry when a later rule looks back (rule 8).
- Rides follow DECK-0001 section 4.3: a hyperjump looks back (through skipped
  actions and closed brackets) to an enter-hyperspace, whose first ride
  departs from the station within the declared as_of bound, or to a
  hyperjump, whose B it departs from. No ride has length zero (5.6), and that
  is checked before the ride's proof tags. Rides need Bitcoin's block data,
  supplied as a Line (cyberspace_core.hyperspace).

This CLI implements no optional DECK, so its recognized actions are exactly
the base and DECK-0001 actions. The golden vectors in
vectors/chain-rules-2026-09-28-virtual-brackets.json lock every verdict this
module gives, for the TypeScript ports to check against.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from cyberspace_core.coords import AXIS_BITS, coord_to_xyz
from cyberspace_core.hyperspace import Line, verify_enter_hyperspace_event
from cyberspace_core.movement import DEFAULT_MAX_COMPUTE_HEIGHT, decode_nonce, verify_hop_event, verify_sidestep_event
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
    "fork": "two or more events whose e genesis names the newest spawn name the same event as e previous (each event's first e previous tag); the chain is invalid from the spawn, whatever the forking events are and whichever is valid or earlier (8.7.3)",
    "a-tag": "the event carries no A tag, more than one, or one with no value or an empty value; a bare [\"A\"] counts as an A tag (8.8)",
    "malformed": "a tag a chain rule reads is missing, repeated, valueless or ill-formed. Each of these must appear exactly once: e genesis and e previous on every event but the spawn (32-byte lowercase hex); e entry on an exit-virtual (32-byte lowercase hex); C on every recognized action and c on every recognized action but the exit-virtual (32-byte lowercase hex); proof on a hop, sidestep, enter-hyperspace or hyperjump (32-byte lowercase hex); mr (three colon-joined 32-byte lowercase hex roots), mp (non-empty) and hx, hy and hz (base-10) on a sidestep; from_height and B (base-10) and mp (non-empty) on a hyperjump; as_of (base-10) on the first ride after boarding, when it is present at all. mn (16 lowercase hex characters) may be absent on a sidestep or hyperjump (6.16, DECK-0001 5.8) but not repeated",
    "sector-tags": "a recognized action's X, Y, Z or S tag is missing, repeated (a valueless copy counts), or not the value computed from its C (10)",
    "spawn-coordinate": "the spawn's C is not its pubkey (8.3)",
    "c-mismatch": "c is not the C of the nearest recognized action before it (8.9 item 2, continuity)",
    "hop-proof": "the hop's proof does not verify (8.7.1)",
    "sidestep-proof": "the sidestep does not verify at Level 1 (8.7.2): its geometry, the values of its height tags, its openings, its price, or a missing mn on an unlisted sidestep (6.16)",
    "enter-hyperspace-moved": "an enter-hyperspace's C is not its c (DECK-0001 3.1)",
    "enter-hyperspace-proof": "the entry proof does not verify (DECK-0001 3.2)",
    "hyperjump-predecessor": "the action a hyperjump looks back to is neither enter-hyperspace nor hyperjump (DECK-0001 4.3)",
    "hyperjump-zero-length": "a ride whose B equals its from_height; there is no zero-length ride (DECK-0001 5.2, 5.6)",
    "hyperjump-as-of": "the first ride after boarding has no as_of tag, or its as_of is not a height on the line, or is below B (DECK-0001 4.2, 4.3)",
    "hyperjump-station": "the first ride after boarding does not depart from the station (DECK-0001 4.2, 4.3)",
    "hyperjump-from-height": "a later ride does not depart from the previous ride's B (DECK-0001 4.3)",
    "hyperjump-stop": "the ride's C is not the stop coordinate of B, or B is not a height on the line (DECK-0001 5.5 Level 1 step 2)",
    "hyperjump-proof": "the ride's proof does not verify at Level 1 (DECK-0001 5.5, 5.8): openings that do not decode or do not reach the root, the price, or a missing mn on an unlisted ride",
    "enter-virtual-moved": "an enter-virtual's C is not its c; entering a game does not move the identity (8.11.1)",
    "region": "the enter-virtual's region tag is missing, repeated (a valueless copy counts) or ill-formed: H not canonical in [0, 85], or the base not aligned (8.11.1)",
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
class Resolution:
    """The outcome of 8.7.3: the active chain from the spawn, or, when two or
    more events name the same event as previous, the chain up to that event
    and the ids of the events that fork from it (sorted)."""

    chain: List[Dict[str, Any]]
    fork: Tuple[str, ...] = ()


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
    coordinate when the spawn itself is invalid or the chain forks. The chain
    is frozen there until the identity respawns. `invalid_index` counts from
    the spawn at 0, and `reason` is a code in REASONS. For a fork, `chain`
    runs from the spawn to the event the forking events name, `invalid_at` is
    the spawn, and `detail` names the forking events."""

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

Bad = Tuple[str, str]


def _named(event: Dict[str, Any], name: str) -> List[List[str]]:
    """Every tag with this name, whatever its length: a bare [name] counts."""
    return [t for t in (event.get("tags") or []) if isinstance(t, list) and t and t[0] == name]


def _value(tag: List[str]) -> str:
    """A tag's value, the empty string for a bare tag."""
    return tag[1] if len(tag) >= 2 and isinstance(tag[1], str) else ""


def _marked_e(event: Dict[str, Any], marker: str) -> List[List[str]]:
    """The e tags with this marker: ["e", <id>, <relay>, <marker>]."""
    return [t for t in _named(event, "e") if len(t) >= 4 and t[3] == marker]


def _first_e(event: Dict[str, Any], marker: str) -> Optional[str]:
    """The id the first e tag with this marker names: what resolution follows."""
    tags = _marked_e(event, marker)
    return _value(tags[0]) if tags else None


def _is_hex32(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _is_decimal(value: str) -> bool:
    return value.isascii() and value.isdigit()


def _is_roots(value: str) -> bool:
    parts = value.split(":")
    return len(parts) == 3 and all(_is_hex32(p) for p in parts)


def _non_empty(value: str) -> bool:
    return value != ""


def _once(event: Dict[str, Any], name: str, form: Callable[[str], bool]) -> Optional[str]:
    """The value of the one tag with this name, if there is exactly one and
    its value has the form; else None."""
    tags = _named(event, name)
    return _value(tags[0]) if len(tags) == 1 and form(_value(tags[0])) else None


def _require(event: Dict[str, Any], forms: Iterable[Tuple[str, Callable[[str], bool]]]) -> Optional[Bad]:
    for name, form in forms:
        if _once(event, name, form) is None:
            return "malformed", f"{name}: expected exactly once with a well-formed value"
    return None


def _at_most_once(event: Dict[str, Any], name: str, form: Callable[[str], bool]) -> Optional[Bad]:
    tags = _named(event, name)
    if len(tags) > 1 or (tags and not form(_value(tags[0]))):
        return "malformed", f"{name}: expected at most once with a well-formed value"
    return None


def _action(event: Dict[str, Any]) -> Optional[str]:
    """8.8: the value of the one A tag, None when there is not exactly one or its value is empty."""
    tags = _named(event, "A")
    return _value(tags[0]) if len(tags) == 1 and _value(tags[0]) else None


def _is_spawn(event: Dict[str, Any]) -> bool:
    """8.7.3 rule 1: any A tag whose value is spawn makes an event a spawn, wherever it stands among the tags."""
    return any(_value(t) == "spawn" for t in _named(event, "A"))


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
    hashes to, and resolution must never meet one: it compares created_at,
    and a tag holding a null would otherwise read as some other tag."""
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
    """Section 10: X, Y, Z and S each exactly once (a valueless copy counts),
    equal to the values computed from C (base-10 with no sign or leading
    zeros, S as "<sx>-<sy>-<sz>"). Comparing with the computed strings checks
    the format and the values at once."""
    sid, _ = coord_to_sector_id(coord=int(coord_hex, 16))
    want = {"X": str(sid.sx), "Y": str(sid.sy), "Z": str(sid.sz), "S": sid.tag()}
    return all(_once(event, name, lambda v, w=value: v == w) is not None for name, value in want.items())


def parse_region(event: Dict[str, Any]) -> Tuple[Optional[Region], str]:
    """8.11.1: the one region tag ["region", <coord_hex>, <H>] (a valueless
    copy counts), with H written canonically in [0, 85] and the base aligned
    (the low H bits of each axis zero). Returns (region, "") or (None, why).
    A check of form only."""
    tags = _named(event, "region")
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
    the pubkey 32 bytes of lowercase hex. The relay hint may be empty. p tags
    without the game marker are not read. The game is never contacted: this
    is a check of form only."""
    games = [t for t in _named(event, "p") if len(t) >= 4 and t[3] == "game"]
    return len(games) == 1 and _is_hex32(games[0][1])


# ---------------------------------------------------------------- resolving (8.7.3)

def resolve_active_chain(events: Iterable[Dict[str, Any]], pubkey: str) -> Resolution:
    """8.7.3: the identity's active chain, spawn first, from events in any order.

    Every event that is not authentic is discarded first and treated as if
    it never existed, so a branch through one is cut off: the event that
    names it as previous is never reached, and the chain ends at the event
    before it. A discarded event is never a branch of a fork. Then, by links
    alone, with no proof or tag value checked:

    1. The newest spawn by created_at, the larger id when they tie, whether
       or not it is valid. Any A tag equal to spawn makes an event a spawn.
    2. Only events whose e genesis names that spawn take part; the rest are an
       older chain's history.
    3. From the spawn, follow e previous links forward.
    4. A fork is fatal: when more than one event names the current event as
       previous, resolution stops there and reports the fork, whatever the
       forking events are and whichever is valid or earlier.
    5. Otherwise the chain ends at the first event that nothing names as
       previous.

    A spawn names no previous event, so an event that is a spawn is never a
    link: it starts a chain of its own wherever it was published. The first
    e tag with each marker is the one followed; a second copy makes the event
    invalid when the chain is verified, but does not change what is followed.
    Events that are never reached, behind a discarded event or naming an id
    nobody holds, cannot make a fork, because the walk never comes to them."""
    mine: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        if is_authentic(ev, pubkey) and ev["id"] not in mine:
            mine[ev["id"]] = ev
    spawns = [ev for ev in mine.values() if _is_spawn(ev)]
    if not spawns:
        return Resolution([])
    spawn = max(spawns, key=lambda ev: (ev["created_at"], ev["id"]))
    children: Dict[str, List[Dict[str, Any]]] = {}
    for ev in mine.values():
        if _is_spawn(ev):
            continue
        previous = _first_e(ev, "previous")
        if _first_e(ev, "genesis") == spawn["id"] and previous:
            children.setdefault(previous, []).append(ev)
    chain = [spawn]
    while True:
        nxt = children.get(chain[-1]["id"], [])
        if not nxt:
            return Resolution(chain)
        if len(nxt) > 1:
            return Resolution(chain, tuple(sorted(ev["id"] for ev in nxt)))
        chain.append(nxt[0])


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

    def step(self, index: int, event: Dict[str, Any]) -> Optional[Bad]:
        """Check one event; returns (reason, detail) when it breaks a rule."""
        action = _action(event)
        if action is None:
            return "a-tag", f"expected exactly one A tag with a value, found {len(_named(event, 'A'))} A tags"
        if index == 0:
            return self._spawn(event)
        for marker in ("genesis", "previous"):
            tags = _marked_e(event, marker)
            if len(tags) != 1 or not _is_hex32(_value(tags[0])):
                return "malformed", f"e {marker}: expected exactly once with a 32-byte lowercase hex id"
        if self.bracket is not None:
            return self._inside(event, action)
        if action not in RECOGNIZED_ACTIONS:
            # 8.9: authentic, linked and one A tag, all now established; otherwise as if absent.
            self.skipped.append(event["id"])
            return None
        return self._outside(event, action)

    def _spawn(self, event: Dict[str, Any]) -> Optional[Bad]:
        C = _once(event, "C", _is_hex32)
        if C is None:
            return "malformed", "C: expected exactly once with a 32-byte lowercase hex coordinate"
        if C != event.get("pubkey"):
            return "spawn-coordinate", "the spawn's C is not its pubkey"
        if not sector_tags_ok(event, C):
            return "sector-tags", "the spawn's sector tags are not X, Y, Z and S once each, computed from C"
        self.position = C
        self.lookback = event
        return None

    def _inside(self, event: Dict[str, Any], action: str) -> Optional[Bad]:
        """8.11.5 steps 2 and 3: a virtual action, checked only for its links
        and its one A tag (already established), or the exit."""
        b = self.bracket
        assert b is not None
        if action in NOT_IN_BRACKET:
            return "base-action-in-bracket", f"{action} inside the bracket opened by {b.entry_id}"
        if action != "exit-virtual":
            return None
        entry = _marked_e(event, "entry")
        if len(entry) != 1 or not _is_hex32(_value(entry[0])):
            return "malformed", "e entry: expected exactly once with a 32-byte lowercase hex id"
        if _value(entry[0]) != b.entry_id:
            return "exit-wrong-entry", f"e entry names {_value(entry[0])}, the open bracket is {b.entry_id}"
        C = _once(event, "C", _is_hex32)
        if C is None:
            return "malformed", "C: expected exactly once with a 32-byte lowercase hex coordinate"
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

    def _outside(self, event: Dict[str, Any], action: str) -> Optional[Bad]:
        if action == "exit-virtual":
            return "exit-without-bracket", "no bracket is open"
        bad = _require(event, (("c", _is_hex32), ("C", _is_hex32)))
        if bad:
            return bad
        c, C = _once(event, "c", _is_hex32), _once(event, "C", _is_hex32)
        if c != self.position:
            return "c-mismatch", "c is not the C of the nearest recognized action before it"
        if not sector_tags_ok(event, C):  # type: ignore[arg-type]
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
            self.bracket = _Bracket(event["id"], c, self.lookback)  # type: ignore[arg-type]
            return None
        if action == "hop":
            bad = _require(event, (("proof", _is_hex32),))
            if bad:
                return bad
            failures = verify_hop_event(event, max_compute_height=self.max_compute_height)
            if failures:
                return "hop-proof", "; ".join(failures)
        elif action == "sidestep":
            bad = _require(event, (("proof", _is_hex32), ("mr", _is_roots), ("mp", _non_empty),
                                   ("hx", _is_decimal), ("hy", _is_decimal), ("hz", _is_decimal)))
            bad = bad or _at_most_once(event, "mn", lambda v: decode_nonce(v) is not None)
            if bad:
                return bad
            failures = verify_sidestep_event(event)
            if failures:
                return "sidestep-proof", "; ".join(failures)
        elif action == "enter-hyperspace":
            if C != c:
                return "enter-hyperspace-moved", "C is not c; boarding does not move the identity"
            bad = _require(event, (("proof", _is_hex32),))
            if bad:
                return bad
            failures = verify_enter_hyperspace_event(event)
            if failures:
                return "enter-hyperspace-proof", "; ".join(failures)
        elif action == "hyperjump":
            bad = self._ride(event, C)  # type: ignore[arg-type]
            if bad:
                return bad
        self.position = C  # type: ignore[assignment]
        self.lookback = event
        return None

    def _ride(self, event: Dict[str, Any], C: str) -> Optional[Bad]:
        """DECK-0001 5.6 (before the proof tags, which a zero-length ride
        cannot carry in a verifiable form), the ride's tags, 4.3 against the
        action this ride looks back to, then the stop of B and the ride's
        proof (5.5 Level 1)."""
        if self.line is None:
            raise LineRequired(f"hyperjump {event['id']} needs the line's block data")
        line = self.line
        bad = _require(event, (("from_height", _is_decimal), ("B", _is_decimal)))
        if bad:
            return bad
        from_height, to_height = int(_once(event, "from_height", _is_decimal)), int(_once(event, "B", _is_decimal))  # type: ignore[arg-type]
        if from_height == to_height:
            return "hyperjump-zero-length", "B equals from_height; every ride passes at least one block"
        bad = _require(event, (("proof", _is_hex32), ("mp", _non_empty)))
        bad = bad or _at_most_once(event, "mn", lambda v: decode_nonce(v) is not None)
        if bad:
            return bad
        before = _action(self.lookback)
        if before not in ("enter-hyperspace", "hyperjump"):
            return "hyperjump-predecessor", f"the action before this ride is {before}"
        if before == "enter-hyperspace":
            as_of_tags = _named(event, "as_of")
            if not as_of_tags:
                return "hyperjump-as-of", "the first ride after boarding carries no as_of"
            if len(as_of_tags) > 1 or not _is_decimal(_value(as_of_tags[0])):
                return "malformed", "as_of: expected exactly once with a base-10 height"
            as_of = int(_value(as_of_tags[0]))
            if as_of > line.tip or as_of < to_height:
                return "hyperjump-as-of", "as_of must be a height on the line and at least B"
            station = line.station(_once(self.lookback, "C", _is_hex32), as_of)  # type: ignore[arg-type]
            if from_height != station:
                return "hyperjump-station", f"from_height {from_height} but the station within {as_of} is {station}"
        else:
            previous_b = int(_once(self.lookback, "B", _is_decimal))  # type: ignore[arg-type]
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
    (8.7.3), reject a fork, and verify the chain under the chain rules of
    revision CHAIN_RULES_REVISION.

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
    resolution = resolve_active_chain(events, pubkey)  # type: ignore[arg-type]
    chain = resolution.chain
    ids = tuple(ev["id"] for ev in chain)
    if not chain:
        return ChainVerdict(valid=False, reason="no-spawn", detail=REASONS["no-spawn"])
    if resolution.fork:
        return ChainVerdict(
            valid=False, chain=ids, position=pubkey, reason="fork", invalid_at=ids[0], invalid_index=0,
            detail=f"{', '.join(resolution.fork)} all name {ids[-1]} as previous",
        )
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
