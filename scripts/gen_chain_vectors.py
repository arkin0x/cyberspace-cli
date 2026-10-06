#!/usr/bin/env python3
"""Regenerate vectors/chain-rules-2026-09-28-virtual-brackets.json, the golden
vectors for the chain rules of CYBERSPACE_V2.md section 8.12.

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
from typing import Any, Dict, List, Optional

from coincurve import PrivateKey

from cyberspace_cli.nostr_event import _sector_tags_from_coord_hex, compute_event_id_hex
from cyberspace_core.cantor import sha256
from cyberspace_core.chain import CHAIN_RULES_REVISION, REASONS, verify_chain
from cyberspace_core.coords import coord_to_xyz, xyz_to_coord
from cyberspace_core.hyperspace import Line, enter_hyperspace_proof
from cyberspace_core.movement import compute_hop_proof, compute_sidestep_proof, encode_nonce, encode_openings
from cyberspace_core.ride import K_LINE, encode_ride_openings, line_terrain_k, prove_ride
from cyberspace_core.terrain import terrain_k

OUT = Path(__file__).resolve().parents[1] / "vectors" / f"chain-rules-{CHAIN_RULES_REVISION}.json"
SPEC_COMMIT = "df00a48654cd2162103c0812fbe3494da611e3b5"
KEY_DOMAIN = b"CYBERSPACE_CHAIN_VECTORS_KEY"
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


# ---------------------------------------------------------------- the key and the line

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

class Builder:
    """Signed kind 3333 events by the test key, created_at counting up from T0."""

    def __init__(self, sk: PrivateKey, pub: str, line: Line):
        self.sk, self.pub, self.line = sk, pub, line
        self.clock = T0

    def sign(self, tags: List[List[str]], created_at: Optional[int] = None, content: str = "") -> Dict[str, Any]:
        if created_at is None:
            self.clock += 1
            created_at = self.clock
        eid = compute_event_id_hex(pubkey_hex=self.pub, created_at=created_at, kind=3333, tags=tags, content=content)
        sig = self.sk.sign_schnorr(bytes.fromhex(eid), bytes(32)).hex()
        return {"id": eid, "pubkey": self.pub, "created_at": created_at, "kind": 3333, "tags": tags, "content": content, "sig": sig}

    def spawn(self, created_at: Optional[int] = None, coord: Optional[str] = None) -> Dict[str, Any]:
        coord = coord or self.pub
        return self.sign([["A", "spawn"], ["C", coord]] + _sector_tags_from_coord_hex(coord), created_at)

    def link(self, action: str, genesis: Dict, prev: Dict, c: str, C: str, extra: Optional[List[List[str]]] = None,
             created_at: Optional[int] = None, entry: Optional[Dict] = None) -> Dict[str, Any]:
        tags = [["A", action], ["e", genesis["id"], "", "genesis"], ["e", prev["id"], "", "previous"]]
        if entry is not None:
            tags.append(["e", entry["id"], "", "entry"])
        tags += [["c", c], ["C", C]] + (extra or []) + _sector_tags_from_coord_hex(C)
        return self.sign(tags, created_at)

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
        C = C or self.line.stop(to_height).coord_hex
        lo, hi = min(from_height, to_height), max(from_height, to_height)
        root, nonce, openings = prove_ride(bytes.fromhex((seed or prev)["id"]), lo, hi, self.line.block_hash, workers=1)
        extra = [["from_height", str(from_height)], ["B", str(to_height)]]
        if as_of is not None:
            extra.append(["as_of", str(as_of)])
        extra += [["proof", root.hex()], ["mp", encode_ride_openings(openings)], ["mn", encode_nonce(nonce)]]
        return self.link("hyperjump", genesis, prev, c, C, extra)

    def enter(self, genesis: Dict, prev: Dict, c: str, C: str, region: List[str], games: Optional[List[List[str]]] = None) -> Dict[str, Any]:
        if games is None:
            games = [["p", GAME, "wss://game.example", "game"]]
        return self.link("enter-virtual", genesis, prev, c, C, [["region"] + region] + games)

    def exit(self, genesis: Dict, prev: Dict, entry: Optional[Dict], c: str, C: str) -> Dict[str, Any]:
        if entry is None:
            tags = [["A", "exit-virtual"], ["e", genesis["id"], "", "genesis"], ["e", prev["id"], "", "previous"],
                    ["c", c], ["C", C]] + _sector_tags_from_coord_hex(C)
            return self.sign(tags)
        return self.link("exit-virtual", genesis, prev, c, C, entry=entry)


GAME = sha256(GAME_DOMAIN).hex()


def region_around(coord_hex: str, h: int) -> List[str]:
    """The aligned cube of height h that holds the coordinate, as a region tag's values."""
    x, y, z, p = coord_to_xyz(int(coord_hex, 16))
    base = xyz_to_coord((x >> h) << h, (y >> h) << h, (z >> h) << h, p)
    return [format(base, "064x"), str(h)]


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


