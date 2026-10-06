"""The chain rules of CYBERSPACE_V2.md section 8.12, revision
2026-09-28-virtual-brackets: which movement chains are valid and which event
is an identity's position.

A verifier holds whatever kind 3333 events relays gave it for one pubkey, in
no particular order. It sets aside every event that is not authentic: one
whose id is not its NIP-01 hash or, when signatures are checked, whose sig
does not verify (8.2). Such an event was not published by the identity, and
anyone can make one, so it must not take part in choosing the chain: a forged
event naming a real one as previous, with an earlier created_at, would
otherwise win the fork and end a chain its owner never broke (3.2). It then
resolves the rest into the active chain (8.7.3):
the newest spawn, then forward through e previous links among the events
whose e genesis names that spawn, the branch signed first continuing at a
fork. It then walks the active chain from the spawn and checks every event
in order. The first event that breaks a rule makes the chain invalid from
that event, and the walk stops there.

What the walk checks:

- Recognized actions (8.9) are the base actions (spawn, hop, sidestep,
  enter-virtual, exit-virtual) and the actions of every mandatory DECK
  (DECK-0001: enter-hyperspace, hyperjump). Each must start where the chain
  carries it: its c equals the C of the nearest recognized action before it.
  Hops, sidesteps, boardings and rides have their proofs checked in full at
  Level 1, each seeded by the id its e previous tag names.
- An action the verifier does not recognize is skipped (8.9): it is linked
  through but otherwise treated as absent, so it neither moves the identity
  nor stands in for the action before the next one. A skipped action that
  changed the position leaves the next recognized action's c mismatched.
- A virtual bracket (8.11) runs from an enter-virtual action to the
  exit-virtual action that closes it. Inside it every name that is not a
  base action is a virtual action, checked only for its links, its c and that
  its C lies in the declared region. The identity's position is held at the
  entry's c throughout, and an exit stands in for the action before its entry
  when a later rule looks back (rule 8).
- Rides follow DECK-0001 section 4.3: a hyperjump looks back (through skipped
  actions and closed brackets) to an enter-hyperspace, whose first ride
  departs from the station within the declared as_of bound, or to a
  hyperjump, whose B it departs from. Rides need Bitcoin's block data,
  supplied as a Line (cyberspace_core.hyperspace).

Sector tags (section 10) are not checked: they are derived from C for
relays to index, and the chain rules read nothing from them.

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

CHAIN_RULES_REVISION = "2026-09-28-virtual-brackets"

MOVEMENT_KIND = 3333

# 8.8: the base actions.
BASE_ACTIONS = frozenset({"spawn", "hop", "sidestep", "enter-virtual", "exit-virtual"})
# 8.9, 8.12: the actions of every mandatory DECK. At this revision that is DECK-0001 alone.
MANDATORY_DECK_ACTIONS = frozenset({"enter-hyperspace", "hyperjump"})
RECOGNIZED_ACTIONS = BASE_ACTIONS | MANDATORY_DECK_ACTIONS
# 8.11.4 rule 3: the names that make an event inside a bracket invalid.
NOT_IN_BRACKET = frozenset({"hop", "sidestep", "enter-hyperspace", "hyperjump", "enter-virtual"})

# 8.11.1: a region's height is an integer in [0, 85].
REGION_MAX_HEIGHT = AXIS_BITS

# The reason a chain is invalid, one code per rule. The codes, not the
# free-text detail, are what the golden vectors lock.
REASONS: Dict[str, str] = {
    "no-spawn": "no spawn event for this pubkey, so there is no chain (8.7.3 step 1)",
    "malformed": "a tag the chain rules read is missing, repeated or ill-formed: A, e genesis, e previous, e entry, c, C, from_height, B",
    "spawn-coordinate": "the spawn's C is not its pubkey (8.3)",
    "c-mismatch": "c is not the C of the nearest recognized action before it (8.9 step 2), or inside a bracket not the C of the previous event (8.11.5)",
    "hop-proof": "the hop's proof does not verify (8.7.1), including a missing or ill-formed proof tag",
    "sidestep-proof": "the sidestep does not verify at Level 1 (8.7.2), including its geometry, height tags, price and openings",
    "enter-hyperspace-moved": "an enter-hyperspace's C is not its c (DECK-0001 3.1)",
    "enter-hyperspace-proof": "the entry proof does not verify (DECK-0001 3.2)",
    "hyperjump-predecessor": "the action a hyperjump looks back to is neither enter-hyperspace nor hyperjump (DECK-0001 4.3)",
    "hyperjump-as-of": "the first ride after boarding has no as_of tag, or as_of is not a height on the line, or is below B (DECK-0001 4.2, 4.3)",
    "hyperjump-station": "the first ride after boarding does not depart from the station (DECK-0001 4.2, 4.3)",
    "hyperjump-from-height": "a later ride does not depart from the previous ride's B (DECK-0001 4.3)",
    "hyperjump-zero-length": "a ride with from_height equal to B that is not a first ride from the station (DECK-0001 5.2, 5.6)",
    "hyperjump-stop": "the ride's C is not the stop coordinate of B, or B is not a height on the line (DECK-0001 5.5 Level 1 step 2)",
    "hyperjump-proof": "the ride's proof does not verify at Level 1 (DECK-0001 5.5, 5.8), including ill-formed proof, mp or mn tags",
    "region": "the enter-virtual's region tag is missing, repeated or ill-formed: H not canonical in [0, 85], or the base not aligned (8.11.1)",
    "game-tag": "the enter-virtual does not carry exactly one p tag marked game holding a 32-byte lowercase hex pubkey (8.11.1)",
    "outside-region": "the C of an enter-virtual or a virtual action lies outside the declared region (8.11.4 rule 4)",
    "base-action-in-bracket": "hop, sidestep, enter-hyperspace, hyperjump or enter-virtual inside an open bracket (8.11.4 rule 3)",
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
    """8.11.1: the aligned cube of height H at base (bx, by, bz) on plane P."""

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

    For a valid chain, `position` is the identity's position in cyberspace:
    the C of the last recognized action (8.9 step 5), or the c of the
    enter-virtual left open at the head (8.11.4 rule 7), whose id is then
    `open_bracket`. `head` is the id of the last event of the active chain,
    which may be a skipped action. For an invalid chain, `invalid_at` and
    `invalid_index` name the first event that breaks a rule (the index counts
    from the spawn at 0) and `reason` is its code in REASONS.
    `last_valid_position` is the position the walk carried up to that event;
    the spec does not say whether that, or the spawn, is where an identity
    with an invalid chain stands (section 3.2 calls both a derezz), so it is
    reported and not locked by the vectors."""

    valid: bool
    chain: Tuple[str, ...] = ()
    position: Optional[str] = None
    head: Optional[str] = None
    open_bracket: Optional[str] = None
    skipped: Tuple[str, ...] = ()
    reason: Optional[str] = None
    invalid_at: Optional[str] = None
    invalid_index: Optional[int] = None
    last_valid_position: Optional[str] = None
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


