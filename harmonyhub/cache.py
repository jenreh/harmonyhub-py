"""Cross-platform XDG-style paths and on-disk caches."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def config_dir() -> Path:
    """Return the per-user config directory (~/.config/harmony-local or %APPDATA%)."""
    if _is_windows():
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / "harmony-local"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "harmony-local"


def cache_dir() -> Path:
    """Return the per-user cache directory."""
    if _is_windows():
        base = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        )
        return base / "harmony-local" / "cache"
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base / "harmony-local"


def hub_cache_dir(hub_id: str) -> Path:
    """Return the cache directory for a specific hub, creating it if needed."""
    path = cache_dir() / hub_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.toml"


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True))
