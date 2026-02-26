from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from cyberspace_cli import chains
from cyberspace_cli.parsing import normalize_hex_32
from cyberspace_cli.state import CyberspaceState

_UNNAMED_RE = re.compile(r"^unnamed_(\d+)$")


def _find_target_index_by_label(targets: List[Dict[str, str]], label: str) -> int:
    for i, t in enumerate(targets):
        if t.get("label") == label:
            return i
    return -1


def _find_target_index_by_coord_hex(targets: List[Dict[str, str]], coord_hex: str) -> int:
    for i, t in enumerate(targets):
        if t.get("coord_hex") == coord_hex:
            return i
    return -1


def _next_unnamed_label(targets: List[Dict[str, str]]) -> str:
    max_n = 0
    for t in targets:
        m = _UNNAMED_RE.match(str(t.get("label", "")))
        if not m:
            continue
        try:
            max_n = max(max_n, int(m.group(1)))
        except ValueError:
            continue
    return f"unnamed_{max_n + 1}"


def set_target(state: CyberspaceState, coord: str, *, label: Optional[str]) -> Tuple[str, str]:
    """Add/update a target and set it as current.

    Returns (label, coord_hex_norm).

    Semantics:
    - If `label` is provided and exists, update its coord.
    - If `label` is omitted and coord matches an existing target, just select it.
    - If `label` is omitted and coord is new, create label unnamed_N.
    """

    coord_hex = normalize_hex_32(coord)

    if state.targets is None:
        state.targets = []

    if label is not None:
        norm_label = chains.normalize_label(label)
        idx = _find_target_index_by_label(state.targets, norm_label)
        if idx >= 0:
            state.targets[idx]["coord_hex"] = coord_hex
        else:
            state.targets.append({"label": norm_label, "coord_hex": coord_hex})
        state.active_target_label = norm_label
        return norm_label, coord_hex

    # label omitted
    existing_idx = _find_target_index_by_coord_hex(state.targets, coord_hex)
    if existing_idx >= 0:
        existing_label = str(state.targets[existing_idx].get("label", "")).strip()
        if existing_label:
            state.active_target_label = existing_label
            return existing_label, coord_hex

    new_label = _next_unnamed_label(state.targets)
    state.targets.append({"label": new_label, "coord_hex": coord_hex})
    state.active_target_label = new_label
    return new_label, coord_hex


def get_current_target(state: CyberspaceState) -> Optional[Dict[str, str]]:
    label = (getattr(state, "active_target_label", "") or "").strip()
    if not label:
        return None
    for t in state.targets or []:
        if t.get("label") == label:
            return t
    return None


def format_target_list(state: CyberspaceState) -> List[str]:
    cur = (getattr(state, "active_target_label", "") or "").strip()
    out: List[str] = []
    for t in state.targets or []:
        label = str(t.get("label", "")).strip()
        coord_hex = str(t.get("coord_hex", "")).strip().lower()
        if not label or not coord_hex:
            continue
        prefix = "(current) " if label == cur else ""
        out.append(f"{prefix}{label} 0x{coord_hex}")
    return out
