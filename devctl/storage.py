"""Storage paths and shared helpers.

Everything devctl writes lives under ~/.devctl/ so the tool is fully
self-contained and easy to back up or wipe.
"""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
DEVCTL_DIR = Path(os.environ.get("DEVCTL_HOME", HOME / ".devctl"))

CONFIG_FILE = DEVCTL_DIR / "config.toml"
PROJECTS_DB = DEVCTL_DIR / "projects.db"
PROFILE_FILE = DEVCTL_DIR / "profile.toml"
DOTFILES_DIR = DEVCTL_DIR / "dotfiles"
VAULT_DIR = DEVCTL_DIR / "vault"


def ensure_dirs() -> None:
    """Create the devctl home directory and subfolders on first use."""
    DEVCTL_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
