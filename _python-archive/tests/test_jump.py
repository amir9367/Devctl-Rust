"""Tests for `devctl jump` — fuzzy project picker.

The interactive picker (`_pick`) is exercised directly with the questionary
backend monkeypatched, and via the import-error fallback path. The `jump`
callback's non-interactive branches (no projects, single match, query
narrowing) are driven through the CLI runner.
"""
from __future__ import annotations

import types

import pytest

from devctl import db
from devctl.commands import jump as jump_mod


def test_jump_no_projects_fails(runner, cli_app):
    result = runner.invoke(cli_app, ["jump"])
    assert result.exit_code == 1
    assert "No projects" in result.output


def test_jump_single_project_prints_path(runner, cli_app, tmp_path):
    db.add_project("solo", str(tmp_path))
    result = runner.invoke(cli_app, ["jump", "--print"])
    assert result.exit_code == 0, result.output
    assert str(tmp_path.resolve()) in result.output


def test_jump_query_narrows_to_one(runner, cli_app, tmp_path):
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    db.add_project("alpha", str(a))
    db.add_project("beta", str(b))
    result = runner.invoke(cli_app, ["jump", "--print", "alph"])
    assert result.exit_code == 0, result.output
    assert str(a.resolve()) in result.output


def test_jump_query_no_match_fails(runner, cli_app, tmp_path):
    db.add_project("alpha", str(tmp_path))
    result = runner.invoke(cli_app, ["jump", "zzz"])
    assert result.exit_code == 1
    assert "No project matches" in result.output


def test_jump_touches_chosen_project(runner, cli_app, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    db.add_project("a", str(a))
    db.add_project("b", str(b))  # 'b' currently most-recent
    # Jump to 'a' by exact query → it should float to the top afterwards.
    # (--print precedes the query: `jump` is a Typer group, so a flag after the
    # positional arg would be parsed as a subcommand name — matches the README's
    # documented `devctl jump --print "$@"` shell wrapper.)
    runner.invoke(cli_app, ["jump", "--print", "a"])
    assert db.list_projects()[0]["name"] == "a"


def test_pick_uses_questionary_when_available(monkeypatch):
    projects = [{"name": "x", "path": "/x"}, {"name": "y", "path": "/y"}]
    import questionary

    monkeypatch.setattr(
        questionary,
        "select",
        lambda *a, **k: types.SimpleNamespace(ask=lambda: projects[1]),
    )
    console = _DummyConsole()
    assert jump_mod._pick(projects, console) is projects[1]


def test_pick_falls_back_to_numbered_list(monkeypatch):
    # Simulate questionary not being installed.
    monkeypatch.setitem(__import__("sys").modules, "questionary", None)
    import typer

    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "2")
    projects = [{"name": "x", "path": "/x"}, {"name": "y", "path": "/y"}]
    console = _DummyConsole()
    assert jump_mod._pick(projects, console) is projects[1]


def test_pick_invalid_choice_returns_none(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "questionary", None)
    import typer

    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "99")
    projects = [{"name": "x", "path": "/x"}]
    console = _DummyConsole()
    assert jump_mod._pick(projects, console) is None


class _DummyConsole:
    """Minimal stand-in for rich.console.Console used by _pick."""

    def print(self, *args, **kwargs):  # noqa: D401 - swallow output
        pass


@pytest.fixture(autouse=True)
def _restore_questionary():
    """Ensure a real questionary import is restored after monkeypatch tests."""
    yield
