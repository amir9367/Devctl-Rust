"""`devctl env` — scaffold and register projects in the local index.

Heavy imports (rich) are deferred into the command bodies so importing this
module — which cli.py must do to register the sub-app — costs only ``import
typer``.  Commands that never render a table (``add``, ``rm``) skip the ~45 ms
``rich.table`` import entirely.
"""
from __future__ import annotations

from pathlib import Path

import typer

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

# Files that, if present in a directory, reveal its language — used by `add`
# to auto-tag projects when the user doesn't pass --lang.
_LANG_MARKERS: list[tuple[str, str]] = [
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("requirements.txt", "python"),
    ("package.json", "node"),
    ("Cargo.toml", "rust"),
    ("go.mod", "go"),
]


def _detect_lang(path: Path) -> str | None:
    """Best-effort language detection from well-known marker files."""
    for marker, lang in _LANG_MARKERS:
        if (path / marker).exists():
            return lang
    return None


@app.command("new")
def new(
    name: str,
    lang: str = typer.Option("generic", help="python | node | generic"),
    root: Path = typer.Option(
        Path.cwd(), help="Parent directory to create the project in."
    ),
) -> None:
    """Scaffold a new project folder and auto-register it."""
    from rich.console import Console

    from .. import db

    console = Console()
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
    lang: str = typer.Option(None, help="Optional language tag (auto-detected if omitted)."),
) -> None:
    """Register an existing folder as a project (language auto-detected)."""
    from rich.console import Console

    from .. import db

    console = Console()
    path = path.resolve()
    if not path.is_dir():
        console.print(f"[red]{path} is not a directory.[/]")
        raise typer.Exit(1)
    resolved_lang = lang or _detect_lang(path)
    db.add_project(name or path.name, path, resolved_lang)
    tag = f" [magenta]({resolved_lang})[/]" if resolved_lang else ""
    console.print(f"[green]✓[/] Registered [bold]{name or path.name}[/]{tag}")


@app.command("rm")
def rm(name: str) -> None:
    """Remove a project from the registry (does NOT delete files)."""
    from rich.console import Console

    from .. import db

    console = Console()
    if db.remove_project(name):
        console.print(f"[green]✓[/] Removed [bold]{name}[/]")
    else:
        console.print(f"[yellow]No project named '{name}'.[/]")


@app.command("ls")
def ls() -> None:
    """List all registered projects, ranked by frecency."""
    from rich.console import Console
    from rich.table import Table

    from .. import db

    console = Console()
    rows = db.list_projects()
    if not rows:
        console.print("[dim]No projects yet.[/]")
        return
    table = Table(title="Projects", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Lang", style="magenta")
    table.add_column("Uses", style="green", justify="right")
    table.add_column("Path", style="white")
    for r in rows:
        table.add_row(r["name"], r["lang"] or "-", str(r["use_count"]), r["path"])
    console.print(table)
