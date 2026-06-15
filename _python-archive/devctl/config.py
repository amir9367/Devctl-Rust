"""Global devctl config persisted as TOML at ~/.devctl/config.toml."""
from __future__ import annotations

import sys
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .storage import CONFIG_FILE, ensure_dirs

DEFAULT_CONFIG: dict[str, Any] = {
    "sync": {
        "repo": "",          # git remote for dotfiles
        "tracked": [],       # absolute paths of tracked dotfiles/dirs
    },
}


def load() -> dict[str, Any]:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)
    # Backfill defaults so callers can rely on keys existing.
    for section, defaults in DEFAULT_CONFIG.items():
        data.setdefault(section, {})
        for k, v in defaults.items():
            data[section].setdefault(k, v)
    return data


def save(data: dict[str, Any]) -> None:
    ensure_dirs()
    with CONFIG_FILE.open("wb") as f:
        tomli_w.dump(data, f)
