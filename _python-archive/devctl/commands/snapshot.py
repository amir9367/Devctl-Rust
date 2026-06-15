"""`devctl snapshot` and `devctl restore` — portable machine profile.

Cross-platform: captures packages from Homebrew, apt, pip **and** the Windows
managers scoop / Chocolatey / winget, plus VS Code extensions, shell aliases
(bash/zsh and PowerShell) and env-var *names* (never values).

``rich`` and ``tomli_w`` are imported inside the command bodies so importing
this module costs only the stdlib + ``typer``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import typer

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ..storage import PROFILE_FILE, ensure_dirs

app = typer.Typer(help="Capture and restore your machine's dev environment.")


def _run(cmd: list[str]) -> str:
    """Run a shell command and return stdout, or '' if the binary is missing."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return out.stdout
    except FileNotFoundError:
        return ""


# ── Package capture (per manager) ──────────────────────────────────────────────


def _capture_scoop() -> list[str]:
    """Scoop app names. Newer scoop emits JSON from `export`; older emits lines."""
    raw = _run(["scoop", "export"]).strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        apps = data.get("apps", []) if isinstance(data, dict) else data
        return [a.get("Name", "") if isinstance(a, dict) else str(a) for a in apps if a]
    except ValueError:
        # Plain-text fallback: first whitespace-delimited token per line.
        return [line.split()[0] for line in raw.splitlines() if line.strip()]


def _capture_choco() -> list[str]:
    """Chocolatey package ids via the machine-readable `--limit-output` format."""
    raw = _run(["choco", "list", "--local-only", "--limit-output"])
    return [line.split("|")[0] for line in raw.splitlines() if "|" in line]


def _capture_winget() -> list[str]:
    """winget package identifiers. `winget export` only writes a file, so we
    export to a temp file, read it back, and clean up."""
    tmp = Path(tempfile.gettempdir()) / "devctl-winget-export.json"
    _run(["winget", "export", "-o", str(tmp), "--accept-source-agreements"])
    if not tmp.exists():
        return []
    try:
        data = json.loads(tmp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    finally:
        tmp.unlink(missing_ok=True)
    ids: list[str] = []
    for source in data.get("Sources", []):
        for pkg in source.get("Packages", []):
            pid = pkg.get("PackageIdentifier")
            if pid:
                ids.append(pid)
    return ids


def _capture_packages() -> dict[str, list[str]]:
    """Capture installed packages from every package manager on this machine."""
    pkgs: dict[str, list[str]] = {}
    if shutil.which("brew"):
        pkgs["brew"] = _run(["brew", "leaves"]).split()
    if shutil.which("apt"):
        # `apt list --installed` is human-formatted; dpkg is parseable.
        raw = _run(["dpkg", "--get-selections"])
        pkgs["apt"] = [line.split()[0] for line in raw.splitlines() if line.strip()]
    if shutil.which("scoop"):
        pkgs["scoop"] = _capture_scoop()
    if shutil.which("choco"):
        pkgs["choco"] = _capture_choco()
    if shutil.which("winget"):
        pkgs["winget"] = _capture_winget()
    if shutil.which("pip"):
        raw = _run([sys.executable, "-m", "pip", "freeze"])
        pkgs["pip"] = [
            line for line in raw.splitlines() if line and not line.startswith("-e ")
        ]
    # Drop managers that returned nothing so the profile stays tidy.
    return {k: v for k, v in pkgs.items() if v}


def _capture_vscode() -> list[str]:
    if not shutil.which("code"):
        return []
    return [line for line in _run(["code", "--list-extensions"]).splitlines() if line]


def _capture_aliases() -> list[str]:
    """Read bash/zsh aliases by sourcing the user's shell rc and running `alias`."""
    shell = os.environ.get("SHELL", "")
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc"}.get(os.path.basename(shell), "")
    if not rc:
        return []
    expanded = os.path.expanduser(rc)
    if not os.path.exists(expanded):
        return []
    raw = _run([shell, "-i", "-c", f"source {expanded} 2>/dev/null; alias"])
    return [line for line in raw.splitlines() if line.startswith("alias ") or "=" in line]


def _capture_powershell_aliases() -> list[str]:
    """PowerShell aliases as ``name=definition`` lines (profile loaded)."""
    shell = "pwsh" if shutil.which("pwsh") else ("powershell" if shutil.which("powershell") else "")
    if not shell:
        return []
    raw = _run([shell, "-Command", "Get-Alias | ForEach-Object { \"$($_.Name)=$($_.Definition)\" }"])
    return [line.strip() for line in raw.splitlines() if "=" in line]


def _capture_env_keys() -> list[str]:
    """Only key names — never values — so the profile is safe to commit."""
    return sorted(os.environ.keys())


@app.command("snapshot")
def snapshot() -> None:
    """Capture installed packages, VS Code extensions, aliases, env key names."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    import tomli_w

    ensure_dirs()
    profile: dict[str, Any] = {}
    steps = [
        ("packages", _capture_packages),
        ("vscode_extensions", _capture_vscode),
        ("aliases", _capture_aliases),
        ("powershell_aliases", _capture_powershell_aliases),
        ("env_keys", _capture_env_keys),
    ]
    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as progress:
        for key, fn in steps:
            task = progress.add_task(f"Capturing {key}…", total=None)
            profile[key] = fn()
            progress.remove_task(task)

    with PROFILE_FILE.open("wb") as f:
        tomli_w.dump(profile, f)
    Console().print(f"[green]✓[/] Wrote profile → {PROFILE_FILE}")


def _build_plan(profile: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Turn a captured profile into an ordered list of (label, command) steps,
    skipping managers/tools that aren't present on the current machine."""
    plan: list[tuple[str, list[str]]] = []
    pkgs = profile.get("packages", {})
    if pkgs.get("brew") and shutil.which("brew"):
        plan.append(("brew", ["brew", "install", *pkgs["brew"]]))
    if pkgs.get("apt") and shutil.which("apt"):
        plan.append(("apt", ["sudo", "apt", "install", "-y", *pkgs["apt"]]))
    if pkgs.get("scoop") and shutil.which("scoop"):
        plan.append(("scoop", ["scoop", "install", *pkgs["scoop"]]))
    if pkgs.get("choco") and shutil.which("choco"):
        plan.append(("choco", ["choco", "install", "-y", *pkgs["choco"]]))
    if pkgs.get("winget") and shutil.which("winget"):
        for pid in pkgs["winget"]:
            plan.append((
                f"winget:{pid}",
                ["winget", "install", "--id", pid, "-e",
                 "--accept-package-agreements", "--accept-source-agreements"],
            ))
    if pkgs.get("pip"):
        plan.append(("pip", [sys.executable, "-m", "pip", "install", *pkgs["pip"]]))
    if profile.get("vscode_extensions") and shutil.which("code"):
        for ext in profile["vscode_extensions"]:
            plan.append((f"vscode:{ext}", ["code", "--install-extension", ext]))
    return plan


@app.command("restore")
def restore(
    yes: bool = typer.Option(False, "-y", help="Skip confirmation prompts."),
) -> None:
    """Replay a profile: install packages and VS Code extensions."""
    from rich.console import Console

    console = Console()
    if not PROFILE_FILE.exists():
        console.print(f"[red]No profile at {PROFILE_FILE}.[/] Run snapshot first.")
        raise typer.Exit(1)
    with PROFILE_FILE.open("rb") as f:
        profile = tomllib.load(f)

    plan = _build_plan(profile)
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
