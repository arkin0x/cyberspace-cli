"""`cyberspace cloud`: HOSAKA quotes, jobs, balance, deposits and settings.

The move command uses HOSAKA on its own when a hop is taller than this
machine computes; these commands are for looking before paying, finishing an
interrupted job, topping up a prepaid balance, and changing the defaults.
"""

from __future__ import annotations

import time
from typing import Optional

import typer

from cyberspace_cli import chains, cloud_jobs
from cyberspace_cli.cloud_move import CloudOptions, CloudVerificationFailed, finish_cloud_job, format_quote, decide_action
from cyberspace_cli.cloud_verify import CloudSidestep
from cyberspace_cli.config import CLOUD_MODES, load_config, save_config
from cyberspace_cli.hosaka import CloudError, CloudJobFailed, HosakaClient, coord, wait_for_job, wait_for_settlement
from cyberspace_cli.nostr_event import make_hop_event, make_sidestep_event
from cyberspace_cli.parsing import parse_destination_xyz_or_coord
from cyberspace_cli.state import load_state, save_state
from cyberspace_core.coords import coord_to_xyz, xyz_to_coord
from cyberspace_core.movement import find_lca_height

cloud_app = typer.Typer(no_args_is_help=True)


def _state():
    st = load_state()
    if st is None:
        typer.echo("No identity yet. Run `cyberspace init` first.", err=True)
        raise typer.Exit(code=1)
    return st


def _client(api_url: Optional[str] = None, signed: bool = True) -> HosakaClient:
    cfg = load_config()
    if signed:
        st = _state()
        return HosakaClient(api_url or cfg.cloud_api_url, st.privkey_hex, st.pubkey_hex)
    return HosakaClient(api_url or cfg.cloud_api_url)


def _fail(e: Exception) -> None:
    typer.echo(f"HOSAKA: {e}", err=True)
    raise typer.Exit(code=2)


@cloud_app.command("config")
def cloud_config(
    mode: Optional[str] = typer.Option(None, "--mode", help="auto | ask | off"),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="HOSAKA API base URL"),
    auto_max_sats: Optional[int] = typer.Option(None, "--auto-max-sats", min=0, help="In auto mode, submit without asking up to this many sats (0 = always ask)"),
) -> None:
    """Show or change the cloud defaults."""
    cfg = load_config()
    changed = False
    if mode is not None:
        if mode not in CLOUD_MODES:
            typer.echo(f"--mode must be one of {', '.join(CLOUD_MODES)}", err=True)
            raise typer.Exit(code=2)
        cfg.cloud_mode = mode
        changed = True
    if api_url is not None:
        cfg.cloud_api_url = api_url.rstrip("/")
        changed = True
    if auto_max_sats is not None:
        cfg.cloud_auto_max_sats = int(auto_max_sats)
        changed = True
    if changed:
        save_config(cfg)
        typer.echo("Saved.")
    typer.echo(f"cloud_mode: {cfg.cloud_mode}")
    typer.echo(f"cloud_api_url: {cfg.cloud_api_url}")
    typer.echo(f"cloud_auto_max_sats: {cfg.cloud_auto_max_sats}")


@cloud_app.command("limits")
def cloud_limits(api_url: Optional[str] = typer.Option(None, "--api-url")) -> None:
    """What the server accepts: caps, minimums, invoice lifetime."""
    try:
        lim = _client(api_url, signed=False).limits()
    except CloudError as e:
        _fail(e)
    for k, v in lim.__dict__.items():
        typer.echo(f"{k}: {v}")


@cloud_app.command("quote")
def cloud_quote(
    to: Optional[str] = typer.Option(None, "--to", help="Destination as x,y,z[,plane] or 256-bit coord hex."),
    by: Optional[str] = typer.Option(None, "--by", help="Relative dx,dy,dz."),
    api_url: Optional[str] = typer.Option(None, "--api-url"),
) -> None:
    """Price a move on HOSAKA without submitting it."""
    st = _state()
    x1, y1, z1, plane1 = coord_to_xyz(int.from_bytes(bytes.fromhex(st.coord_hex), "big"))
    if (to is None) == (by is None):
        typer.echo("Give exactly one of --to or --by.", err=True)
        raise typer.Exit(code=2)
    if to is not None:
        dest = parse_destination_xyz_or_coord(to, default_plane=plane1)
        x2, y2, z2, plane2 = dest.x, dest.y, dest.z, dest.plane
    else:
        parts = [int(p.strip()) for p in by.split(",")]
        if len(parts) not in (3, 4):
            typer.echo("--by needs dx,dy,dz[,plane]", err=True)
            raise typer.Exit(code=2)
        x2, y2, z2 = x1 + parts[0], y1 + parts[1], z1 + parts[2]
        plane2 = parts[3] if len(parts) == 4 else plane1
    client = _client(api_url, signed=False)
    try:
        lim = client.limits()
        heights = (find_lca_height(x1, x2), find_lca_height(y1, y2), find_lca_height(z1, z2))
        action = decide_action(heights, lim)
        q = client.quote(action, coord(x1, y1, z1, plane2), coord(x2, y2, z2, plane2))
    except CloudError as e:
        _fail(e)
    typer.echo(format_quote(q, action, (x2, y2, z2, plane2)))
    cfg = load_config()
    typer.echo(f"local ceiling: h{cfg.default_max_lca_height}; cloud_mode: {cfg.cloud_mode}")


