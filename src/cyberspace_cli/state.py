from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from cyberspace_cli.paths import state_path

STATE_VERSION = "2026-02-22-cli-state-v2"


def default_state_path() -> Path:
    # Back-compat shim.
    return state_path()


@dataclass
class CyberspaceState:
    version: str
    privkey_hex: str
    pubkey_hex: str
    coord_hex: str
    active_chain_label: str

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CyberspaceState":
        return CyberspaceState(
            version=str(d.get("version", "")),
            privkey_hex=str(d.get("privkey_hex", "")),
            pubkey_hex=str(d.get("pubkey_hex", "")),
            coord_hex=str(d.get("coord_hex", "")),
            active_chain_label=str(d.get("active_chain_label", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "privkey_hex": self.privkey_hex,
            "pubkey_hex": self.pubkey_hex,
            "coord_hex": self.coord_hex,
            "active_chain_label": self.active_chain_label,
        }


def load_state(path: Optional[Path] = None) -> Optional[CyberspaceState]:
    p = path or default_state_path()
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return CyberspaceState.from_dict(data)


def save_state(state: CyberspaceState, path: Optional[Path] = None) -> None:
    p = path or default_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)