def invalid(chain: List[Dict], at: Optional[Dict], reason: str) -> Dict[str, Any]:
    assert reason in REASONS, reason
    return {
        "valid": False,
        "chain": [e["id"] for e in chain],
        "reason": reason,
        "invalid_at": at["id"] if at else None,
        "invalid_index": next(i for i, e in enumerate(chain) if e is at) if at else None,
    }


def build(sk: PrivateKey, pub: str, line: Line) -> List[Dict[str, Any]]:
    b = Builder(sk, pub, line)
    P = pub
    PX, PY, PZ = flip(P, dx=1), flip(P, dy=1), flip(P, dz=1)
    R = region_around(P, 8)  # the game's box around the spawn
    G0, G1, G2 = flip(P, dx=0x10), flip(P, dx=0x10, dy=0x20), flip(P, dz=0x40)  # inside R
    OUT_R = flip(P, dx=0x100)  # outside R, on the same plane
    S = {h: line.stop(h).coord_hex for h in range(TIP + 1)}
    vectors: List[Dict[str, Any]] = []

    def add(name: str, spec: List[str], description: str, events: List[Dict], expected: Dict, open_question: Optional[str] = None):
        v = {"name": name, "spec": spec, "description": description}
        if open_question:
            v["open_question"] = open_question
        v["events"] = events
        v["expected"] = expected
        vectors.append(v)

    # ------------------------------------------------ resolution (8.7.3) and the spawn
    s = b.spawn()
    add("spawn-only", ["8.3", "8.7.3"], "A spawn alone is a valid chain; the position is the spawn coordinate, the pubkey.",
        [s], valid([s], P))

    s = b.spawn(coord=PX)
    add("spawn-coordinate-not-pubkey", ["8.3"], "A spawn whose C is not its pubkey is invalid, and so is the chain from it.",
        [s], invalid([s], s, "spawn-coordinate"))

    ghost = {"id": "ab" * 32}
    h = b.hop(ghost, ghost, P, PX)
    add("no-spawn", ["8.7.3"], "Events with no spawn among them resolve to no chain.", [h], invalid([], None, "no-spawn"))

    s = b.spawn()
    hb = b.hop(s, s, P, PX, created_at=T0 + 1000)
    ha = b.hop(s, s, P, PY, created_at=T0 + 1001)
    ha2 = b.hop(s, ha, PY, flip(PY, dz=1), created_at=T0 + 1002)
    add("fork-older-branch-continues", ["8.7.3"],
        "Two hops name the spawn as previous. The one signed first (smaller created_at) continues the chain and the other "
        "branch, with its descendant, is dropped. Events are listed out of order on purpose.",
        [ha2, ha, s, hb], valid([s, hb], PX))

    s = b.spawn()
    t = T0 + 2000
    f1, f2 = b.hop(s, s, P, PX, created_at=t), b.hop(s, s, P, PY, created_at=t)
    win = min((f1, f2), key=lambda e: e["id"])
    add("fork-tie-smaller-id", ["8.7.3"], "Two branches with the same created_at: the smaller event id continues the chain.",
        [f1, f2, s], valid([s, win], win["tags"][4][1]))

    s1 = b.spawn()
    h1 = b.hop(s1, s1, P, PX)
    s2 = b.spawn()
    stale = b.hop(s1, s2, P, PY)  # names the new spawn as previous but the old one as genesis
    add("respawn-newest-spawn", ["3.2", "8.7.3"],
        "The newest spawn starts the active chain. An event whose e genesis names the older spawn is ignored even "
        "though its e previous names the newest spawn.",
        [s1, h1, s2, stale], valid([s2], P))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    copy = dict(h1, content="altered by someone else")
    add("forged-copy-ignored", ["8.2", "8.7.3"],
        "A copy of a real event with its content altered keeps the real id and sig, but the id is not its hash: it is not "
        "an event by this pubkey and is set aside before resolving, whichever copy a relay returns first.",
        [copy, s, h1], valid([s, h1], PX))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX, created_at=T0 + 3001)
    fake = {"id": "ee" * 32, "pubkey": P, "created_at": T0 + 3000, "kind": 3333, "content": "", "sig": h1["sig"],
            "tags": [["A", "hop"], ["e", s["id"], "", "genesis"], ["e", s["id"], "", "previous"], ["c", P], ["C", PY], ["proof", "00" * 32]]}
    add("forged-fork-ignored", ["8.2", "8.7.3", "3.2"],
        "An event whose id is not its hash names the spawn as previous with an earlier created_at than the real hop. It is "
        "not authentic, so it takes no part in the fork, and nothing another identity publishes can end this chain.",
        [s, fake, h1], valid([s, h1], PX))

    # ------------------------------------------------ base movement
    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    h2 = b.hop(s, h1, PX, flip(PX, dy=1), seed=s)
    add("hop-proof-wrong-seed", ["8.7.1", "5.3"], "A hop whose proof is seeded by an id other than its e previous is invalid.",
        [s, h1, h2], invalid([s, h1, h2], h2, "hop-proof"))

    s = b.spawn()
    unsigned = b.hop(s, s, P, PY, created_at=T0 + 4000)
    unsigned = dict(unsigned, sig=b.sk.sign_schnorr(bytes.fromhex(s["id"]), bytes(32)).hex())
    h1 = b.hop(s, s, P, PX, created_at=T0 + 4001)
    add("unsigned-fork-ignored", ["8.2", "8.7.3"],
        "A hop with a correct id and a valid proof whose sig signs a different id, signed earlier than the real hop. With "
        "signatures checked (verify_with) it is set aside and the real hop continues the chain; a verifier that does not "
        "check signatures would follow it instead.",
        [s, unsigned, h1], valid([s, h1], PX))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    st = b.sidestep(s, w, P, PZ, seed=s)
    add("sidestep-proof-wrong-seed", ["8.7.2", "8.9 step 3"],
        "A sidestep after a skipped action whose trees and proof were seeded by the spawn instead of the skipped action is invalid.",
        [s, w, st], invalid([s, w, st], st, "sidestep-proof"))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    h2 = b.hop(s, h1, P, PY)
    add("hop-c-mismatch", ["8.4", "8.9"], "A hop whose c is not the previous C is invalid.",
        [s, h1, h2], invalid([s, h1, h2], h2, "c-mismatch"))

    # ------------------------------------------------ skipping (8.9)
    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    h1 = b.hop(s, w, P, PX)
    add("skip-unknown-nonmoving-then-hop", ["8.9 steps 1-3"],
        "An unrecognized action that does not move is skipped; the hop after it starts from the carried position and its "
        "proof is seeded by the skipped action's id.",
        [s, w, h1], valid([s, w, h1], PX, skipped=[w]))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    h1 = b.hop(s, w, P, PX, seed=s)
    add("skip-hop-seeded-by-nearest-recognized", ["8.9 step 3"],
        "Work is seeded by the actual previous event. A hop after a skipped action whose proof was seeded by the nearest "
        "recognized action (the spawn) instead is invalid.",
        [s, w, h1], invalid([s, w, h1], h1, "hop-proof"))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    st = b.sidestep(s, w, P, PZ)
    add("skip-then-sidestep", ["8.9 step 3", "8.7.2"], "A sidestep after a skipped action is seeded by the skipped id and fully checked.",
        [s, w, st], valid([s, w, st], PZ, skipped=[w]))

    s = b.spawn()
    tp = b.link("teleport", s, s, P, PY)
    h1 = b.hop(s, tp, PY, flip(PY, dx=1))
    add("skip-unknown-moving-then-hop-from-moved", ["8.9 step 2"],
        "An unrecognized action that changes the position is skipped, so the hop after it, starting where the skipped "
        "action left off, has a c that is not the carried position: the chain is invalid from the hop.",
        [s, tp, h1], invalid([s, tp, h1], h1, "c-mismatch"))

    s = b.spawn()
    tp = b.link("teleport", s, s, P, PY)
    h1 = b.hop(s, tp, P, PX)
    add("skip-unknown-moving-then-hop-from-carried", ["8.9 step 2"],
        "A hop after a skipped moving action is valid when its c is the carried position (the C of the nearest "
        "recognized action), since the skipped action is treated as if it were not on the chain.",
        [s, tp, h1], valid([s, tp, h1], PX, skipped=[tp]))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    tp = b.link("teleport", s, h1, PX, PY)
    w = b.link("wave", s, tp, PY, PY)
    add("skip-chain-ends-on-unknown", ["8.9 step 5"],
        "A chain that ends on skipped actions is valid; the position is the C of the last recognized action, and the head "
        "is the last skipped event.",
        [s, h1, tp, w], valid([s, h1, tp, w], PX, skipped=[tp, w]))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    ev = b.enter(s, w, P, G0, R)
    x = b.exit(s, ev, ev, G0, P)
    add("skip-then-bracket", ["8.9 step 2", "8.11.5"], "An enter-virtual after a skipped action starts from the carried position.",
        [s, w, ev, x], valid([s, w, ev, x], P, skipped=[w]))

    # ------------------------------------------------ brackets (8.11)
    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, PX, G0, R)
    v1 = b.link("move", s, ev, G0, G1)
    v2 = b.link("score", s, v1, G1, G1)
    x = b.exit(s, v2, ev, G1, PX)
    h2 = b.hop(s, x, PX, flip(PX, dy=1))
    add("bracket-valid-then-hop", ["8.11.1-8.11.5", "8.11.4 rule 8"],
        "Enter, two virtual actions with names of the game's choosing, exit back to the base position, then a hop from "
        "it seeded by the exit's id.",
        [s, h1, ev, v1, v2, x, h2], valid([s, h1, ev, v1, v2, x, h2], flip(PX, dy=1)))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    v1 = b.link("move", s, ev, G0, G2)
    x = b.exit(s, v1, ev, G2, P)
    add("bracket-position-held", ["8.11.4 rules 1, 2"], "After the exit the position is the entry's c, wherever the game moved.",
        [s, ev, v1, x], valid([s, ev, v1, x], P))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    x = b.exit(s, ev, ev, G0, P)
    add("bracket-empty", ["8.11.3"], "An exit straight after its entry: e previous and e entry both name the entry.",
        [s, ev, x], valid([s, ev, x], P))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, PX, G0, R)
    v1 = b.link("move", s, ev, G0, G1)
    v2 = b.link("move", s, v1, G1, G2)
    add("bracket-unclosed", ["8.11.4 rule 7"], "A chain may end inside a bracket; the position is the open entry's c.",
        [s, h1, ev, v1, v2], valid([s, h1, ev, v1, v2], PX, open_bracket=ev))

    far = port(b"CYBERSPACE_CHAIN_VECTORS_FAR_BOX")
    far = flip(far, plane=coord_to_xyz(int(P, 16))[3])
    s = b.spawn()
    ev = b.enter(s, s, P, far, region_around(far, 4))
    x = b.exit(s, ev, ev, far, P)
    add("bracket-region-elsewhere", ["8.11.1"], "The game's box need not hold the base position; only the C tags inside the bracket must lie in it.",
        [s, ev, x], valid([s, ev, x], P))

    for name, action in (("hop", "hop"), ("enter-hyperspace", "enter-hyperspace"), ("enter-virtual", "enter-virtual"), ("sidestep", "sidestep")):
        s = b.spawn()
        ev = b.enter(s, s, P, G0, R)
        v1 = b.link("move", s, ev, G0, G1)
        if action == "hop":
            bad = b.hop(s, v1, G1, flip(G1, dx=1))
        elif action == "sidestep":
            bad = b.sidestep(s, v1, G1, flip(G1, dz=1))
        elif action == "enter-hyperspace":
            bad = b.board(s, v1, G1)
        else:
            bad = b.enter(s, v1, G1, G2, R)
        add(f"bracket-{name}-inside", ["8.11.4 rule 3"],
            f"A {action} inside an open bracket is invalid, even with a valid proof and a C in the box. Brackets do not nest.",
            [s, ev, v1, bad], invalid([s, ev, v1, bad], bad, "base-action-in-bracket"))

    s = b.spawn()
    eh = b.board(s, s, P)
    ev = b.enter(s, eh, P, G0, R)
    hj = b.ride(s, ev, G0, 2, 4, as_of=5)
    add("bracket-hyperjump-inside", ["8.11.4 rule 3", "DECK-0001 8"], "A hyperjump inside an open bracket is invalid.",
        [s, eh, ev, hj], invalid([s, eh, ev, hj], hj, "base-action-in-bracket"))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    v1 = b.link("teleport", s, ev, G0, OUT_R)
    add("bracket-virtual-outside-region", ["8.11.4 rules 4, 5"],
        "Inside a bracket an unrecognized name is a virtual action, not a skipped one: its C must lie in the box.",
        [s, ev, v1], invalid([s, ev, v1], v1, "outside-region"))

    s = b.spawn()
    ev = b.enter(s, s, P, OUT_R, R)
    add("bracket-entry-outside-region", ["8.11.1", "8.11.4 rule 4"], "The enter-virtual's own C must lie in the box.",
        [s, ev], invalid([s, ev], ev, "outside-region"))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    v1 = b.link("move", s, ev, G0, G1)
    x = b.exit(s, v1, ev, G1, G1)
    add("bracket-exit-position-mismatch", ["8.11.4 rule 2"], "An exit whose C is not the entry's c is invalid.",
        [s, ev, v1, x], invalid([s, ev, v1, x], x, "exit-position"))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    x = b.exit(s, h1, s, PX, PX)
    add("bracket-exit-without-bracket", ["8.11.4 rule 6"], "An exit with no bracket open is invalid.",
        [s, h1, x], invalid([s, h1, x], x, "exit-without-bracket"))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    x1 = b.exit(s, ev, ev, G0, P)
    x2 = b.exit(s, x1, ev, P, P)
    add("bracket-exit-twice", ["8.11.4 rule 6"], "A second exit naming a bracket that is already closed: no bracket is open.",
        [s, ev, x1, x2], invalid([s, ev, x1, x2], x2, "exit-without-bracket"))

    s = b.spawn()
    ev1 = b.enter(s, s, P, G0, R)
    x1 = b.exit(s, ev1, ev1, G0, P)
    ev2 = b.enter(s, x1, P, G1, R)
    v1 = b.link("move", s, ev2, G1, G2)
    x2 = b.exit(s, v1, ev1, G2, P)
    add("bracket-exit-wrong-entry", ["8.11.4 rule 6"], "An exit whose e entry names an earlier, closed bracket instead of the open one is invalid.",
        [s, ev1, x1, ev2, v1, x2], invalid([s, ev1, x1, ev2, v1, x2], x2, "exit-wrong-entry"))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    x = b.exit(s, ev, None, G0, P)
    add("bracket-exit-missing-entry-tag", ["8.11.3"], "An exit without an e entry tag is malformed.",
        [s, ev, x], invalid([s, ev, x], x, "malformed"))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    v1 = b.link("move", s, ev, G0, G1)
    x = b.exit(s, v1, ev, G0, P)
    add("bracket-exit-c-mismatch", ["8.11.3"], "An exit's c is the C of the previous event, the last position inside the game.",
        [s, ev, v1, x], invalid([s, ev, v1, x], x, "c-mismatch"),
        open_question="8.11.5 step 3 does not list this check; 8.11.3 defines the exit's c as the previous C, read here as a rule.")

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R)
    v1 = b.link("move", s, ev, G1, G2)
    add("bracket-virtual-c-mismatch", ["8.11.2", "8.11.5 step 2"], "A virtual action's c is the C of the previous event.",
        [s, ev, v1], invalid([s, ev, v1], v1, "c-mismatch"))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, P, G0, R)
    add("bracket-entry-c-mismatch", ["8.11.5 step 1"], "An entry's c is the carried position.",
        [s, h1, ev], invalid([s, h1, ev], ev, "c-mismatch"))

    for name, games in (
        ("missing", []),
        ("duplicated", [["p", GAME, "", "game"], ["p", GAME, "", "game"]]),
        ("unmarked", [["p", GAME, "wss://game.example"]]),
        ("bad-pubkey", [["p", GAME.upper(), "", "game"]]),
    ):
        s = b.spawn()
        ev = b.enter(s, s, P, G0, R, games=games)
        add(f"bracket-game-tag-{name}", ["8.11.1", "8.11.5"],
            "An enter-virtual must carry exactly one p tag marked game holding a 32-byte lowercase hex pubkey.",
            [s, ev], invalid([s, ev], ev, "game-tag"))

    s = b.spawn()
    ev = b.enter(s, s, P, G0, R, games=[["p", GAME, "", "game"], ["p", "cd" * 32, "", "referee"]])
    x = b.exit(s, ev, ev, G0, P)
    add("bracket-game-tag-with-other-p", ["8.11.1"], "Other p tags are not game tags; one marked game is exactly one.",
        [s, ev, x], valid([s, ev, x], P))

    unaligned = [format(int(R[0], 16) | (1 << 3), "064x"), "8"]
    for name, region in (("unaligned", unaligned), ("noncanonical-height", [R[0], "08"]), ("height-above-85", [R[0], "86"]), ("missing", None)):
        s = b.spawn()
        if region is None:
            tags = [["A", "enter-virtual"], ["e", s["id"], "", "genesis"], ["e", s["id"], "", "previous"], ["c", P], ["C", G0],
                    ["p", GAME, "", "game"]] + _sector_tags_from_coord_hex(G0)
            ev = b.sign(tags)
        else:
            ev = b.enter(s, s, P, G0, region)
        add(f"bracket-region-{name}", ["8.11.1"],
            "The region tag must be present once, with H a canonical decimal in [0, 85] and the base aligned to H.",
            [s, ev], invalid([s, ev], ev, "region"))

    s1 = b.spawn()
    ev = b.enter(s1, s1, P, G0, R)
    v1 = b.link("move", s1, ev, G0, G1)
    s2 = b.spawn()
    h1 = b.hop(s2, s2, P, PX)
    add("bracket-spawn-inside", ["8.11.2", "8.11.4", "8.7.3"],
        "A spawn while a bracket is open is a respawn, not a virtual action: it starts a new chain and the open bracket "
        "stays in the old chain's history.",
        [s1, ev, v1, s2, h1], valid([s2, h1], PX))

    # ------------------------------------------------ DECK-0001 rides, with look-back (8.9 step 4, 8.11.4 rule 8)
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
    j1 = b.ride(s, eh, P, 6, 4, as_of=7)
    add("ride-as-of-selects-station", ["DECK-0001 4.2"],
        "With the bound 7 the nearest stop is 6, which is newer than the destination 4: the ride departs from 6.",
        [s, eh, j1], valid([s, eh, j1], S[4]))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=7)
    add("ride-not-from-station", ["DECK-0001 4.2, 4.3"],
        "With the bound 7 the station is stop 6, so a first ride from stop 2 is invalid.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-station"))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 2, as_of=5)
    add("ride-zero-length-first", ["DECK-0001 5.6"],
        "A first ride whose destination is the station has length 0, a zero proof, zero mn and empty mp; it moves the identity to the stop.",
        [s, eh, j1], valid([s, eh, j1], S[2]))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5)
    j2 = b.ride(s, j1, S[4], 4, 4)
    add("ride-zero-length-later", ["DECK-0001 5.2, 5.6"],
        "A later ride with from_height equal to B: 5.2 allows B_to = B_from only when 5.6 applies, and 5.6 is the first ride from the station.",
        [s, eh, j1, j2], invalid([s, eh, j1, j2], j2, "hyperjump-zero-length"),
        open_question="Published chains contain such rides (for example 331059b3... and d457ac3a..., both on the exemption "
                      "list of DECK-0001 5.8, which says no chain is invalidated). Read literally, 5.2 makes them invalid.")

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    j1 = b.ride(s, h1, PX, 2, 4, as_of=5)
    add("ride-after-hop", ["DECK-0001 4.3"], "A hyperjump whose previous action is a hop is invalid.",
        [s, h1, j1], invalid([s, h1, j1], j1, "hyperjump-predecessor"))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4)
    add("ride-missing-as-of", ["DECK-0001 4.3"], "The first ride after boarding must carry as_of.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-as-of"))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=3)
    add("ride-as-of-below-destination", ["DECK-0001 4.2"], "as_of must be at least B.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-as-of"))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=TIP + 1)
    add("ride-as-of-beyond-tip", ["DECK-0001 4.2"], "as_of must be a height that exists; the line ends at 7.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-as-of"))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5)
    j2 = b.ride(s, j1, S[4], 3, 5)
    add("ride-later-from-height-mismatch", ["DECK-0001 4.3"], "A later ride departs from the previous ride's B.",
        [s, eh, j1, j2], invalid([s, eh, j1, j2], j2, "hyperjump-from-height"))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5, C=S[5])
    add("ride-wrong-stop", ["DECK-0001 5.5"], "A ride's C must be the stop coordinate of its B.",
        [s, eh, j1], invalid([s, eh, j1], j1, "hyperjump-stop"))

    s = b.spawn()
    eh = b.board(s, s, P, C=PX)
    add("board-moves", ["DECK-0001 3.1"], "An enter-hyperspace whose C differs from its c is invalid.",
        [s, eh], invalid([s, eh], eh, "enter-hyperspace-moved"))

    s = b.spawn()
    w = b.link("wave", s, s, P, P)
    eh = b.board(s, w, P, seed=s)
    add("board-proof-wrong-seed", ["DECK-0001 3.2", "8.9 step 3"],
        "The entry proof is seeded by the actual previous event, here a skipped action; one seeded by the spawn is invalid.",
        [s, w, eh], invalid([s, w, eh], eh, "enter-hyperspace-proof"))

    s = b.spawn()
    eh = b.board(s, s, P)
    ev = b.enter(s, eh, P, G0, R)
    v1 = b.link("move", s, ev, G0, G1)
    x = b.exit(s, v1, ev, G1, P)
    j1 = b.ride(s, x, P, 2, 4, as_of=5)
    add("lookback-ride-through-bracket", ["8.11.4 rule 8", "DECK-0001 4.3, 8"],
        "Board, play a game, exit, ride: the exit stands for the boarding, so this is the first ride and departs from the "
        "station. Its work is seeded by the exit's id.",
        [s, eh, ev, v1, x, j1], valid([s, eh, ev, v1, x, j1], S[4]))

    s = b.spawn()
    eh = b.board(s, s, P)
    ev = b.enter(s, eh, P, G0, R)
    x = b.exit(s, ev, ev, G0, P)
    j1 = b.ride(s, x, P, 2, 4, as_of=5, seed=eh)
    add("lookback-ride-seeded-by-boarding", ["8.11.4 rule 8", "DECK-0001 5.3"],
        "The exit stands in for the boarding only for the look-back rule; a ride seeded by the boarding instead of the exit is invalid.",
        [s, eh, ev, x, j1], invalid([s, eh, ev, x, j1], j1, "hyperjump-proof"))

    s = b.spawn()
    eh = b.board(s, s, P)
    w = b.link("wave", s, eh, P, P)
    j1 = b.ride(s, w, P, 2, 4, as_of=5)
    add("lookback-ride-through-skipped", ["8.9 step 4", "DECK-0001 4.3"],
        "A skipped action between boarding and the first ride: the boarding stands before the ride, which is seeded by the skipped id.",
        [s, eh, w, j1], valid([s, eh, w, j1], S[4], skipped=[w]))

    s = b.spawn()
    h1 = b.hop(s, s, P, PX)
    ev = b.enter(s, h1, PX, G0, R)
    x = b.exit(s, ev, ev, G0, PX)
    j1 = b.ride(s, x, PX, 2, 4, as_of=5)
    add("lookback-exit-stands-for-hop", ["8.11.4 rule 8", "DECK-0001 4.3"],
        "The exit stands for the hop before its entry, so the ride has no boarding before it and is invalid.",
        [s, h1, ev, x, j1], invalid([s, h1, ev, x, j1], j1, "hyperjump-predecessor"))

    s = b.spawn()
    eh = b.board(s, s, P)
    j1 = b.ride(s, eh, P, 2, 4, as_of=5)
    ev = b.enter(s, j1, S[4], flip(S[4], dx=2), region_around(S[4], 4))
    x = b.exit(s, ev, ev, flip(S[4], dx=2), S[4])
    w = b.link("wave", s, x, S[4], S[4])
    j2 = b.ride(s, w, S[4], 4, 5)
    add("lookback-later-ride-through-bracket-and-skipped", ["8.9 step 4", "8.11.4 rule 8", "DECK-0001 4.3, 8"],
        "A game played at a stop and a skipped action, then the next ride: it looks back to the previous ride and departs from its B.",
        [s, eh, j1, ev, x, w, j2], valid([s, eh, j1, ev, x, w, j2], S[5], skipped=[w]))

    return vectors


