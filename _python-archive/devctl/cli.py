"""devctl entry point — lazy per-command module loading for fast startup.

The original loaded ALL subcommand modules at import time, meaning even
`devctl version` paid the full import cost of snapshot (tarfile), secret
(keyring/cryptography), sync (subprocess chains), etc.

This version inspects sys.argv BEFORE importing anything heavy and only
loads the one module that is actually needed.  All subcommands still work
identically — the only difference is startup time.
"""
from __future__ import annotations

import sys

import typer

from . import __version__

# ── App ───────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="devctl",
    help="Your personal dev environment manager — dotfiles, projects, snapshots, secrets.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# ── Lazy subcommand registry ──────────────────────────────────────────────────
# Strategy:
#   • `devctl <known-subcommand> …` → import ONLY that module
#   • `devctl` / `devctl --help` / `devctl <unknown>` → import everything
#     (needed so help text and error messages are complete)
#
# Each _add_* helper uses a local `from .commands.X import …` so that merely
# defining the helper function costs nothing — the import only runs when the
# helper is called.

_SUBAPP_NAMES: frozenset[str] = frozenset({"jump", "env", "sync", "secret", "run"})
_SNAPSHOT_NAMES: frozenset[str] = frozenset({"snapshot", "restore"})
_ALL_COMMANDS: frozenset[str] = _SUBAPP_NAMES | _SNAPSHOT_NAMES | {"doctor", "version"}


def _add_jump() -> None:
    from .commands.jump import app as sub
    app.add_typer(sub, name="jump")


def _add_env() -> None:
    from .commands.env import app as sub
    app.add_typer(sub, name="env")


def _add_sync() -> None:
    from .commands.sync import app as sub
    app.add_typer(sub, name="sync")


def _add_secret() -> None:
    from .commands.secret import app as sub
    app.add_typer(sub, name="secret")


def _add_run() -> None:
    # run is a top-level verb (like snapshot/restore), not a sub-app, so its
    # trailing variadic argument parses cleanly.
    from .commands.run import run
    app.command("run")(run)


def _add_doctor() -> None:
    from .commands.doctor import doctor
    app.command("doctor")(doctor)


def _add_snapshot() -> None:
    # snapshot / restore are top-level verbs, not a sub-app.
    from .commands.snapshot import snapshot, restore
    app.command("snapshot")(snapshot)
    app.command("restore")(restore)


_LOADERS: dict[str, object] = {
    "jump":     _add_jump,
    "env":      _add_env,
    "sync":     _add_sync,
    "secret":   _add_secret,
    "run":      _add_run,
    "doctor":   _add_doctor,
    "snapshot": _add_snapshot,
    "restore":  _add_snapshot,   # same loader; registers both at once
}

# ── Decide what to load ───────────────────────────────────────────────────────
# Read the first *positional* token (skip leading flags like --version/-h).
_argv1: str | None = next(
    (a for a in sys.argv[1:] if not a.startswith("-")),
    None,
)

if _argv1 is None or _argv1 not in _ALL_COMMANDS:
    # No subcommand (bare `devctl`), a flag, or an unknown token — load all so
    # that `--help` output and error messages include every subcommand.
    _add_jump()
    _add_env()
    _add_sync()
    _add_secret()
    _add_run()
    _add_doctor()
    _add_snapshot()
elif _argv1 in _LOADERS:
    # Fast path: one targeted import.
    _LOADERS[_argv1]()           # type: ignore[operator]
# "version" falls through — its handler below needs no module import.

# ── Built-in commands ─────────────────────────────────────────────────────────

@app.callback()
def _root() -> None:
    """devctl — your personal dev-environment manager.

    This no-op callback exists so Typer always treats the app as a multi-command
    group.  Without it, the fast `version` path (which registers only the single
    `version` command) would collapse into a single-command CLI, and Typer would
    reject the command name itself as an unexpected argument.
    """


@app.command()
def version() -> None:
    """Print the devctl version."""
    # Use typer.echo instead of rich Console — avoids importing rich just for
    # a one-liner.  Styled output is unnecessary here.
    typer.echo(f"devctl {__version__}")


if __name__ == "__main__":
    app()