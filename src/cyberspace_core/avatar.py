"""The work an avatar owes (kind 11333, spec 8.10).

An avatar is drawn on every screen near its owner whether they like it or
not, so its size and its detail are paid for in proof of work on the event
itself, NIP-13 style: the event id must carry ``required`` leading zero bits,
with the target committed in a ``nonce`` tag. Any viewer verifies with one
hash and a walk over the vertices, and draws its default avatar instead for an
avatar that has not paid.

    required = ceil(10 + 2 log2(reach) + 1.5 log2(detail / 32))

``reach`` is the farthest vertex from the build origin in gibsons at true
scale (a model unit is 2^unit gibsons), never below one; ``detail`` is the
vertex count plus the face count, never below 32. The terms are summed and
the total rounded up once. The content is at most 131,072 bytes of UTF-8; a
reader draws the default avatar for a larger one. Only the committed target
is read from the nonce tag: a miner may vary the nonce anywhere, such as a
trailing ``nonce`` field of the payload. The same rule, constants and vectors
(the spec's avatar-vectors.json) as cyberspace-core's avatar.ts.

Until 2026-11 the floor was 16 bits and detail 3 bits per doubling; no shape
costs more now, so every avatar published before the change stays paid.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Union

AVATAR_FLOOR_BITS = 10
AVATAR_SIZE_BITS = 2
AVATAR_DETAIL_BITS = 1.5  # per doubling of detail beyond the free 32 (three per fourfold)
AVATAR_DETAIL_FREE = 32
AVATAR_CONTENT_MAX = 131072  # bytes of content, UTF-8
AVATAR_KIND = 11333  # replaceable; was 33331 before spec #26
_TICKS_PER_UNIT = 120


def _is_number(x: Any) -> bool:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False  # an integer too large for a float, which JSON.parse reads as Infinity


def unpack_ticks(packed: Optional[Sequence[Union[Sequence[int], int]]], count: int) -> List[List[int]]:
    """The ticks column unpacked to one triple per vertex; -N stands for N zero
    triples. Stops at ``count`` triples, so a huge run costs nothing."""
    out: List[List[int]] = []
    for item in packed or []:
        if len(out) >= count:
            break
        if _is_number(item):
            out.extend([[0, 0, 0]] * min(int(-item), count - len(out)))  # type: ignore[arg-type]
        else:
            out.append([item[a] if len(item) > a else 0 for a in range(3)])  # type: ignore[index,arg-type]
    while len(out) < count:
        out.append([0, 0, 0])
    return out[:count]


def avatar_readable(payload: Any) -> bool:
    """Whether the work can be read from a payload at all (spec 8.10: content a
    client cannot read is not an avatar): vertices a list of lists whose first
    three entries, where present, are numbers; ticks, where present, runs
    (whole numbers, zero or below) and such lists; faces, where present, a list."""
    if not isinstance(payload, dict) or not isinstance(payload.get("vertices"), list):
        return False
    def triple(v: Any) -> bool:
        return isinstance(v, list) and all(_is_number(x) for x in v[:3])
    if not all(triple(v) for v in payload["vertices"]):
        return False
    ticks = payload.get("ticks")
    if ticks is not None and not (isinstance(ticks, list) and all(
            (_is_number(t) and t <= 0 and t == int(t)) or triple(t) for t in ticks)):
        return False
    faces = payload.get("faces")
    return faces is None or isinstance(faces, list)


def avatar_reach(payload: Dict[str, Any]) -> float:
    """The farthest any vertex reaches from the build origin, in gibsons at true scale."""
    unit = payload.get("unit") if _is_number(payload.get("unit")) else 0
    vertices = payload["vertices"]
    ticks = unpack_ticks(payload.get("ticks"), len(vertices))
    reach = 0.0
    for i, v in enumerate(vertices):
        for a in range(3):
            reach = max(reach, abs((v[a] if len(v) > a else 0) + ticks[i][a] / _TICKS_PER_UNIT))
    try:
        return reach * (2.0 ** unit)
    except OverflowError:
        return math.inf  # a unit too large for a float: no work can pay for it


def avatar_detail(payload: Dict[str, Any]) -> int:
    """Vertices plus faces, before the free allowance."""
    return len(payload["vertices"]) + len(payload.get("faces") or [])


def avatar_bits(reach: float, detail: int) -> int:
    """The bits owed for a reach in gibsons and a detail: the terms summed, rounded up once."""
    r = max(1.0, reach)
    d = max(AVATAR_DETAIL_FREE, detail)
    raw = AVATAR_FLOOR_BITS + AVATAR_SIZE_BITS * math.log2(r) + AVATAR_DETAIL_BITS * math.log2(d / AVATAR_DETAIL_FREE)
    return raw if math.isinf(raw) else math.ceil(raw)  # type: ignore[return-value]


def avatar_work(payload: Dict[str, Any]) -> int:
    """The leading zero bits the avatar's event id must carry."""
    return avatar_bits(avatar_reach(payload), avatar_detail(payload))


