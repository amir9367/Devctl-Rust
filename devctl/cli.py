"""devctl entry point — wires every subcommand into a single Typer app."""
from __future__ import annotations

import typer
from rich.console import Console

from . import __version__
from .commands import env, jump, secret, snapshot, sync

console = Console()

app = typer.Typer(
    name="devctl",
    help="Your personal dev environment manager — dotfiles, projects, snapshots, secrets.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# `jump` is registered as a callback-style sub-app so `devctl jump` works directly.
app.add_typer(jump.app, name="jump")
app.add_typer(env.app, name="env")
app.add_typer(sync.app, name="sync")
app.add_typer(secret.app, name="secret")
# snapshot/restore are exposed as top-level verbs.
app.command("snapshot")(snapshot.snapshot)
app.command("restore")(snapshot.restore)


@app.command()
def version() -> None:
    """Print the devctl version."""
    console.print(f"devctl [cyan]{__version__}[/]")


if __name__ == "__main__":
    app()