def main() -> None:
    j, sk, pub = test_key()
    blocks = make_line(pub)
    line = Line.from_blocks(blocks)
    for bound, station in ((2, 2), (5, 2), (6, 6), (7, 6)):
        assert line.station(pub, bound) == station, (bound, line.station(pub, bound))
    vectors = build(sk, pub, line)
    names = [v["name"] for v in vectors]
    assert len(names) == len(set(names)), "vector names must be unique"
    for v in vectors:
        got = verify_chain(v["events"], pubkey=pub, line=line, check_signatures=True).expected()
        if got != v["expected"]:
            raise SystemExit(f"{v['name']}: the verifier says {json.dumps(got)}, the vector says {json.dumps(v['expected'])}")
    doc = {
        "name": "cyberspace chain rules golden vectors",
        "chain_rules_revision": CHAIN_RULES_REVISION,
        "spec": {"repository": "arkin0x/cyberspace", "commit": SPEC_COMMIT},
        "generator": "scripts/gen_chain_vectors.py in arkin0x/cyberspace-cli",
        "regenerate": "PYTHONPATH=src python scripts/gen_chain_vectors.py",
        "format": "vectors/README.md",
        "verify_with": {"check_signatures": True, "line": "line.blocks below"},
        "test_key": {
            "secret_key": sha256(KEY_DOMAIN + j.to_bytes(4, "big")).hex(),
            "pubkey": pub,
            "derivation": f"sha256({KEY_DOMAIN.decode()} || be32({j})), the first j whose spawn coordinate has terrain K <= {MAX_K}",
        },
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
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(vectors)} vectors to {OUT}")


if __name__ == "__main__":
    main()
