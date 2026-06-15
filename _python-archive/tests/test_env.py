"""Tests for `devctl env` commands via the CLI runner."""
from __future__ import annotations

from devctl import db


def test_env_new_scaffolds_and_registers(runner, cli_app, tmp_path):
    result = runner.invoke(
        cli_app, ["env", "new", "myapp", "--lang", "python", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    project_dir = tmp_path / "myapp"
    assert (project_dir / "pyproject.toml").exists()
    assert (project_dir / "src" / "myapp" / "__init__.py").exists()
    rec = db.get_project("myapp")
    assert rec is not None and rec["lang"] == "python"


def test_env_new_unknown_lang_fails(runner, cli_app, tmp_path):
    result = runner.invoke(
        cli_app, ["env", "new", "x", "--lang", "cobol", "--root", str(tmp_path)]
    )
    assert result.exit_code == 1


def test_env_add_existing_dir(runner, cli_app, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    result = runner.invoke(cli_app, ["env", "add", str(target), "--name", "ex"])
    assert result.exit_code == 0, result.output
    assert db.get_project("ex") is not None


def test_env_rm(runner, cli_app, tmp_path):
    db.add_project("temp", str(tmp_path))
    result = runner.invoke(cli_app, ["env", "rm", "temp"])
    assert result.exit_code == 0
    assert db.get_project("temp") is None


def test_env_rm_missing_is_graceful(runner, cli_app):
    result = runner.invoke(cli_app, ["env", "rm", "ghost"])
    assert result.exit_code == 0
    assert "No project" in result.output


def test_env_add_nonexistent_dir_fails(runner, cli_app, tmp_path):
    missing = tmp_path / "nope"
    result = runner.invoke(cli_app, ["env", "add", str(missing)])
    assert result.exit_code == 1


def test_env_new_existing_dir_fails(runner, cli_app, tmp_path):
    (tmp_path / "dup").mkdir()
    result = runner.invoke(
        cli_app, ["env", "new", "dup", "--root", str(tmp_path)]
    )
    assert result.exit_code == 1


def test_env_ls_empty(runner, cli_app):
    result = runner.invoke(cli_app, ["env", "ls"])
    assert result.exit_code == 0
    assert "No projects" in result.output


def test_env_ls_shows_registered(runner, cli_app, tmp_path):
    db.add_project("shown", str(tmp_path), "node")
    result = runner.invoke(cli_app, ["env", "ls"])
    assert result.exit_code == 0
    assert "shown" in result.output


def test_env_add_defaults_name_to_folder(runner, cli_app, tmp_path):
    target = tmp_path / "folder-name"
    target.mkdir()
    result = runner.invoke(cli_app, ["env", "add", str(target)])
    assert result.exit_code == 0, result.output
    assert db.get_project("folder-name") is not None
