"""The move command against a real HOSAKA API running in this process.

hosaka-api is started in a thread with in-process compute (HOSAKA_LOCAL_COMPUTE),
a fake wallet whose invoices settle when the test says so, and a temp
database. The CLI talks to it over HTTP exactly as it would to production.
The oracle for every appended proof is the CLI's own local computation.
"""

import asyncio
import contextlib
import hashlib
import os
import socket
import tempfile
import threading
import time
import unittest

try:
    import uvicorn
    import hosaka_api.main as api_main
    from hosaka_api.payments import Invoice, InvoiceStatus, set_wallet

    HAVE_API = True
except Exception:  # pragma: no cover
    HAVE_API = False

from typer.testing import CliRunner

from cyberspace_cli import chains, cloud_jobs
from cyberspace_cli.cli import app
from cyberspace_cli.config import CyberspaceConfig, save_config
from cyberspace_cli.nostr_event import make_spawn_event
from cyberspace_cli.nostr_keys import pubkey_hex_from_privkey
from cyberspace_cli.state import STATE_VERSION, CyberspaceState, save_state
from cyberspace_core.coords import xyz_to_coord
from cyberspace_core.movement import compute_hop_proof, compute_sidestep_proof

PRIVKEY_HEX = "5a" * 32
PUBKEY_HEX = pubkey_hex_from_privkey(bytes.fromhex(PRIVKEY_HEX))


class FakeWallet:
    def __init__(self):
        self.invoices = {}
        self.settled = {}
        self.calls = 0

    async def make_invoice(self, amount_msats, description, expiry_seconds):
        self.calls += 1
        ph = hashlib.sha256(f"{self.calls}:{description}".encode()).hexdigest()
        now = int(time.time())
        inv = Invoice(bolt11=f"lnbc-fake-{self.calls}", payment_hash=ph, amount_msats=amount_msats, created_at=now, expires_at=now + expiry_seconds)
        self.invoices[ph] = inv
        return inv

    def settle_all(self):
        for ph, inv in self.invoices.items():
            self.settled[ph] = inv.amount_msats

    async def lookup_invoice(self, payment_hash):
        inv = self.invoices[payment_hash]
        paid = self.settled.get(payment_hash)
        return InvoiceStatus(payment_hash=payment_hash, amount_msats=paid or inv.amount_msats, settled=paid is not None,
                             settled_at=int(time.time()) if paid is not None else None, preimage="ab" * 32 if paid is not None else None,
                             expires_at=inv.expires_at)

    async def get_balance_msats(self):
        return sum(self.settled.values())


class LocalHosaka:
    """hosaka-api in a thread, in-process compute, fake wallet."""

    def __init__(self, tmpdir: str, max_hop_height: int = 25):
        import hosaka_api.limits as limits
        import hosaka_api.routes.cantor as cantor
        import hosaka_api.routes.hop as hop
        from hosaka_api.mailbox import LocalMailbox, set_mailbox

        os.environ["HOSAKA_LOCAL_COMPUTE"] = "1"
        os.environ["HOSAKA_LOCAL_MAX_HEIGHT"] = "22"
        api_main._db_path = os.path.join(tmpdir, "hosaka.db")
        for name in list(vars(api_main)):
            if name.endswith("_store") and name.startswith("_"):
                setattr(api_main, name, None)
        roots = os.path.join(tmpdir, "cantor-roots")
        cantor.CANTOR_ROOTS_DIR = roots
        limits.CANTOR_ROOTS_DIR = roots
        hop.MAX_HOSAKA_HEIGHT = max_hop_height
        hop._hop_queue = None
        set_mailbox(LocalMailbox())
        self.wallet = FakeWallet()
        set_wallet(self.wallet)

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(api_main.app, host="127.0.0.1", port=self.port, log_level="warning", loop="asyncio")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("local HOSAKA did not start")

    def fund(self, pubkey: str, msats: int) -> None:
        api_main.get_balance_store().credit_deposit(pubkey, msats, f"seed-{pubkey[:8]}-{msats}")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        set_wallet(None)
        os.environ.pop("HOSAKA_LOCAL_COMPUTE", None)


def _setup_cli(td: str, x: int, y: int, z: int, api_url: str, max_lca: int = 16, mode: str = "auto", auto_max_sats: int = 1000):
    os.environ["CYBERSPACE_HOME"] = td
    label = "cloud"
    c0 = xyz_to_coord(x, y, z, plane=0).to_bytes(32, "big").hex()
    genesis = make_spawn_event(pubkey_hex=PUBKEY_HEX, created_at=1700000000, coord_hex=c0)
    chains.create_new_chain(label, genesis, overwrite=False)
    save_state(CyberspaceState(version=STATE_VERSION, privkey_hex=PRIVKEY_HEX, pubkey_hex=PUBKEY_HEX, coord_hex=c0,
                               active_chain_label=label, targets=[], active_target_label=""))
    cfg = CyberspaceConfig.default()
    cfg.default_max_lca_height = max_lca
    cfg.cloud_mode = mode
    cfg.cloud_api_url = api_url
    cfg.cloud_auto_max_sats = auto_max_sats
    save_config(cfg)
    return label, genesis


