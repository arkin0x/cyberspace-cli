"""HOSAKA cloud compute integration for cyberspace-cli.

Handles cloud fallback when LCA height exceeds local capacity.
Uses cyberspace-cli's Nostr keys for authentication (NIP-98).
"""
import asyncio
import sys
from typing import Optional, Dict, Any
from pathlib import Path

# Import from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from cyberspace_cli.nostr_signer import create_nip98_auth_header
import nest_asyncio
nest_asyncio.apply()

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
        """Redeem zap receipt to credit balance and activate job."""
        url = f"{self.api_url}/api/v1/deposit/redeem"
        headers = self._get_auth_header(url, "POST")
        
        response = await self.http.post(
            url,
            json={"receipt": receipt, "job_id": job_id},
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
    """Submit job with integrated payment flow.
    
    Flow:
    1. Get estimate
    2. Request invoice
    3. Display QR and wait for payment
    4. User pays → send zap receipt to redeem
    5. Submit job (now funded)
    6. Return job info
    """
    import typer
    from cyberspace_cli.nostr_keys import generate_privkey_bytes, privkey_bytes_from_nsec_or_hex
    
    # Step 1: Get estimate
    estimate = await self.get_estimate(job_type, params)
    amount_msats = estimate["cost_msats"]
    
    # Step 2: Request invoice
    deposit = await self.request_deposit(amount_msats)
    bolt11 = deposit["bolt11"]
    
    # Display QR and wait for payment
    typer.echo("\n" + "=" * 60)
    typer.echo("⚡  LIGHTNING PAYMENT")
    typer.echo("=" * 60)
    typer.echo(f"\nAmount: {amount_msats // 1000} sats (${estimate.get('cost_usd', 0):.2f})")
    typer.echo("\nScan QR code with Lightning wallet:\n")
    
    display_qr_terminal(
        bolt11=bolt11,
        amount_sats=amount_msats // 1000,
        title="⚡ Pay HOSAKA Invoice"
    )
    
    typer.echo(f"\n📋 Invoice: {bolt11}")
    typer.echo("\n⏳ Waiting for payment...")
    typer.echo("   After paying, the zap receipt will be verified automatically.")
    
    # For now, just ask user to press Enter after paying
    # TODO: Automatically listen for zap receipt via Nostr relay
    typer.echo("   Press Enter after you've paid the invoice:")
    typer.prompt(" ", default="")
    
    # TODO: Redeem zap receipt to credit balance
    # For now, we'll skip this step and assume manual balance top-up
    typer.echo("⚠️  NOTE: Zap receipt redemption not yet implemented.")
    typer.echo("   Please manually top up your balance or use test mode.")
    typer.echo("\nℹ️  To complete this flow, you need to:")
    typer.echo("   1. Pay the invoice above")
    typer.echo("   2. API will detect zap receipt (coming soon)")
    typer.echo("   3. Job will auto-submit when payment confirmed")
    
    # For testing, return the invoice info without submitting job
    return {
        "bolt11": bolt11,
        "amount_msats": amount_msats,
        "amount_sats": amount_msats // 1000,
        "status": "payment_pending",
        "estimate": estimate,
        "note": "Job submission pending - zap receipt redemption TBD",
    }


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
        
        # If we get here, payment was processed (future implementation)
        # Poll for completion
        typer.echo(f"\n⏳ Polling job {result['job_id'][:8]}...")
        final_job = await client.poll_job(result["job_id"], timeout=3600)
        
        if final_job.get("status") == "completed":
            typer.echo("\n✅ Cloud compute complete!")
            proof = final_job.get("result")
            if not proof:
                typer.echo("❌ No proof in result", err=True)
                raise typer.Exit(code=2)
            return proof
        else:
            typer.echo(f"\n❌ Job failed: {final_job.get('error', 'Unknown')}", err=True)
            raise typer.Exit(code=2)
