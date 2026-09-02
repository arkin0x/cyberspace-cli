"""Local record of HOSAKA jobs, written before an invoice is shown.

A paid job must survive Ctrl+C, a crash or a reboot: the record holds the job
id, its poll token, the move it proves and the chain head it was bound to, so
`cyberspace cloud resume` can finish it, and refuse it if the chain moved on.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cyberspace_cli.paths import cyberspace_home


def cloud_jobs_path() -> Path:
    return cyberspace_home() / "cloud_jobs.jsonl"


def _read_all() -> List[Dict[str, Any]]:
    p = cloud_jobs_path()
    if not p.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


def _write_all(rows: List[Dict[str, Any]]) -> None:
    p = cloud_jobs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    tmp.replace(p)


def record(job: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or replace the record for job["job_id"]."""
    rows = [r for r in _read_all() if r.get("job_id") != job["job_id"]]
    job = dict(job)
    job.setdefault("created_at", int(time.time()))
    job["updated_at"] = int(time.time())
    rows.append(job)
    _write_all(rows)
    return job


def update(job_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    rows = _read_all()
    for r in rows:
        if r.get("job_id") == job_id:
            r.update(fields)
            r["updated_at"] = int(time.time())
            _write_all(rows)
            return r
    return None


def get(job_id: str) -> Optional[Dict[str, Any]]:
    for r in _read_all():
        if r.get("job_id") == job_id:
            return r
    return None


def pending() -> List[Dict[str, Any]]:
    return [r for r in _read_all() if r.get("state") not in ("appended", "abandoned", "failed", "expired")]


def all_jobs() -> List[Dict[str, Any]]:
    return _read_all()
