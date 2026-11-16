"""What a reader checks on an avatar (spec 8.10), pinned to the spec's golden
vectors, fixtures/avatar-vectors.json, which cyberspace-core shares. The file
is copied unchanged from arkin0x/cyberspace (commit below); never edit it here.
An avatar carries no proof of work: no verdict reads a tag."""
import hashlib
import json
from pathlib import Path

import pytest

import cyberspace_core.avatar as avatar
from cyberspace_core.avatar import (
    AVATAR_CONTENT_MAX,
    AVATAR_CONTENT_WARN,
    AVATAR_KIND,
    avatar_reach,
    avatar_readable,
    leading_zero_bits,
    verify_avatar,
    verify_avatar_work,
)

RAW = (Path(__file__).parent / "fixtures" / "avatar-vectors.json").read_bytes()
SPEC_COMMIT = "938b1050320de6afce5d3646a1c2c06166744e02"  # branch of spec PR #109; re-pin to its merge commit
SHA256 = "22830c6e13ef4f259337197624ba52e8cdf96f5ef66449adb2386939ae84725f"
V = json.loads(RAW)


def content_of(e):
    if e["content"] is not None:
        return e["content"]
    r = e["content_recipe"]
    return r["prefix"] + r["fill"] * r["count"] + r["suffix"]


def test_the_vectors_are_the_spec_file_unchanged():
    assert hashlib.sha256(RAW).hexdigest() == SHA256


def test_constants():
    assert V["constants"] == {"kind": AVATAR_KIND, "content_max": AVATAR_CONTENT_MAX}
    assert AVATAR_CONTENT_WARN == 64000


@pytest.mark.parametrize("v", V["verdicts"], ids=[v["name"] for v in V["verdicts"]])
def test_verdicts(v):
    e = {**v["event"], "content": content_of(v["event"])}
    assert verify_avatar(e) == v["verdict"]
    assert verify_avatar({**e, "tags": []}) == v["verdict"]


@pytest.mark.parametrize("v", V["content_limit"], ids=[str(v["bytes"]) for v in V["content_limit"]])
def test_content_limit(v):
    prefix = '{"vertices":[[0,0,0]],"pad":"'
    body = '{"vertices":[[0,0,0]]}' if v["bytes"] < len(prefix) + 2 else prefix + "a" * (v["bytes"] - len(prefix) - 2) + '"}'
    assert (verify_avatar({"kind": AVATAR_KIND, "content": body})["reason"] == "too-large") == v["refused"]


@pytest.mark.parametrize("v", V["corpus"], ids=[v["name"] for v in V["corpus"]])
def test_corpus(v):
    assert (v["bytes"] > AVATAR_CONTENT_MAX) == v["refused"]


def test_limit_counts_utf8_bytes():
    prefix = '{"vertices":[[0,0,0]],"faces":[],"pad":"'
    body = prefix + "é" * ((AVATAR_CONTENT_MAX - len(prefix)) // 2 + 1) + '"}'
    assert len(body) < AVATAR_CONTENT_MAX
    assert verify_avatar({"kind": AVATAR_KIND, "content": body})["reason"] == "too-large"
    assert verify_avatar({"kind": AVATAR_KIND, "content": b"{}"})["reason"] == "not-an-avatar"


def test_verify_avatar_work_is_deprecated_and_never_checks_work():
    old = next(v for v in V["verdicts"] if v["name"].startswith("published before 2026-11"))
    with pytest.warns(DeprecationWarning):
        r = verify_avatar_work({**old["event"], "content": content_of(old["event"])})
    assert r == {"ok": True, "reason": "ok", "required": 0, "committed": 16, "zeros": 16}
    low = next(v for v in V["verdicts"] if v["name"].startswith("a nonce tag committing to more"))
    with pytest.warns(DeprecationWarning):
        assert verify_avatar_work({**low["event"], "content": content_of(low["event"])})["ok"]


def test_the_price_is_gone():
    for name in ("avatar_work", "avatar_bits", "AVATAR_FLOOR_BITS", "AVATAR_DETAIL_BITS"):
        assert not hasattr(avatar, name)


def test_reach_and_readable():
    assert avatar_reach({"unit": 0, "vertices": [[0, 0, 0], [-1, -1, -1]], "ticks": [[60, 60, 60], [60, 60, 60]]}) == pytest.approx(0.5)
    assert avatar_reach({"unit": 2, "vertices": [[4, 0, 0]]}) == 16
    assert avatar_reach({"vertices": [[3, 0, 0], [0, 0, 0]], "ticks": [-2]}) == 3
    assert avatar_readable({"vertices": [[0, 0, 0]]})
    for p in (None, [], {"vertices": "no"}, {"vertices": [None]}, {"vertices": [["x", 0, 0]]}, {"vertices": [[0, 0, 0]], "faces": 5}, {"vertices": [[0, 0, 0]], "ticks": [True]}):
        assert not avatar_readable(p)


def test_leading_zero_bits():
    assert leading_zero_bits("0000ffff") == 16
    assert leading_zero_bits("000f") == 12
    assert leading_zero_bits("1abc") == 3
    assert leading_zero_bits("") == 0
