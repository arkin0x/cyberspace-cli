"""HOSAKA cloud compute integration for cyberspace-cli.

Handles cloud fallback when LCA height exceeds local capacity.
Uses cyberspace-cli's Nostr keys for authentication (NIP-98).

SECURITY: Private keys NEVER leave this module. All signing happens
locally using nostr_signer. HosakaClient receives only pre-signed headers.
"""
import asyncio
import json
from typing import Optional, Dict, Any
from pathlib import Path

from cyberspace_cli.nostr_signer import sign_nip98_request
import nest_asyncio
nest_asyncio.apply()

# HOSAKA/Arkinox recipient pubkey (from Strike LNURL)
HOSAKA_RECIPIENT_PUBKEY = "e8ed3798c6ffebffa08501ac39e271662bfd160f688f94c45d692d8767dd345a"

try:
    import httpx
    from hosaka_client import display_qr_terminal
    HAS_HOSAKA = True
except ImportError:
    HAS_HOSAKA = False


HOSAKA_API_URL = "https://arkin0x--hosaka-api-api-server.modal.run"  # Production

# Allow override via environment variable for local testing
import os as _os
if _os.environ.get("HOSAKA_API_URL"):
    HOSAKA_API_URL = _os.environ.get("HOSAKA_API_URL")


def create_auth_header(privkey_hex: str, pubkey_hex: str, url: str, method: str = "GET") -> Dict[str, str]:
    """Create NIP-98 Authorization header.
    
    Args:
        privkey_hex: Private key (hex) - NEVER transmitted
        pubkey_hex: Public key (hex)
        url: Full URL being requested
        method: HTTP method
        
    Returns:
        Dict with \"Authorization\" header value
    """
    import hashlib
    
    # Sign the request
    auth_value = sign_nip98_request(
        privkey_hex=privkey_hex,
        pubkey_hex=pubkey_hex,
        url=url,
        method=method,
    )
    return {"Authorization": auth_value}


class HosakaClient:
    """Stateless HTTP client for HOSAKA API.
    
    Receives pre-signed Authorization headers from cyberspace-cli.
    Never handles private keys directly.
    """
    
    def __init__(
        self,
        api_url: str = HOSAKA_API_URL,
        timeout: float = 300.0,  # 5 minutes per request
    ):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.http = httpx.AsyncClient(base_url=self.api_url, timeout=timeout)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.http.aclose()
    
    async def get_estimate(self, job_type: str, params: Dict[str, Any], auth_headers: Dict[str, str]) -> Dict:
        """Get cost estimate for a job.
        
        Args:
            job_type: "hop" or "sidestep"
            params: Job parameters
            auth_headers: Pre-computed Authorization header (from cyberspace-cli)
        """
        url = f"{self.api_url}/api/v1/estimate"
        
        response = await self.http.post(
            url,
            params={"job_type": job_type},
            json=params,
            headers=auth_headers,
        )
        response.raise_for_status()
        return response.json()
    
    async def submit_job(self, job_type: str, params: Dict, max_cost_msats: int, auth_headers: Dict[str, str]) -> Dict:
        """Submit job.
        
        Args:
            job_type: "hop" or "sidestep"
            params: Job parameters (height, base)
            max_cost_msats: Maximum cost in millisats
            auth_headers: Pre-computed Authorization header
        """
        url = f"{self.api_url}/api/v1/jobs"
        
        response = await self.http.post(
            url,
            json={
                "job_type": job_type,
                "params": params,
                "max_cost_msats": max_cost_msats,
            },
            headers=auth_headers,
        )
        response.raise_for_status()
        return response.json()
    
    async def get_job(self, job_id: str, auth_headers: Dict[str, str]) -> Dict:
        """Get job status (requires NIP-98 auth)."""
        url = f"{self.api_url}/api/v1/jobs/{job_id}"
        response = await self.http.get(url, headers=auth_headers)
        response.raise_for_status()
        return response.json()
    
    async def poll_job(self, job_id: str, auth_headers: Dict[str, str], timeout: int = 3600, interval: int = 20) -> Dict:
        """Poll job until completion.
        
        Args:
            job_id: Job ID to poll
            auth_headers: NIP-98 auth headers
            timeout: Max seconds to wait (default 1 hour)
            interval: Target seconds between poll START times (default 20s)
        """
        import time
        import typer
        
        typer.echo(f"   Polling job {job_id} (target interval: {interval}s)...")
        start = time.time()
        poll_count = 0
        while True:
            poll_count += 1
            poll_start = time.time()
            elapsed = int(poll_start - start)
            typer.echo(f"   [Poll {poll_count}, {elapsed}s] Fetching job status...")
            
            job = await self.get_job(job_id, auth_headers)
            
            poll_duration = time.time() - poll_start
            typer.echo(f"   Response took {poll_duration:.1f}s")
            
            status = job.get("status", "unknown")
            typer.echo(f"   Status: {status}")
            
            if status in ["completed", "failed"]:
                typer.echo(f"   Job finished after {elapsed}s")
                return job
            
            if time.time() - start > timeout:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            
            # Sleep for remaining interval time (if any)
            sleep_time = max(0, interval - poll_duration)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)