@unittest.skipUnless(HAVE_API, "hosaka-api not importable in this environment")
class TestMoveCloud(unittest.TestCase):
    def setUp(self):
        self._old_home = os.environ.get("CYBERSPACE_HOME")
        self._td = tempfile.TemporaryDirectory()
        self.runner = CliRunner()

    def tearDown(self):
        if getattr(self, "api", None):
            self.api.stop()
        self._td.cleanup()
        if self._old_home is None:
            os.environ.pop("CYBERSPACE_HOME", None)
        else:
            os.environ["CYBERSPACE_HOME"] = self._old_home

    def test_funded_cloud_hop_matches_local_proof(self):
        self.api = LocalHosaka(self._td.name)
        x, y, z = 1000, 2000, 3000
        label, genesis = _setup_cli(self._td.name, x, y, z, self.api.url, max_lca=8)
        self.api.fund(PUBKEY_HEX, 50_000)
        x2 = x + (1 << 9)  # h=10 > local ceiling 8: goes to the cloud

        r = self.runner.invoke(app, ["move", "--to", f"{x2},{y},{z}"], env={"CYBERSPACE_HOME": self._td.name})
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("HOSAKA cloud hop", r.output)
        self.assertIn("Verified cloud hop", r.output)
        self.assertIn("source: HOSAKA cloud job", r.output)

        events = chains.read_events(label)
        self.assertEqual(len(events), 2)
        ev = events[-1]
        tags = {t[0]: t[1:] for t in ev["tags"]}
        self.assertEqual(tags["A"][0], "hop")
        local = compute_hop_proof(x, y, z, x2, y, z, plane=0, previous_event_id_hex=genesis["id"], max_compute_height=12)
        self.assertEqual(tags["proof"][0], local.proof_hash)

        rec = cloud_jobs.all_jobs()
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["state"], "appended")
        self.assertEqual(rec[0]["event_id"], ev["id"])

    def test_unfunded_hop_pays_an_invoice_then_completes(self):
        self.api = LocalHosaka(self._td.name)
        x, y, z = 4096, 77, 77
        label, genesis = _setup_cli(self._td.name, x, y, z, self.api.url, max_lca=8)
        x2 = x + (1 << 10)  # h=11

        def settle_later():
            deadline = time.time() + 20
            while time.time() < deadline and not self.api.wallet.invoices:
                time.sleep(0.05)
            time.sleep(0.5)
            self.api.wallet.settle_all()

        t = threading.Thread(target=settle_later, daemon=True)
        t.start()
        r = self.runner.invoke(app, ["move", "--to", f"{x2},{y},{z}", "--cloud-yes"], env={"CYBERSPACE_HOME": self._td.name})
        t.join(timeout=30)
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("lnbc-fake-1", r.output)          # the invoice was shown
        self.assertIn("Paid. Starting the job.", r.output)
        ev = chains.read_events(label)[-1]
        local = compute_hop_proof(x, y, z, x2, y, z, plane=0, previous_event_id_hex=genesis["id"], max_compute_height=12)
        self.assertEqual({t[0]: t[1:] for t in ev["tags"]}["proof"][0], local.proof_hash)

    def test_toward_crosses_a_tall_wall_with_a_cloud_sidestep(self):
        # Server hop cap 10: the h=14 boundary needs a sidestep, landing 1 gibson past the wall.
        self.api = LocalHosaka(self._td.name, max_hop_height=10)
        x, y, z = (1 << 13) - 1, 5, 5
        label, genesis = _setup_cli(self._td.name, x, y, z, self.api.url, max_lca=8)
        self.api.fund(PUBKEY_HEX, 50_000)
        target_x = (1 << 13) + 3

        r = self.runner.invoke(app, ["move", "--toward", f"{target_x},{y},{z}"], env={"CYBERSPACE_HOME": self._td.name})
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("HOSAKA cloud sidestep", r.output)
        self.assertIn("Arrived.", r.output)

        events = chains.read_events(label)
        side = [e for e in events if {t[0]: t[1:] for t in e["tags"]}.get("A", [""])[0] == "sidestep"]
        self.assertEqual(len(side), 1)
        tags = {t[0]: t[1:] for t in side[0]["tags"]}
        self.assertEqual(tags["hx"][0], "14")
        local = compute_sidestep_proof(x, y, z, 1 << 13, y, z, plane=0, previous_event_id_hex=genesis["id"])
        self.assertEqual(tags["proof"][0], local.proof_hash)
        self.assertEqual(tags["mr"][0].split(":")[0], local.merkle_x.hex())
        self.assertEqual(tags["mp"][0].split(":")[0], "".join(s.hex() for s in local.inclusion_proofs["x"]))

    def test_no_cloud_keeps_the_refusal(self):
        self.api = LocalHosaka(self._td.name)
        x, y, z = 1000, 2000, 3000
        _setup_cli(self._td.name, x, y, z, self.api.url, max_lca=8)
        r = self.runner.invoke(app, ["move", "--to", f"{x + (1 << 9)},{y},{z}", "--no-cloud"], env={"CYBERSPACE_HOME": self._td.name})
        self.assertEqual(r.exit_code, 2)
        self.assertIn("Move is too large", r.output + str(r.stderr_bytes or b""))


if __name__ == "__main__":
    unittest.main()
