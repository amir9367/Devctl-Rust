"""`devctl jump` — fuzzy-pick a registered project and print its path.

Performance changes vs original
────────────────────────────────
• `rich.console.Console` and `db` are imported INSIDE the command function,
  not at module level.  This means importing jump.py (which cli.py must do
  to get `jump.app`) costs nothing beyond `import typer`.
• `_pick` receives the console object so we don't construct it twice.
• Query filtering pre-computes `.lower()` once instead of on every item.
• `_pick` accepts a type-hinted list so editors can offer completions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from rich.console import Console  # import only for type-checking, free at runtime

app = typer.Typer(help="Fuzzy-search registered projects and jump to one.")


@app.callback(invoke_without_command=True)
def jump(
    query: str = typer.Argument("", help="Optional substring to pre-filter."),
    print_path: bool = typer.Option(
        False, "--print", help="Print only the chosen path (for shell wrapper)."
    ),
) -> None:
    # ── Deferred imports ──────────────────────────────────────────────────────
    # Importing here (instead of at module level) means `cli.py` can import
    # this module cheaply.  Python caches imports in sys.modules, so the cost
    # is paid only once — on the first `devctl jump` invocation.
    from rich.console import Console

    from .. import db

    console = Console()

    # ── Fetch & filter ────────────────────────────────────────────────────────
    projects = db.list_projects()
    if not projects:
        console.print("[yellow]No projects registered.[/] Try `devctl env add <path>`.")
        raise typer.Exit(1)

    if query:
        q_lower = query.lower()  # compute once, reuse in list-comp
        projects = [p for p in projects if q_lower in p["name"].lower()]
        if not projects:
            console.print(f"[red]No project matches '{query}'.[/]")
            raise typer.Exit(1)

    # ── Pick ──────────────────────────────────────────────────────────────────
    chosen = projects[0] if len(projects) == 1 else _pick(projects, console)
    if chosen is None:
        raise typer.Exit(1)

    db.touch(chosen["name"])

    if print_path:
        # Plain stdout so a shell function can do: cd "$(devctl jump --print)"
        print(chosen["path"])
    else:
        console.print(f"[green]→[/] {chosen['path']}")


def _pick(projects: list[dict], console: "Console") -> dict | None:
    """Interactive picker — questionary when available, numbered-list fallback."""
    try:
        import questionary
    except ImportError:
        questionary = None  # type: ignore[assignment]

    if questionary is not None:
        choices = [
            questionary.Choice(title=f"{p['name']} — {p['path']}", value=p)
            for p in projects
        ]
        return questionary.select("Jump to:", choices=choices).ask()

    # ── Fallback: plain numbered list ─────────────────────────────────────────
    for i, p in enumerate(projects, 1):
        console.print(f"  [cyan]{i:>2}[/] {p['name']} [dim]{p['path']}[/]")
    raw = typer.prompt("Pick #")
    try:
        return projects[int(raw) - 1]
    except (ValueError, IndexError):
        console.print("[red]Invalid choice.[/]")
        return None