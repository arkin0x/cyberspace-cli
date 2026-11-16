"""What a reader checks on an avatar (kind 11333, spec 8.10).

An avatar carries no proof of work (owner ruling 2026-11-16). A reader draws
it when its content is within AVATAR_CONTENT_MAX bytes of UTF-8 and holds a
payload the reader can read, and draws its default avatar otherwise. A
``nonce`` tag, which avatars published before 2026-11 carry, is ignored: no
verdict reads a tag. The same rule and vectors (the spec's avatar-vectors.json)
as cyberspace-core's avatar.ts.

Until 2026-11 an avatar paid NIP-13 work priced by its reach and detail; a
miner that varies the end of the content made that price meaningless, so it
was dropped. ``verify_avatar_work`` stays as a deprecated alias of
``verify_avatar`` that never checks work.
"""
from __future__ import annotations

import json
import math
import re
import warnings
from typing import Any, Dict, List, Optional, Sequence, Union

AVATAR_CONTENT_MAX = 131072  # bytes of content, UTF-8 (128 KiB)
AVATAR_CONTENT_WARN = 64000  # a publishing client warns above this: some NIP-46 signers refuse
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
    if reach == 0:
        return 0.0
    try:
        return reach * (2.0 ** unit)
    except OverflowError:
        return math.inf  # a unit too large for a float: no work can pay for it


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


def verify_avatar(event: Dict[str, Any]) -> Dict[str, Any]:
    """Whether a reader draws this avatar event (spec 8.10): the kind is 11333,
    the content is within AVATAR_CONTENT_MAX (checked before parsing) and holds
    a readable payload. Tags are not read. Returns ok and reason: ok,
    not-an-avatar or too-large. Empty content is the default avatar, the
    caller's to handle first; here it is not-an-avatar."""
    if event.get("kind") != AVATAR_KIND:
        return {"ok": False, "reason": "not-an-avatar"}
    content = event.get("content", "")
    if not isinstance(content, str):
        return {"ok": False, "reason": "not-an-avatar"}
    if avatar_content_bytes(content) > AVATAR_CONTENT_MAX:
        return {"ok": False, "reason": "too-large"}
    try:
        # NaN and Infinity are not JSON; integers read as floats, as JSON.parse reads them.
        payload = json.loads(content, parse_constant=_refuse_constant, parse_int=float)
    except (ValueError, TypeError, RecursionError):
        return {"ok": False, "reason": "not-an-avatar"}
    if not avatar_readable(payload):
        return {"ok": False, "reason": "not-an-avatar"}
    return {"ok": True, "reason": "ok"}


def verify_avatar_work(event: Dict[str, Any]) -> Dict[str, Any]:
    """Deprecated: an avatar carries no proof of work. verify_avatar's verdict,
    with required always 0 and the nonce tag's target and the id's zeros for
    display only; work is never checked."""
    warnings.warn("verify_avatar_work is deprecated: avatars carry no proof of work; use verify_avatar", DeprecationWarning, stacklevel=2)
    tags = event.get("tags")
    tags = tags if isinstance(tags, list) else []
    nonce = next((t for t in tags if isinstance(t, list) and t and t[0] == "nonce"), None)
    target = nonce[2] if nonce and len(nonce) > 2 else None
    committed = int(target) if isinstance(target, str) and re.fullmatch(r"[0-9]{1,15}", target) else None
    ident = event.get("id")
    return {**verify_avatar(event), "required": 0, "committed": committed, "zeros": leading_zero_bits(ident) if isinstance(ident, str) else 0}
