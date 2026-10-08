#!/usr/bin/env python3
"""Regenerate vectors/chain-rules-2026-09-28-virtual-brackets.json, the golden
vectors for the chain rules of CYBERSPACE_V2.md section 8.12, revision
2026-09-28-virtual-brackets with the rulings folded in on 2026-10-07 and
clarified on 2026-10-08 (arkin0x/cyberspace 912f3d7).

    PYTHONPATH=src python scripts/gen_chain_vectors.py

Every vector is a small synthetic chain of real, signed kind 3333 events and
the verdict the chain rules give it. The verdict of each vector is written
here by hand, as the reading of the spec it locks, and the file is written
only if cyberspace_core.chain agrees with every one of them.

What keeps the vectors cheap while every proof in them is real:

- The test key is the first of a fixed sequence of secrets whose spawn
  coordinate has a terrain K of at most 3, so every temporal tree is at most
  eight leaves. Hops and sidesteps move one gibson by flipping an axis's low
  bit, so every spatial tree is height 1, and a flip never leaves the
  height-3 terrain cell, so K stays the same.
- The line is eight synthetic stops, all ports (C is the merkle root), each
  with a terrain K of at most 3 so a hop out of it is cheap too. Block hashes
  follow the spec's decks/hyperjump-reference.py stand-in, so every block's
  ride leaf is a tree of height at most 10. Rides are one or two blocks long,
  so the re-roll price is one attempt (A = 1). An attempt is one height-16
  Cantor tree, about a second in Python, which makes rides the dearest part.
- Signatures use a zero auxiliary random value, so a rerun writes the same
  file byte for byte.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from coincurve import PrivateKey

from cyberspace_cli.nostr_event import _sector_tags_from_coord_hex, compute_event_id_hex
from cyberspace_core.cantor import sha256
from cyberspace_core.chain import CHAIN_RULES_REVISION, REASONS, verify_chain
from cyberspace_core.coords import coord_to_xyz, xyz_to_coord
from cyberspace_core.hyperspace import Line, enter_hyperspace_proof, stop_distance
from cyberspace_core.movement import compute_hop_proof, compute_sidestep_proof, encode_nonce, encode_openings
from cyberspace_core.ride import K_LINE, encode_ride_openings, line_terrain_k, prove_ride
from cyberspace_core.terrain import terrain_k

OUT = Path(__file__).resolve().parents[1] / "vectors" / f"chain-rules-{CHAIN_RULES_REVISION}.json"
SPEC_COMMIT = "912f3d70e4d15d70054e9fa98646098a1c216d47"
KEY_DOMAIN = b"CYBERSPACE_CHAIN_VECTORS_KEY"
OTHER_KEY_DOMAIN = b"CYBERSPACE_CHAIN_VECTORS_OTHER_KEY"
STOP_DOMAIN = b"CYBERSPACE_CHAIN_VECTORS_STOP"
GAME_DOMAIN = b"CYBERSPACE_CHAIN_VECTORS_GAME"
T0 = 1790000000
TIP = 7
MAX_K = 3


def k_of(coord_hex: str) -> int:
    x, y, z, p = coord_to_xyz(int(coord_hex, 16))
    return terrain_k(x=x, y=y, z=z, plane=p)


def flip(coord_hex: str, dx: int = 0, dy: int = 0, dz: int = 0, plane: Optional[int] = None) -> str:
    """The coordinate with axis bits XORed, so a small mask stays inside every
    aligned cube at or above its highest bit."""
    x, y, z, p = coord_to_xyz(int(coord_hex, 16))
    return format(xyz_to_coord(x ^ dx, y ^ dy, z ^ dz, p if plane is None else plane), "064x")


# ---------------------------------------------------------------- the keys and the line

def test_key() -> tuple:
    j = 0
    while True:
        secret = sha256(KEY_DOMAIN + j.to_bytes(4, "big"))
        sk = PrivateKey(secret)
        pub = sk.public_key_xonly.format().hex()
        if k_of(pub) <= MAX_K:
            return j, sk, pub
        j += 1


def block_hash(b: int) -> str:
    """The spec reference's stand-in: the first sha256(TEST_BLOCK || be64(b) || be32(j)) with K + 6 <= 10."""
    j = 0
    while True:
        h = sha256(b"CYBERSPACE_TEST_BLOCK" + b.to_bytes(8, "big") + j.to_bytes(4, "big"))
        if line_terrain_k(h) + K_LINE <= 10:
            return h.hex()
        j += 1


def port(seed: bytes, near: Optional[str] = None, low_bits: int = 0) -> str:
    """A port (plane 1) with terrain K <= MAX_K: random, or `near`'s axes with
    their low `low_bits` bits drawn at random, which puts it within distance
    low_bits of `near` (DECK-0001 4.1)."""
    j = 0
    while True:
        r = int.from_bytes(sha256(seed + j.to_bytes(4, "big")), "big")
        if near is None:
            coord = format(r | 1, "064x")
        else:
            x, y, z, _ = coord_to_xyz(int(near, 16))
            mask = (1 << low_bits) - 1
            rx, ry, rz = r & mask, (r >> 85) & mask, (r >> 170) & mask
            coord = format(xyz_to_coord((x & ~mask) | rx, (y & ~mask) | ry, (z & ~mask) | rz, 1), "064x")
        if k_of(coord) <= MAX_K:
            return coord
        j += 1


def make_line(spawn: str) -> List[Dict[str, Any]]:
    """Heights 0..7. Stop 2 lies within distance 20 of the spawn and stop 6
    within 10, every other stop at random: the station is 2 for a bound of 2
    to 5 and 6 for a bound of 6 or 7."""
    blocks = []
    for h in range(TIP + 1):
        seed = STOP_DOMAIN + h.to_bytes(8, "big")
        root = port(seed, spawn, 20) if h == 2 else port(seed, spawn, 10) if h == 6 else port(seed)
        blocks.append({"height": h, "block_hash": block_hash(h), "merkle_root": root, "coord": root})
    return blocks


# ---------------------------------------------------------------- events

GAME = sha256(GAME_DOMAIN).hex()
Tags = List[List[str]]