async def run_cloud_compute(
    privkey_hex: str,
    pubkey_hex: str,
    job_type: str,
    params: Dict[str, Any],
    lca_height: int,
    max_compute_height: int,
) -> Dict[str, Any]:
    """Run cloud compute flow.
    
    Args:
        privkey_hex: Nostr private key (hex) - used LOCALLY for signing only
        pubkey_hex: Nostr public key (hex)
        job_type: "hop" or "sidestep"
        params: Job parameters
        lca_height: Required LCA height
        max_compute_height: Local compute limit
    
    Returns:
        Proof result dict
    """
    import typer
    
    if not HAS_HOSAKA:
        typer.echo("HOSAKA client not available. Install hosaka-client package.", err=True)
        raise typer.Exit(code=2)
    
    api_url = HOSAKA_API_URL
    
    # Notify user
    typer.echo(f"\n☁️  LCA height {lca_height} exceeds local limit ({max_compute_height})")
    typer.echo("   HOSAKA cloud compute available...\n")
    
    # Create stateless client (no keys stored)
    async with HosakaClient(api_url=api_url) as client:
        # Create auth header for this request (signing happens here, privkey stays local)
        estimate_url = f"{api_url}/api/v1/estimate"
        auth_headers = create_auth_header(privkey_hex, pubkey_hex, estimate_url, "POST")
        
        # Get estimate
        estimate = await client.get_estimate(job_type, params, auth_headers)
        
        typer.echo("=" * 60)
        typer.echo(f"☁️  Cloud compute ({estimate['tier']} tier)")
        typer.echo(f"   Cost: {estimate['cost_sats']} sats (${estimate['cost_usd']:.2f})")
        typer.echo(f"   Time: {estimate['est_time']}")
        typer.echo(f"   BTC rate: ${estimate['btc_usd_rate']:,.2f}")
        typer.echo("=" * 60)
        
        # Confirm (auto-confirm if HOSAKA_AUTO_CONFIRM is set)
        import os
        if os.environ.get("HOSAKA_AUTO_CONFIRM"):
            typer.echo("   [Auto-confirmed via HOSAKA_AUTO_CONFIRM]")
        else:
            response = typer.prompt("Proceed with cloud compute", default="Y")
            if response.lower() not in ["", "y", "yes"]:
                typer.echo("Cancelled.")
                raise typer.Exit(code=0)
        
        # Create job
        typer.echo("\n📝 Submitting job request...")
        job_url = f"{api_url}/api/v1/jobs"
        typer.echo("   Creating auth header...")
        job_auth_headers = create_auth_header(privkey_hex, pubkey_hex, job_url, "POST")
        typer.echo("   Sending POST request...")
        
        import time
        submit_start = time.time()
        job = await client.submit_job(job_type, params, estimate["cost_msats"], job_auth_headers)
        submit_time = time.time() - submit_start
        typer.echo(f"   Job submitted in {submit_time:.2f}s")
        
        job_id = job["id"]
        typer.echo(f"   Job ID: {job_id}")
        typer.echo(f"   Status: {job.get('status', 'pending')}")
        typer.echo(f"   DEBUG payment_required: {job.get('payment_required', 'MISSING')}")
        typer.echo(f"   DEBUG balance_debited: {job.get('balance_debited', 'MISSING')}")
        typer.echo(f"   DEBUG full job keys: {list(job.keys())}")
        
        # Check if balance was sufficient (compute started immediately)
        if not job.get("payment_required", True):
            # Balance was debited, compute already started
            prev = job.get('previous_balance_msats', 0) // 1000
            new = job.get('new_balance_msats', 0) // 1000
            typer.echo(f"   💰 Balance debited: {prev} → {new} sats")
            typer.echo("\n⏳ Waiting for compute to complete...")
            # Auth headers for polling (same as job submission)
            poll_auth_headers = create_auth_header(privkey_hex, pubkey_hex, job_url, "GET")
            final_job = await client.poll_job(job_id, poll_auth_headers, timeout=3600)
        else:
            # Need to pay via Lightning
            typer.echo("\n💳 Generating Lightning invoice...")
            
            from cyberspace_cli.nostr_event import create_zap_request
            from cyberspace_cli.nostr_signer import sign_event
            
            # LNURL callback for payment
            # Default was arkin0x@strike.me but Strike service is no longer available
            # Override with HOSAKA_LNURL_CALLBACK environment variable for alternative providers
            callback_url = os.environ.get(
                "HOSAKA_LNURL_CALLBACK",
                ""  # Empty means payment flow will fail gracefully with instructions
            )
            if not callback_url:
                typer.echo("   ❌ No LNURL payment provider configured")
                typer.echo("   ⚠️  Strike.me service is unavailable")
                typer.echo("   ℹ️  Set HOSAKA_LNURL_CALLBACK env var with alternative LNURL endpoint")
                typer.echo("   ℹ️  Or credit balance directly via /api/v1/admin/credit (test mode)")
                raise typer.Exit(code=1)
            
            RELAYS = ["wss://cyberspace.nostr1.com"]
            amount_msats = estimate["cost_msats"]
            
            # Create 9734 zap request
            zap_req = create_zap_request(
                payer_pubkey_hex=pubkey_hex,
                recipient_pubkey_hex=HOSAKA_RECIPIENT_PUBKEY,
                amount_msats=amount_msats,
                relays=RELAYS,
                callback_url=callback_url,
                job_id=job_id,
            )
            zap_req = sign_event(zap_req, privkey_hex)
            
            # Get invoice from Strike
            import httpx as sync_httpx
            with sync_httpx.Client() as sync_client:
                resp = sync_client.get(
                    callback_url,
                    params={"amount": str(amount_msats), "nostr": json.dumps(zap_req)},
                    timeout=10,
                )
                resp.raise_for_status()
                invoice_data = resp.json()
            
            if "pr" not in invoice_data:
                reason = invoice_data.get("reason", "Unknown error")
                typer.echo(f"   ❌ LNURL callback failed: {reason}")
                typer.echo(f"   ⚠️  Strike service may be unavailable or account inactive")
                typer.echo(f"   ℹ️  Callback URL: {callback_url}")
                raise typer.Exit(code=1)
            
            bolt11 = invoice_data["pr"]
            typer.echo(f"   Invoice generated for {amount_msats // 1000} sats")
            
            # Display QR
            typer.echo("\n" + "=" * 60)
            typer.echo("⚡  LIGHTNING PAYMENT REQUIRED")
            typer.echo("=" * 60)
            typer.echo(f"\nAmount: {amount_msats // 1000} sats (${estimate.get('cost_usd', 0):.2f})")
            typer.echo(f"Job: {job_id}")
            
            display_qr_terminal(
                bolt11=bolt11,
                amount_sats=amount_msats // 1000,
                title="⚡ Pay to Start Compute"
            )
            
            typer.echo(f"\n📋 Or copy: {bolt11}")
            typer.echo("\n⏳ Listening for payment on Nostr relays...")
            
            # Listen for receipt
            from cyberspace_cli.nostr_relay import NostrRelayListener
            
            listener = NostrRelayListener()
            receipt_found = False
            receipt_event = None
            
            async def on_receipt(event: dict):
                nonlocal receipt_found, receipt_event
                receipt_found = True
                receipt_event = event
                typer.echo(f"\n✅ Payment detected on Nostr relays!")
                typer.echo(f"   Receipt kind: {event.get('kind')}")
                typer.echo(f"   Receipt tags: {len(event.get('tags', []))}")
            
            typer.echo("\n⏳ Listening for payment on Nostr relays...")
            typer.echo(f"   Receipt will be published to: wss://cyberspace.nostr1.com")
            
            # Subscribe to zap receipts
            await listener.subscribe_to_zap_receipts(
                job_id=job_id,
                user_pubkey=pubkey_hex,
                callback=on_receipt,
                timeout=600,
            )
            
            if not receipt_found:
                typer.echo("   ❌ Payment timeout - no receipt received")
                raise typer.Exit(code=1)
            
            typer.echo("\n✅ Payment detected on Nostr relays!")
            typer.echo("   Redeeming receipt...")
            
            # Redeem receipt with HOSAKA API
            import httpx as sync_httpx
            redeem_url = f"{api_url}/api/v1/deposit/redeem"
            redeem_auth_headers = create_auth_header(privkey_hex, pubkey_hex, redeem_url, "POST")
            
            with sync_httpx.Client() as sync_client:
                resp = sync_client.post(
                    redeem_url,
                    json=receipt_event,  # Send receipt as top-level body, not nested
                    headers=redeem_auth_headers,
                    timeout=30,
                )
                resp.raise_for_status()
                redeem_result = resp.json()
            
            typer.echo(f"   ✅ {redeem_result.get('message', 'Balance credited!')}")
            
            # Poll for compute completion
            typer.echo(f"\n⏳ Polling job {job_id[:8]}...")
            poll_auth_headers = create_auth_header(privkey_hex, pubkey_hex, f"{api_url}/api/v1/jobs/{job_id}", "GET")
            final_job = await client.poll_job(job_id, poll_auth_headers, timeout=3600)
        
        # Handle completion
        if final_job.get("status") == "completed":
            typer.echo("\n✅ Cloud compute complete!")
            result = final_job.get("result")
            if not result:
                typer.echo("❌ No result in job", err=True)
                raise typer.Exit(code=2)
            
            # Extract Cantor root from result
            axis_root_hex = result.get("axis_root_hex")
            if isinstance(axis_root_hex, int):
                axis_root_hex = hex(axis_root_hex)
            if axis_root_hex and axis_root_hex.startswith("0x"):
                axis_root_hex = axis_root_hex[2:]
            
            # Compute proof_hash as double SHA256
            import hashlib
            if axis_root_hex:
                axis_root_bytes = bytes.fromhex(axis_root_hex)
                proof_hash = hashlib.sha256(hashlib.sha256(axis_root_bytes).digest()).digest().hex()
            else:
                proof_hash = "0" * 64
            
            # Return minimal proof structure for make_hop_event
            proof = {
                "proof_hash": proof_hash,
                "terrain_k": result.get("terrain_k", 0),
            }
            
            return proof
        else:
            typer.echo(f"\n❌ Job failed: {final_job.get('error', 'Unknown')}", err=True)
            raise typer.Exit(code=2)
