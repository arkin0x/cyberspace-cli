"""HOSAKA cloud compute integration via the encapsulated /api/v1/hop endpoint.

When a hop's max-axis LCA height exceeds the local compute limit, the CLI
delegates the entire §4.7 + §5 hop pipeline to HOSAKA. The server runs the
three per-axis Cantor jobs in parallel, composes region_n, derives K and
cantor_t, composes hop_n, and returns the canonical file envelope. The CLI
takes ``result.hop_n.public_proof`` as the §5.6 proof_hash for the Nostr
hop event — no local Cantor work is required.

Key boundary: the user's nsec NEVER leaves this module. nostr_signer
produces NIP-98 auth headers and signed zap events from a private key
held in CLI state; this module only forwards finished headers/events.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, Optional

import nest_asyncio

nest_asyncio.apply()

from cyberspace_cli.nostr_event import create_zap_request
from cyberspace_cli.nostr_signer import sign_event, sign_nip98_request

try:
    import httpx
    from hosaka_client import display_qr_terminal
    HAS_HOSAKA = True
except ImportError:
    HAS_HOSAKA = False


HOSAKA_API_URL = os.environ.get(
    "HOSAKA_API_URL",
    "https://arkin0x--hosaka-api-api-server.modal.run",
)

# Recipient pubkey for zap payments. Override only for testing against a
# different LNURL identity.
HOSAKA_RECIPIENT_PUBKEY = os.environ.get(
    "HOSAKA_RECIPIENT_PUBKEY",
    "e8ed3798c6ffebffa08501ac39e271662bfd160f688f94c45d692d8767dd345a",
)


def _auth_headers(privkey_hex: str, pubkey_hex: str, url: str, method: str) -> Dict[str, str]:
    """Build a NIP-98 Authorization header for one HOSAKA request."""
    return {
        "Authorization": sign_nip98_request(
            privkey_hex=privkey_hex,
            pubkey_hex=pubkey_hex,
            url=url,
            method=method,
        )
    }


class HosakaClient:
    """Thin async HTTP wrapper. Stateless: all auth is per-request."""

    def __init__(self, api_url: str = HOSAKA_API_URL, timeout: float = 300.0):
        self.api_url = api_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.api_url, timeout=timeout)

    async def __aenter__(self) -> "HosakaClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.http.aclose()

    async def submit_hop(
        self,
        v1: Dict[str, int],
        v2: Dict[str, int],
        previous_event_id: str,
        auth: Dict[str, str],
    ) -> Dict[str, Any]:
        url = f"{self.api_url}/api/v1/hop"
        resp = await self.http.post(
            url,
            json={"v1": v1, "v2": v2, "previous_event_id": previous_event_id},
            headers=auth,
        )
        if resp.status_code == 400:
            detail = resp.json().get("detail", {})
            if isinstance(detail, dict) and detail.get("error") == "height_exceeds_hosaka_cap":
                raise CloudHeightExceeded(detail)
            raise RuntimeError(f"HOSAKA API error: {detail}")
        resp.raise_for_status()
        return resp.json()

    async def get_job(self, job_id: str, auth: Dict[str, str]) -> Dict[str, Any]:
        resp = await self.http.get(f"{self.api_url}/api/v1/jobs/{job_id}", headers=auth)
        resp.raise_for_status()
        return resp.json()

    async def poll_job(
        self,
        job_id: str,
        privkey_hex: str,
        pubkey_hex: str,
        timeout: int = 3600,
        interval: int = 20,
    ) -> Dict[str, Any]:
        """Poll /jobs/{id} until status is terminal. Each poll signs a fresh header."""
        import typer

        start = time.time()
        n = 0
        url = f"{self.api_url}/api/v1/jobs/{job_id}"
        while True:
            n += 1
            elapsed = int(time.time() - start)
            typer.echo(f"   [Poll {n}, {elapsed}s] checking job…")
            auth = _auth_headers(privkey_hex, pubkey_hex, url, "GET")
            job = await self.get_job(job_id, auth)
            status = job.get("status", "unknown")
            typer.echo(f"   status={status}")
            if status in ("completed", "failed"):
                return job
            if time.time() - start > timeout:
                raise TimeoutError(f"job {job_id} did not complete in {timeout}s")
            await asyncio.sleep(interval)


class CloudHeightExceeded(Exception):
    """Raised when /api/v1/hop refuses a height above MAX_HOSAKA_HEIGHT."""

    def __init__(self, detail: Dict[str, Any]):
        self.detail = detail
        super().__init__(detail.get("hint") or "height exceeds HOSAKA cap")


async def _run_payment_flow(
    job: Dict[str, Any],
    privkey_hex: str,
    pubkey_hex: str,
    api_url: str,
) -> None:
    """Pay the LNURL invoice referenced by ``job`` and redeem the receipt.

    Mutates HOSAKA balance state so a subsequent /jobs/{id} poll observes a
    debited (and therefore computing) job. Raises typer.Exit on payment
    timeout or any LNURL failure.
    """
    import typer

    callback_url = os.environ.get("HOSAKA_LNURL_CALLBACK") or job.get("callback_url")
    if not callback_url:
        typer.echo(
            "   ❌ no LNURL callback configured — set HOSAKA_LNURL_CALLBACK "
            "or top up balance via /api/v1/admin/credit (test mode)",
            err=True,
        )
        raise typer.Exit(code=1)

    amount_msats = int(job.get("amount_due_msats") or job.get("compute_msats_estimate"))
    job_id = job["id"]

    # Build + sign zap request, exchange for a bolt11 invoice via LNURL.
    relays = ["wss://cyberspace.nostr1.com"]
    zap_req = create_zap_request(
        payer_pubkey_hex=pubkey_hex,
        recipient_pubkey_hex=HOSAKA_RECIPIENT_PUBKEY,
        amount_msats=amount_msats,
        relays=relays,
        callback_url=callback_url,
        job_id=job_id,
    )
    zap_req = sign_event(zap_req, privkey_hex)

    with httpx.Client() as sync:
        resp = sync.get(
            callback_url,
            params={"amount": str(amount_msats), "nostr": json.dumps(zap_req)},
            timeout=10,
        )
        resp.raise_for_status()
        invoice_data = resp.json()

    if "pr" not in invoice_data:
        typer.echo(f"   ❌ LNURL callback failed: {invoice_data.get('reason', 'unknown')}", err=True)
        raise typer.Exit(code=1)

    bolt11 = invoice_data["pr"]
    typer.echo(f"\n⚡  pay {amount_msats // 1000} sats to start compute")
    display_qr_terminal(bolt11=bolt11, amount_sats=amount_msats // 1000, title="⚡ Pay HOSAKA")
    typer.echo(f"\n📋 or copy: {bolt11}\n")

    # Listen for kind-9735 receipt on the relay and redeem with HOSAKA.
    from cyberspace_cli.nostr_relay import NostrRelayListener

    listener = NostrRelayListener()
    receipt: Dict[str, Any] = {}

    async def on_receipt(event: Dict[str, Any]) -> None:
        receipt.update(event)

    typer.echo(f"⏳ listening for zap receipt on {relays[0]}…")
    await listener.subscribe_to_zap_receipts(
        job_id=job_id, user_pubkey=pubkey_hex, callback=on_receipt, timeout=600,
    )
    if not receipt:
        typer.echo("   ❌ payment timeout — no receipt observed", err=True)
        raise typer.Exit(code=1)

    redeem_url = f"{api_url}/api/v1/deposit/redeem"
    auth = _auth_headers(privkey_hex, pubkey_hex, redeem_url, "POST")
    with httpx.Client() as sync:
        resp = sync.post(redeem_url, json=receipt, headers=auth, timeout=30)
        resp.raise_for_status()
        typer.echo(f"   ✅ {resp.json().get('message', 'balance credited')}")


async def run_cloud_hop(
    privkey_hex: str,
    pubkey_hex: str,
    v1: Dict[str, int],
    v2: Dict[str, int],
    previous_event_id: str,
    *,
    api_url: str = HOSAKA_API_URL,
    auto_confirm: bool = False,
) -> Dict[str, Any]:
    """Submit a hop to HOSAKA, optionally pay the invoice, return the proof.

    Returns:
        {
          "proof_hash": "<hex>",       # = result.hop_n.public_proof per §5.6
          "hop_n":     {file_id, secret_key, public_proof, ...},
          "region_n":  {...},
          "K":         int,
          "max_height": int,
          "job_id":    str,
        }
    """
    import typer

    if not HAS_HOSAKA:
        typer.echo("HOSAKA client unavailable — install hosaka-client.", err=True)
        raise typer.Exit(code=2)

    async with HosakaClient(api_url=api_url) as client:
        submit_url = f"{api_url}/api/v1/hop"
        auth = _auth_headers(privkey_hex, pubkey_hex, submit_url, "POST")

        typer.echo(f"\n☁️  submitting hop to HOSAKA at {api_url}…")
        try:
            job = await client.submit_hop(v1, v2, previous_event_id, auth)
        except CloudHeightExceeded as exc:
            d = exc.detail
            typer.echo(
                f"   ❌ HOSAKA refuses h={d.get('requested_max_height')}: cap is "
                f"h={d.get('max_hosaka_height')}. {d.get('hint','')}",
                err=True,
            )
            raise typer.Exit(code=2)
        except RuntimeError as exc:
            typer.echo(f"   ❌ {exc}", err=True)
            raise typer.Exit(code=2)

        job_id = job["id"]
        cost = job.get("compute_msats_estimate", 0)
        typer.echo(f"   job {job_id}, est. {cost // 1000} sats")

        if job.get("payment_required"):
            if not auto_confirm and not os.environ.get("HOSAKA_AUTO_CONFIRM"):
                resp = typer.prompt(f"pay {cost // 1000} sats", default="Y")
                if resp.lower() not in ("", "y", "yes"):
                    typer.echo("cancelled.")
                    raise typer.Exit(code=0)
            await _run_payment_flow(job, privkey_hex, pubkey_hex, api_url)
        else:
            prev = job.get("previous_balance_msats", 0) // 1000
            new = job.get("new_balance_msats", 0) // 1000
            typer.echo(f"   💰 balance: {prev} → {new} sats")

        final = await client.poll_job(job_id, privkey_hex, pubkey_hex)

        if final.get("status") != "completed":
            typer.echo(f"   ❌ job failed: {final.get('error', 'unknown')}", err=True)
            raise typer.Exit(code=2)

        result = final.get("result") or {}
        hop_n = result.get("hop_n") or {}
        proof_hash = hop_n.get("public_proof")
        if not proof_hash:
            typer.echo("   ❌ result missing hop_n.public_proof", err=True)
            raise typer.Exit(code=2)

        typer.echo(f"   ✅ proof_hash={proof_hash[:16]}…")
        return {
            "proof_hash": proof_hash,
            "hop_n": hop_n,
            "region_n": result.get("region_n", {}),
            "K": result.get("K"),
            "max_height": result.get("max_height"),
            "job_id": job_id,
        }


def run_cloud_hop_sync(
    privkey_hex: str,
    pubkey_hex: str,
    v1: Dict[str, int],
    v2: Dict[str, int],
    previous_event_id: str,
    *,
    api_url: str = HOSAKA_API_URL,
    auto_confirm: bool = False,
) -> Dict[str, Any]:
    """Sync wrapper for the Typer-driven CLI command path."""
    return asyncio.run(run_cloud_hop(
        privkey_hex=privkey_hex,
        pubkey_hex=pubkey_hex,
        v1=v1,
        v2=v2,
        previous_event_id=previous_event_id,
        api_url=api_url,
        auto_confirm=auto_confirm,
    ))
