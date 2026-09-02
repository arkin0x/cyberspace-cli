from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from cyberspace_cli.paths import config_path
from cyberspace_core.geoid import DEFAULT_GEOID_MODEL, normalize_geoid_model

CONFIG_VERSION = "2026-03-18-cli-config-v2"

DEFAULT_MAX_LCA_HEIGHT = 16

# HOSAKA cloud compute. "auto" submits without asking up to cloud_auto_max_sats
# (0 means always ask), "ask" always asks, "off" restores the plain refusal.
DEFAULT_CLOUD_MODE = "auto"
DEFAULT_CLOUD_API_URL = "https://arkin0x--hosaka-api-api-server.modal.run"
DEFAULT_CLOUD_AUTO_MAX_SATS = 0
CLOUD_MODES = ("auto", "ask", "off")


@dataclass
class CyberspaceConfig:
    version: str
    default_max_lca_height: int
    gps_geoid_model: str
    cloud_mode: str = DEFAULT_CLOUD_MODE
    cloud_api_url: str = DEFAULT_CLOUD_API_URL
    cloud_auto_max_sats: int = DEFAULT_CLOUD_AUTO_MAX_SATS

    @staticmethod
    def default() -> "CyberspaceConfig":
        return CyberspaceConfig(
            version=CONFIG_VERSION,
            default_max_lca_height=DEFAULT_MAX_LCA_HEIGHT,
            gps_geoid_model=DEFAULT_GEOID_MODEL,
        )

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CyberspaceConfig":
        try:
            v = int(d.get("default_max_lca_height", DEFAULT_MAX_LCA_HEIGHT))
        except Exception:
            v = DEFAULT_MAX_LCA_HEIGHT
        try:
            geoid_model = normalize_geoid_model(str(d.get("gps_geoid_model", DEFAULT_GEOID_MODEL)))
        except Exception:
            geoid_model = DEFAULT_GEOID_MODEL
        cloud_mode = str(d.get("cloud_mode", DEFAULT_CLOUD_MODE)).lower()
        if cloud_mode not in CLOUD_MODES:
            cloud_mode = DEFAULT_CLOUD_MODE
        try:
            auto_max = max(0, int(d.get("cloud_auto_max_sats", DEFAULT_CLOUD_AUTO_MAX_SATS)))
        except Exception:
            auto_max = DEFAULT_CLOUD_AUTO_MAX_SATS
        return CyberspaceConfig(
            version=str(d.get("version", "")) or CONFIG_VERSION,
            default_max_lca_height=v,
            gps_geoid_model=geoid_model,
            cloud_mode=cloud_mode,
            cloud_api_url=str(d.get("cloud_api_url") or DEFAULT_CLOUD_API_URL),
            cloud_auto_max_sats=auto_max,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "default_max_lca_height": int(self.default_max_lca_height),
            "gps_geoid_model": self.gps_geoid_model,
            "cloud_mode": self.cloud_mode,
            "cloud_api_url": self.cloud_api_url,
            "cloud_auto_max_sats": int(self.cloud_auto_max_sats),
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
