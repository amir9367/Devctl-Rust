"""Tests for the encrypted secret vault."""
from __future__ import annotations

from devctl.commands import secret


def _pw() -> bytes:
    return b"test-password"  # matches DEVCTL_MASTER_PASSWORD in conftest


def test_set_and_load_roundtrip():
    secret._save("proj", _pw(), {"API_KEY": "abc123"})
    data = secret._load("proj", _pw())
    assert data == {"API_KEY": "abc123"}


def test_update_existing_reuses_salt():
    from nacl import pwhash

    saltbytes = pwhash.argon2id.SALTBYTES
    secret._save("proj", _pw(), {"A": "1"})
    salt_before = secret._vault_path("proj").read_bytes()[:saltbytes]
    secret._save("proj", _pw(), {"A": "1", "B": "2"})
    salt_after = secret._vault_path("proj").read_bytes()[:saltbytes]
    assert salt_before == salt_after
    assert secret._load("proj", _pw()) == {"A": "1", "B": "2"}


def test_load_missing_vault_is_empty():
    assert secret._load("never-created", _pw()) == {}


def test_wrong_password_fails():
    import typer

    secret._save("proj", _pw(), {"SECRET": "x"})
    try:
        secret._load("proj", b"wrong-password")
    except typer.Exit as exc:
        assert exc.exit_code == 1
    else:
        raise AssertionError("decryption with wrong password should fail")


# ── CLI-surface tests (password supplied via DEVCTL_MASTER_PASSWORD) ───────────


def test_cli_set_then_get(runner, cli_app):
    set_res = runner.invoke(cli_app, ["secret", "set", "API_KEY", "abc123", "-p", "proj"])
    assert set_res.exit_code == 0, set_res.output

    get_res = runner.invoke(cli_app, ["secret", "get", "API_KEY", "-p", "proj"])
    assert get_res.exit_code == 0, get_res.output
    assert "abc123" in get_res.output


def test_cli_get_missing_key_fails(runner, cli_app):
    runner.invoke(cli_app, ["secret", "set", "A", "1", "-p", "proj"])
    res = runner.invoke(cli_app, ["secret", "get", "MISSING", "-p", "proj"])
    assert res.exit_code == 1


def test_cli_list_masks_values(runner, cli_app):
    runner.invoke(cli_app, ["secret", "set", "TOKEN", "supersecret", "-p", "proj"])
    res = runner.invoke(cli_app, ["secret", "list", "-p", "proj"])
    assert res.exit_code == 0, res.output
    assert "TOKEN" in res.output
    assert "supersecret" not in res.output  # value must be masked


def test_cli_list_empty_vault(runner, cli_app):
    res = runner.invoke(cli_app, ["secret", "list", "-p", "empty"])
    assert res.exit_code == 0
    assert "empty" in res.output


def test_cli_rm(runner, cli_app):
    runner.invoke(cli_app, ["secret", "set", "GONE", "x", "-p", "proj"])
    rm_res = runner.invoke(cli_app, ["secret", "rm", "GONE", "-p", "proj"])
    assert rm_res.exit_code == 0, rm_res.output

    get_res = runner.invoke(cli_app, ["secret", "get", "GONE", "-p", "proj"])
    assert get_res.exit_code == 1


def test_cli_rm_missing_is_graceful(runner, cli_app):
    res = runner.invoke(cli_app, ["secret", "rm", "NEVER", "-p", "proj"])
    assert res.exit_code == 0
    assert "No such key" in res.output
