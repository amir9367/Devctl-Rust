"""`devctl secret` — per-project encrypted .env vault using PyNaCl.

The vault is a single file per project at ~/.devctl/vault/<project>.enc.
Key derivation: argon2id(master_password, salt) → 32-byte key for SecretBox.

``rich`` is imported inside each command so the scripting-friendly ``secret get``
path (which prints a bare value to stdout) doesn't pay the ~45 ms ``rich.table``
import.  ``nacl`` stays at module level because every command needs it.
"""
from __future__ import annotations

import json
import os
import secrets as _secrets
from pathlib import Path
from typing import Optional

import typer
from nacl import pwhash, secret, utils

from ..storage import VAULT_DIR, ensure_dirs

app = typer.Typer(help="Per-project encrypted .env vault.")

# Salt is stored alongside the ciphertext so the same password unlocks across machines.
_KDF = pwhash.argon2id.kdf
_OPS = pwhash.argon2id.OPSLIMIT_INTERACTIVE
_MEM = pwhash.argon2id.MEMLIMIT_INTERACTIVE


def _project_name(explicit: Optional[str]) -> str:
    """Use --project if given, otherwise the current directory name."""
    return explicit or Path.cwd().name


def _vault_path(project: str) -> Path:
    ensure_dirs()
    return VAULT_DIR / f"{project}.enc"


def _password() -> bytes:
    """Read the master password from env or prompt the user."""
    env = os.environ.get("DEVCTL_MASTER_PASSWORD")
    if env:
        return env.encode()
    pw = typer.prompt("Master password", hide_input=True)
    return pw.encode()


def _load(project: str, password: bytes) -> dict[str, str]:
    path = _vault_path(project)
    if not path.exists():
        return {}
    blob = path.read_bytes()
    salt, ciphertext = blob[:pwhash.argon2id.SALTBYTES], blob[pwhash.argon2id.SALTBYTES:]
    key = _KDF(secret.SecretBox.KEY_SIZE, password, salt, opslimit=_OPS, memlimit=_MEM)
    try:
        plaintext = secret.SecretBox(key).decrypt(ciphertext)
    except Exception:
        from rich.console import Console

        Console().print("[red]Failed to decrypt — wrong password?[/]")
        raise typer.Exit(1)
    return json.loads(plaintext.decode())


def _save(project: str, password: bytes, data: dict[str, str]) -> None:
    path = _vault_path(project)
    # Reuse existing salt so the password doesn't need to re-derive every save.
    if path.exists():
        salt = path.read_bytes()[: pwhash.argon2id.SALTBYTES]
    else:
        salt = _secrets.token_bytes(pwhash.argon2id.SALTBYTES)
    key = _KDF(secret.SecretBox.KEY_SIZE, password, salt, opslimit=_OPS, memlimit=_MEM)
    ciphertext = secret.SecretBox(key).encrypt(
        json.dumps(data).encode(), utils.random(secret.SecretBox.NONCE_SIZE)
    )
    path.write_bytes(salt + ciphertext)


@app.command("set")
def set_(
    key: str,
    value: str,
    project: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Store or update a secret."""
    from rich.console import Console

    console = Console()
    proj = _project_name(project)
    pw = _password()
    data = _load(proj, pw)
    data[key] = value
    _save(proj, pw, data)
    console.print(f"[green]✓[/] Saved [bold]{key}[/] in vault '{proj}'")


@app.command("get")
def get(
    key: str,
    project: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Print a single secret value (plain stdout, scripting-friendly)."""
    proj = _project_name(project)
    data = _load(proj, _password())
    if key not in data:
        from rich.console import Console

        Console().print(f"[red]No such key '{key}' in vault '{proj}'.[/]")
        raise typer.Exit(1)
    print(data[key])


@app.command("list")
def list_(project: Optional[str] = typer.Option(None, "--project", "-p")) -> None:
    """List all keys in the vault (values masked)."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    proj = _project_name(project)
    data = _load(proj, _password())
    if not data:
        console.print(f"[dim]Vault '{proj}' is empty.[/]")
        return
    table = Table(title=f"Vault: {proj}")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="dim")
    for k, v in sorted(data.items()):
        table.add_row(k, "•" * min(len(v), 12))
    console.print(table)


@app.command("rm")
def rm(
    key: str,
    project: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Delete a secret."""
    from rich.console import Console

    console = Console()
    proj = _project_name(project)
    pw = _password()
    data = _load(proj, pw)
    if data.pop(key, None) is None:
        console.print(f"[yellow]No such key '{key}'.[/]")
        return
    _save(proj, pw, data)
    console.print(f"[green]✓[/] Removed [bold]{key}[/]")