def avatar_content_bytes(content: str) -> int:
    """The content's length as the limit counts it: UTF-8 bytes."""
    return len(content.encode("utf-8", errors="surrogatepass"))


def leading_zero_bits(hex_str: str) -> int:
    """Leading zero bits of a hex string, as NIP-13 counts them."""
    n = 0
    for ch in hex_str:
        try:
            nib = int(ch, 16)
        except ValueError:
            break
        if nib == 0:
            n += 4
            continue
        n += 4 - nib.bit_length()
        break
    return n


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def verify_avatar_work(event: Dict[str, Any]) -> Dict[str, Any]:
    """Whether an avatar event has paid for its shape (NIP-13): the content is
    within AVATAR_CONTENT_MAX (checked before parsing), the nonce tag's
    committed target covers what the shape owes, and the id carries at least
    the committed zeros. Returns ok, required, committed, zeros, reason; the
    reasons are not-an-avatar, too-large, no-nonce, under-committed, unpaid, ok."""
    zeros = leading_zero_bits(event.get("id", ""))
    if event.get("kind") != AVATAR_KIND:
        return {"ok": False, "required": 0, "committed": None, "zeros": zeros, "reason": "not-an-avatar"}
    content = event.get("content", "")
    if not isinstance(content, str):
        return {"ok": False, "required": 0, "committed": None, "zeros": zeros, "reason": "not-an-avatar"}
    if avatar_content_bytes(content) > AVATAR_CONTENT_MAX:
        return {"ok": False, "required": 0, "committed": None, "zeros": zeros, "reason": "too-large"}
    try:
        payload = json.loads(content, parse_constant=_refuse_constant)  # NaN and Infinity are not JSON
    except (ValueError, TypeError, RecursionError):
        return {"ok": False, "required": 0, "committed": None, "zeros": zeros, "reason": "not-an-avatar"}
    if not avatar_readable(payload):
        return {"ok": False, "required": 0, "committed": None, "zeros": zeros, "reason": "not-an-avatar"}
    required = avatar_work(payload)
    nonce = next((t for t in event.get("tags", []) if t and t[0] == "nonce"), None)
    committed = int(nonce[2]) if nonce and len(nonce) > 2 and re.fullmatch(r"[0-9]+", str(nonce[2])) else None
    if committed is None:
        return {"ok": False, "required": required, "committed": None, "zeros": zeros, "reason": "no-nonce"}
    if committed < required:
        return {"ok": False, "required": required, "committed": committed, "zeros": zeros, "reason": "under-committed"}
    if zeros < committed:
        return {"ok": False, "required": required, "committed": committed, "zeros": zeros, "reason": "unpaid"}
    return {"ok": True, "required": required, "committed": committed, "zeros": zeros, "reason": "ok"}
