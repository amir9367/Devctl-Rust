"""Shared pytest fixtures.

DEVCTL_HOME must be set BEFORE any devctl module is imported, because
storage.py resolves its paths at import time.  We point it at a throwaway
temp directory and wipe that directory between tests for isolation.
"""
from __future__ import annotations

import gc
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

# ── Redirect all devctl state into a temp dir (before importing devctl) ────────
_TMP_HOME = Path(tempfile.mkdtemp(prefix="devctl-tests-"))
os.environ["DEVCTL_HOME"] = str(_TMP_HOME)
os.environ["DEVCTL_MASTER_PASSWORD"] = "test-password"  # unlock the secret vault

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from devctl import db  # noqa: E402
from devctl.cli import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_home():
    """Reset the SQLite connection and empty DEVCTL_HOME around every test."""
    db.reset_connection()
    _wipe(_TMP_HOME)
    yield
    db.reset_connection()
    _wipe(_TMP_HOME)


def _on_rm_error(func, path, _exc) -> None:
    """rmtree handler: clear the read-only bit and retry.

    Git marks objects/packs under ``.git`` read-only, and on Windows a
    read-only file cannot be unlinked.  GitPython may also still hold handles
    when a test finishes, so we ``gc.collect()`` before wiping.  This keeps
    test isolation deterministic instead of leaking a half-deleted ``.git``
    into the next test (which made ``sync init`` falsely report "already
    initialised").
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _wipe(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    gc.collect()  # drop lingering GitPython repo handles before deleting .git
    rm_kwargs = (
        {"onexc": _on_rm_error}
        if sys.version_info >= (3, 12)
        else {"onerror": lambda f, p, e: _on_rm_error(f, p, e)}
    )
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, **rm_kwargs)
        else:
            try:
                child.unlink()
            except PermissionError:
                os.chmod(child, stat.S_IWRITE)
                child.unlink()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_app():
    return app