class Builder:
    """Signed kind 3333 events by one key, created_at counting up from T0."""

    def __init__(self, sk: PrivateKey, line: Line, clock: Optional[List[int]] = None):
        self.sk, self.line = sk, line
        self.pub = sk.public_key_xonly.format().hex()
        self.clock = clock if clock is not None else [T0]

    def sign(self, tags: Tags, created_at: Optional[int] = None, content: str = "", kind: int = 3333) -> Dict[str, Any]:
        if created_at is None:
            self.clock[0] += 1
            created_at = self.clock[0]
        eid = compute_event_id_hex(pubkey_hex=self.pub, created_at=created_at, kind=kind, tags=tags, content=content)
        sig = self.sk.sign_schnorr(bytes.fromhex(eid), bytes(32)).hex()
        return {"id": eid, "pubkey": self.pub, "created_at": created_at, "kind": kind, "tags": tags, "content": content, "sig": sig}

    def sign_raw(self, created_at: Any, tags: Any, content: Any = "", kind: Any = 3333) -> Dict[str, Any]:
        """An event of any shape whose id is the hash of its serialization and
        whose sig signs that id: well signed, but not NIP-01 unless the shape is."""
        payload = [0, self.pub, created_at, kind, tags, content]
        eid = sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hex()
        sig = self.sk.sign_schnorr(bytes.fromhex(eid), bytes(32)).hex()
        return {"id": eid, "pubkey": self.pub, "created_at": created_at, "kind": kind, "tags": tags, "content": content, "sig": sig}

    def retag(self, event: Dict[str, Any], change: Callable[[Tags], Tags]) -> Dict[str, Any]:
        """The event re-signed with its tags changed, at the same created_at."""
        return self.sign(change([list(t) for t in event["tags"]]), event["created_at"], event["content"])

    def spawn(self, created_at: Optional[int] = None, coord: Optional[str] = None) -> Dict[str, Any]:
        coord = coord or self.pub
        return self.sign([["A", "spawn"], ["C", coord]] + _sector_tags_from_coord_hex(coord), created_at)

    def link(self, action: str, genesis: Dict, prev: Dict, c: Optional[str], C: str, extra: Optional[Tags] = None,
             created_at: Optional[int] = None, entry: Optional[Dict] = None) -> Dict[str, Any]:
        tags = [["A", action], ["e", genesis["id"], "", "genesis"], ["e", prev["id"], "", "previous"]]
        if entry is not None:
            tags.append(["e", entry["id"], "", "entry"])
        tags += ([["c", c]] if c is not None else []) + [["C", C]] + (extra or []) + _sector_tags_from_coord_hex(C)
        return self.sign(tags, created_at)

    def game(self, genesis: Dict, prev: Dict, name: str, extra: Optional[Tags] = None) -> Dict[str, Any]:
        """A virtual action: its name, its links, and whatever tags the game gives it."""
        return self.sign([["A", name], ["e", genesis["id"], "", "genesis"], ["e", prev["id"], "", "previous"]] + (extra or []))

    def hop(self, genesis: Dict, prev: Dict, c: str, C: str, seed: Optional[Dict] = None, **kw) -> Dict[str, Any]:
        (x1, y1, z1, _), (x2, y2, z2, p2) = coord_to_xyz(int(c, 16)), coord_to_xyz(int(C, 16))
        proof = compute_hop_proof(x1, y1, z1, x2, y2, z2, plane=p2, previous_event_id_hex=(seed or prev)["id"])
        return self.link("hop", genesis, prev, c, C, [["proof", proof.proof_hash]], **kw)

    def sidestep(self, genesis: Dict, prev: Dict, c: str, C: str, seed: Optional[Dict] = None) -> Dict[str, Any]:
        (x1, y1, z1, _), (x2, y2, z2, p2) = coord_to_xyz(int(c, 16)), coord_to_xyz(int(C, 16))
        s = compute_sidestep_proof(x1, y1, z1, x2, y2, z2, plane=p2, previous_event_id_hex=(seed or prev)["id"])
        extra = [
            ["proof", s.proof_hash],
            ["mr", ":".join(r.hex() for r in (s.merkle_x, s.merkle_y, s.merkle_z))],
            ["mp", ":".join(encode_openings(s.openings[a]) for a in "xyz")],
            ["mn", encode_nonce(s.nonce)],
            ["hx", str(s.lca_heights[0])], ["hy", str(s.lca_heights[1])], ["hz", str(s.lca_heights[2])],
        ]
        return self.link("sidestep", genesis, prev, c, C, extra)

    def board(self, genesis: Dict, prev: Dict, c: str, C: Optional[str] = None, seed: Optional[Dict] = None) -> Dict[str, Any]:
        C = C or c
        proof = enter_hyperspace_proof(C, bytes.fromhex((seed or prev)["id"]))
        return self.link("enter-hyperspace", genesis, prev, c, C, [["proof", proof]])

    def ride(self, genesis: Dict, prev: Dict, c: str, from_height: int, to_height: int, as_of: Optional[int] = None,
             C: Optional[str] = None, seed: Optional[Dict] = None) -> Dict[str, Any]:
        """A hyperjump with a real proof. A ride with from_height equal to B
        (which no longer exists, DECK-0001 5.6) carries the proof shape the
        earlier draft gave it: a zero root, a zero nonce and an empty mp."""
        C = C or self.line.stop(to_height).coord_hex
        lo, hi = min(from_height, to_height), max(from_height, to_height)
        if lo == hi:
            root, nonce, mp = bytes(32), 0, ""
        else:
            root, nonce, openings = prove_ride(bytes.fromhex((seed or prev)["id"]), lo, hi, self.line.block_hash, workers=1)
            mp = encode_ride_openings(openings)
        extra = [["from_height", str(from_height)], ["B", str(to_height)]]
        if as_of is not None:
            extra.append(["as_of", str(as_of)])
        extra += [["proof", root.hex()], ["mp", mp], ["mn", encode_nonce(nonce)]]
        return self.link("hyperjump", genesis, prev, c, C, extra)

    def enter(self, genesis: Dict, prev: Dict, c: str, region: List[str], games: Optional[Tags] = None, C: Optional[str] = None) -> Dict[str, Any]:
        """An enter-virtual: its C repeats its c unless told otherwise."""
        if games is None:
            games = [["p", GAME, "wss://game.example", "game"]]
        return self.link("enter-virtual", genesis, prev, c, C or c, [["region"] + region] + games)

    def exit(self, genesis: Dict, prev: Dict, entry: Optional[Dict], C: str, c: Optional[str] = None) -> Dict[str, Any]:
        """An exit-virtual. Its c is optional and belongs to the game (8.11.3)."""
        if entry is None:
            tags = [["A", "exit-virtual"], ["e", genesis["id"], "", "genesis"], ["e", prev["id"], "", "previous"], ["C", C]]
            return self.sign(tags + _sector_tags_from_coord_hex(C))
        return self.link("exit-virtual", genesis, prev, c, C, entry=entry)


def region_around(coord_hex: str, h: int) -> List[str]:
    """The aligned cube of height h that holds the coordinate, as a region tag's values."""
    x, y, z, p = coord_to_xyz(int(coord_hex, 16))
    base = xyz_to_coord((x >> h) << h, (y >> h) << h, (z >> h) << h, p)
    return [format(base, "064x"), str(h)]


def drop(name: str) -> Callable[[Tags], Tags]:
    return lambda tags: [t for t in tags if t[0] != name]


def duplicate(name: str) -> Callable[[Tags], Tags]:
    return lambda tags: tags + [list(next(t for t in tags if t[0] == name))]


def set_value(name: str, value: Callable[[str], str]) -> Callable[[Tags], Tags]:
    return lambda tags: [[name, value(t[1])] + t[2:] if t[0] == name else t for t in tags]


# ---------------------------------------------------------------- expectations

def valid(chain: List[Dict], position: str, open_bracket: Optional[Dict] = None, skipped: Optional[List[Dict]] = None) -> Dict[str, Any]:
    return {
        "valid": True,
        "chain": [e["id"] for e in chain],
        "position": position,
        "head": chain[-1]["id"],
        "open_bracket": open_bracket["id"] if open_bracket else None,
        "skipped": [e["id"] for e in (skipped or [])],
    }


def invalid(chain: List[Dict], at: Optional[Dict], reason: str, position: Optional[str]) -> Dict[str, Any]:
    """`position` is the last valid position, where the frozen chain leaves the identity (3.2, 8.7.3)."""
    assert reason in REASONS, reason
    return {
        "valid": False,
        "chain": [e["id"] for e in chain],
        "position": position,
        "reason": reason,
        "invalid_at": at["id"] if at else None,
        "invalid_index": next(i for i, e in enumerate(chain) if e is at) if at else None,
    }


