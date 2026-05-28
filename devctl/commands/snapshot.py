"""`devctl snapshot` and `devctl restore` — portable machine profile."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

import tomli_w
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ..storage import PROFILE_FILE, ensure_dirs

console = Console()
app = typer.Typer(help="Capture and restore your machine's dev environment.")


def _run(cmd: list[str]) -> str:
    """Run a shell command and return stdout, or '' if the binary is missing."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return out.stdout
    except FileNotFoundError:
        return ""


def _capture_packages() -> dict[str, list[str]]:
    pkgs: dict[str, list[str]] = {}
    if shutil.which("brew"):
        pkgs["brew"] = _run(["brew", "leaves"]).split()
    if shutil.which("apt"):
        # `apt list --installed` is human-formatted; dpkg is parseable.
        raw = _run(["dpkg", "--get-selections"])
        pkgs["apt"] = [line.split()[0] for line in raw.splitlines() if line.strip()]
    if shutil.which("pip"):
        raw = _run([sys.executable, "-m", "pip", "freeze"])
        pkgs["pip"] = [l for l in raw.splitlines() if l and not l.startswith("-e ")]
    return pkgs


def _capture_vscode() -> list[str]:
    if not shutil.which("code"):
        return []
    return [l for l in _run(["code", "--list-extensions"]).splitlines() if l]


def _capture_aliases() -> list[str]:
    """Read aliases by sourcing the user's shell rc and running `alias`."""
    shell = os.environ.get("SHELL", "")
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc"}.get(os.path.basename(shell), "")
    if not rc:
        return []
    expanded = os.path.expanduser(rc)
    if not os.path.exists(expanded):
        return []
    raw = _run([shell, "-i", "-c", f"source {expanded} 2>/dev/null; alias"])
    return [l for l in raw.splitlines() if l.startswith("alias ") or "=" in l]


def _capture_env_keys() -> list[str]:
    """Only key names — never values — so the profile is safe to commit."""
    return sorted(os.environ.keys())


@app.command("snapshot")
def snapshot() -> None:
    """Capture installed packages, VS Code extensions, aliases, env key names."""
    ensure_dirs()
    profile: dict[str, Any] = {}
    steps = [
        ("packages", _capture_packages),
        ("vscode_extensions", _capture_vscode),
        ("aliases", _capture_aliases),
        ("env_keys", _capture_env_keys),
    ]
    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as progress:
        for key, fn in steps:
            task = progress.add_task(f"Capturing {key}…", total=None)
            profile[key] = fn()
            progress.remove_task(task)

    with PROFILE_FILE.open("wb") as f:
        tomli_w.dump(profile, f)
    console.print(f"[green]✓[/] Wrote profile → {PROFILE_FILE}")


@app.command("restore")
def restore(
    yes: bool = typer.Option(False, "-y", help="Skip confirmation prompts."),
) -> None:
    """Replay a profile: install packages and VS Code extensions."""
    if not PROFILE_FILE.exists():
        console.print(f"[red]No profile at {PROFILE_FILE}.[/] Run snapshot first.")
        raise typer.Exit(1)
    with PROFILE_FILE.open("rb") as f:
        profile = tomllib.load(f)

    plan: list[tuple[str, list[str]]] = []
    pkgs = profile.get("packages", {})
    if pkgs.get("brew") and shutil.which("brew"):
        plan.append(("brew", ["brew", "install", *pkgs["brew"]]))
    if pkgs.get("apt") and shutil.which("apt"):
        plan.append(("apt", ["sudo", "apt", "install", "-y", *pkgs["apt"]]))
    if pkgs.get("pip"):
        plan.append(("pip", [sys.executable, "-m", "pip", "install", *pkgs["pip"]]))
    if profile.get("vscode_extensions") and shutil.which("code"):
        for ext in profile["vscode_extensions"]:
            plan.append((f"vscode:{ext}", ["code", "--install-extension", ext]))

    if not plan:
        console.print("[yellow]Nothing to install on this machine.[/]")
        return

    console.print(f"[bold]Plan:[/] {len(plan)} step(s)")
    if not yes and not typer.confirm("Proceed?", default=True):
        raise typer.Exit()

    for label, cmd in plan:
        console.print(f"[cyan]→ {label}[/]")
        subprocess.run(cmd, check=False)

    if profile.get("env_keys"):
        console.print(
            "\n[dim]Env keys captured (values not stored):[/] "
            + ", ".join(profile["env_keys"][:10])
            + (" …" if len(profile["env_keys"]) > 10 else "")
        )
    console.print("[green]✓ Restore complete.[/]")
