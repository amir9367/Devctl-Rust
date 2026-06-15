"""Tests for `devctl doctor` — environment diagnostics."""
from __future__ import annotations

from devctl import db
from devctl.commands import doctor as doc


def test_checks_pass_on_clean_setup():
    statuses = {c.label: c.status for c in doc._run_checks()}
    assert statuses["Python"] == "ok"
    assert statuses["devctl home"] == "ok"
    assert statuses["config"] == "ok"
    # Fresh registry with no projects is fine.
    assert statuses["registry"] == "ok"


def test_registry_flags_stale_paths(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    db.add_project("real", str(real))
    db.add_project("ghost", str(tmp_path / "deleted"))  # path never created

    registry = next(c for c in doc._run_checks() if c.label == "registry")
    assert registry.status == "warn"
    assert "ghost" in registry.detail
    assert "1 stale" in registry.detail


def test_doctor_command_exit_ok(runner, cli_app):
    result = runner.invoke(cli_app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "doctor" in result.output.lower()


def test_doctor_command_warns_but_succeeds_on_stale(runner, cli_app, tmp_path):
    db.add_project("ghost", str(tmp_path / "missing"))
    result = runner.invoke(cli_app, ["doctor"])
    # Stale paths are warnings, not errors → still exit 0.
    assert result.exit_code == 0, result.output
    assert "warning" in result.output.lower()
