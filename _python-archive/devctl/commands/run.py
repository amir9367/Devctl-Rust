"""`devctl run` — per-project task runner.

Tasks live in a ``devctl.toml`` at the project root::

    [tasks]
    test = "pytest -q"
    dev  = "uvicorn app:main --reload"
    fmt  = "ruff format ."

Usage::

    devctl run <project> <task>          # run a task in that project's directory
    devctl run <project>                 # list the project's tasks
    devctl run                           # resolve the project from the cwd
    devctl run <project> <task> -- ARGS  # append extra args to the command
    devctl run <project> --init          # scaffold a starter devctl.toml

This module exposes a plain ``run`` function (registered as a top-level command
in cli.py, like snapshot/restore) rather than a sub-app, so the trailing
variadic ``extra`` argument parses cleanly.

Heavy imports are deferred into the function body so importing this module
costs only ``import typer``.
"""
from __future__ import annotations

from typing import List, Optional

import typer

_STARTER_TOML = """\
# devctl tasks - run with `devctl run <project> <task>`
[tasks]
test = "echo replace me with your test command"
"""


def run(
    project: str = typer.Argument(
        "", help="Registered project name. Omit to use the current directory."
    ),
    task: str = typer.Argument("", help="Task to run. Omit to list available tasks."),
    extra: Optional[List[str]] = typer.Argument(
        None, help="Extra args appended to the command (use -- to separate)."
    ),
    init: bool = typer.Option(
        False, "--init", help="Create a starter devctl.toml in the project root."
    ),
) -> None:
    """Run a task defined in a project's devctl.toml."""
    # ── Deferred imports ──────────────────────────────────────────────────────
    import subprocess
    import sys
    from pathlib import Path

    from rich.console import Console
    from rich.table import Table

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    from .. import db

    console = Console()

    # ── Resolve the project directory ─────────────────────────────────────────
    if project:
        record = db.get_project(project)
        if record is None:
            console.print(
                f"[red]No registered project named '{project}'.[/] "
                "Run [bold]devctl env ls[/] to see projects."
            )
            raise typer.Exit(1)
        proj_name = record["name"]
        proj_dir = Path(record["path"])
    else:
        proj_dir = Path.cwd()
        proj_name = proj_dir.name

    toml_path = proj_dir / "devctl.toml"

    # ── --init: scaffold and stop ─────────────────────────────────────────────
    if init:
        if toml_path.exists():
            console.print(f"[yellow]{toml_path} already exists.[/]")
            raise typer.Exit(1)
        proj_dir.mkdir(parents=True, exist_ok=True)
        toml_path.write_text(_STARTER_TOML, encoding="utf-8")
        console.print(f"[green]OK[/] Wrote starter [bold]{toml_path}[/]")
        return

    # ── Load tasks ────────────────────────────────────────────────────────────
    if not toml_path.exists():
        hint = f"devctl run {project} --init" if project else "devctl run --init"
        console.print(
            f"[red]No devctl.toml in {proj_dir}.[/] Create one with [bold]{hint}[/]."
        )
        raise typer.Exit(1)

    with toml_path.open("rb") as f:
        data = tomllib.load(f)
    tasks = data.get("tasks", {})
    if not isinstance(tasks, dict) or not tasks:
        console.print(f"[yellow]No [tasks] defined in {toml_path}.[/]")
        raise typer.Exit(1)

    # ── No task → list ────────────────────────────────────────────────────────
    if not task:
        table = Table(title=f"Tasks for {proj_name}")
        table.add_column("Task", style="cyan")
        table.add_column("Command", style="white")
        for name, cmd in tasks.items():
            table.add_row(name, str(cmd))
        console.print(table)
        return

    # ── Run the task ──────────────────────────────────────────────────────────
    if task not in tasks:
        console.print(
            f"[red]No task '{task}' in {toml_path}.[/] Available: {', '.join(tasks)}"
        )
        raise typer.Exit(1)

    command = str(tasks[task])
    if extra:
        command = command + " " + " ".join(extra)

    console.print(f"[dim]> {command}[/]")
    result = subprocess.run(command, shell=True, cwd=str(proj_dir))
    raise typer.Exit(result.returncode)