def build(sk: PrivateKey, other: PrivateKey, line: Line) -> List[Dict[str, Any]]:
    b = Builder(sk, line)
    o = Builder(other, line, b.clock)
    P = b.pub
    PX, PY, PZ = flip(P, dx=1), flip(P, dy=1), flip(P, dz=1)
    FAR_SECTOR = flip(P, dx=1 << 30)  # another sector, for wrong sector tags
    R = region_around(P, 8)  # a game's box around the spawn
    G0, G1, G2 = flip(P, dx=0x10), flip(P, dx=0x10, dy=0x20), flip(P, dz=0x40)  # inside R
    OUT_R = flip(P, dx=0x100)  # outside R, on the same plane
    S = {h: line.stop(h).coord_hex for h in range(TIP + 1)}
    vectors: List[Dict[str, Any]] = []

    def add(name: str, spec: List[str], description: str, events: List[Dict], expected: Dict):
        vectors.append({"name": name, "spec": spec, "description": description, "events": events, "expected": expected})

    # ------------------------------------------------ the spawn (3.2, 8.3)
    s = b.spawn()
    add("spawn-only", ["8.3", "8.7.3"], "A spawn alone is a valid chain; the position is the spawn coordinate, the pubkey.",
        [s], valid([s], P))

    s = b.spawn(coord=PX)
    add("spawn-coordinate-not-pubkey", ["3.2", "8.3"],
        "A spawn whose C is not its pubkey is invalid; with no valid event, the identity stands at its spawn coordinate.",
        [s], invalid([s], s, "spawn-coordinate", P))

    s = b.retag(b.spawn(), lambda t: t[:2] + _sector_tags_from_coord_hex(FAR_SECTOR))
    add("spawn-sector-tags-wrong", ["8.3", "10"], "A spawn whose sector tags are computed from another coordinate is invalid.",
        [s], invalid([s], s, "sector-tags", P))

    s1 = b.spawn()
    h1 = b.hop(s1, s1, P, PX)
    s2 = b.spawn(coord=PX)
    add("spawn-newest-invalid-no-fallback", ["3.2", "8.7.3 rule 1"],
        "The newest spawn is invalid. It still starts the active chain, the reader does not fall back to the older spawn "
        "and its valid hop, and the identity stands at its spawn coordinate.",
        [s1, h1, s2], invalid([s2], s2, "spawn-coordinate", P))

    ghost = {"id": "ab" * 32}
    h = b.hop(ghost, ghost, P, PX)
    add("no-spawn", ["8.7.3"], "Events with no spawn among them resolve to no chain.", [h], invalid([], None, "no-spawn", None))

    # ------------------------------------------------ resolution (8.7.3)
    s = b.spawn()
    hb = b.hop(s, s, P, PX, created_at=T0 + 1000)
    ha = b.hop(s, s, P, PY, created_at=T0 + 1001)
    ha2 = b.hop(s, ha, PY, flip(PY, dz=1), created_at=T0 + 1002)
    add("fork-both-valid-dead", ["8.7.3 rule 4"],
        "Two valid hops name the spawn as previous, one with a valid descendant. A fork is fatal whichever branch is "
        "valid or earlier: the chain is invalid from the spawn and the identity stands at its spawn coordinate. Events "
        "are listed out of order on purpose.",
        [ha2, ha, s, hb], invalid([s], s, "fork", P))

    s = b.spawn()
    t = T0 + 2000
    f1, f2 = b.hop(s, s, P, PX, created_at=t), b.hop(s, s, P, PY, created_at=t)
    add("fork-same-created-at-dead", ["8.7.3 rule 4"], "Two branches with the same created_at: a fork, so the chain is dead; no tie-break applies.",
        [f1, f2, s], invalid([s], s, "fork", P))

    s = b.spawn()
    bad = b.hop(s, s, P, PY, seed={"id": "cd" * 32}, created_at=T0 + 2500)
    good = b.hop(s, s, P, PX, created_at=T0 + 2501)
    add("fork-invalid-and-valid-dead", ["8.7.3 rule 4"],
        "One branch has an invalid proof and the other is valid. The fork is found from the links before any proof is "
        "checked, so the reason is the fork, and the chain is dead at the spawn coordinate.",
        [good, bad, s], invalid([s], s, "fork", P))

    s = b.spawn()
    hist = [s]
    here = P
    for mask in (dict(dx=1), dict(dy=1), dict(dz=1), dict(dx=1), dict(dy=1)):
        nxt = flip(here, **mask)
        hist.append(b.hop(s, hist[-1], here, nxt))
        here = nxt
    fa = b.hop(s, hist[-1], here, flip(here, dz=1))
    fb = b.hop(s, hist[-1], here, flip(here, dx=1))
    add("fork-deep-in-history-dead", ["8.7.3 rule 4", "3.2"],
        "Five valid hops, then two hops that both name the fifth. The fork is fatal however much valid travel came "
        "before it: the chain is invalid from the spawn and the identity stands at its spawn coordinate, not at the "
        "fifth hop.",
        hist + [fa, fb], invalid(hist, s, "fork", P))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    w = b.link("wave", s, h1, PX, PX)
    h2 = b.hop(s, h1, PX, flip(PX, dy=1))
    add("fork-skipped-and-hop-dead", ["8.7.3 rule 4", "8.9"],
        "A skipped action and a hop both name the same event as previous. A skipped action is still a link, so this is a fork and the chain is dead.",
        [s, h1, w, h2], invalid([s, h1], s, "fork", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.game(s, ev, "move")
    v2 = b.game(s, ev, "score")
    add("fork-virtual-actions-dead", ["8.7.3 rule 4", "8.11"],
        "Two virtual actions inside a bracket both name the entry as previous. The bracket is opaque, but its links are not: a fork, and the chain is dead.",
        [s, ev, v1, v2], invalid([s, ev], s, "fork", P))

    s1 = b.spawn()
    h1 = b.hop(s1, s1, P, PX)
    s2 = b.spawn()
    stale = b.hop(s1, s2, P, PY)  # names the new spawn as previous but the old one as genesis
    add("respawn-newest-spawn", ["3.2", "8.7.3 rules 1, 2"],
        "The newest spawn starts the active chain. An event whose e genesis names the older spawn is ignored even "
        "though its e previous names the newest spawn.",
        [s1, h1, s2, stale], valid([s2], P))

    # ------------------------------------------------ authentic events only (8.2, 8.7.3)
    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    copy = dict(h1, content="altered by someone else")
    add("forged-copy-ignored", ["8.2", "8.7.3 authentic events only"],
        "A copy of a real event with its content altered keeps the real id and sig, but the id is not its hash: it is "
        "discarded before resolving, whichever copy a relay returns first.",
        [copy, s, h1], valid([s, h1], PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX, created_at=T0 + 3001)
    fake = {"id": "ee" * 32, "pubkey": P, "created_at": T0 + 3000, "kind": 3333, "content": "", "sig": h1["sig"],
            "tags": [["A", "hop"], ["e", s["id"], "", "genesis"], ["e", s["id"], "", "previous"], ["c", P], ["C", PY], ["proof", "00" * 32]]}
    add("forged-fork-ignored", ["8.2", "8.7.3 authentic events only", "3.2"],
        "An event whose id is not its hash names the spawn as previous with an earlier created_at than the real hop. It "
        "is discarded, so there is no fork and the chain is valid: a forged event cannot kill a chain.",
        [s, fake, h1], valid([s, h1], PX))

    s = b.spawn()
    unsigned = b.hop(s, s, P, PY, created_at=T0 + 4000)
    unsigned = dict(unsigned, sig=b.sk.sign_schnorr(bytes.fromhex(s["id"]), bytes(32)).hex())
    h1 = b.hop(s, s, P, PX, created_at=T0 + 4001)
    add("unsigned-fork-ignored", ["8.2", "8.7.3 authentic events only"],
        "A hop with a correct id and a valid proof whose sig signs a different id, signed earlier than the real hop. It "
        "is not authentic and is discarded, so there is no fork and the real hop continues the chain.",
        [s, unsigned, h1], valid([s, h1], PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX, created_at=T0 + 4500)
    stranger = o.sign([["A", "hop"], ["e", s["id"], "", "genesis"], ["e", s["id"], "", "previous"], ["c", P], ["C", PY]]
                      + _sector_tags_from_coord_hex(PY), created_at=T0 + 4499)
    add("other-author-ignored", ["8.7.3 authentic events only"],
        "A validly signed event by another pubkey names this spawn as previous, signed earlier than the real hop. Its "
        "pubkey is not the identity's, so it is discarded and makes no fork. Verify with the test key's pubkey as the identity.",
        [s, stranger, h1], valid([s, h1], PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    forged = b.hop(s, h1, PX, flip(PX, dy=1))
    forged = dict(forged, sig=b.sk.sign_schnorr(bytes.fromhex(h1["id"]), bytes(32)).hex())
    after = b.hop(s, forged, flip(PX, dy=1), flip(PX, dy=1, dz=1))
    add("forged-event-cuts-branch", ["8.7.3 a branch through a discarded event is cut off"],
        "An inauthentic event names the head as previous, and an authentic event names the inauthentic one. The "
        "inauthentic event never existed, so the branch is cut off and the head is the event before it; the chain is valid.",
        [s, h1, forged, after], valid([s, h1], PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    forged = b.hop(s, h1, PX, flip(PX, dy=1))
    forged = dict(forged, sig=b.sk.sign_schnorr(bytes.fromhex(h1["id"]), bytes(32)).hex())
    after = b.hop(s, forged, flip(PX, dy=1), flip(PX, dy=1, dz=1))
    h2 = b.hop(s, h1, PX, flip(PX, dz=1))
    add("cut-off-then-continue", ["8.7.3 a branch through a discarded event is cut off"],
        "After a cut-off branch the identity continues from the head: its next action names the head as previous and is "
        "not a fork, because the cut-off events count for nothing.",
        [s, h1, forged, after, h2], valid([s, h1, h2], flip(PX, dz=1)))

    # ------------------------------------------------ exactly one A tag (8.8)
    s = b.spawn()
    h1 = b.retag(b.hop(s, s, P, PX), lambda t: [["A", "hop"]] + t)
    add("a-tag-two-on-hop", ["8.8"], "A hop with two A tags is invalid.", [s, h1], invalid([s, h1], h1, "a-tag", P))

    s = b.spawn()
    w = b.sign([["e", s["id"], "", "genesis"], ["e", s["id"], "", "previous"], ["c", P], ["C", P]])
    add("a-tag-missing", ["8.8", "8.9"], "An event with no A tag is invalid, not skipped.", [s, w], invalid([s, w], w, "a-tag", P))

    s = b.spawn()
    w = b.retag(b.link("wave", s, s, P, P), lambda t: t + [["A", "wave"]])
    add("a-tag-two-on-skipped", ["8.8", "8.9"], "An unrecognized action with two A tags is invalid, not skipped.",
        [s, w], invalid([s, w], w, "a-tag", P))

    # ------------------------------------------------ base movement and frozen chains
    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    h2 = b.hop(s, h1, PX, flip(PX, dy=1), seed=s)
    add("hop-proof-wrong-seed", ["8.7.1", "5.3"], "A hop whose proof is seeded by an id other than its e previous is invalid.",
        [s, h1, h2], invalid([s, h1, h2], h2, "hop-proof", PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    h2 = b.hop(s, h1, PX, flip(PX, dy=1), seed=s)
    h3 = b.hop(s, h2, flip(PX, dy=1), flip(PX, dy=1, dz=1))
    add("frozen-after-invalid", ["3.2", "8.7.3 validity and position"],
        "A valid hop after an invalid one does not move the identity: the chain is frozen at its last valid position.",
        [s, h1, h2, h3], invalid([s, h1, h2, h3], h2, "hop-proof", PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    h2 = b.hop(s, h1, P, PY)
    add("hop-c-mismatch", ["8.4", "8.9 item 2"], "A hop whose c is not the previous C is invalid.",
        [s, h1, h2], invalid([s, h1, h2], h2, "c-mismatch", PX))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    st = b.sidestep(s, w, P, PZ, seed=s)
    add("sidestep-proof-wrong-seed", ["8.7.2", "8.9 item 3"],
        "A sidestep after a skipped action whose trees and proof were seeded by the spawn instead of the skipped action is invalid.",
        [s, w, st], invalid([s, w, st], st, "sidestep-proof", P))

    for name, change, why in (
        ("missing", drop("S"), "without its S tag"),
        ("duplicated", duplicate("X"), "with its X tag twice"),
        ("wrong", set_value("Y", lambda v: str(int(v) + 1)), "with a Y tag one sector off"),
        ("noncanonical", set_value("X", lambda v: "0" + v), "with a leading zero on X"),
    ):
        s = b.spawn()
        h1 = b.retag(b.hop(s, s, P, PX), change)
        add(f"hop-sector-tags-{name}", ["8.4", "10"], f"A hop {why} is invalid.", [s, h1], invalid([s, h1], h1, "sector-tags", P))

    s = b.spawn()
    st = b.retag(b.sidestep(s, s, P, PZ), drop("Z"))
    add("sidestep-sector-tags-missing", ["8.5", "10"], "A sidestep without its Z tag is invalid.",
        [s, st], invalid([s, st], st, "sector-tags", P))

    # ------------------------------------------------ skipping (8.9)
    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    h1 = b.hop(s, w, P, PX)
    add("skip-unknown-nonmoving-then-hop", ["8.9 items 1-3"],
        "An unrecognized action that does not move is skipped; the hop after it starts from the carried position and its "
        "proof is seeded by the skipped action's id.",
        [s, w, h1], valid([s, w, h1], PX, skipped=[w]))

    s = b.spawn()
    w = b.sign([["A", "wave"], ["e", s["id"], "", "genesis"], ["e", s["id"], "", "previous"], ["X", "x"]])
    h1 = b.hop(s, w, P, PX)
    add("skip-checks-nothing-else", ["8.9 what a skipped action is checked for"],
        "A skipped action is checked only for being authentic, linked and carrying one A tag: one with no c, no C and a "
        "malformed sector tag is still skipped.",
        [s, w, h1], valid([s, w, h1], PX, skipped=[w]))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    h1 = b.hop(s, w, P, PX, seed=s)
    add("skip-hop-seeded-by-nearest-recognized", ["8.9 item 3"],
        "Work is seeded by the actual previous event. A hop after a skipped action whose proof was seeded by the nearest "
        "recognized action (the spawn) instead is invalid.",
        [s, w, h1], invalid([s, w, h1], h1, "hop-proof", P))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    st = b.sidestep(s, w, P, PZ)
    add("skip-then-sidestep", ["8.9 item 3", "8.7.2"], "A sidestep after a skipped action is seeded by the skipped id and fully checked.",
        [s, w, st], valid([s, w, st], PZ, skipped=[w]))

    s = b.spawn()
    tp = b.link("teleport", s, s, P, PY)
    h1 = b.hop(s, tp, PY, flip(PY, dx=1))
    add("skip-unknown-moving-then-hop-from-moved", ["8.9 item 2"],
        "An unrecognized action that changes the position is skipped, so the hop after it, starting where the skipped "
        "action left off, has a c that is not the carried position: the chain is invalid from the hop.",
        [s, tp, h1], invalid([s, tp, h1], h1, "c-mismatch", P))

    s = b.spawn()
    tp = b.link("teleport", s, s, P, PY)
    h1 = b.hop(s, tp, P, PX)
    add("skip-unknown-moving-then-hop-from-carried", ["8.9 item 2"],
        "A hop after a skipped moving action is valid when its c is the carried position (the C of the nearest "
        "recognized action), since the skipped action is treated as if it were not on the chain.",
        [s, tp, h1], valid([s, tp, h1], PX, skipped=[tp]))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    tp = b.link("teleport", s, h1, PX, PY)
    w = b.link("wave", s, tp, PY, PY)
    add("skip-chain-ends-on-unknown", ["8.9 item 5"],
        "A chain that ends on skipped actions is valid; the position is the C of the last recognized action, and the head "
        "is the last skipped event.",
        [s, h1, tp, w], valid([s, h1, tp, w], PX, skipped=[tp, w]))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    tp = b.link("teleport", s, h1, PX, PY)
    h2 = b.hop(s, tp, PY, flip(PY, dz=1))
    add("skip-invalid-after-skipped", ["8.7.3 validity and position", "8.9 item 5"],
        "When the last valid event is a skipped action, the last valid position is the C of the last recognized action.",
        [s, h1, tp, h2], invalid([s, h1, tp, h2], h2, "c-mismatch", PX))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    ev = b.enter(s, w, P, R)
    x = b.exit(s, ev, ev, P)
    add("skip-then-bracket", ["8.9 continuity and virtual brackets"], "An enter-virtual after a skipped action starts from the carried position.",
        [s, w, ev, x], valid([s, w, ev, x], P, skipped=[w]))

    # ------------------------------------------------ virtual brackets (8.11)
    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, PX, R)
    v1 = b.game(s, ev, "move", [["c", G0], ["C", G1]] + _sector_tags_from_coord_hex(G1))
    v2 = b.game(s, v1, "score", [["points", "3"]])
    x = b.exit(s, v2, ev, PX, c=G1)
    h2 = b.hop(s, x, PX, flip(PX, dy=1))
    add("bracket-valid-then-hop", ["8.11.1-8.11.5", "8.11.4 rule 8"],
        "Enter (C repeats c), two virtual actions with names and tags of the game's choosing, exit back to the base "
        "position, then a hop from it seeded by the exit's id.",
        [s, h1, ev, v1, v2, x, h2], valid([s, h1, ev, v1, v2, x, h2], flip(PX, dy=1)))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.game(s, ev, "move", [["c", G0], ["C", G2]])
    x = b.exit(s, v1, ev, P, c=G2)
    add("bracket-position-held", ["8.11.4 rules 1, 2"], "After the exit the position is the entry's c, wherever the game moved.",
        [s, ev, v1, x], valid([s, ev, v1, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x = b.exit(s, ev, ev, P)
    add("bracket-empty", ["8.11.3"], "An exit straight after its entry: e previous and e entry both name the entry.",
        [s, ev, x], valid([s, ev, x], P))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, PX, R)
    v1 = b.game(s, ev, "move")
    v2 = b.game(s, v1, "move")
    add("bracket-unclosed", ["8.11.4 rule 7"], "A chain may end inside a bracket; the position is the open entry's c.",
        [s, h1, ev, v1, v2], valid([s, h1, ev, v1, v2], PX, open_bracket=ev))

    far = port(b"CYBERSPACE_CHAIN_VECTORS_FAR_BOX")
    s = b.spawn()
    ev = b.enter(s, s, P, region_around(far, 4))
    x = b.exit(s, ev, ev, P)
    add("bracket-region-elsewhere", ["8.11.1"],
        "The base position need not lie in or near the declared region: an identity can play a game without traveling to it.",
        [s, ev, x], valid([s, ev, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v = [ev]
    for name, extra in (
        ("noop", []),
        ("teleport", [["c", "zz"], ["C", OUT_R]]),
        ("move", [["c", PX], ["C", far]] + _sector_tags_from_coord_hex(G0)),
        ("tag", [["X", "1"], ["X", "2"], ["S", "nowhere"]]),
    ):
        v.append(b.game(s, v[-1], name, extra))
    x = b.exit(s, v[-1], ev, P)
    add("bracket-game-events-unchecked", ["8.11.2", "8.11.4 rules 4, 5"],
        "The inside of a bracket belongs to the game. Virtual actions with no coordinates, malformed ones, ones far "
        "outside the region or on another plane, and missing, wrong or repeated sector tags are all valid.",
        [s] + v + [x], valid([s] + v + [x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.game(s, ev, "move", [["C", G1]])
    x = b.exit(s, v1, ev, P)
    add("bracket-exit-c-missing", ["8.11.3"], "An exit without a c tag is valid; its c is optional.",
        [s, ev, v1, x], valid([s, ev, v1, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.game(s, ev, "move", [["C", G1]])
    x = b.exit(s, v1, ev, P, c=OUT_R)
    add("bracket-exit-c-unchecked", ["8.11.3", "8.11.4 rule 4"],
        "An exit whose c is neither the previous event's C nor anything else in particular is valid; its c is not checked.",
        [s, ev, v1, x], valid([s, ev, v1, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R, C=G0)
    add("bracket-enter-moves", ["8.11.1", "8.11.5 step 1"], "An enter-virtual whose C is not its c is invalid: entering a game does not move the identity.",
        [s, ev], invalid([s, ev], ev, "enter-virtual-moved", P))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, P, R)
    add("bracket-entry-c-mismatch", ["8.11.1", "8.11.5 step 1"], "An entry's c is the carried position.",
        [s, h1, ev], invalid([s, h1, ev], ev, "c-mismatch", PX))

    s = b.spawn()
    ev = b.retag(b.enter(s, s, P, R), lambda t: [x for x in t if x[0] not in "XYZS"] + _sector_tags_from_coord_hex(FAR_SECTOR))
    add("bracket-enter-sector-tags-wrong", ["8.11.1", "10"], "An enter-virtual's sector tags are computed from its C, the base position.",
        [s, ev], invalid([s, ev], ev, "sector-tags", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x = b.retag(b.exit(s, ev, ev, P), drop("X"))
    add("bracket-exit-sector-tags-missing", ["8.11.3", "10"], "An exit-virtual without its X tag is invalid.",
        [s, ev, x], invalid([s, ev, x], x, "sector-tags", P))

    for name, action in (("hop", "hop"), ("enter-hyperspace", "enter-hyperspace"), ("enter-virtual", "enter-virtual"), ("sidestep", "sidestep")):
        s = b.spawn()
        ev = b.enter(s, s, P, R)
        v1 = b.game(s, ev, "move", [["c", P], ["C", G1]])
        if action == "hop":
            bad = b.hop(s, v1, G1, flip(G1, dx=1))
        elif action == "sidestep":
            bad = b.sidestep(s, v1, G1, flip(G1, dz=1))
        elif action == "enter-hyperspace":
            bad = b.board(s, v1, G1)
        else:
            bad = b.enter(s, v1, G1, R)
        add(f"bracket-{name}-inside", ["8.11.4 rule 3"],
            f"A {action} inside an open bracket is invalid, even when it is valid on its own: the name is reserved. Brackets do not nest.",
            [s, ev, v1, bad], invalid([s, ev, v1, bad], bad, "base-action-in-bracket", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    ev = b.enter(s, eh, P, R)
    hj = b.ride(s, ev, P, 2, 4, as_of=5)
    add("bracket-hyperjump-inside", ["8.11.4 rule 3", "DECK-0001 8"], "A hyperjump inside an open bracket is invalid.",
        [s, eh, ev, hj], invalid([s, eh, ev, hj], hj, "base-action-in-bracket", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.game(s, ev, "move")
    v2 = b.retag(b.game(s, v1, "move"), lambda t: t + [["A", "score"]])
    add("bracket-virtual-two-a-tags", ["8.8", "8.11.4 rule 4"],
        "A virtual action with two A tags is invalid; inside a bracket the last valid position is the base position.",
        [s, ev, v1, v2], invalid([s, ev, v1, v2], v2, "a-tag", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.game(s, ev, "move")
    x = b.exit(s, v1, ev, G1)
    add("bracket-exit-position-mismatch", ["8.11.4 rule 2"], "An exit whose C is not the entry's c is invalid.",
        [s, ev, v1, x], invalid([s, ev, v1, x], x, "exit-position", P))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    x = b.exit(s, h1, s, PX, c=PX)
    add("bracket-exit-without-bracket", ["8.11.4 rule 6"], "An exit with no bracket open is invalid.",
        [s, h1, x], invalid([s, h1, x], x, "exit-without-bracket", PX))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x1 = b.exit(s, ev, ev, P)
    x2 = b.exit(s, x1, ev, P, c=P)
    add("bracket-exit-twice", ["8.11.4 rule 6"], "A second exit naming a bracket that is already closed: no bracket is open.",
        [s, ev, x1, x2], invalid([s, ev, x1, x2], x2, "exit-without-bracket", P))

    s = b.spawn()
    ev1 = b.enter(s, s, P, R)
    x1 = b.exit(s, ev1, ev1, P)
    ev2 = b.enter(s, x1, P, R)
    v1 = b.game(s, ev2, "move")
    x2 = b.exit(s, v1, ev1, P)
    add("bracket-exit-wrong-entry", ["8.11.4 rule 6"], "An exit whose e entry names an earlier, closed bracket instead of the open one is invalid.",
        [s, ev1, x1, ev2, v1, x2], invalid([s, ev1, x1, ev2, v1, x2], x2, "exit-wrong-entry", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x = b.exit(s, ev, None, P)
    add("bracket-exit-missing-entry-tag", ["8.11.3"], "An exit without an e entry tag is malformed.",
        [s, ev, x], invalid([s, ev, x], x, "malformed", P))

    for name, games in (
        ("missing", []),
        ("duplicated", [["p", GAME, "", "game"], ["p", GAME, "", "game"]]),
        ("unmarked", [["p", GAME, "wss://game.example"]]),
        ("bad-pubkey", [["p", GAME.upper(), "", "game"]]),
    ):
        s = b.spawn()
        ev = b.enter(s, s, P, R, games=games)
        add(f"bracket-game-tag-{name}", ["8.11.1", "8.11.5"],
            "An enter-virtual must carry exactly one p tag marked game holding a 32-byte lowercase hex pubkey.",
            [s, ev], invalid([s, ev], ev, "game-tag", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R, games=[["p", GAME, "", "game"], ["p", "cd" * 32, "", "referee"]])
    x = b.exit(s, ev, ev, P)
    add("bracket-game-tag-with-other-p", ["8.11.1"], "Other p tags are not game tags; one marked game is exactly one.",
        [s, ev, x], valid([s, ev, x], P))

    unaligned = [format(int(R[0], 16) | (1 << 3), "064x"), "8"]
    for name, region in (("unaligned", unaligned), ("noncanonical-height", [R[0], "08"]), ("height-above-85", [R[0], "86"]), ("missing", None)):
        s = b.spawn()
        ev = b.enter(s, s, P, region or R)
        if region is None:
            ev = b.retag(ev, drop("region"))
        add(f"bracket-region-{name}", ["8.11.1"],
            "The region tag must be present once, with H a canonical decimal in [0, 85] and the base aligned to H.",
            [s, ev], invalid([s, ev], ev, "region", P))

    s1 = b.spawn()
    ev = b.enter(s1, s1, P, R)
    v1 = b.game(s1, ev, "move")
    s2 = b.spawn()
    h1 = b.hop(s2, s2, P, PX)
    add("bracket-spawn-inside", ["8.11.2", "8.11.4", "8.7.3"],
        "A spawn while a bracket is open is a respawn, not a virtual action: it starts a new chain and the open bracket "
        "stays in the old chain's history.",
        [s1, ev, v1, s2, h1], valid([s2, h1], PX))

    # ------------------------------------------------ DECK-0001 rides, with look-back (8.9 item 4, 8.11.4 rule 8)
    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    eh = b.board(s, h1, PX)
    j1 = b.ride(s, eh, PX, 2, 4, as_of=5)
    j2 = b.ride(s, j1, S[4], 4, 3)
    out = b.hop(s, j2, S[3], flip(S[3], dx=1))
    add("ride-valid", ["DECK-0001 3, 4.2, 4.3, 5, 6"],
        "Board, ride from the station (stop 2 within the bound 5) to stop 4, ride on to stop 3, exit by a hop.",
        [s, h1, eh, j1, j2, out], valid([s, h1, eh, j1, j2, out], flip(S[3], dx=1)))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 3, as_of=5)
    j2 = b.ride(s, j1, S[3], 3, 2)
    add("ride-out-and-back-to-station", ["DECK-0001 5.6"],
        "To stand at its own station an identity rides to a different stop and back: two rides, each passing a block.",
        [s, eh, j1, j2], valid([s, eh, j1, j2], S[2]))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 6, 4, as_of=7)
    add("ride-as-of-selects-station", ["DECK-0001 4.2"],
        "With the bound 7 the nearest stop is 6, which is newer than the destination 4: the ride departs from 6.",
        [s, eh, j1], valid([s, eh, j1], S[4]))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=7)
    add("ride-not-from-station", ["DECK-0001 4.2, 4.3"],
        "With the bound 7 the station is stop 6, so a first ride from stop 2 is invalid.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-station", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 2, as_of=5)
    add("ride-zero-length-first", ["DECK-0001 5.2, 5.6"],
        "A first ride from the station to the station itself, in the shape the earlier draft defined, is invalid: there is no zero-length ride.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-zero-length", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5)
    j2 = b.ride(s, j1, S[4], 4, 4)
    add("ride-zero-length-later", ["DECK-0001 5.2, 5.6"], "A later ride with from_height equal to B is invalid.",
        [s, eh, j1, j2], invalid([s, eh, j1, j2], j2, "hyperjump-zero-length", S[4]))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    j1 = b.ride(s, h1, PX, 2, 4, as_of=5)
    add("ride-after-hop", ["DECK-0001 4.3"], "A hyperjump whose previous action is a hop is invalid.",
        [s, h1, j1], invalid([s, h1, j1], j1, "hyperjump-predecessor", PX))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4)
    add("ride-missing-as-of", ["DECK-0001 4.3"], "The first ride after boarding must carry as_of.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-as-of", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=3)
    add("ride-as-of-below-destination", ["DECK-0001 4.2"], "as_of must be at least B.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-as-of", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=TIP + 1)
    add("ride-as-of-beyond-tip", ["DECK-0001 4.2"], "as_of must be a height that exists; the line ends at 7.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-as-of", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5)
    j2 = b.ride(s, j1, S[4], 3, 5)
    add("ride-later-from-height-mismatch", ["DECK-0001 4.3"], "A later ride departs from the previous ride's B.",
        [s, eh, j1, j2], invalid([s, eh, j1, j2], j2, "hyperjump-from-height", S[4]))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5, C=S[5])
    add("ride-wrong-stop", ["DECK-0001 5.5"], "A ride's C must be the stop coordinate of its B.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-stop", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.retag(b.ride(s, eh, P, 2, 4, as_of=5), set_value("S", lambda v: v + "0"))
    add("ride-sector-tags-wrong", ["DECK-0001 1.3", "10"], "A ride whose S tag is not computed from its C is invalid.",
        [s, eh, j1], invalid([s, eh, j1], j1, "sector-tags", P))

    s = b.spawn()
    eh = b.board(s, s, P, C=PX)
    add("board-moves", ["DECK-0001 3.1"], "An enter-hyperspace whose C differs from its c is invalid.",
        [s, eh], invalid([s, eh], eh, "enter-hyperspace-moved", P))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    eh = b.board(s, w, P, seed=s)
    add("board-proof-wrong-seed", ["DECK-0001 3.2", "8.9 item 3"],
        "The entry proof is seeded by the actual previous event, here a skipped action; one seeded by the spawn is invalid.",
        [s, w, eh], invalid([s, w, eh], eh, "enter-hyperspace-proof", P))

    s = b.spawn()
    eh = b.retag(b.board(s, s, P), duplicate("S"))
    add("board-sector-tags-duplicated", ["DECK-0001 1.3", "10"], "An enter-hyperspace with its S tag twice is invalid.",
        [s, eh], invalid([s, eh], eh, "sector-tags", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    ev = b.enter(s, eh, P, R)
    v1 = b.game(s, ev, "move", [["C", G1]])
    x = b.exit(s, v1, ev, P, c=G1)
    j1 = b.ride(s, x, P, 2, 4, as_of=5)
    add("lookback-ride-through-bracket", ["8.11.4 rule 8", "DECK-0001 4.3, 8"],
        "Board, play a game, exit, ride: the exit stands for the boarding, so this is the first ride and departs from the "
        "station. Its work is seeded by the exit's id.",
        [s, eh, ev, v1, x, j1], valid([s, eh, ev, v1, x, j1], S[4]))

    s = b.spawn()
    eh = b.board(s, s, P)
    ev = b.enter(s, eh, P, R)
    x = b.exit(s, ev, ev, P)
    j1 = b.ride(s, x, P, 2, 4, as_of=5, seed=eh)
    add("lookback-ride-seeded-by-boarding", ["8.11.4 rule 8", "DECK-0001 5.3"],
        "The exit stands in for the boarding only for the look-back rule; a ride seeded by the boarding instead of the exit is invalid.",
        [s, eh, ev, x, j1], invalid([s, eh, ev, x, j1], j1, "hyperjump-proof", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    w = b.link("wave", s, eh, P, P)
    j1 = b.ride(s, w, P, 2, 4, as_of=5)
    add("lookback-ride-through-skipped", ["8.9 item 4", "DECK-0001 4.3"],
        "A skipped action between boarding and the first ride: the boarding stands before the ride, which is seeded by the skipped id.",
        [s, eh, w, j1], valid([s, eh, w, j1], S[4], skipped=[w]))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, PX, R)
    x = b.exit(s, ev, ev, PX)
    j1 = b.ride(s, x, PX, 2, 4, as_of=5)
    add("lookback-exit-stands-for-hop", ["8.11.4 rule 8", "DECK-0001 4.3"],
        "The exit stands for the hop before its entry, so the ride has no boarding before it and is invalid.",
        [s, h1, ev, x, j1], invalid([s, h1, ev, x, j1], j1, "hyperjump-predecessor", PX))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5)
    ev = b.enter(s, j1, S[4], region_around(S[4], 4))
    x = b.exit(s, ev, ev, S[4])
    w = b.link("wave", s, x, S[4], S[4])
    j2 = b.ride(s, w, S[4], 4, 5)
    add("lookback-later-ride-through-bracket-and-skipped", ["8.9 item 4", "8.11.4 rule 8", "DECK-0001 4.3, 8"],
        "A game played at a stop and a skipped action, then the next ride: it looks back to the previous ride and departs from its B.",
        [s, eh, j1, ev, x, w, j2], valid([s, eh, j1, ev, x, w, j2], S[5], skipped=[w]))

    # ------------------------------------------------ events that are not NIP-01 at all (8.2, 8.7.3)
    s = b.spawn()
    h1 = b.hop(s, s, P, PX, created_at=T0 + 5001)
    rival = b.hop(s, s, P, PY, created_at=T0 + 5000)
    surrogate = dict(rival, content="\ud800")
    add("forged-lone-surrogate-ignored", ["8.2", "8.7.3 authentic events only"],
        "An event under the identity's pubkey whose content holds a lone surrogate, signed earlier than the real hop. A "
        "lone surrogate has no UTF-8 encoding, so the event has no canonical serialization: it is not a NIP-01 event and "
        "is discarded. A verifier must not stop on it.",
        [s, surrogate, h1], valid([s, h1], PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX, created_at=T0 + 5101)
    rival = b.hop(s, s, P, PY, created_at=T0 + 5100)
    stringly = b.sign_raw(str(T0 + 5100), rival["tags"])
    add("forged-string-created-at-ignored", ["8.2", "8.7.3 authentic events only"],
        "An event whose created_at is a string, signed over its own serialization and earlier than the real hop. "
        "NIP-01 requires an integer created_at, so it is discarded and makes no fork.",
        [s, stringly, h1], valid([s, h1], PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX, created_at=T0 + 5201)
    rival = b.hop(s, s, P, PY, created_at=T0 + 5200)
    nulled = b.sign_raw(T0 + 5200, [["A", "hop", None]] + rival["tags"][1:])
    add("forged-null-in-tag-ignored", ["8.2", "8.7.3 authentic events only"],
        "An event whose A tag holds a null, signed over its own serialization and earlier than the real hop. NIP-01 "
        "tags are arrays of strings, so it is discarded and makes no fork.",
        [s, nulled, h1], valid([s, h1], PX))

    # ------------------------------------------------ more resolution (8.7.3 rule 1)
    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    fake_spawn = b.spawn(created_at=T0 + 6000)
    fake_spawn = dict(fake_spawn, sig=b.sk.sign_schnorr(bytes.fromhex(s["id"]), bytes(32)).hex())
    add("forged-spawn-ignored", ["8.7.3 authentic events only", "8.7.3 rule 1"],
        "A spawn newer than the real one whose sig signs another id is discarded, so it cannot restart the chain.",
        [s, h1, fake_spawn], valid([s, h1], PX))

    t = T0 + 7000
    sa = b.sign([["A", "spawn"], ["C", P]] + _sector_tags_from_coord_hex(P), t, content="a")
    sb = b.sign([["A", "spawn"], ["C", P]] + _sector_tags_from_coord_hex(P), t, content="b")
    newer, older = max((sa, sb), key=lambda e: e["id"]), min((sa, sb), key=lambda e: e["id"])
    h_old = b.hop(older, older, P, PX)
    add("spawn-tie-larger-id", ["8.7.3 rule 1"],
        "Two spawns with the same created_at: the one with the larger id is newer and starts the active chain. The hop "
        "on the other spawn is an older chain's history and makes no fork, because its e genesis names the other spawn.",
        [sa, sb, h_old], valid([newer], P))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX, created_at=T0 + 8001)
    rival = b.hop(s, s, P, PY, created_at=T0 + 8000)
    note = b.sign(rival["tags"], rival["created_at"], kind=1)
    add("other-kind-ignored", ["8.1", "8.7.3"],
        "A kind 1 event signed by the identity with the links and tags of a hop, signed earlier than the real hop, is "
        "not a movement event and makes no fork.",
        [s, note, h1], valid([s, h1], PX))

    # ------------------------------------------------ more rides (DECK-0001 3.3, 4.2, 4.3)
    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 0, 1, as_of=1)
    add("ride-station-tie-lowest-height", ["DECK-0001 4.2"],
        "With the bound 1, stops 0 and 1 are both at distance 85 from the boarding; the tie goes to the lowest height, "
        "so the station is 0 and a first ride from 0 to 1 is valid.",
        [s, eh, j1], valid([s, eh, j1], S[1]))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 1, 0, as_of=1)
    add("ride-station-tie-not-higher", ["DECK-0001 4.2"],
        "With the same tie, the station is 0, not 1, so a first ride from 1 to 0 is invalid.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-station", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    h1 = b.hop(s, eh, P, PX)
    j1 = b.ride(s, h1, PX, 2, 4, as_of=5)
    add("ride-after-board-then-hop", ["DECK-0001 3.3, 4.3"],
        "A hop right after boarding moves as usual and cancels the boarding, so a ride after the hop is invalid.",
        [s, eh, h1, j1], invalid([s, eh, h1, j1], j1, "hyperjump-predecessor", PX))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5)
    eh2 = b.board(s, j1, S[4])
    j2 = b.ride(s, eh2, S[4], 4, 5, as_of=5)
    add("ride-reboard-at-stop", ["DECK-0001 3.3, 4.2"],
        "Boarding again while standing at stop 4 makes stop 4 the station (distance 0), and the next ride departs from it.",
        [s, eh, j1, eh2, j2], valid([s, eh, j1, eh2, j2], S[5]))

    # ------------------------------------------------ more brackets (8.11)
    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x = b.exit(s, ev, ev, P, c="zz")
    add("bracket-exit-c-not-hex", ["8.11.3", "8.11.4 rule 4"], "An exit whose c is not a coordinate at all is valid; its c is not checked.",
        [s, ev, x], valid([s, ev, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x = b.retag(b.exit(s, ev, ev, P, c=G1), lambda t: t + [["c", G2]])
    add("bracket-exit-two-c-tags", ["8.11.3", "8.11.4 rule 4"], "An exit with two c tags is valid; its c is not checked.",
        [s, ev, x], valid([s, ev, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x = b.retag(b.exit(s, ev, ev, P, c=FAR_SECTOR),
                lambda t: [y for y in t if y[0] not in ("X", "Y", "Z", "S")] + _sector_tags_from_coord_hex(FAR_SECTOR))
    add("bracket-exit-sector-tags-from-c", ["8.11.3", "10"],
        "An exit's sector tags are computed from its C, the base position, not from its c.",
        [s, ev, x], invalid([s, ev, x], x, "sector-tags", P))

    other_plane = flip(far, plane=1 - coord_to_xyz(int(P, 16))[3])
    for name, region, why in (
        ("other-plane", region_around(other_plane, 4), "on the other plane from the base position"),
        ("height-0", [far, "0"], "of height 0, a single point"),
        ("height-85", [format(xyz_to_coord(0, 0, 0, 1), "064x"), "85"], "of height 85, a whole plane"),
    ):
        s = b.spawn()
        ev = b.enter(s, s, P, region)
        x = b.exit(s, ev, ev, P)
        add(f"bracket-region-{name}", ["8.11.1"], f"A region {why} is valid: the region is checked for form only.",
            [s, ev, x], valid([s, ev, x], P))

    s = b.spawn()
    eh = b.retag(b.board(s, s, P), set_value("Z", lambda v: "0" + v))
    add("board-sector-tags-noncanonical", ["DECK-0001 1.3", "10"], "An enter-hyperspace with a leading zero on its Z tag is invalid.",
        [s, eh], invalid([s, eh], eh, "sector-tags", P))

    s = b.spawn()
    ev = b.retag(b.enter(s, s, P, R), set_value("Y", lambda v: "0" + v))
    add("bracket-enter-sector-tags-noncanonical", ["8.11.1", "10"], "An enter-virtual with a leading zero on its Y tag is invalid.",
        [s, ev], invalid([s, ev], ev, "sector-tags", P))

    # ------------------------------------------------ a spawn with another A tag (8.7.3 rule 1, 8.8)
    for name, a_tags in (("spawn-first", [["A", "spawn"], ["A", "hop"]]), ("spawn-second", [["A", "hop"], ["A", "spawn"]])):
        s1 = b.spawn()
        h1 = b.hop(s1, s1, P, PX)
        s2 = b.sign(a_tags + [["C", P]] + _sector_tags_from_coord_hex(P))
        add(f"spawn-two-a-tags-{name}", ["8.7.3 rule 1", "8.8"],
            "Any A tag equal to spawn makes an event a spawn, wherever it stands among the tags. This one is newest, so it "
            "starts the active chain, and its second A tag makes it an invalid spawn: the chain is dead at the spawn "
            "coordinate, with no fallback to the older chain.",
            [s1, h1, s2], invalid([s2], s2, "a-tag", P))

    # ------------------------------------------------ every read tag exactly once, with a value
    def hop_with(change, name, why, reason, spec):
        s = b.spawn()
        h1 = b.retag(b.hop(s, s, P, PX), change)
        add(name, spec, why, [s, h1], invalid([s, h1], h1, reason, P))

    def first(tag_name, tag):
        def change(tags):
            i = next(i for i, t in enumerate(tags) if t[0] == tag_name)
            return tags[:i] + [tag] + tags[i:]
        return change

    hop_with(lambda t: [["A"]] + t[1:], "a-tag-bare", "A hop whose only A tag is a bare [\"A\"]: it is an A tag with no value, and invalid.", "a-tag", ["8.8"])
    hop_with(lambda t: t + [["A"]], "a-tag-hop-plus-bare", "A hop with [\"A\", \"hop\"] and a bare [\"A\"]: two A tags.", "a-tag", ["8.8"])
    hop_with(lambda t: [["A", ""]] + t[1:], "a-tag-empty-value", "A hop whose A tag is [\"A\", \"\"]: an empty value, and invalid.", "a-tag", ["8.8"])
    hop_with(duplicate("C"), "hop-two-c-tags", "A hop with its C tag twice, both copies equal: still invalid.", "malformed", ["8.4", "8.12"])
    hop_with(duplicate("proof"), "hop-two-proof-tags-equal", "A hop with its valid proof tag twice.", "malformed", ["8.4", "8.12"])
    hop_with(lambda t: t + [["proof", "zz"]], "hop-two-proof-tags-good-first", "A hop with its valid proof tag and then a garbage one.", "malformed", ["8.4", "8.12"])
    hop_with(first("proof", ["proof", "zz"]), "hop-two-proof-tags-garbage-first", "A hop with a garbage proof tag and then its valid one: the same verdict as with the valid one first.", "malformed", ["8.4", "8.12"])
    hop_with(lambda t: t + [["X"]], "hop-sector-tags-valueless-copy", "A hop with its valid X tag and a valueless [\"X\"]: two X tags.", "sector-tags", ["8.4", "10"])
    hop_with(duplicate("c"), "hop-two-lowercase-c-tags", "A hop with its c tag twice.", "malformed", ["8.4", "8.12"])
    hop_with(lambda t: [x for x in t if x[0] != "proof"] + [["proof"]], "hop-proof-valueless", "A hop whose only proof tag is a bare [\"proof\"].", "malformed", ["8.4", "8.12"])
    s = b.spawn()
    h1 = b.retag(b.hop(s, s, P, PX), first("e", ["e", "", "", "previous"]))
    add("hop-empty-first-e-previous-unlinked", ["8.7.3 rule 3", "8.12"],
        "A hop with an empty e previous tag ahead of its real one. Resolution follows the first copy, which names "
        "nothing, so the hop is never reached: it is not on the chain, and the chain is the spawn alone, valid.",
        [s, h1], valid([s], P))

    s = b.spawn()
    h1 = b.retag(b.hop(s, s, P, PX), lambda t: t + [list(next(x for x in t if x[0] == "e" and x[3] == "previous"))])
    add("hop-e-previous-twice", ["8.4", "8.12"], "A hop with its e previous tag twice, both copies equal: resolution follows the first, and validity rejects the event.",
        [s, h1], invalid([s, h1], h1, "malformed", P))

    s = b.spawn()
    w = b.retag(b.link("wave", s, s, P, P), lambda t: t + [list(next(x for x in t if x[0] == "e" and x[3] == "genesis"))])
    add("skip-two-e-genesis-tags", ["8.9", "8.12"], "A skipped action with its e genesis tag twice is invalid: on a skipped action the A tag and the e tags are constrained.",
        [s, w], invalid([s, w], w, "malformed", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.retag(b.game(s, ev, "move"), lambda t: t + [list(next(x for x in t if x[0] == "e" and x[3] == "previous"))])
    add("bracket-virtual-two-e-previous-tags", ["8.11.4 rule 4", "8.12"],
        "A virtual action with its e previous tag twice is invalid: inside a bracket the A tag and the e tags are constrained.",
        [s, ev, v1], invalid([s, ev, v1], v1, "malformed", P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    v1 = b.game(s, ev, "move", [["score", ""], ["board"], ["c", ""], ["C"], ["X", ""], ["proof"]])
    x = b.exit(s, v1, ev, P)
    add("bracket-game-tags-empty-values", ["8.11.2", "8.11.4 rule 4"],
        "A virtual action whose game-defined tags are empty or valueless, including tags whose names base reads elsewhere (c, C, X, proof), is valid: "
        "inside a bracket only the A tag and the e tags are constrained.",
        [s, ev, v1, x], valid([s, ev, v1, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, R)
    x = b.retag(b.exit(s, ev, ev, P), lambda t: t + [list(next(y for y in t if y[0] == "e" and y[3] == "entry"))])
    add("bracket-exit-two-entry-tags", ["8.11.3", "8.12"], "An exit with its e entry tag twice is invalid.",
        [s, ev, x], invalid([s, ev, x], x, "malformed", P))

    s = b.spawn()
    ev = b.retag(b.enter(s, s, P, R), duplicate("region"))
    add("bracket-region-two-tags", ["8.11.1"], "An enter-virtual with its region tag twice is invalid.",
        [s, ev], invalid([s, ev], ev, "region", P))

    s = b.spawn()
    ev = b.retag(b.enter(s, s, P, R), lambda t: t + [["region"]])
    add("bracket-region-plus-valueless", ["8.11.1"], "An enter-virtual with its region tag and a bare [\"region\"]: two region tags.",
        [s, ev], invalid([s, ev], ev, "region", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.retag(b.ride(s, eh, P, 2, 4, as_of=5), duplicate("B"))
    add("ride-two-b-tags", ["DECK-0001 5.2", "8.12"], "A ride with its B tag twice is invalid.",
        [s, eh, j1], invalid([s, eh, j1], j1, "malformed", P))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.retag(b.ride(s, eh, P, 2, 4, as_of=5), duplicate("as_of"))
    add("ride-two-as-of-tags", ["DECK-0001 4.2", "8.12"], "A first ride with its as_of tag twice is invalid.",
        [s, eh, j1], invalid([s, eh, j1], j1, "malformed", P))

    s = b.spawn()
    st = b.retag(b.sidestep(s, s, P, PZ), duplicate("mn"))
    add("sidestep-two-mn-tags", ["8.5", "8.12"], "A sidestep with its mn tag twice is invalid.",
        [s, st], invalid([s, st], st, "malformed", P))

    return vectors


def main() -> None:
    j, sk, pub = test_key()
    other = PrivateKey(sha256(OTHER_KEY_DOMAIN))
    blocks = make_line(pub)
    line = Line.from_blocks(blocks)
    for bound, station in ((2, 2), (5, 2), (6, 6), (7, 6)):
        assert line.station(pub, bound) == station, (bound, line.station(pub, bound))
    # the tie-break vectors need stops 0 and 1 equally far from the spawn
    xyz = coord_to_xyz(int(pub, 16))[:3]
    assert stop_distance(xyz, line.stop(0).xyzp[:3]) == stop_distance(xyz, line.stop(1).xyzp[:3]) == 85
    vectors = build(sk, other, line)
    names = [v["name"] for v in vectors]
    assert len(names) == len(set(names)), "vector names must be unique"
    for v in vectors:
        got = verify_chain(v["events"], pubkey=pub, line=line).expected()
        if got != v["expected"]:
            raise SystemExit(f"{v['name']}: the verifier says {json.dumps(got)}, the vector says {json.dumps(v['expected'])}")
    doc = {
        "name": "cyberspace chain rules golden vectors",
        "chain_rules_revision": CHAIN_RULES_REVISION,
        "revision_note": "2026-09-28-virtual-brackets with the rulings folded in on 2026-10-07 and clarified on 2026-10-08 (CYBERSPACE_V2.md 8.12)",
        "spec": {"repository": "arkin0x/cyberspace", "commit": SPEC_COMMIT},
        "generator": "scripts/gen_chain_vectors.py in arkin0x/cyberspace-cli",
        "regenerate": "PYTHONPATH=src python scripts/gen_chain_vectors.py",
        "format": "vectors/README.md",
        "verify_with": {"identity": pub, "line": "line.blocks below"},
        "test_key": {
            "secret_key": sha256(KEY_DOMAIN + j.to_bytes(4, "big")).hex(),
            "pubkey": pub,
            "derivation": f"sha256({KEY_DOMAIN.decode()} || be32({j})), the first j whose spawn coordinate has terrain K <= {MAX_K}",
        },
        "other_key": {"pubkey": other.public_key_xonly.format().hex(), "derivation": f"sha256({OTHER_KEY_DOMAIN.decode()})"},
        "game_pubkey": GAME,
        "line": {
            "description": "Synthetic stops 0..7, all ports (plane bit 1), so each stop coordinate is its merkle root. "
                           "Block hashes are the spec reference's stand-in (decks/hyperjump-reference.py). "
                           "Stop 2 is the station for an as_of bound of 2 to 5 and stop 6 for 6 or 7.",
            "blocks": blocks,
        },
        "reasons": REASONS,
        "vectors": vectors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # ASCII with escapes, so a vector can carry a lone surrogate, which has no UTF-8 encoding.
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {len(vectors)} vectors to {OUT}")


if __name__ == "__main__":
    main()
