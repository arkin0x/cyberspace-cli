"""HOSAKA cloud compute integration for cyberspace-cli.

Handles cloud fallback when LCA height exceeds local capacity.
Uses cyberspace-cli's Nostr keys for authentication (NIP-98).
"""
import asyncio
import sys
import json
from typing import Optional, Dict, Any
from pathlib import Path

# Import from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from cyberspace_cli.nostr_signer import create_nip98_auth_header
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


HOSAKA_API_URL = "https://arkin0x--hosaka-api-api-server.modal.run"


class HosakaClient:
    """Minimal HOSAKA client that delegates signing to cyberspace-cli.
    
    Never handles private keys - signing is done by nostr_signer module.
    """
    
    def __init__(
        self,
        api_url: str = HOSAKA_API_URL,
        privkey_hex: Optional[str] = None,
        pubkey_hex: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.privkey_hex = privkey_hex
        self.pubkey_hex = pubkey_hex
        self.http = httpx.AsyncClient(base_url=self.api_url, timeout=timeout)
    
    async def close(self):
        await self.http.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    def _get_auth_header(self, url: str, method: str = "GET") -> Dict[str, str]:
        """Create NIP-98 Authorization header."""
        if not self.privkey_hex or not self.pubkey_hex:
            raise ValueError("Nostr keys required for authentication")
        
        return create_nip98_auth_header(
            privkey_hex=self.privkey_hex,
            pubkey_hex=self.pubkey_hex,
            url=url,
            method=method,
        )
    
    async def get_estimate(self, job_type: str, params: Dict[str, Any]) -> Dict:
        """Get cost estimate for a job."""
        url = f"{self.api_url}/api/v1/estimate"
        headers = self._get_auth_header(url, "POST")
        
        response = await self.http.post(
            url,
            params={"job_type": job_type},
            json=params,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    
    async def submit_job(self, job_type: str, params: Dict, max_cost_msats: int) -> Dict:
        """Submit job (requires pre-funded balance)."""
        url = f"{self.api_url}/api/v1/jobs"
        headers = self._get_auth_header(url, "POST")
        
        response = await self.http.post(
            url,
            json={
                "job_type": job_type,
                "params": params,
                "max_cost_msats": max_cost_msats,
            },
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    
    async def request_deposit(self, amount_msats: int) -> Dict:
        """Request Lightning invoice."""
        url = f"{self.api_url}/api/v1/deposit"
        headers = self._get_auth_header(url, "POST")
        
        response = await self.http.post(
            url,
            json={"amount_msats": amount_msats},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    
    async def redeem_zap_receipt(self, receipt: Dict, job_id: Optional[str] = None) -> Dict:
        """Redeem zap receipt to credit balance and activate job.
        
        Args:
            receipt: Kind 9735 event dict
            job_id: Optional job ID to activate after crediting
        
        Returns:
            Redeem result from API
        """
        url = f"{self.api_url}/api/v1/deposit/redeem"
        headers = self._get_auth_header(url, "POST")
        
        # Build payload - receipt fields at top level, job_id optional
        payload = dict(receipt)  # Copy all receipt fields
        if job_id:
            payload["job_id"] = job_id
        
        response = await self.http.post(
            url,
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    
    async def get_job(self, job_id: str) -> Dict:
        """Get job status."""
        url = f"{self.api_url}/api/v1/jobs/{job_id}"
        headers = self._get_auth_header(url)
        
        response = await self.http.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    
    async def poll_job(self, job_id: str, timeout: int = 3600, interval: int = 5) -> Dict:
        """Poll job until completion."""
        import time
        
        start = time.time()
        while True:
            job = await self.get_job(job_id)
            status = job.get("status", "unknown")
            
            if status in ["completed", "failed"]:
                return job
            
            if time.time() - start > timeout:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            
            await asyncio.sleep(interval)
    
    async def submit_job_with_payment(self, job_type: str, params: Dict) -> Dict:
        """Submit job with integrated payment flow per README.md.
    
        Correct Flow:
        1. Submit job (creates pending job)
        2. Request invoice  
        3. Display QR and wait
        4. Listen for zap receipt (TODO: implement relay listener)
        5. Redeem receipt to credit balance and activate job
        6. Poll for completion
        """
        import typer
    
        # Step 1: Get estimate
        estimate = await self.get_estimate(job_type, params)
        amount_msats = estimate["cost_msats"]
    
        # Step 2: Submit job
        typer.echo("\n📝 Submitting job request...")
        job = await self.submit_job(job_type, params, amount_msats)
        job_id = job["id"]
        typer.echo(f"   Job ID: {job_id}")
        typer.echo(f"   Status: {job.get('status', 'pending')}")
    
        # Check if balance was sufficient and compute started immediately
        if not job.get("payment_required", True):
            # Balance was debited, compute already started
            typer.echo(f"   💰 Balance debited: {job.get('previous_balance_msats', 0) // 1000} → {job.get('new_balance_msats', 0) // 1000} sats")
            typer.echo("\n⏳ Waiting for compute to complete...")
            return await self.poll_job(job_id, timeout=3600)
    
        # Insufficient balance - go through payment flow
        typer.echo("\n💳 Generating Lightning invoice...")
        
        # IMPORTANT: Per NIP-57, we need to create a kind 9734 zap request
        # and send it to the LNURL callback to get the bolt11 invoice.
        # The zap request MUST include a "relays" tag specifying where
        # the receipt (kind 9735) should be published.
        
        # Get LNURL callback from API
        deposit = await self.request_deposit(amount_msats)
        callback_url = deposit.get("callback_url") or deposit.get("lnurl")
        
        if not callback_url:
            typer.echo("   ❌ Failed to get LNURL callback from API")
            raise typer.Exit(code=1)
        
        # Create 9734 zap request with relays tag
        from cyberspace_cli.nostr_event import create_zap_request
        from cyberspace_cli.nostr_signer import sign_event
        
        RELAYS = ["wss://cyberspace.nostr1.com"]  # Primary relay for receipts
        
        zap_req = create_zap_request(
            payer_pubkey_hex=self.pubkey_hex,
            recipient_pubkey_hex=HOSAKA_RECIPIENT_PUBKEY,
            amount_msats=amount_msats,
            relays=RELAYS,
            callback_url=callback_url,
            job_id=job_id,
        )
        
        # Sign the zap request with user's key
        zap_req = sign_event(zap_req, self.privkey_hex)
        
        # POST zap request to LNURL callback to get bolt11
        import httpx
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                callback_url,
                params={"amount": str(amount_msats), "nostr": json.dumps(zap_req)},
                timeout=10,
            )
            resp.raise_for_status()
            invoice_data = resp.json()
        
        if "pr" not in invoice_data:
            typer.echo("   ❌ Callback didn't return bolt11 invoice")
            raise typer.Exit(code=1)
        
        bolt11 = invoice_data["pr"]
        typer.echo(f"   Invoice generated for {amount_msats // 1000} sats")
        typer.echo(f"   Zap receipt will be published to: {RELAYS[0]}")
    
        # Step 4: Display QR and wait for payment
        typer.echo("\n" + "=" * 60)
        typer.echo("⚡  LIGHTNING PAYMENT REQUIRED")
        typer.echo("=" * 60)
        typer.echo(f"\nAmount: {amount_msats // 1000} sats (${estimate.get('cost_usd', 0):.2f})")
        typer.echo(f"Job: {job_id}")
        typer.echo("\nScan QR with Lightning wallet:\n")
    
        display_qr_terminal(
            bolt11=bolt11,
            amount_sats=amount_msats // 1000,
            title="⚡ Pay to Start Compute"
        )
    
        typer.echo(f"\n📋 Or copy: {bolt11}")
        typer.echo("\n⏳ Listening for payment on Nostr relays...")
        typer.echo("   Receipt will be published to: wss://cyberspace.nostr1.com")
        
        # Listen for zap receipt
        from cyberspace_cli.nostr_relay import NostrRelayListener
        
        listener = NostrRelayListener()
        receipt_found = False
        
        async def on_receipt(event: dict):
            nonlocal receipt_found
            receipt_found = True
            typer.echo("\n✅ Payment detected on Nostr relays!")
            typer.echo("   Redeeming receipt...")
            
            # Debug: print what we're sending
            print(f"   RECEIPT EVENT: {json.dumps(event)[:500]}...")
            
            # Redeem the receipt to credit balance
            try:
                redeem_result = await self.redeem_zap_receipt(receipt=event)
                typer.echo(f"   ✅ Balance credited: {redeem_result['amount_msats'] // 1000} sats")
                typer.echo(f"   New balance: {redeem_result['new_balance_msats'] // 1000} sats")
            except Exception as e:
                typer.echo(f"   ❌ Redeem failed: {e}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    typer.echo(f"   Response: {e.response.text}")
                raise
        
        # Start listening for receipt
        typer.echo("   Connecting to relay...")
        found = await listener.subscribe_to_zap_receipts(
            job_id=job_id,
            user_pubkey=self.pubkey_hex,
            callback=on_receipt,
            timeout=600,  # 10 minutes
        )
        
        if not found:
            typer.echo("\n⏰ Timeout - payment not detected after 10 minutes")
            typer.echo("   If you paid, the receipt may not have propagated yet.")
            raise typer.Exit(code=1)
        
        # Payment detected and redeemed - now poll for job completion
        typer.echo(f"\n⏳ Polling job {job_id[:8]}...")
        final_job = await self.poll_job(job_id, timeout=3600)
        
        if final_job.get("status") == "completed":
            typer.echo("\n✅ Cloud compute complete!")
            proof = final_job.get("result")
            if not proof:
                typer.echo("❌ No proof in result", err=True)
                raise typer.Exit(code=2)
            return proof


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
        privkey_hex: Nostr private key (hex)
        pubkey_hex: Nostr public key (hex)
        job_type: "hop" or "sidestep"
        params: Job parameters
        lca_height: Required LCA height
        max_compute_height: Local compute limit
    
    Returns:
        Proof result dict from HOSAKA
    """
    import typer
    
    if not HAS_HOSAKA:
        typer.echo("HOSAKA client not installed. Run: pip install hosaka-client", err=True)
        raise typer.Exit(code=2)
    
    api_url = HOSAKA_API_URL
    
    # Notify user
    typer.echo(f"\n☁️  LCA height {lca_height} exceeds local limit ({max_compute_height})")
    typer.echo("   HOSAKA cloud compute available...\n")
    
    async with HosakaClient(
        api_url=api_url,
        privkey_hex=privkey_hex,
        pubkey_hex=pubkey_hex,
    ) as client:
        # Get estimate
        estimate = await client.get_estimate(job_type, params)
        
        typer.echo("=" * 60)
        typer.echo(f"☁️  Cloud compute ({estimate['tier']} tier)")
        typer.echo(f"   Cost: {estimate['cost_sats']} sats (${estimate['cost_usd']:.2f})")
        typer.echo(f"   Time: {estimate['est_time']}")
        typer.echo(f"   BTC rate: ${estimate['btc_usd_rate']:,.2f}")
        typer.echo("=" * 60)
        
        # Confirm
        response = typer.prompt("Proceed with cloud compute", default="Y")
        if response.lower() not in ["", "y", "yes"]:
            typer.echo("Cancelled.")
            raise typer.Exit(code=0)
        
        # Submit with payment
        typer.echo("\nInitiating payment flow...")
        result = await client.submit_job_with_payment(job_type, params)
        
        # Check if payment is complete
        if result.get("status") == "payment_pending":
            typer.echo("\n⏸️  Payment flow paused.")
            typer.echo("   Zap receipt redemption will be implemented next.")
            typer.echo("\n✅ Invoice generated successfully!")
            typer.echo("   The next step is to implement:")
            typer.echo("   1. Nostr relay listener for zap receipts")
            typer.echo("   2. /deposit/redeem endpoint to credit balance")
            typer.echo("   3. Automatic job submission after payment")
            raise typer.Exit(code=0)
        
        # If we get here, balance was debited and compute started
        # Poll for completion
        job_id = result.get('id') or result.get('job_id')
        typer.echo(f"\n⏳ Polling job {job_id[:8]}...")
        final_job = await client.poll_job(job_id, timeout=3600)
        
        if final_job.get("status") == "completed":
            typer.echo("\n✅ Cloud compute complete!")
            result = final_job.get("result")
            if not result:
                typer.echo("❌ No result in job", err=True)
                raise typer.Exit(code=2)
            
            # HOSAKA returns {axis_root_hex, height, base, proof_type, ...}
            # Construct a minimal proof dict for the CLI
            axis_root_hex = result.get("axis_root_hex")
            if isinstance(axis_root_hex, int):
                axis_root_hex = hex(axis_root_hex)
            if axis_root_hex and axis_root_hex.startswith("0x"):
                axis_root_hex = axis_root_hex[2:]
            
            # Compute proof_hash as double SHA256 of the axis root bytes
            import hashlib
            if axis_root_hex:
                axis_root_bytes = bytes.fromhex(axis_root_hex)
                proof_hash = hashlib.sha256(hashlib.sha256(axis_root_bytes).digest()).hex()
            else:
                proof_hash = "0" * 64
            
            # Return minimal proof structure
            proof = {
                "proof_hash": proof_hash,
                "terrain_k": result.get("terrain_k", 0),
            }
            
            return proof
        else:
            typer.echo(f"\n❌ Job failed: {final_job.get('error', 'Unknown')}", err=True)
            raise typer.Exit(code=2)
