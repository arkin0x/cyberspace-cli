from __future__ import annotations

import os
from pathlib import Path


def cyberspace_home() -> Path:
    env = os.environ.get("CYBERSPACE_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cyberspace"


def state_path() -> Path:
    # Highest precedence override (useful for tests).
    env = os.environ.get("CYBERSPACE_STATE_PATH")
    if env:
        return Path(env).expanduser()
    return cyberspace_home() / "state.json"


def chains_dir() -> Path:
    return cyberspace_home() / "chains"
