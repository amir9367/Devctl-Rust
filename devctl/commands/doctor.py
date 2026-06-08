"""`devctl doctor` — diagnose the health of your devctl setup.

Runs a series of independent checks and prints a tidy report.  Exits non-zero
if any check is a hard *error* (so it can gate CI / scripts); *warnings* don't
fail the run.  Like ``run``/``snapshot``, this is registered as a top-level
command rather than a sub-app.

Heavy imports are deferred so importing this module costs only ``import typer``.
"""
from __future__ import annotations

from typing import Literal, NamedTuple

import typer

Status = Literal["ok", "warn", "error"]


class Check(NamedTuple):
    status: Status
    label: str
    detail: str


def _run_checks() -> list[Check]:
    """Collect health checks. Pure (no printing) so it's easy to unit-test."""
    import shutil
    import sys
    from pathlib import Path

    from .. import config, db
    from ..storage import CONFIG_FILE, DEVCTL_DIR, DOTFILES_DIR

    checks: list[Check] = []

    # ── Python ────────────────────────────────────────────────────────────────
    v = sys.version_info
    if v >= (3, 9):
        checks.append(Check("ok", "Python", f"{v.major}.{v.minor}.{v.micro}"))
    else:
        checks.append(Check("error", "Python", f"{v.major}.{v.minor} (need ≥ 3.9)"))

    # ── git (needed for `sync`) ───────────────────────────────────────────────
    git_path = shutil.which("git")
    if git_path:
        checks.append(Check("ok", "git", git_path))
    else:
        checks.append(Check("warn", "git", "not found — `devctl sync` will not work"))

    # ── devctl home is writable ───────────────────────────────────────────────
    try:
        DEVCTL_DIR.mkdir(parents=True, exist_ok=True)
        probe = DEVCTL_DIR / ".devctl-write-probe"
        probe.write_text("ok")
        probe.unlink()
        checks.append(Check("ok", "devctl home", str(DEVCTL_DIR)))
    except OSError as e:
        checks.append(Check("error", "devctl home", f"not writable: {e}"))

    # ── config parses ─────────────────────────────────────────────────────────
    try:
        config.load()
        where = str(CONFIG_FILE) if CONFIG_FILE.exists() else "defaults (no file yet)"
        checks.append(Check("ok", "config", where))
    except Exception as e:  # noqa: BLE001 — report any parse failure as an error
        checks.append(Check("error", "config", f"failed to load: {e}"))

    # ── project registry + stale paths ────────────────────────────────────────
    try:
        projects = db.list_projects()
    except Exception as e:  # noqa: BLE001
        checks.append(Check("error", "registry", f"unreadable: {e}"))
        projects = []
    else:
        stale = [p["name"] for p in projects if not Path(p["path"]).exists()]
        if not projects:
            checks.append(Check("ok", "registry", "no projects registered yet"))
        elif stale:
            shown = ", ".join(stale[:5]) + (" …" if len(stale) > 5 else "")
            checks.append(Check(
                "warn", "registry",
                f"{len(projects)} project(s); {len(stale)} stale path(s): {shown}",
            ))
        else:
            checks.append(Check("ok", "registry", f"{len(projects)} project(s), all paths exist"))

    # ── dotfiles repo (only if sync was initialised) ──────────────────────────
    repo_url = config.load().get("sync", {}).get("repo", "")
    if repo_url:
        if (DOTFILES_DIR / ".git").exists():
            checks.append(Check("ok", "dotfiles repo", str(DOTFILES_DIR)))
        else:
            checks.append(Check(
                "warn", "dotfiles repo",
                "configured but mirror missing — run `devctl sync init`",
            ))

    return checks


def doctor() -> None:
    """Diagnose your devctl setup and report any problems."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    checks = _run_checks()

    glyph = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "error": "[red]✗[/]"}
    table = Table(title="devctl doctor", show_lines=False)
    table.add_column("", justify="center")
    table.add_column("Check", style="cyan")
    table.add_column("Detail", style="white")
    for c in checks:
        table.add_row(glyph[c.status], c.label, c.detail)
    console.print(table)

    errors = sum(1 for c in checks if c.status == "error")
    warns = sum(1 for c in checks if c.status == "warn")
    if errors:
        console.print(f"[red]✗ {errors} error(s)[/]" + (f", [yellow]{warns} warning(s)[/]" if warns else ""))
        raise typer.Exit(1)
    if warns:
        console.print(f"[yellow]! {warns} warning(s)[/] — everything else looks good.")
    else:
        console.print("[green]✓ All checks passed.[/]")
