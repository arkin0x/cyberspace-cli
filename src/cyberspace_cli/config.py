from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from cyberspace_cli.paths import config_path

CONFIG_VERSION = "2026-02-26-cli-config-v1"

DEFAULT_MAX_LCA_HEIGHT = 16


@dataclass
class CyberspaceConfig:
    version: str
    default_max_lca_height: int

    @staticmethod
    def default() -> "CyberspaceConfig":
        return CyberspaceConfig(version=CONFIG_VERSION, default_max_lca_height=DEFAULT_MAX_LCA_HEIGHT)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CyberspaceConfig":
        try:
            v = int(d.get("default_max_lca_height", DEFAULT_MAX_LCA_HEIGHT))
        except Exception:
            v = DEFAULT_MAX_LCA_HEIGHT
        return CyberspaceConfig(
            version=str(d.get("version", "")) or CONFIG_VERSION,
            default_max_lca_height=v,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "default_max_lca_height": int(self.default_max_lca_height),
        }


def load_config(path: Optional[Path] = None) -> CyberspaceConfig:
    p = path or config_path()
    if not p.exists():
        return CyberspaceConfig.default()
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return CyberspaceConfig.default()
        return CyberspaceConfig.from_dict(data)
    except Exception:
        return CyberspaceConfig.default()


def save_config(cfg: CyberspaceConfig, path: Optional[Path] = None) -> None:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)
