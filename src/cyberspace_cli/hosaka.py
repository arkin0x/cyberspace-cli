"""HTTP client for HOSAKA, the cloud compute service for Cyberspace proofs.

Standard library only. The contract it follows is hosaka-api's payments v2:
quotes and limits are public; hop and sidestep submissions are signed with
NIP-98; a short balance comes back as a pending job plus a Lightning invoice;
the client pays with any wallet, claims the deposit, starts the job, and
polls the job with its poll token. Nothing about payment is trusted from
this side: the server's node decides when an invoice settled.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from cyberspace_cli.nip98 import nip98_authorization

DEFAULT_API_URL = "https://arkin0x--hosaka-api-api-server.modal.run"
USER_AGENT = "cyberspace-cli/hosaka"


class CloudError(Exception):
    """Any failure talking to HOSAKA. `detail` is the server's error body."""

    def __init__(self, message: str, status: int = 0, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class CloudUnavailable(CloudError):
    """Network trouble, or the server cannot issue invoices right now."""


class CloudHeightExceeded(CloudError):
    """The move is taller than the server's cap for this action."""


class CloudBusy(CloudError):
    """Per-key or global job ceiling reached; nothing was charged."""


class CloudPaymentExpired(CloudError):
    """The invoice expired unpaid. Quote again; never pay a stale invoice."""


class CloudJobFailed(CloudError):
    """The server could not compute the proof. The charge was refunded."""


@dataclass
class Limits:
    max_hop_height: int
    max_sidestep_height: int
    hop_min_msats: int
    deposit_min_msats: int
    deposit_max_msats: int
    invoice_ttl_seconds: int
    local_compute: bool = False

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Limits":
        return Limits(
            max_hop_height=int(d["max_hop_height"]),
            max_sidestep_height=int(d["max_sidestep_height"]),
            hop_min_msats=int(d.get("hop_min_msats", 0)),
            deposit_min_msats=int(d.get("deposit_min_msats", 0)),
            deposit_max_msats=int(d.get("deposit_max_msats", 0)),
            invoice_ttl_seconds=int(d.get("invoice_ttl_seconds", 3600)),
            local_compute=bool(d.get("local_compute", False)),
        )


@dataclass
class Quote:
    action: str
    cost_msats: Optional[int]
    within_cap: bool
    cap: int
    max_height: int
    per_axis_heights: Dict[str, int]
    bases: Dict[str, int]
    K: int
    tier: Optional[str]
    est_time: Optional[str]
    hint: Optional[str]

    @property
    def cost_sats(self) -> Optional[int]:
        return None if self.cost_msats is None else (self.cost_msats + 999) // 1000

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Quote":
        return Quote(
            action=d["action"],
            cost_msats=d.get("cost_msats"),
            within_cap=bool(d.get("within_cap")),
            cap=int(d.get("cap", 0)),
            max_height=int(d.get("max_height", 0)),
            per_axis_heights={k: int(v) for k, v in d.get("per_axis_heights", {}).items()},
            bases={k: int(v) for k, v in d.get("bases", {}).items()},
            K=int(d.get("K", 0)),
            tier=d.get("tier"),
            est_time=d.get("est_time"),
            hint=d.get("hint"),
        )


def coord(x: int, y: int, z: int, plane: int = 0) -> Dict[str, int]:
    return {"x": int(x), "y": int(y), "z": int(z), "plane": int(plane)}


class HosakaClient:
    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        privkey_hex: Optional[str] = None,
        pubkey_hex: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.api_url = api_url.rstrip("/")
        self.privkey_hex = privkey_hex
        self.pubkey_hex = pubkey_hex
        self.timeout = timeout

    # -- transport ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        auth: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = self.api_url + path
        data = None
        req_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if auth:
            if not (self.privkey_hex and self.pubkey_hex):
                raise CloudError("this request needs the CLI identity (privkey and pubkey)")
            req_headers["Authorization"] = nip98_authorization(self.privkey_hex, self.pubkey_hex, url, method)
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                payload = {"detail": raw.decode("utf-8", "replace")}
            raise self._error_for(e.code, payload) from None
        except urllib.error.URLError as e:
            raise CloudUnavailable(f"cannot reach HOSAKA at {self.api_url}: {e.reason}") from None

    @staticmethod
    def _error_for(status: int, payload: Dict[str, Any]) -> CloudError:
        detail = payload.get("detail", payload)
        code = detail.get("error") if isinstance(detail, dict) else None
        message = detail.get("hint") or detail.get("error") if isinstance(detail, dict) else str(detail)
        message = f"HOSAKA {status}: {message}"
        if code in ("height_exceeds_hosaka_cap", "height_exceeds_sidestep_cap"):
            return CloudHeightExceeded(message, status, detail)
        if status == 429:
            return CloudBusy(message, status, detail)
        if status == 503 or code == "payments_unavailable":
            return CloudUnavailable(message, status, detail)
        return CloudError(message, status, detail)

    # -- public routes -----------------------------------------------------

    def limits(self) -> Limits:
        return Limits.from_dict(self._request("GET", "/api/v1/limits"))

    def quote(self, action: str, v1: Dict[str, int], v2: Dict[str, int]) -> Quote:
        return Quote.from_dict(self._request("POST", "/api/v1/quote", {"action": action, "v1": v1, "v2": v2}))

    # -- signed routes -----------------------------------------------------

    def submit(self, action: str, v1: Dict[str, int], v2: Dict[str, int], previous_event_id: str) -> Dict[str, Any]:
        if action not in ("hop", "sidestep"):
            raise ValueError("action must be hop or sidestep")
        return self._request("POST", f"/api/v1/{action}", {"v1": v1, "v2": v2, "previous_event_id": previous_event_id}, auth=True)

    def get_job(self, job_id: str, poll_token: Optional[str] = None) -> Dict[str, Any]:
        if poll_token:
            return self._request("GET", f"/api/v1/jobs/{job_id}", headers={"X-Job-Token": poll_token})
        return self._request("GET", f"/api/v1/jobs/{job_id}", auth=True)

    def start_job(self, job_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/jobs/{job_id}/start", auth=True)

    def jobs(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/v1/jobs", auth=True).get("jobs", [])

    def balance(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/balance", auth=True)

    def deposit(self, amount_msats: int) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/deposit", {"amount_msats": int(amount_msats)}, auth=True)

    def claim_deposit(self, deposit_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/deposit/{deposit_id}/claim", auth=True)


# -- waiting ----------------------------------------------------------------

def wait_for_settlement(
    client: HosakaClient,
    deposit_id: str,
    expires_at: int,
    *,
    on_tick: Optional[Callable[[int], None]] = None,
    interval: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    """Claim the deposit until the node reports settlement or the invoice expires."""
    while True:
        dep = client.claim_deposit(deposit_id)
        if dep.get("status") == "settled":
            return dep
        if dep.get("status") == "expired" or now() >= expires_at:
            raise CloudPaymentExpired("the invoice expired before it was paid", detail=dep)
        if on_tick:
            on_tick(max(0, int(expires_at - now())))
        sleep(interval)


def wait_for_job(
    client: HosakaClient,
    job_id: str,
    poll_token: Optional[str],
    *,
    on_tick: Optional[Callable[[Dict[str, Any]], None]] = None,
    interval: float = 5.0,
    timeout: float = 3600.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    """Poll the job until it completes. A failed job raises CloudJobFailed."""
    deadline = now() + timeout
    while True:
        job = client.get_job(job_id, poll_token)
        status = job.get("status")
        if status == "completed":
            return job
        if status == "failed":
            raise CloudJobFailed(f"HOSAKA job {job_id} failed: {job.get('error')}", detail=job)
        if now() >= deadline:
            raise CloudError(f"HOSAKA job {job_id} still {status} after {int(timeout)} s; resume later with `cyberspace cloud resume {job_id}`", detail=job)
        if on_tick:
            on_tick(job)
        sleep(interval)
