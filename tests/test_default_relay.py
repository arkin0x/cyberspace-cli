"""The default anchor relay (2026-11-05 switch): its fallback to nostr1, a named relay asked alone, and sync paging."""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import List
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cyberspace_cli import cli

NEW = "wss://relay.onosendai.tech"
OLD = "wss://cyberspace.nostr1.com"
runner = CliRunner()


def _event(height: int, created_at: int = 0) -> dict:
    return {"id": f"{height:064x}", "kind": 321, "tags": [["B", str(height)]], "created_at": created_at}


def _fetch(relay) -> list:
    return cli._nak_req_events(relay=relay, kind=321, tags={"B": ["974600"]}, limit=1)


def test_default_relay_is_the_new_canonical_relay() -> None:
    assert cli.DEFAULT_HYPERJUMP_RELAY == NEW
    assert cli.SECOND_HYPERJUMP_RELAY == OLD


def test_no_relay_given_with_events_asks_only_the_default() -> None:
    calls: list = []

    def once(*, relay, **_kw):
        calls.append(relay)
        return [_event(974600)]

    with patch.object(cli, "_nak_req_events_once", side_effect=once):
        assert _fetch(None) == [_event(974600)]
    assert calls == [NEW]


def test_no_relay_given_and_nothing_on_the_default_asks_nostr1_once() -> None:
    calls: list = []

    def once(*, relay, **_kw):
        calls.append(relay)
        return [_event(974600)] if relay == OLD else []

    with patch.object(cli, "_nak_req_events_once", side_effect=once):
        assert _fetch(None) == [_event(974600)]
    assert calls == [NEW, OLD]


@pytest.mark.parametrize("named", ["wss://mine.example", NEW, "wss://Relay.Onosendai.Tech/"])
def test_a_named_relay_is_asked_alone_even_the_default_one(named: str) -> None:
    calls: list = []

    def once(*, relay, **_kw):
        calls.append(relay)
        return []

    with patch.object(cli, "_nak_req_events_once", side_effect=once):
        assert _fetch(named) == []
    assert calls == [named]


def _nak_result(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["nak"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_an_unreachable_default_relay_falls_back_to_nostr1() -> None:
    """nak exits 3 when it cannot reach the relay."""
    import json

    asked: list = []

    def run(cmd, **_kw):
        asked.append(cmd[-1])
        if cmd[-1] == NEW:
            return _nak_result(3, stderr="failed to connect to wss://relay.onosendai.tech")
        return _nak_result(0, stdout=json.dumps(_event(974600)) + "\n")

    with patch.object(cli.subprocess, "run", side_effect=run):
        assert _fetch(None) == [_event(974600)]
    assert asked == [NEW, OLD]


def test_an_unreachable_named_relay_fails_without_asking_another() -> None:
    import typer

    asked: list = []

    def run(cmd, **_kw):
        asked.append(cmd[-1])
        return _nak_result(3, stderr="failed to connect")

    with patch.object(cli.subprocess, "run", side_effect=run):
        with pytest.raises(typer.Exit):
            _fetch(NEW)
    assert asked == [NEW]


def test_the_command_line_tells_a_named_default_relay_from_none() -> None:
    calls: list = []

    def once(*, relay, **_kw):
        calls.append(relay)
        return []

    with patch.object(cli, "_nak_req_events_once", side_effect=once):
        runner.invoke(cli.app, ["hyperjump", "show", "974600"])
        assert calls == [NEW, OLD]
        calls.clear()
        runner.invoke(cli.app, ["hyperjump", "show", "974600", "--relay", NEW])
        assert calls == [NEW]


# ---------- hyperjump sync paging ----------

def _shared_seconds(n_seconds: int = 12, per_second: int = 3, start: int = 1_000) -> List[dict]:
    """Anchors that share seconds, as they do on the relays (several per second)."""
    out = []
    h = 0
    for s in range(n_seconds):
        for _ in range(per_second):
            out.append(_event(h, start + s))
            h += 1
    return out


def _fake_relay(events: List[dict], *, inclusive: bool, cap: int):
    """A relay answering newest first, `until` inclusive (NIP-01) or exclusive, at most `cap` events."""
    ordered = sorted(events, key=lambda e: (-e["created_at"], e["id"]))

    def once(*, relay, limit, until=None, **_kw):
        if relay != NEW:
            return []
        if until is None:
            hits = ordered
        else:
            hits = [e for e in ordered if (e["created_at"] <= until if inclusive else e["created_at"] < until)]
        return hits[: min(limit, cap)]

    return once


def _sync(events: List[dict], *, inclusive: bool, cap: int, limit: int) -> List[dict]:
    seen: List[dict] = []

    def capture(evs, **_kw):
        seen.extend(evs)
        return {}

    old_home = os.environ.get("CYBERSPACE_HOME")
    with tempfile.TemporaryDirectory() as home:
        os.environ["CYBERSPACE_HOME"] = home
        try:
            with patch.object(cli, "_nak_req_events_once", side_effect=_fake_relay(events, inclusive=inclusive, cap=cap)), \
                 patch.object(cli, "_dedup_hyperjumps", side_effect=capture):
                result = runner.invoke(cli.app, ["hyperjump", "sync", "--limit", str(limit)])
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home
    assert result.exit_code == 0, result.output
    return seen


@pytest.mark.parametrize("inclusive", [True, False], ids=["until-inclusive", "until-exclusive"])
@pytest.mark.parametrize("limit", [4, 5, 7])
def test_sync_loses_no_anchor_at_a_page_boundary_second(inclusive: bool, limit: int) -> None:
    events = _shared_seconds()
    got = _sync(events, inclusive=inclusive, cap=limit, limit=limit)
    assert sorted(e["id"] for e in got) == sorted(e["id"] for e in events)
    assert len({e["id"] for e in got}) == len(got)


@pytest.mark.parametrize("inclusive", [True, False], ids=["until-inclusive", "until-exclusive"])
def test_sync_goes_on_past_a_relay_that_caps_the_limit(inclusive: bool) -> None:
    events = _shared_seconds()
    got = _sync(events, inclusive=inclusive, cap=5, limit=10_000)
    assert sorted(e["id"] for e in got) == sorted(e["id"] for e in events)


def test_next_sync_until_never_rises_and_always_ends() -> None:
    assert cli._next_sync_until(None, 100, True) == 101
    assert cli._next_sync_until(101, 100, True) == 101
    assert cli._next_sync_until(101, 100, False) == 100
    assert cli._next_sync_until(100, 100, False) == 99
    assert cli._next_sync_until(100, 101, False) is None
