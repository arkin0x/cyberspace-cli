"""The bag's height tag is `H`, read with a fallback to a legacy `h` (spec section 8.6).

NIP-29 reads `h` on an event of any kind as a group id, so cyberspace stopped
writing it on 2026-10-21. Readers still accept `h` on bags published before.
"""

import json
import os
import tempfile
import unittest

from typer.testing import CliRunner

from cyberspace_cli.cli import app
from cyberspace_cli.nostr_event import height_from_tags, make_encrypted_content_event

from test_encrypt_cli import _setup_min_state

BASE = [["d", "aa" * 32], ["encrypted", "aes-256-gcm", "Zm9v"], ["version", "2"]]


def tags(*height):
    return BASE + [list(t) for t in height]


class TestHeightFromTags(unittest.TestCase):
    def test_reads_H(self) -> None:
        self.assertEqual(height_from_tags(tags(["H", "6"])), 6)

    def test_reads_legacy_h_without_H(self) -> None:
        self.assertEqual(height_from_tags(tags(["h", "7"])), 7)

    def test_H_wins_when_both_are_present(self) -> None:
        self.assertEqual(height_from_tags(tags(["h", "7"], ["H", "6"])), 6)
        self.assertEqual(height_from_tags(tags(["H", "6"], ["h", "7"])), 6)
        # H wins even when it is malformed: the bag then states no height.
        self.assertIsNone(height_from_tags(tags(["H", "06"], ["h", "7"])))
        self.assertIsNone(height_from_tags(tags(["H"], ["h", "7"])))

    def test_none_when_neither(self) -> None:
        self.assertIsNone(height_from_tags(tags()))
        self.assertIsNone(height_from_tags(None))

    def test_none_when_duplicated_or_malformed(self) -> None:
        self.assertIsNone(height_from_tags(tags(["H", "6"], ["H", "6"])))
        self.assertIsNone(height_from_tags(tags(["h", "7"], ["h", "7"])))
        for bad in ["", "+3", "-1", "03", "1.0", "x", " 4"]:
            self.assertIsNone(height_from_tags(tags(["H", bad])), bad)


class TestWriter(unittest.TestCase):
    def test_writes_H_never_h(self) -> None:
        ev = make_encrypted_content_event(
            pubkey_hex="11" * 32, created_at=1, lookup_id_hex="aa" * 32,
            algorithm="aes-256-gcm", ciphertext_b64="Zm9v", height_hint=9,
        )
        self.assertIn(["H", "9"], ev["tags"])
        self.assertFalse(any(t[0] == "h" for t in ev["tags"]))

    def test_writes_neither_without_a_height(self) -> None:
        ev = make_encrypted_content_event(
            pubkey_hex="11" * 32, created_at=1, lookup_id_hex="aa" * 32,
            algorithm="aes-256-gcm", ciphertext_b64="Zm9v",
        )
        self.assertFalse(any(t[0] in ("H", "h") for t in ev["tags"]))


class TestDecryptReadsTheHeightTag(unittest.TestCase):
    """`--max-height 0` scans only height 0, so a height-4 bag opens only if its tag was read."""

    def setUp(self) -> None:
        self.runner = CliRunner()
        self.old_home = os.environ.get("CYBERSPACE_HOME")
        self.td = tempfile.TemporaryDirectory()
        os.environ["CYBERSPACE_HOME"] = self.td.name
        _setup_min_state(self.td.name)
        enc = self.runner.invoke(app, ["encrypt", "--text", "under the bridge", "--height", "4", "--publish-height"])
        self.assertEqual(enc.exit_code, 0, msg=enc.output)
        self.event = json.loads(enc.output.strip().splitlines()[-1].strip())

    def tearDown(self) -> None:
        self.td.cleanup()
        if self.old_home is None:
            os.environ.pop("CYBERSPACE_HOME", None)
        else:
            os.environ["CYBERSPACE_HOME"] = self.old_home

    def decrypt_with(self, *height):
        ev = dict(self.event)
        ev["tags"] = [t for t in ev["tags"] if t[0] not in ("H", "h")] + [list(t) for t in height]
        return self.runner.invoke(app, ["decrypt", "--event-json", json.dumps(ev), "--max-height", "0"])

    def test_H(self) -> None:
        res = self.decrypt_with(["H", "4"])
        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn("height: 4", res.output)

    def test_legacy_h(self) -> None:
        res = self.decrypt_with(["h", "4"])
        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn("height: 4", res.output)

    def test_both_H_wins(self) -> None:
        self.assertEqual(self.decrypt_with(["h", "9"], ["H", "4"]).exit_code, 0)
        # A malformed H still wins, so the correct h is ignored and the scan finds nothing.
        self.assertEqual(self.decrypt_with(["H", "04"], ["h", "4"]).exit_code, 1)

    def test_neither_falls_back_to_the_scan(self) -> None:
        self.assertEqual(self.decrypt_with().exit_code, 1)
        res = self.runner.invoke(app, ["decrypt", "--event-json", json.dumps({**self.event, "tags": [t for t in self.event["tags"] if t[0] != "H"]}), "--max-height", "8"])
        self.assertEqual(res.exit_code, 0, msg=res.output)
        self.assertIn("height: 4", res.output)


if __name__ == "__main__":
    unittest.main()
