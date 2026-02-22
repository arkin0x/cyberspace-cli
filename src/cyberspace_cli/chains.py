from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List

from cyberspace_cli.paths import chains_dir


_LABEL_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def normalize_label(label: str) -> str:
    label = label.strip()
    if not label:
        raise ValueError("label must be non-empty")
    # Keep it filesystem-friendly.
    label = _LABEL_RE.sub("_", label)
    return label


def chain_path(label: str) -> Path:
    d = chains_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{normalize_label(label)}.jsonl"


def list_chain_labels() -> List[str]:
    d = chains_dir()
    if not d.exists():
        return []
    out: List[str] = []
    for p in sorted(d.glob("*.jsonl")):
        out.append(p.stem)
    return out


def iter_events(label: str) -> Iterator[Dict[str, Any]]:
    p = chain_path(label)
    if not p.exists():
        return
        yield  # pragma: no cover

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def read_events(label: str) -> List[Dict[str, Any]]:
    return list(iter_events(label))


def append_event(label: str, event: Dict[str, Any]) -> None:
    p = chain_path(label)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")


def chain_length(label: str) -> int:
    p = chain_path(label)
    if not p.exists():
        return 0
    n = 0
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def create_new_chain(label: str, genesis_event: Dict[str, Any], *, overwrite: bool = False) -> None:
    p = chain_path(label)
    if p.exists() and not overwrite:
        raise FileExistsError(f"chain already exists: {label}")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(genesis_event, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")
