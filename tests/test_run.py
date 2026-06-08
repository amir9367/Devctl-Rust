"""Tests for `devctl run` via the CLI runner."""
from __future__ import annotations

from devctl import db


def _make_project(tmp_path, tasks_toml: str | None = None):
    proj = tmp_path / "proj"
    proj.mkdir()
    db.add_project("proj", str(proj))
    if tasks_toml is not None:
        (proj / "devctl.toml").write_text(tasks_toml, encoding="utf-8")
    return proj


def test_run_init_creates_toml(runner, cli_app, tmp_path):
    _make_project(tmp_path)
    result = runner.invoke(cli_app, ["run", "proj", "--init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "proj" / "devctl.toml").exists()


def test_run_lists_tasks(runner, cli_app, tmp_path):
    _make_project(tmp_path, '[tasks]\nhello = "echo hi"\nbye = "echo bye"\n')
    result = runner.invoke(cli_app, ["run", "proj"])
    assert result.exit_code == 0, result.output
    assert "hello" in result.output
    assert "bye" in result.output


def test_run_executes_task(runner, cli_app, tmp_path):
    _make_project(tmp_path, '[tasks]\nok = "exit 0"\n')
    result = runner.invoke(cli_app, ["run", "proj", "ok"])
    assert result.exit_code == 0, result.output


def test_run_forwards_exit_code(runner, cli_app, tmp_path):
    _make_project(tmp_path, '[tasks]\nfail = "exit 3"\n')
    result = runner.invoke(cli_app, ["run", "proj", "fail"])
    assert result.exit_code == 3


def test_run_unknown_task_fails(runner, cli_app, tmp_path):
    _make_project(tmp_path, '[tasks]\nok = "exit 0"\n')
    result = runner.invoke(cli_app, ["run", "proj", "missing"])
    assert result.exit_code == 1


def test_run_unknown_project_fails(runner, cli_app):
    result = runner.invoke(cli_app, ["run", "ghost", "task"])
    assert result.exit_code == 1


def test_run_no_toml_fails(runner, cli_app, tmp_path):
    _make_project(tmp_path)  # no devctl.toml written
    result = runner.invoke(cli_app, ["run", "proj"])
    assert result.exit_code == 1