def parse_region(event: Dict[str, Any]) -> Tuple[Optional[Region], str]:
    """8.11.1: the one region tag ["region", <coord_hex>, <H>], with H written
    canonically in [0, 85] and the base aligned (the low H bits of each axis
    zero). Returns (region, "") or (None, why)."""
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

def resolve_active_chain(events: Iterable[Dict[str, Any]], pubkey: str, *, check_signatures: bool = False) -> List[Dict[str, Any]]:
    """8.7.3: the identity's active chain, spawn first, from events in any order.

    1. The newest spawn by created_at, the larger id when they tie.
    2. Only events whose e genesis names that spawn take part; the rest are an
       older chain's history.
    3. From the spawn, follow e previous links forward.
    4. At a fork the event with the smallest created_at continues the chain,
       the smaller id when they tie; the other branches are dropped.
    5. The chain ends at the first event that nothing names as previous.

    A spawn names no previous event, so an event whose A is spawn is never a
    link: it starts a chain of its own wherever it was published. Only
    authentic kind 3333 events by `pubkey` take part: the id is the NIP-01
    hash of the event and, with `check_signatures`, the sig verifies (8.2).
    The first e tag with each marker is the one followed."""
    mine: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        if not (isinstance(ev, dict) and ev.get("kind") == MOVEMENT_KIND and ev.get("pubkey") == pubkey):
            continue
        if ev.get("id") in mine or event_id(ev) != ev.get("id") or (check_signatures and not signature_ok(ev)):
            continue
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
    seen = {spawn["id"]}
    while True:
        nxt = children.get(chain[-1]["id"])
        if not nxt:
            return chain
        head = min(nxt, key=lambda ev: (ev.get("created_at", 0), ev["id"]))
        if head["id"] in seen:  # only forged ids can loop
            return chain
        seen.add(head["id"])
        chain.append(head)