@cloud_app.command("balance")
def cloud_balance(api_url: Optional[str] = typer.Option(None, "--api-url")) -> None:
    """Prepaid balance and recent ledger."""
    try:
        b = _client(api_url).balance()
    except CloudError as e:
        _fail(e)
    typer.echo(f"balance: {b.get('balance_msats', 0)} msats ({(int(b.get('balance_msats', 0)) + 999) // 1000} sats)")
    for row in b.get("ledger", [])[:10]:
        typer.echo(f"  {row.get('created_at')}  {row.get('kind'):8} {row.get('delta_msats'):>10} msats  {row.get('ref', '')}")


@cloud_app.command("deposit")
def cloud_deposit(
    sats: int = typer.Argument(..., min=1, help="Amount to add to the prepaid balance."),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for the payment and credit it."),
    api_url: Optional[str] = typer.Option(None, "--api-url"),
) -> None:
    """Top up the prepaid balance with a Lightning invoice. Funded moves then
    need no payment step at all."""
    client = _client(api_url)
    try:
        dep = client.deposit(sats * 1000)
    except CloudError as e:
        _fail(e)
    typer.echo(f"deposit {dep['deposit_id']} for {sats} sats, expires at {dep['expires_at']}")
    typer.echo(dep["bolt11"])
    typer.echo(f"lightning:{dep['bolt11']}")
    if not wait:
        typer.echo(f"Claim it after paying with: cyberspace cloud claim {dep['deposit_id']}")
        return
    try:
        settled = wait_for_settlement(client, dep["deposit_id"], int(dep["expires_at"]))
    except CloudError as e:
        _fail(e)
    typer.echo(f"settled: {settled.get('settled_msats')} msats; balance now {settled.get('balance_msats')} msats")


@cloud_app.command("claim")
def cloud_claim(deposit_id: str, api_url: Optional[str] = typer.Option(None, "--api-url")) -> None:
    """Ask the server to check and credit a paid deposit."""
    try:
        dep = _client(api_url).claim_deposit(deposit_id)
    except CloudError as e:
        _fail(e)
    typer.echo(f"status: {dep.get('status')}  settled: {dep.get('settled_msats')} msats  balance: {dep.get('balance_msats')} msats")


@cloud_app.command("jobs")
def cloud_jobs_cmd() -> None:
    """Local record of cloud jobs (pending first)."""
    rows = cloud_jobs.all_jobs()
    if not rows:
        typer.echo("No cloud jobs recorded.")
        return
    rows.sort(key=lambda r: (r.get("state") in ("appended", "abandoned", "failed", "expired"), -int(r.get("created_at", 0))))
    for r in rows:
        v2 = r.get("v2") or {}
        typer.echo(f"{r['job_id']}  {r.get('state', '?'):16} {r.get('action', '?'):8} -> x={v2.get('x')} y={v2.get('y')} z={v2.get('z')}  chain={r.get('chain_label')}")


@cloud_app.command("status")
def cloud_status(job_id: str, api_url: Optional[str] = typer.Option(None, "--api-url")) -> None:
    """Server status of a job, plus the local record (including the location
    decryption key of a completed hop)."""
    rec = cloud_jobs.get(job_id)
    client = _client(api_url or (rec or {}).get("api_url"))
    try:
        job = client.get_job(job_id, (rec or {}).get("poll_token"))
    except CloudError as e:
        _fail(e)
    typer.echo(f"status: {job.get('status')}  cost: {job.get('cost_msats')} msats  error: {job.get('error')}")
    if rec:
        typer.echo(f"local: {rec.get('state')}  chain={rec.get('chain_label')}  event={rec.get('event_id', '')}")
    res = job.get("result") or {}
    if job.get("status") == "completed" and "hop_n" in res:
        typer.echo(f"proof_hash: {res['hop_n']['public_proof']}")
        typer.echo(f"lookup_id: {res['region_n']['public_proof']}")
        typer.echo(f"location_decryption_key: {res['region_n'].get('secret_key')}")
    elif job.get("status") == "completed" and "proof_hash" in res:
        typer.echo(f"proof_hash: {res['proof_hash']}")


