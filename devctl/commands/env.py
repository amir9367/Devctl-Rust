"""`devctl env` — scaffold and register projects in the local index."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .. import db

console = Console()
app = typer.Typer(help="Manage your project registry.")


# Minimal language-specific scaffolds — kept small on purpose.
SCAFFOLDS: dict[str, dict[str, str]] = {
    "python": {
        "README.md": "# {name}\n",
        "pyproject.toml": '[project]\nname = "{name}"\nversion = "0.1.0"\n',
        "src/{name}/__init__.py": "",
        ".gitignore": "__pycache__/\n.venv/\n*.pyc\n",
    },
    "node": {
        "README.md": "# {name}\n",
        "package.json": '{{\n  "name": "{name}",\n  "version": "0.1.0"\n}}\n',
        ".gitignore": "node_modules/\n.env\n",
    },
    "generic": {"README.md": "# {name}\n", ".gitignore": ".env\n"},
}


@app.command("new")
def new(
    name: str,
    lang: str = typer.Option("generic", help="python | node | generic"),
    root: Path = typer.Option(
        Path.cwd(), help="Parent directory to create the project in."
    ),
) -> None:
    """Scaffold a new project folder and auto-register it."""
    if lang not in SCAFFOLDS:
        console.print(f"[red]Unknown lang '{lang}'.[/] Choose: {', '.join(SCAFFOLDS)}")
        raise typer.Exit(1)

    project_path = (root / name).resolve()
    if project_path.exists():
        console.print(f"[red]{project_path} already exists.[/]")
        raise typer.Exit(1)

    for rel, template in SCAFFOLDS[lang].items():
        file_path = project_path / rel.format(name=name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(template.format(name=name))

    db.add_project(name, project_path, lang)
    console.print(f"[green]✓[/] Created and registered [bold]{name}[/] at {project_path}")


@app.command("add")
def add(
    path: Path,
    name: str = typer.Option(None, help="Defaults to folder name."),
    lang: str = typer.Option(None, help="Optional language tag."),
) -> None:
    """Register an existing folder as a project."""
    path = path.resolve()
    if not path.is_dir():
        console.print(f"[red]{path} is not a directory.[/]")
        raise typer.Exit(1)
    db.add_project(name or path.name, path, lang)
    console.print(f"[green]✓[/] Registered [bold]{name or path.name}[/]")


@app.command("rm")
def rm(name: str) -> None:
    """Remove a project from the registry (does NOT delete files)."""
    n = db.remove_project(name)
    if n == 0:
        console.print(f"[yellow]No project named '{name}'.[/]")
    else:
        console.print(f"[green]✓[/] Removed [bold]{name}[/]")


@app.command("ls")
def ls() -> None:
    """List all registered projects."""
    rows = db.list_projects()
    if not rows:
        console.print("[dim]No projects yet.[/]")
        return
    table = Table(title="Projects", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Lang", style="magenta")
    table.add_column("Path", style="white")
    for r in rows:
        table.add_row(r["name"], r["lang"] or "-", r["path"])
    console.print(table)
