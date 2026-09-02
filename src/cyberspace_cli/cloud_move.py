"""The cloud branch of `cyberspace move`: quote, pay, wait, verify.

Local first, cloud second, sidestep third. This module runs once the move
command has decided the hop is taller than this machine will compute. It
talks to HOSAKA, shows the user the price and the invoice, keeps a local
record of the job before any money moves, waits for the result, checks it
(cloud_verify) and hands back an object the event construction understands.
Auto mode never means auto-pay: the CLI has no wallet, so "auto" means the
invoice is shown without a confirmation step.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple, Union

from cyberspace_cli import cloud_jobs
from cyberspace_cli.cloud_verify import (
    CloudHop,
    CloudSidestep,
    cloud_hop_from_result,
    cloud_sidestep_from_result,
    verify_cloud_hop,
    verify_cloud_sidestep,
)
from cyberspace_cli.hosaka import (
    CloudError,
    CloudHeightExceeded,
    HosakaClient,
    Limits,
    Quote,
    coord,
    wait_for_job,
    wait_for_settlement,
)
from cyberspace_core.movement import find_lca_height


class CloudDeclined(Exception):
    """The user (or the budget rule) said no. Nothing was submitted."""


class CloudVerificationFailed(Exception):
    def __init__(self, failures):
        super().__init__("; ".join(failures))
        self.failures = list(failures)


@dataclass
class CloudOptions:
    mode: str = "auto"                 # auto | ask | off
    api_url: str = ""
    auto_max_sats: int = 0
    yes: bool = False                  # skip the prompt regardless of budget
    max_sats: Optional[int] = None     # refuse anything above this, this run
    poll_interval: float = 5.0
    claim_interval: float = 3.0
    job_timeout: float = 3600.0

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


Echo = Callable[[str], None]
Confirm = Callable[[str], bool]


def spec_sidestep_landings(v1: int, v2: int) -> Tuple[int, ...]:
    """Destinations CYBERSPACE_V2 6.3 allows for a sidestep from v1 across the
    LCA boundary toward v2: the first leaf of the adjacent aligned subtree.
    Going down, the TypeScript reference lands on that subtree's last leaf (the
    reading of "exactly 1 gibson past the boundary"); both are accepted here
    until the spec wording is settled."""
    h = find_lca_height(v1, v2)
    if h == 0:
        return (v1,)
    base = (v1 >> h) << h
    half = 1 << (h - 1)
    if v2 > v1:
        return (base + half,)
    return (base, base + half - 1)


def decide_action(heights: Tuple[int, int, int], limits: Limits) -> str:
    max_h = max(heights)
    if max_h <= limits.max_hop_height:
        return "hop"
    if max_h <= limits.max_sidestep_height:
        return "sidestep"
    raise CloudHeightExceeded(
        f"max per-axis LCA height {max_h} exceeds HOSAKA's hop cap {limits.max_hop_height} "
        f"and sidestep cap {limits.max_sidestep_height}",
        detail={"max_height": max_h, "limits": limits.__dict__},
    )


def format_quote(q: Quote, action: str, dest: Tuple[int, int, int, int]) -> str:
    sats = "n/a" if q.cost_sats is None else f"{q.cost_sats} sats"
    lines = [
        f"HOSAKA cloud {action}: {sats} ({q.cost_msats} msats)",
        f"  tier: {q.tier}  expected: {q.est_time}",
        f"  LCA heights: X={q.per_axis_heights.get('x')} Y={q.per_axis_heights.get('y')} Z={q.per_axis_heights.get('z')} (cap {q.cap})",
        f"  destination: x={dest[0]} y={dest[1]} z={dest[2]} plane={dest[3]}",
    ]
    if action == "sidestep":
        lines.append("  a sidestep lands 1 gibson past the wall; the rest of the journey continues from there")
    return "\n".join(lines)


def _approve(q: Quote, opts: CloudOptions, confirm: Confirm, echo: Echo) -> None:
    sats = q.cost_sats or 0
    if opts.max_sats is not None and sats > opts.max_sats:
        raise CloudDeclined(f"quote {sats} sats exceeds --cloud-max-sats {opts.max_sats}")
    if opts.yes:
        return
    if opts.mode == "auto" and sats <= opts.auto_max_sats:
        return
    if not sys.stdin.isatty():
        raise CloudDeclined(
            f"quote is {sats} sats; rerun with --cloud-yes, or raise the budget with "
            f"`cyberspace cloud config --auto-max-sats N`"
        )
    if not confirm(f"Pay {sats} sats for this cloud {q.action}?"):
        raise CloudDeclined("declined")


def _show_invoice(dep: Dict, echo: Echo) -> None:
    bolt11 = dep["bolt11"]
    sats = (int(dep["amount_msats"]) + 999) // 1000
    echo(f"Pay {sats} sats to fund this job (invoice expires in {max(0, int(dep['expires_at'] - time.time()))} s):")
    try:
        import qrcode  # optional extra: pip install cyberspace-cli[cloud]

        qr = qrcode.QRCode(border=1)
        qr.add_data("lightning:" + bolt11.upper())
        qr.make(fit=True)
        import io

        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        echo(buf.getvalue())
    except Exception:
        pass
    echo(bolt11)
    echo(f"lightning:{bolt11}")


def run_cloud_move(
    *,
    privkey_hex: str,
    pubkey_hex: str,
    chain_label: str,
    opts: CloudOptions,
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    plane2: int,
    previous_event_id: str,
    local_ceiling: int,
    echo: Echo,
    confirm: Confirm,
    sleep: Callable[[float], None] = time.sleep,
) -> Union[CloudHop, CloudSidestep]:
    client = HosakaClient(opts.api_url, privkey_hex, pubkey_hex)
    limits = client.limits()
    heights = (find_lca_height(x1, x2), find_lca_height(y1, y2), find_lca_height(z1, z2))
    action = decide_action(heights, limits)

    if action == "sidestep":
        for name, a, b in (("X", x1, x2), ("Y", y1, y2), ("Z", z1, z2)):
            if a != b and b not in spec_sidestep_landings(a, b):
                raise CloudError(
                    f"a sidestep lands exactly 1 gibson past the wall (CYBERSPACE_V2 6.3); "
                    f"axis {name} destination {b} is not that landing. Use --toward, which walks boundary by boundary."
                )

    v1, v2 = coord(x1, y1, z1, plane2), coord(x2, y2, z2, plane2)
    q = client.quote(action, v1, v2)
    if not q.within_cap or q.cost_msats is None:
        raise CloudHeightExceeded(q.hint or "over the cap", detail=q.__dict__)
    echo(format_quote(q, action, (x2, y2, z2, plane2)))
    _approve(q, opts, confirm, echo)

    job = client.submit(action, v1, v2, previous_event_id)
    record = cloud_jobs.record({
        "job_id": job["id"],
        "poll_token": job.get("poll_token"),
        "action": action,
        "chain_label": chain_label,
        "v1": v1, "v2": v2,
        "previous_event_id": previous_event_id,
        "cost_msats": job.get("cost_msats"),
        "api_url": opts.api_url,
        "state": "awaiting_payment" if job.get("payment_required") else "computing",
        "deposit_id": (job.get("deposit") or {}).get("deposit_id"),
        "bolt11": (job.get("deposit") or {}).get("bolt11"),
        "expires_at": (job.get("deposit") or {}).get("expires_at"),
    })
    echo(f"HOSAKA job {job['id']} (resume with: cyberspace cloud resume {job['id']})")

    try:
        if job.get("payment_required"):
            dep = job["deposit"]
            _show_invoice(dep, echo)
            last = [0.0]

            def tick(remaining: int) -> None:
                if time.time() - last[0] >= 15:
                    last[0] = time.time()
                    echo(f"  waiting for payment... {remaining} s left on the invoice")

            wait_for_settlement(client, dep["deposit_id"], int(dep["expires_at"]), on_tick=tick, interval=opts.claim_interval, sleep=sleep)
            echo("Paid. Starting the job.")
            started = client.start_job(job["id"])
            if started.get("payment_required"):
                raise CloudError("the balance is still short after payment; top up with `cyberspace cloud deposit`", detail=started)
            cloud_jobs.update(job["id"], state="computing")

        started_at = time.time()
        last_tick = [0.0]

        def job_tick(j: Dict) -> None:
            if time.time() - last_tick[0] >= 15:
                last_tick[0] = time.time()
                prog = j.get("progress") or {}
                pct = prog.get("percent") if isinstance(prog, dict) else None
                echo(f"  computing... {int(time.time() - started_at)} s elapsed" + (f", about {pct}%" if pct is not None else ""))

        done = wait_for_job(client, job["id"], job.get("poll_token"), on_tick=job_tick, interval=opts.poll_interval, timeout=opts.job_timeout, sleep=sleep)
    except KeyboardInterrupt:
        echo(f"\nInterrupted. The job is safe on the server; finish it with: cyberspace cloud resume {job['id']}")
        raise

    return finish_cloud_job(record, done, x1, y1, z1, x2, y2, z2, plane2=plane2, previous_event_id=previous_event_id, local_ceiling=local_ceiling, echo=echo)


def finish_cloud_job(
    record: Dict,
    done: Dict,
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    *,
    plane2: int,
    previous_event_id: str,
    local_ceiling: int,
    echo: Echo,
) -> Union[CloudHop, CloudSidestep]:
    """Verify a completed job and turn it into a proof object; record the outcome."""
    action = record["action"]
    result = done.get("result") or {}
    if action == "hop":
        failures = verify_cloud_hop(result, x1, y1, z1, x2, y2, z2, plane=plane2, previous_event_id_hex=previous_event_id, local_ceiling=local_ceiling)
    else:
        failures = verify_cloud_sidestep(result, x1, y1, z1, x2, y2, z2, plane=plane2, previous_event_id_hex=previous_event_id)
    if failures:
        cloud_jobs.update(record["job_id"], state="rejected", failures=failures)
        raise CloudVerificationFailed(failures)
    cloud_jobs.update(record["job_id"], state="verified")
    echo(f"Verified cloud {action} ({len(failures)} failed checks).")
    if action == "hop":
        return cloud_hop_from_result(done, x1, y1, z1, x2, y2, z2)
    return cloud_sidestep_from_result(done, x1, y1, z1, x2, y2, z2, plane=plane2, previous_event_id_hex=previous_event_id)