@cloud_app.command("resume")
def cloud_resume(job_id: str, api_url: Optional[str] = typer.Option(None, "--api-url")) -> None:
    """Finish an interrupted cloud move: pay if still unpaid, wait, verify, append."""
    rec = cloud_jobs.get(job_id)
    if rec is None:
        typer.echo(f"No local record for job {job_id}; nothing to resume.", err=True)
        raise typer.Exit(code=2)
    if rec.get("state") == "appended":
        typer.echo(f"Job {job_id} was already appended as event {rec.get('event_id')}.")
        return
    st = _state()
    label = rec["chain_label"]
    events = chains.read_events(label)
    head = events[-1]["id"] if events else None
    if head != rec["previous_event_id"]:
        cloud_jobs.update(job_id, state="abandoned", reason="chain head moved")
        typer.echo(
            f"The chain {label} moved on since this job was created (head {head}, job bound to {rec['previous_event_id']}). "
            "The proof is worthless now; nothing appended.",
            err=True,
        )
        raise typer.Exit(code=2)

    client = _client(api_url or rec.get("api_url"))
    try:
        job = client.get_job(job_id, rec.get("poll_token"))
        if job.get("status") == "pending":
            if rec.get("deposit_id"):
                typer.echo("Waiting for the invoice to be paid...")
                typer.echo(rec.get("bolt11", ""))
                wait_for_settlement(client, rec["deposit_id"], int(rec.get("expires_at") or 0) or int(time.time()) + 3600)
            started = client.start_job(job_id)
            if started.get("payment_required"):
                typer.echo("Balance still short; top up with `cyberspace cloud deposit`.", err=True)
                raise typer.Exit(code=2)
            cloud_jobs.update(job_id, state="computing")
        done = wait_for_job(client, job_id, rec.get("poll_token"))
    except CloudJobFailed as e:
        cloud_jobs.update(job_id, state="failed")
        _fail(e)
    except CloudError as e:
        _fail(e)

    v1, v2 = rec["v1"], rec["v2"]
    try:
        obj = finish_cloud_job(
            rec, done, v1["x"], v1["y"], v1["z"], v2["x"], v2["y"], v2["z"],
            plane2=int(v2.get("plane", 0)), previous_event_id=rec["previous_event_id"],
            local_ceiling=int(load_config().default_max_lca_height), echo=typer.echo,
        )
    except CloudVerificationFailed as e:
        typer.echo("HOSAKA result failed verification; nothing appended:", err=True)
        for f in e.failures:
            typer.echo(f"  - {f}", err=True)
        raise typer.Exit(code=3)

    coord_hex = xyz_to_coord(v2["x"], v2["y"], v2["z"], plane=int(v2.get("plane", 0))).to_bytes(32, "big").hex()
    created_at = int(time.time())
    if isinstance(obj, CloudSidestep):
        ev = make_sidestep_event(
            pubkey_hex=st.pubkey_hex, created_at=created_at, genesis_event_id=events[0]["id"],
            previous_event_id=rec["previous_event_id"], prev_coord_hex=st.coord_hex, coord_hex=coord_hex,
            proof_hash_hex=obj.proof_hash,
            merkle_roots_hex=":".join(r.hex() for r in (obj.merkle_x, obj.merkle_y, obj.merkle_z)),
            merkle_proofs_hex=":".join("".join(s.hex() for s in obj.inclusion_proofs[a]) for a in ("x", "y", "z")),
            lca_heights=obj.lca_heights,
        )
    else:
        ev = make_hop_event(
            pubkey_hex=st.pubkey_hex, created_at=created_at, genesis_event_id=events[0]["id"],
            previous_event_id=rec["previous_event_id"], prev_coord_hex=st.coord_hex, coord_hex=coord_hex,
            proof_hash_hex=obj.proof_hash,
        )
    chains.append_event(label, ev)
    st.coord_hex = coord_hex
    save_state(st)
    cloud_jobs.update(job_id, state="appended", event_id=ev["id"])
    typer.echo(f"Moved. chain={label} len={chains.chain_length(label)}")
    typer.echo(f"coord: 0x{coord_hex}")
    typer.echo(f"proof: {obj.proof_hash}")
