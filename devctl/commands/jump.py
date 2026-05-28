"""`devctl jump` — fuzzy-pick a registered project and print its path."""
from __future__ import annotations

import typer
from rich.console import Console

from .. import db

console = Console()
app = typer.Typer(help="Fuzzy-search registered projects and jump to one.")


@app.callback(invoke_without_command=True)
def jump(
    query: str = typer.Argument("", help="Optional substring to pre-filter."),
    print_path: bool = typer.Option(
        False, "--print", help="Print only the chosen path (for shell wrapper)."
    ),
) -> None:
    projects = db.list_projects()
    if not projects:
        console.print("[yellow]No projects registered.[/] Try `devctl env add <path>`.")
        raise typer.Exit(1)

    if query:
        projects = [p for p in projects if query.lower() in p["name"].lower()]
        if not projects:
            console.print(f"[red]No project matches '{query}'.[/]")
            raise typer.Exit(1)

    # Single match — go straight there. Multiple — interactive picker.
    if len(projects) == 1:
        chosen = projects[0]
    else:
        chosen = _pick(projects)
        if chosen is None:
            raise typer.Exit(1)

    db.touch(chosen["name"])
    if print_path:
        # Plain stdout so a shell function can `cd "$(devctl jump --print)"`.
        print(chosen["path"])
    else:
        console.print(f"[green]→[/] {chosen['path']}")


def _pick(projects):
    """Interactive fuzzy picker via questionary, falls back to numbered list."""
    try:
        import questionary
    except ImportError:
        questionary = None

    if questionary is not None:
        choices = [
            questionary.Choice(title=f"{p['name']}  —  {p['path']}", value=p)
            for p in projects
        ]
        return questionary.select("Jump to:", choices=choices).ask()

    for i, p in enumerate(projects, 1):
        console.print(f"  [cyan]{i:>2}[/]  {p['name']}  [dim]{p['path']}[/]")
    raw = typer.prompt("Pick #")
    try:
        return projects[int(raw) - 1]
    except (ValueError, IndexError):
        console.print("[red]Invalid choice.[/]")
        return None
