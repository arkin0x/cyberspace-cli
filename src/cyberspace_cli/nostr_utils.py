"""Nostr utility functions for cyberspace-cli.

Network queries, event parsing, and relay interactions.
"""
from typing import List, Dict, Optional
import json
import subprocess


def nak_req_events(
    *,
    relay: str,
    kind: int,
    tags: Dict[str, List[str]],
    limit: int,
    timeout_seconds: int = 20,
    verbose: bool = False,
    until: Optional[int] = None,
    since: Optional[int] = None,
) -> List[dict]:
    """Fetch events from Nostr relay using nak CLI.
    
    Args:
        relay: Relay URL
        kind: Event kind number
        tags: Filter tags (e.g. {"C": ["coord_hex"]})
        limit: Max events to fetch
        timeout_seconds: Query timeout
        verbose: Print debug output
        until: Max created_at timestamp
        since: Min created_at timestamp
        
    Returns:
        List of event dicts
        
    Raises:
        typer.Exit: If nak command fails
    """
    import typer
    
    cmd = ["nak", "req", "-q", "-k", str(kind), "-l", str(limit)]
    if until is not None:
        cmd.extend(["--until", str(until)])
    if since is not None:
        cmd.extend(["--since", str(since)])
    
    req_filter: Dict[str, object] = {"kinds": [kind], "limit": limit}
    if until is not None:
        req_filter["until"] = until
    if since is not None:
        req_filter["since"] = since
    
    for tag_name, values in tags.items():
        req_filter[f"#{tag_name}"] = values
        for v in values:
            cmd.extend(["--tag", f"{tag_name}={v}"])
    
    cmd.append(relay)
    
    if verbose:
        typer.echo("req_filter:")
        typer.echo(json.dumps(req_filter, separators=(",", ":"), ensure_ascii=False))
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        typer.echo("`nak` is not installed or not available in PATH.", err=True)
        raise typer.Exit(code=1)
    except OSError as e:
        typer.echo(f"Nostr query failed to start: {e}", err=True)
        raise typer.Exit(code=1)
    except subprocess.TimeoutExpired:
        typer.echo(f"Nostr query timed out after {timeout_seconds}s.", err=True)
        return []
    
    if verbose:
        typer.echo(f"nak_exit_code: {proc.returncode}")
        typer.echo("nak_stdout:")
        stdout = proc.stdout or ""
        if stdout.strip():
            for ln in stdout.rstrip("\n").splitlines():
                typer.echo(ln)
        else:
            typer.echo("(empty)")
        typer.echo("nak_stderr:")
        stderr = proc.stderr or ""
        if stderr.strip():
            for ln in stderr.rstrip("\n").splitlines():
                typer.echo(ln)
        else:
            typer.echo("(empty)")
    
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if stderr:
            typer.echo(f"Nostr query failed: {stderr}", err=True)
        else:
            typer.echo("Nostr query failed.", err=True)
        raise typer.Exit(code=1)
    
    # Parse JSONL output
    out: List[dict] = []
    for line in (proc.stdout or "").splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    
    return out


def get_event_tag(event: dict, key: str) -> Optional[str]:
    """Extract tag value from Nostr event.
    
    Args:
        event: Nostr event dict
        key: Tag key (e.g. "C", "B")
        
    Returns:
        Tag value or None
    """
    tags = event.get("tags", [])
    for tag in tags:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] == key:
            return tag[1]
    return None
