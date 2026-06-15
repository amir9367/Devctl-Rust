"""Tests for `devctl snapshot` / `devctl restore`.

System interactions (package managers, VS Code, subprocess installs) are
monkeypatched so the tests are deterministic and never touch the real machine.
"""
from __future__ import annotations

import sys

from devctl.commands import snapshot as snap
from devctl.storage import PROFILE_FILE

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def test_capture_env_keys_returns_sorted_names(monkeypatch):
    monkeypatch.setenv("DEVCTL_TEST_MARKER", "value-should-not-be-captured")
    keys = snap._capture_env_keys()
    assert "DEVCTL_TEST_MARKER" in keys
    assert keys == sorted(keys)
    # Crucially, values are never captured — only names.
    assert "value-should-not-be-captured" not in keys


def test_snapshot_writes_profile(runner, cli_app, monkeypatch):
    monkeypatch.setattr(snap, "_capture_packages", lambda: {"pip": ["rich==13.7.0"]})
    monkeypatch.setattr(snap, "_capture_vscode", lambda: ["ms-python.python"])
    monkeypatch.setattr(snap, "_capture_aliases", lambda: ["alias gs='git status'"])
    monkeypatch.setattr(snap, "_capture_env_keys", lambda: ["HOME", "PATH"])

    result = runner.invoke(cli_app, ["snapshot"])
    assert result.exit_code == 0, result.output
    assert PROFILE_FILE.exists()

    with PROFILE_FILE.open("rb") as f:
        profile = tomllib.load(f)
    assert profile["packages"]["pip"] == ["rich==13.7.0"]
    assert profile["vscode_extensions"] == ["ms-python.python"]
    assert profile["env_keys"] == ["HOME", "PATH"]


def test_restore_without_profile_fails(runner, cli_app):
    assert not PROFILE_FILE.exists()
    result = runner.invoke(cli_app, ["restore"])
    assert result.exit_code == 1
    assert "No profile" in result.output


def test_restore_empty_profile_installs_nothing(runner, cli_app):
    import tomli_w

    with PROFILE_FILE.open("wb") as f:
        tomli_w.dump({"packages": {}, "env_keys": []}, f)
    result = runner.invoke(cli_app, ["restore", "-y"])
    assert result.exit_code == 0
    assert "Nothing to install" in result.output


def test_restore_runs_pip_plan(runner, cli_app, monkeypatch):
    import tomli_w

    with PROFILE_FILE.open("wb") as f:
        tomli_w.dump({"packages": {"pip": ["rich==13.7.0"]}, "env_keys": ["PATH"]}, f)

    calls: list[list[str]] = []
    monkeypatch.setattr(snap.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    result = runner.invoke(cli_app, ["restore", "-y"])
    assert result.exit_code == 0, result.output
    # A pip install command for the captured package should have been issued.
    assert any("pip" in part for cmd in calls for part in cmd)
    assert any("rich==13.7.0" in cmd for cmd in calls)


def test_run_helper_handles_missing_binary(monkeypatch):
    """_run returns '' (not a crash) when the binary isn't installed."""
    def _boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(snap.subprocess, "run", _boom)
    assert snap._run(["nonexistent-binary"]) == ""


# ── Windows package managers ──────────────────────────────────────────────────


def test_capture_choco_parses_limit_output(monkeypatch):
    monkeypatch.setattr(snap.shutil, "which", lambda b: f"/c/{b}" if b == "choco" else None)
    monkeypatch.setattr(snap, "_run", lambda cmd: "git|2.43.0\nvscode|1.90.0\n")
    assert snap._capture_packages()["choco"] == ["git", "vscode"]


def test_capture_scoop_parses_json(monkeypatch):
    monkeypatch.setattr(snap.shutil, "which", lambda b: f"/c/{b}" if b == "scoop" else None)
    monkeypatch.setattr(snap, "_run", lambda cmd: '{"apps":[{"Name":"7zip"},{"Name":"ripgrep"}]}')
    assert snap._capture_packages()["scoop"] == ["7zip", "ripgrep"]


def test_capture_scoop_plain_text_fallback(monkeypatch):
    monkeypatch.setattr(snap, "_run", lambda cmd: "7zip 22.0\nripgrep 13.0\n")
    assert snap._capture_scoop() == ["7zip", "ripgrep"]


def test_capture_powershell_aliases(monkeypatch):
    monkeypatch.setattr(snap.shutil, "which", lambda b: f"/c/{b}" if b == "pwsh" else None)
    monkeypatch.setattr(snap, "_run", lambda cmd: "gci=Get-ChildItem\nll=Get-ChildItem\n")
    assert snap._capture_powershell_aliases() == ["gci=Get-ChildItem", "ll=Get-ChildItem"]


def test_restore_plan_includes_windows_managers(monkeypatch):
    monkeypatch.setattr(snap.shutil, "which", lambda b: f"/c/{b}")  # all present
    profile = {
        "packages": {
            "scoop": ["7zip"],
            "choco": ["git"],
            "winget": ["Mozilla.Firefox"],
        }
    }
    plan = snap._build_plan(profile)
    labels = [label for label, _ in plan]
    assert "scoop" in labels
    assert "choco" in labels
    assert any(label.startswith("winget:") for label in labels)
    winget_cmd = next(cmd for label, cmd in plan if label.startswith("winget:"))
    assert "--id" in winget_cmd and "Mozilla.Firefox" in winget_cmd