# ---------------------------------------------------------------- verifying

@dataclass
class _Bracket:
    entry_id: str
    base: str  # the entry's c: the identity's position while the bracket is open (rule 1)
    region: Region
    game_position: str  # the C of the last event inside, which the next one's c must equal
    lookback: Dict[str, Any]  # the action before the entry, which the exit stands for (rule 8)


@dataclass
class _Walk:
    line: Optional[Line]
    max_compute_height: int
    position: str = ""
    lookback: Dict[str, Any] = field(default_factory=dict)  # the recognized action that stands before the next one
    bracket: Optional[_Bracket] = None
    skipped: List[str] = field(default_factory=list)

    def step(self, index: int, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """Check one event; returns (reason, detail) when it breaks a rule."""
        action = _action(event)
        if action is None:
            return "malformed", "A: expected exactly one A tag"
        if index == 0:
            return self._spawn(event)
        if self.bracket is None and action not in RECOGNIZED_ACTIONS:
            # 8.9: linked through, otherwise as if absent.
            self.skipped.append(event["id"])
            return None
        for marker in ("genesis", "previous"):
            if len(_e(event, marker)) != 1:
                return "malformed", f"e {marker}: expected exactly one"
        if self.bracket is not None:
            return self._inside(event, action)
        return self._outside(event, action)

    def _coords(self, event: Dict[str, Any]) -> Tuple[str, str, Optional[Tuple[str, str]]]:
        cs, Cs = _values(event, "c"), _values(event, "C")
        if len(cs) != 1 or not _is_hex32(cs[0]):
            return "", "", ("malformed", "c: expected exactly one 32-byte lowercase hex coordinate")
        if len(Cs) != 1 or not _is_hex32(Cs[0]):
            return "", "", ("malformed", "C: expected exactly one 32-byte lowercase hex coordinate")
        return cs[0], Cs[0], None

    def _spawn(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        Cs = _values(event, "C")
        if len(Cs) != 1 or not _is_hex32(Cs[0]):
            return "malformed", "C: expected exactly one 32-byte lowercase hex coordinate"
        if Cs[0] != event.get("pubkey"):
            return "spawn-coordinate", "the spawn's C is not its pubkey"
        self.position = Cs[0]
        self.lookback = event
        return None

    def _inside(self, event: Dict[str, Any], action: str) -> Optional[Tuple[str, str]]:
        """8.11.5 steps 2 and 3: a virtual action or the exit."""
        b = self.bracket
        assert b is not None
        if action in NOT_IN_BRACKET:
            return "base-action-in-bracket", f"{action} inside the bracket opened by {b.entry_id}"
        c, C, bad = self._coords(event)
        if bad:
            return bad
        if action == "exit-virtual":
            entries = _e(event, "entry")
            if len(entries) != 1:
                return "malformed", "e entry: expected exactly one"
            if entries[0] != b.entry_id:
                return "exit-wrong-entry", f"e entry names {entries[0]}, the open bracket is {b.entry_id}"
            if c != b.game_position:
                return "c-mismatch", "the exit's c is not the C of the previous event"
            if C != b.base:
                return "exit-position", "the exit's C is not the c of its enter-virtual"
            # Rule 2: the base position is restored; rule 8: the exit stands for the action before the entry.
            self.position = C
            self.lookback = b.lookback
            self.bracket = None
            return None
        if c != b.game_position:
            return "c-mismatch", "the virtual action's c is not the C of the previous event"
        if not b.region.contains(C):
            return "outside-region", "the virtual action's C is outside the declared region"
        b.game_position = C
        return None

    def _outside(self, event: Dict[str, Any], action: str) -> Optional[Tuple[str, str]]:
        if action == "exit-virtual":
            return "exit-without-bracket", "no bracket is open"
        c, C, bad = self._coords(event)
        if bad:
            return bad
        if action == "enter-virtual":
            region, why = parse_region(event)
            if region is None:
                return "region", why
            if not game_tag_ok(event):
                return "game-tag", "expected exactly one p tag marked game holding a 32-byte lowercase hex pubkey"
            if c != self.position:
                return "c-mismatch", "the entry's c is not the position the chain carries"
            if not region.contains(C):
                return "outside-region", "the entry's C is outside the declared region"
            # Rule 1: the position is held at c; position and look-back stay as they are until the exit.
            self.bracket = _Bracket(event["id"], c, region, C, self.lookback)
            return None
        if c != self.position:
            return "c-mismatch", "c is not the C of the nearest recognized action before it"
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
        """DECK-0001 4.3 against the action this ride looks back to, then the
        stop of B and the ride's proof (5.5 Level 1)."""
        if self.line is None:
            raise LineRequired(f"hyperjump {event['id']} needs the line's block data")
        line = self.line
        before = _action(self.lookback)
        if before not in ("enter-hyperspace", "hyperjump"):
            return "hyperjump-predecessor", f"the action before this ride is {before}"
        from_height, to_height = _decimal(next(iter(_values(event, "from_height")), None)), _decimal(next(iter(_values(event, "B")), None))
        if from_height is None or to_height is None:
            return "malformed", "from_height and B: expected base-10 block heights"
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
            if from_height == to_height:
                return "hyperjump-zero-length", "only the first ride from the station may have from_height equal to B (5.2, 5.6)"
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
    check_signatures: bool = False,
    max_compute_height: int = DEFAULT_MAX_COMPUTE_HEIGHT,
) -> ChainVerdict:
    """Resolve the identity's active chain (8.7.3) and verify it under the
    chain rules of revision CHAIN_RULES_REVISION.

    `pubkey` defaults to the one pubkey among the kind 3333 events. `line`
    supplies Bitcoin's block data for rides, and LineRequired is raised when
    a ride is met without it. Events that are not authentic are set aside
    before the chain is resolved. Signatures are part of that only when
    `check_signatures` is set, since local chains are unsigned until they
    are published (8.2); without it, anyone who can compute a hash can add a
    branch, so it is for chains the caller made itself. A hop taller than `max_compute_height` raises
    ValueError. Neither exception is a verdict: the rules cannot be applied
    without the data or the work."""
    events = list(events)
    if pubkey is None:
        pubkeys = {ev.get("pubkey") for ev in events if isinstance(ev, dict) and ev.get("kind") == MOVEMENT_KIND}
        if len(pubkeys) != 1:
            raise ValueError(f"expected the events of one pubkey, found {len(pubkeys)}; pass pubkey=")
        pubkey = pubkeys.pop()
    chain = resolve_active_chain(events, pubkey, check_signatures=check_signatures)  # type: ignore[arg-type]
    ids = tuple(ev["id"] for ev in chain)
    if not chain:
        return ChainVerdict(valid=False, reason="no-spawn", detail=REASONS["no-spawn"])
    walk = _Walk(line, max_compute_height)
    for index, event in enumerate(chain):
        before = walk.bracket.base if walk.bracket else walk.position
        failure = walk.step(index, event)
        if failure:
            reason, detail = failure
            assert reason in REASONS, reason
            return ChainVerdict(
                valid=False, chain=ids, reason=reason, invalid_at=event.get("id"), invalid_index=index,
                last_valid_position=before or None, detail=detail,
            )
    return ChainVerdict(
        valid=True,
        chain=ids,
        position=walk.bracket.base if walk.bracket else walk.position,
        head=ids[-1],
        open_bracket=walk.bracket.entry_id if walk.bracket else None,
        skipped=tuple(walk.skipped),
    )
