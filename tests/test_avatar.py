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
SPEC_COMMIT = "9caa0c4"
SHA256 = "8ba4852221e3ebb8a4f88d63c1ce36cba959e250b691cc2a212f27393760b955"
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
    assert avatar_bits(1.5, 48) == 13
    assert [avatar_bits(r, 32) for r in (1, 2, 4, 16, 1000)] == [10, 12, 14, 18, 30]


def test_limit_counts_utf8_bytes():
    prefix = '{"vertices":[[0,0,0]],"faces":[],"pad":"'
    body = prefix + "é" * ((AVATAR_CONTENT_MAX - len(prefix)) // 2 + 1) + '"}'
    assert len(body) < AVATAR_CONTENT_MAX
    ev = {"kind": AVATAR_KIND, "id": "0" * 64, "tags": [["nonce", "0", "10"]], "content": body}
    assert verify_avatar_work(ev)["reason"] == "too-large"


def test_leading_zero_bits():
    assert leading_zero_bits("0000ffff") == 16
    assert leading_zero_bits("000f") == 12
    assert leading_zero_bits("1abc") == 3
    assert leading_zero_bits("") == 0
