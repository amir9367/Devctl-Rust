"""`devctl sync` — track dotfiles in a private Git repo.

Tracked files are copied into ~/.devctl/dotfiles/ which is a real Git repo.
push/pull operate on that repo; status diffs local vs the mirrored copy.

``rich`` and ``GitPython`` are imported lazily so importing this module costs
only ``import typer``; the heavy deps load on first use of a sync command.
"""
from __future__ import annotations

import filecmp
import shutil
from pathlib import Path

import typer

from .. import config
from ..storage import DOTFILES_DIR, HOME, ensure_dirs

app = typer.Typer(help="Dotfile manager backed by a private Git repo.")


def _console():
    from rich.console import Console

    return Console()


def _repo():
    """Lazy import GitPython so the rest of the CLI works without git installed."""
    from git import Repo  # type: ignore
    return Repo


def _mirror_path(src: Path) -> Path:
    """Map an absolute source path into the dotfiles mirror, preserving layout."""
    try:
        rel = src.resolve().relative_to(HOME)
    except ValueError:
        # Paths outside $HOME are stored under an 'abs/' prefix to avoid collisions.
        rel = Path("abs") / src.resolve().relative_to(src.anchor)
    return DOTFILES_DIR / rel


@app.command("init")
def init(repo_url: str = typer.Argument(..., help="Git remote URL for dotfiles.")) -> None:
    """Initialise the local mirror and set the remote."""
    ensure_dirs()
    console = _console()
    Repo = _repo()
    if (DOTFILES_DIR / ".git").exists():
        console.print("[yellow]Dotfiles repo already initialised.[/]")
    else:
        DOTFILES_DIR.mkdir(parents=True, exist_ok=True)
        repo = Repo.init(DOTFILES_DIR)
        repo.create_remote("origin", repo_url)

    data = config.load()
    data["sync"]["repo"] = repo_url
    config.save(data)
    console.print(f"[green]✓[/] Tracking dotfiles in {DOTFILES_DIR} → {repo_url}")


@app.command("add")
def add(paths: list[Path]) -> None:
    """Start tracking one or more dotfiles or directories."""
    console = _console()
    data = config.load()
    tracked = set(data["sync"]["tracked"])
    for p in paths:
        absolute = str(p.expanduser().resolve())
        tracked.add(absolute)
        console.print(f"[green]+[/] {absolute}")
    data["sync"]["tracked"] = sorted(tracked)
    config.save(data)


@app.command("push")
def push(message: str = typer.Option("devctl sync", "-m")) -> None:
    """Copy tracked files into the mirror, commit, and push."""
    console = _console()
    Repo = _repo()
    repo = Repo(DOTFILES_DIR)
    _materialise(verbose=True)

    repo.git.add(A=True)
    if not repo.is_dirty(untracked_files=True):
        console.print("[dim]Nothing to commit.[/]")
        return
    repo.index.commit(message)
    try:
        repo.remote("origin").push(refspec="HEAD:main")
        console.print("[green]✓ Pushed[/]")
    except Exception as e:  # noqa: BLE001 — surface raw git error to user
        console.print(f"[red]Push failed:[/] {e}")


@app.command("pull")
def pull() -> None:
    """Pull the remote repo and apply changes back to live dotfile locations."""
    console = _console()
    Repo = _repo()
    repo = Repo(DOTFILES_DIR)
    try:
        repo.remote("origin").pull("main")
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Pull failed:[/] {e}")
        raise typer.Exit(1)

    data = config.load()
    for src in data["sync"]["tracked"]:
        src_path = Path(src)
        mirror = _mirror_path(src_path)
        if not mirror.exists():
            continue
        if src_path.exists() and _same(src_path, mirror):
            continue
        if src_path.exists():
            overwrite = typer.confirm(f"Overwrite local {src_path}?", default=False)
            if not overwrite:
                continue
        src_path.parent.mkdir(parents=True, exist_ok=True)
        _copy(mirror, src_path)
        console.print(f"[green]↓[/] {src_path}")


@app.command("status")
def status() -> None:
    """Diff view: which tracked files are out of sync with the mirror."""
    from rich.table import Table

    console = _console()
    data = config.load()
    table = Table(title="Dotfile sync status")
    table.add_column("Path")
    table.add_column("State")
    for src in data["sync"]["tracked"]:
        src_path = Path(src)
        mirror = _mirror_path(src_path)
        if not src_path.exists():
            state = "[red]missing locally[/]"
        elif not mirror.exists():
            state = "[yellow]not mirrored (run push)[/]"
        elif _same(src_path, mirror):
            state = "[green]in sync[/]"
        else:
            state = "[yellow]changed[/]"
        table.add_row(src, state)
    console.print(table)


# --- helpers -----------------------------------------------------------------

def _materialise(verbose: bool = False) -> None:
    """Copy each tracked source into the dotfiles mirror."""
    console = _console() if verbose else None
    data = config.load()
    for src in data["sync"]["tracked"]:
        src_path = Path(src)
        if not src_path.exists():
            if verbose:
                console.print(f"[dim]skip (missing): {src}[/]")
            continue
        dest = _mirror_path(src_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        _copy(src_path, dest)
        if verbose:
            console.print(f"[green]↑[/] {src}")


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _same(a: Path, b: Path) -> bool:
    if a.is_dir() != b.is_dir():
        return False
    if a.is_dir():
        cmp = filecmp.dircmp(a, b)
        return not (cmp.diff_files or cmp.left_only or cmp.right_only)
    return filecmp.cmp(a, b, shallow=False)
