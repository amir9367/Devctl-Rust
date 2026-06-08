"""CLI-surface tests: version, help, and lazy subcommand registration."""
from __future__ import annotations

import subprocess
import sys

from devctl import __version__


def test_version(runner, cli_app):
    result = runner.invoke(cli_app, ["version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_version_via_real_argv():
    """Regression: `devctl version` from a real shell registers ONLY the version
    command (lazy loader sees argv[1]=="version").  The in-process CliRunner
    can't catch the single-command collapse because pytest's own argv makes
    cli.py eagerly load every subcommand — so this must run as a subprocess.
    """
    res = subprocess.run(
        [sys.executable, "-m", "devctl.cli", "version"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr + res.stdout
    assert __version__ in res.stdout


def test_help_lists_all_subcommands(runner, cli_app):
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0, result.output
    for cmd in ("jump", "env", "sync", "secret", "run", "snapshot", "restore", "doctor", "version"):
        assert cmd in result.output, f"{cmd!r} missing from --help"


def test_unknown_command_errors(runner, cli_app):
    result = runner.invoke(cli_app, ["definitely-not-a-command"])
    assert result.exit_code != 0
