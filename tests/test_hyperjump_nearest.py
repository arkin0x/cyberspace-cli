"""Tests for improved hyperjump nearest command (expand, cache, count)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from cyberspace_cli.cli import app

runner = CliRunner()


def _setup_min_state(coord_hex: str = "0" * 64) -> None:
    """Write a minimal state.json into the temp CYBERSPACE_HOME."""
    from cyberspace_cli.paths import cyberspace_home
    home = cyberspace_home()
    home.mkdir(parents=True, exist_ok=True)
    state_file = home / "state.json"
    state_file.write_text(json.dumps({
        "version": 2,
        "privkey_nsec": "nsec1" + "a" * 58,
        "pubkey_hex": "aa" * 32,
        "coord_hex": coord_hex,
        "chain_label": "test",
    }))
    chains_dir = home / "chains"
    chains_dir.mkdir(exist_ok=True)
    (chains_dir / "test.jsonl").write_text("")


def _make_hyperjump_event(coord_hex: str, block_height: int = 1, event_id: str = "abcd" * 16) -> dict:
    """Create a minimal hyperjump anchor event."""
    return {
        "kind": 321,
        "id": event_id,
        "pubkey": "bb" * 32,
        "created_at": 1700000000,
        "tags": [
            ["A", "hyperjump"],
            ["B", str(block_height)],
            ["C", coord_hex],
            ["X", "0"],
            ["Y", "0"],
            ["Z", "0"],
        ],
        "content": "",
    }


class TestHyperjumpNearestExpand(unittest.TestCase):
    """Test --expand flag for progressive radius expansion."""

    def test_expand_finds_hyperjump(self) -> None:
        """--expand should try increasing radii until it finds something."""
        # Return empty for first few radii, then return a result.
        call_count = [0]

        def mock_nak_req_events(*, relay, kind, tags, limit, timeout_seconds=20, verbose=False):
            call_count[0] += 1
            if call_count[0] < 3:
                return []
            return [_make_hyperjump_event("0" * 64)]

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()
                with patch("cyberspace_cli.cli._nak_req_events", side_effect=mock_nak_req_events):
                    res = runner.invoke(app, ["hyperjump", "nearest", "--expand"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("nearby_hyperjumps: 1", res.output)
                self.assertIn("search_radius=", res.output)
                self.assertGreaterEqual(call_count[0], 3)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_expand_no_results(self) -> None:
        """--expand with no hyperjumps anywhere should print guidance."""
        def mock_nak_req_events(*, relay, kind, tags, limit, timeout_seconds=20, verbose=False):
            return []

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()
                with patch("cyberspace_cli.cli._nak_req_events", side_effect=mock_nak_req_events):
                    res = runner.invoke(app, ["hyperjump", "nearest", "--expand"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("No hyperjumps found", res.output)
                self.assertIn("hyperjump sync", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


class TestHyperjumpNearestCache(unittest.TestCase):
    """Test --cache flag for local cache search."""

    def test_cache_no_file(self) -> None:
        """--cache with no sync should error."""
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()
                res = runner.invoke(app, ["hyperjump", "nearest", "--cache"])
                self.assertEqual(res.exit_code, 1, msg=res.output)
                self.assertIn("hyperjump sync", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_cache_with_data(self) -> None:
        """--cache should read from local JSONL file."""
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()
                # Write a cache file
                from cyberspace_cli.paths import hyperjump_cache_path
                cache = hyperjump_cache_path()
                cache.parent.mkdir(parents=True, exist_ok=True)
                ev = _make_hyperjump_event("0" * 64)
                cache.write_text(json.dumps(ev) + "\n")

                res = runner.invoke(app, ["hyperjump", "nearest", "--cache"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("nearby_hyperjumps: 1", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


class TestHyperjumpNearestCount(unittest.TestCase):
    """Test --count flag for limiting results."""

    def test_count_limits_output(self) -> None:
        """--count should limit the number of displayed results."""
        events = [
            _make_hyperjump_event("0" * 64, event_id="aa" * 32),
            _make_hyperjump_event("0" * 63 + "1", event_id="bb" * 32),
            _make_hyperjump_event("0" * 63 + "2", event_id="cc" * 32),
        ]

        def mock_nak_req_events(*, relay, kind, tags, limit, timeout_seconds=20, verbose=False):
            return events

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state()
                with patch("cyberspace_cli.cli._nak_req_events", side_effect=mock_nak_req_events):
                    res = runner.invoke(app, ["hyperjump", "nearest", "--count", "1"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                # Should show 1 result but report total count
                self.assertIn("1. id=", res.output)
                self.assertNotIn("2. id=", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


class TestHyperjumpSync(unittest.TestCase):
    """Test hyperjump sync command."""

    def test_sync_creates_cache(self) -> None:
        """sync should write events to the cache file."""
        events = [_make_hyperjump_event("0" * 64)]

        def mock_nak_req_events(*, relay, kind, tags, limit, timeout_seconds=20, verbose=False):
            return events

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                with patch("cyberspace_cli.cli._nak_req_events", side_effect=mock_nak_req_events):
                    res = runner.invoke(app, ["hyperjump", "sync"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("Cached 1 unique hyperjump", res.output)
                from cyberspace_cli.paths import hyperjump_cache_path
                self.assertTrue(hyperjump_cache_path().exists())
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home

    def test_sync_no_events(self) -> None:
        """sync with empty relay should print message."""
        def mock_nak_req_events(*, relay, kind, tags, limit, timeout_seconds=20, verbose=False):
            return []

        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                with patch("cyberspace_cli.cli._nak_req_events", side_effect=mock_nak_req_events):
                    res = runner.invoke(app, ["hyperjump", "sync"])
                self.assertEqual(res.exit_code, 0, msg=res.output)
                self.assertIn("No hyperjump events found", res.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
