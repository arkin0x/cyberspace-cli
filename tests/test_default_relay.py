"""The default anchor relay (2026-11-05 switch) and its one-time fallback to nostr1."""
from __future__ import annotations

from unittest.mock import patch

from cyberspace_cli import cli


def _event(height: int) -> dict:
    return {"id": f"{height:064x}", "kind": 321, "tags": [["B", str(height)]], "created_at": 0}


def _fetch(relay: str) -> list:
    return cli._nak_req_events(relay=relay, kind=321, tags={"B": ["974600"]}, limit=1)


def test_default_relay_is_the_new_canonical_relay() -> None:
    assert cli.DEFAULT_HYPERJUMP_RELAY == "wss://relay.onosendai.tech"
    assert cli.SECOND_HYPERJUMP_RELAY == "wss://cyberspace.nostr1.com"


def test_default_relay_with_events_asks_only_the_default() -> None:
    calls: list = []

    def once(*, relay, **_kw):
        calls.append(relay)
        return [_event(974600)]

    with patch.object(cli, "_nak_req_events_once", side_effect=once):
        assert _fetch(cli.DEFAULT_HYPERJUMP_RELAY) == [_event(974600)]
    assert calls == ["wss://relay.onosendai.tech"]


def test_default_relay_with_nothing_asks_nostr1_once() -> None:
    calls: list = []

    def once(*, relay, **_kw):
        calls.append(relay)
        return [_event(974600)] if relay == "wss://cyberspace.nostr1.com" else []

    with patch.object(cli, "_nak_req_events_once", side_effect=once):
        assert _fetch("wss://Relay.Onosendai.Tech/") == [_event(974600)]
    assert calls == ["wss://Relay.Onosendai.Tech/", "wss://cyberspace.nostr1.com"]


def test_a_named_relay_is_asked_alone() -> None:
    calls: list = []

    def once(*, relay, **_kw):
        calls.append(relay)
        return []

    with patch.object(cli, "_nak_req_events_once", side_effect=once):
        assert _fetch("wss://mine.example") == []
    assert calls == ["wss://mine.example"]
