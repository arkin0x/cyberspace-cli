import json
import os
import tempfile
import unittest

from typer.testing import CliRunner

from cyberspace_cli import chains
from cyberspace_cli.cli import app
from cyberspace_cli.nostr_event import make_spawn_event
from cyberspace_cli.state import CyberspaceState, STATE_VERSION, save_state
from cyberspace_core.coords import xyz_to_coord

def _tag_value(event: dict, key: str):
    for t in event.get("tags", []):
        if isinstance(t, list) and len(t) >= 2 and t[0] == key:
            return t
    return None


def _setup_min_state(td: str) -> None:
    label = "t"
    pubkey_hex = "11" * 32
    privkey_hex = "22" * 32
    c0 = xyz_to_coord(0, 0, 0, plane=0).to_bytes(32, "big").hex()
    genesis = make_spawn_event(pubkey_hex=pubkey_hex, created_at=1700000000, coord_hex=c0)
    chains.create_new_chain(label, genesis, overwrite=False)
    save_state(
        CyberspaceState(
            version=STATE_VERSION,
            privkey_hex=privkey_hex,
            pubkey_hex=pubkey_hex,
            coord_hex=c0,
            active_chain_label=label,
            targets=[],
            active_target_label="",
        )
    )


class TestEncryptDecryptScanCLI(unittest.TestCase):
    def test_encrypt_decrypt_scan_roundtrip(self) -> None:
        runner = CliRunner()
        old_home = os.environ.get("CYBERSPACE_HOME")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["CYBERSPACE_HOME"] = td
                _setup_min_state(td)

                message = "hello ciphertext world"
                enc = runner.invoke(app, ["encrypt", "--text", message, "--height", "4"])
                self.assertEqual(enc.exit_code, 0, msg=enc.output)

                event_json = enc.output.strip().splitlines()[-1].strip()
                event = json.loads(event_json)
                self.assertEqual(event.get("kind"), 33334)
                self.assertEqual(event.get("content"), "")
                encrypted_tag = _tag_value(event, "encrypted")
                self.assertIsNotNone(encrypted_tag)
                self.assertEqual(encrypted_tag[1], "aes-256-gcm")
                self.assertEqual(_tag_value(event, "version")[1], "2")
                self.assertIsNone(_tag_value(event, "h"))

                dec = runner.invoke(app, ["decrypt", "--event-json", event_json])
                self.assertEqual(dec.exit_code, 0, msg=dec.output)
                self.assertIn(message, dec.output)

                enc2 = runner.invoke(
                    app,
                    ["encrypt", "--text", message, "--height", "4", "--publish-height"],
                )
                self.assertEqual(enc2.exit_code, 0, msg=enc2.output)
                event2 = json.loads(enc2.output.strip().splitlines()[-1].strip())
                self.assertEqual(_tag_value(event2, "h")[1], "4")

                events_jsonl = os.path.join(td, "events.jsonl")
                with open(events_jsonl, "w", encoding="utf-8") as f:
                    f.write(event_json + "\n")

                scn = runner.invoke(app, ["scan", "--min-height", "1", "--max-height", "8", "--events-file", events_jsonl])
                self.assertEqual(scn.exit_code, 0, msg=scn.output)
                self.assertIn("matches=1", scn.output)
        finally:
            if old_home is None:
                os.environ.pop("CYBERSPACE_HOME", None)
            else:
                os.environ["CYBERSPACE_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
