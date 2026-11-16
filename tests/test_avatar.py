"""The work an avatar owes (spec 8.10), pinned to the spec's golden vectors,
fixtures/avatar-vectors.json, which cyberspace-core shares. The file is copied
unchanged from arkin0x/cyberspace (commit below); never edit it here."""
import hashlib
import json
from pathlib import Path

import pytest

from cyberspace_core.avatar import (
    AVATAR_CONTENT_MAX,
    AVATAR_DETAIL_BITS,
    AVATAR_DETAIL_FREE,
    AVATAR_FLOOR_BITS,
    AVATAR_KIND,
    AVATAR_SIZE_BITS,
    avatar_bits,
    avatar_reach,
    avatar_work,
    leading_zero_bits,
    verify_avatar_work,
)

RAW = (Path(__file__).parent / "fixtures" / "avatar-vectors.json").read_bytes()
SPEC_COMMIT = "7dd2ce1559a5233acc49492a0b9c5d15680c1908"  # branch of spec PR #109; re-pin to its merge commit
SHA256 = "37d176493a1d304a3f2fcd9cf84b04e91a13a7a5bf5f8e639f73e983463fcbd5"
V = json.loads(RAW)


def content_of(e):
    if e["content"] is not None:
        return e["content"]
    r = e["content_recipe"]
    return r["prefix"] + r["fill"] * r["count"] + r["suffix"]


def test_the_vectors_are_the_spec_file_unchanged():
    assert hashlib.sha256(RAW).hexdigest() == SHA256


def test_constants():
    c = V["constants"]
    assert (c["kind"], c["floor_bits"], c["size_bits"], c["detail_bits"], c["detail_free"], c["content_max"]) == (
        AVATAR_KIND, AVATAR_FLOOR_BITS, AVATAR_SIZE_BITS, AVATAR_DETAIL_BITS, AVATAR_DETAIL_FREE, AVATAR_CONTENT_MAX)


@pytest.mark.parametrize("v", V["price"], ids=[v["name"] for v in V["price"]])
def test_price(v):
    assert avatar_reach(v["payload"]) == pytest.approx(v["reach"])
    assert avatar_work(v["payload"]) == v["required"]


@pytest.mark.parametrize("v", V["bits"], ids=[f"{v['reach']}-{v['detail']}" for v in V["bits"]])
def test_bits(v):
    assert avatar_bits(v["reach"], v["detail"]) == v["required"]
    assert v["required"] <= v["required_before_2026_11"]


@pytest.mark.parametrize("v", V["corpus"], ids=[v["name"] for v in V["corpus"]])
def test_corpus(v):
    assert avatar_bits(v["reach"], v["vertices"] + v["faces"]) == v["required"]
    assert (v["bytes"] > AVATAR_CONTENT_MAX) == v["refused"]


@pytest.mark.parametrize("v", V["verdicts"], ids=[v["name"] for v in V["verdicts"]])
def test_verdicts(v):
    e = {**v["event"], "content": content_of(v["event"])}
    assert verify_avatar_work(e) == v["verdict"]


@pytest.mark.parametrize("v", V["mined"], ids=[v["name"] for v in V["mined"]])
def test_mined_with_the_nonce_at_the_end(v):
    e = v["event"]
    ser = json.dumps([0, e["pubkey"], e["created_at"], e["kind"], e["tags"], e["content"]], separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(ser.encode()).hexdigest() == e["id"]
    assert verify_avatar_work(e) == v["verdict"]
    assert verify_avatar_work(e)["ok"]


def test_rounds_the_sum_once_and_the_ladder():
    assert avatar_bits(1.1, 40) == 11  # each term rounded up would make 12
    assert [avatar_bits(r, 32) for r in (1, 2, 4, 16, 1000)] == [10, 12, 14, 18, 30]


def test_limit_counts_utf8_bytes():
    prefix = '{"vertices":[[0,0,0]],"faces":[],"pad":"'
    body = prefix + "é" * ((AVATAR_CONTENT_MAX - len(prefix)) // 2 + 1) + '"}'
    assert len(body) < AVATAR_CONTENT_MAX
    ev = {"kind": AVATAR_KIND, "id": "0" * 64, "tags": [["nonce", "0", "10"]], "content": body}
    assert verify_avatar_work(ev)["reason"] == "too-large"


@pytest.mark.parametrize("v", V["content_limit"], ids=[str(v["bytes"]) for v in V["content_limit"]])
def test_content_limit(v):
    prefix = '{"vertices":[[0,0,0]],"pad":"'
    body = '{"vertices":[[0,0,0]]}' if v["bytes"] < len(prefix) + 2 else prefix + "a" * (v["bytes"] - len(prefix) - 2) + '"}'
    ev = {"kind": AVATAR_KIND, "id": "0" * 64, "tags": [["nonce", "0", "10"]], "content": body}
    assert (verify_avatar_work(ev)["reason"] == "too-large") == v["refused"]


def test_size_is_checked_before_parsing():
    ev = {"kind": AVATAR_KIND, "id": "0" * 64, "tags": [["nonce", "0", "10"]], "content": "x" * (AVATAR_CONTENT_MAX + 1)}
    assert verify_avatar_work(ev)["reason"] == "too-large"
    assert verify_avatar_work({**ev, "content": b"{}"})["reason"] == "not-an-avatar"


@pytest.mark.parametrize("body", [
    '{"vertices":[["x",0,0]]}', '{"vertices":[null]}', '{"vertices":[[0,0,0]],"faces":5}',
    '{"unit":"x","vertices":[[0,0,0]],"ticks":[-1.5]}', '{"vertices":[[Infinity,0,0]]}',
])
def test_unreadable_payloads_return_a_verdict(body):
    ev = {"kind": AVATAR_KIND, "id": "0" * 64, "tags": [["nonce", "0", "0"]], "content": body}
    assert verify_avatar_work(ev)["reason"] == "not-an-avatar"


def test_huge_unit_is_never_paid():
    ev = {"kind": AVATAR_KIND, "id": "0" * 64, "tags": [["nonce", "0", "64"]], "content": '{"unit":2000,"vertices":[[1,0,0]]}'}
    assert verify_avatar_work(ev)["reason"] == "under-committed"


def test_leading_zero_bits():
    assert leading_zero_bits("0000ffff") == 16
    assert leading_zero_bits("000f") == 12
    assert leading_zero_bits("1abc") == 3
    assert leading_zero_bits("") == 0
