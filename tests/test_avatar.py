"""The work an avatar owes, pinned to fixtures/avatar_work.json shared with cyberspace-core."""
import json
from pathlib import Path

import pytest

from cyberspace_core.avatar import AVATAR_KIND, avatar_reach, avatar_work, leading_zero_bits, verify_avatar_work

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "avatar_work.json").read_text())


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_price_matches_the_vectors(v):
    assert avatar_reach(v["payload"]) == pytest.approx(v["reach"])
    assert avatar_work(v["payload"]) == v["required"]


def test_leading_zero_bits():
    assert leading_zero_bits("0000ffff") == 16
    assert leading_zero_bits("000f") == 12
    assert leading_zero_bits("1abc") == 3
    assert leading_zero_bits("") == 0


def test_verdicts():
    payload = next(v for v in VECTORS if v["name"] == "one gibson, plain")["payload"]
    content = json.dumps(payload)
    def ev(zeros, committed, kind=AVATAR_KIND, body=content):
        tags = [["d", "avatar"]] + ([["nonce", "1", str(committed)]] if committed is not None else [])
        return {"kind": kind, "id": "0" * (zeros // 4) + "f" * (64 - zeros // 4), "tags": tags, "content": body}
    assert verify_avatar_work(ev(16, 16))["ok"]
    assert verify_avatar_work(ev(20, 16))["ok"]
    assert verify_avatar_work(ev(16, 20))["reason"] == "unpaid"
    assert verify_avatar_work(ev(20, 12))["reason"] == "under-committed"
    assert verify_avatar_work(ev(20, None))["reason"] == "no-nonce"
    assert verify_avatar_work(ev(20, 16, kind=1))["reason"] == "not-an-avatar"
    assert verify_avatar_work(ev(20, 16, body="junk"))["reason"] == "not-an-avatar"
