"""Tests for `devctl sync` — dotfile mirroring backed by Git.

Network is never touched: the "remote" is a local **bare** repository created
in a temp dir, so push/pull exercise real Git plumbing entirely offline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from devctl import config, storage
from devctl.commands import sync


# ── Pure helpers (no Git) ──────────────────────────────────────────────────────


def test_mirror_path_home_relative_preserves_layout():
    src = storage.HOME / "cfg" / "app.conf"
    assert sync._mirror_path(src) == storage.DOTFILES_DIR / "cfg" / "app.conf"


def test_mirror_path_outside_home_uses_abs_prefix():
    # A path on the same drive/anchor but clearly not under $HOME.
    src = Path(storage.HOME.anchor) / "opt" / "tool.cfg"
    mirror = sync._mirror_path(src)
    rel = mirror.relative_to(storage.DOTFILES_DIR)
    assert rel.parts[0] == "abs"


def test_same_detects_equal_and_changed(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello")
    b.write_text("hello")
    assert sync._same(a, b) is True
    b.write_text("different")
    assert sync._same(a, b) is False


def test_same_dir_vs_file_is_false(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    f = tmp_path / "f"
    f.write_text("x")
    assert sync._same(d, f) is False


# ── Config tracking ────────────────────────────────────────────────────────────


def test_sync_add_tracks_resolved_path(runner, cli_app, tmp_path):
    f = tmp_path / "dotfile"
    f.write_text("x")
    result = runner.invoke(cli_app, ["sync", "add", str(f)])
    assert result.exit_code == 0, result.output
    assert str(f.resolve()) in config.load()["sync"]["tracked"]


# ── Status states ────────────────────────────────────────────────────────────


def _track(path: Path) -> None:
    data = config.load()
    data["sync"]["tracked"] = [str(path.resolve())]
    config.save(data)


def test_sync_status_missing_locally(runner, cli_app, tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")  # stop Rich from truncating the cell
    _track(tmp_path / "ghost")
    result = runner.invoke(cli_app, ["sync", "status"])
    assert result.exit_code == 0
    assert "missing locally" in result.output


def test_sync_status_transitions(runner, cli_app, tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    f = tmp_path / "file.cfg"
    f.write_text("v1")
    _track(f)

    before = runner.invoke(cli_app, ["sync", "status"])
    assert "not mirrored" in before.output

    sync._materialise()  # copy tracked file into the mirror
    in_sync = runner.invoke(cli_app, ["sync", "status"])
    assert "in sync" in in_sync.output

    f.write_text("v2 changed")
    changed = runner.invoke(cli_app, ["sync", "status"])
    assert "changed" in changed.output


# ── Full Git roundtrip against a local bare remote ─────────────────────────────


@pytest.fixture
def git_identity(monkeypatch):
    """Provide a commit identity via env vars (no global git config needed)."""
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "devctl-test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.com")


def test_sync_init_then_reinit(runner, cli_app, tmp_path, git_identity):
    bare = tmp_path / "remote.git"
    import git

    git.Repo.init(bare, bare=True)
    first = runner.invoke(cli_app, ["sync", "init", str(bare)])
    assert first.exit_code == 0, first.output
    assert (storage.DOTFILES_DIR / ".git").exists()
    assert config.load()["sync"]["repo"] == str(bare)

    second = runner.invoke(cli_app, ["sync", "init", str(bare)])
    assert second.exit_code == 0
    assert "already initialised" in second.output


def test_sync_push_then_pull_roundtrip(runner, cli_app, tmp_path, git_identity):
    import git

    bare = tmp_path / "remote.git"
    git.Repo.init(bare, bare=True)

    assert runner.invoke(cli_app, ["sync", "init", str(bare)]).exit_code == 0

    tracked = tmp_path / "file.cfg"
    tracked.write_text("v1")
    assert runner.invoke(cli_app, ["sync", "add", str(tracked)]).exit_code == 0

    push = runner.invoke(cli_app, ["sync", "push", "-m", "initial"])
    assert push.exit_code == 0, push.output
    assert "Pushed" in push.output

    # Delete the local copy, then pull should restore it from the mirror.
    tracked.unlink()
    pull = runner.invoke(cli_app, ["sync", "pull"])
    assert pull.exit_code == 0, pull.output
    assert tracked.exists()
    assert tracked.read_text() == "v1"


def test_sync_push_nothing_to_commit(runner, cli_app, tmp_path, git_identity):
    import git

    bare = tmp_path / "remote.git"
    git.Repo.init(bare, bare=True)
    runner.invoke(cli_app, ["sync", "init", str(bare)])
    # No tracked files → nothing materialised → nothing to commit.
    result = runner.invoke(cli_app, ["sync", "push"])
    assert result.exit_code == 0
    assert "Nothing to commit" in result.output
