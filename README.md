# devctl (Rust) — your personal dev-environment manager

A single CLI that is the source of truth for your whole dev setup across machines —
projects, dotfiles, machine snapshots, per-project secrets, and task running.
Think of it as a smaller, developer-focused, **personal** Ansible.

This is a from-scratch **Rust** rewrite of the original Python `devctl`. It keeps the
same command surface and behavior, but ships as a single self-contained binary with
no interpreter and no per-invocation import cost.

## Features

| Command | What it does |
|---|---|
| `devctl jump [query]` | Fuzzy-pick a registered project and print its path — ranked by **frecency** (frequency × recency, like zoxide) |
| `devctl env new\|add\|rm\|ls` | Scaffold / register / remove / list projects (language auto-detected on `add`) |
| `devctl run <project> <task>` | Per-project task runner driven by a `devctl.toml` `[tasks]` table |
| `devctl sync init\|add\|push\|pull\|status` | Track dotfiles in a private Git repo and keep machines in sync |
| `devctl snapshot` / `restore` | Capture & rebuild a machine: packages, VS Code extensions, aliases, env-var names |
| `devctl secret set\|get\|list\|rm` | Per-project encrypted `.env` vault (argon2id + XSalsa20-Poly1305) |
| `devctl doctor` | Diagnose your setup: git, registry, stale paths, dotfiles repo, config |

## Install

```bash
cargo install --path .
# or build a release binary directly:
cargo build --release   # → target/release/devctl
```

Requires a stable Rust toolchain. Tested on Linux, macOS, and Windows.

## Quick start

```bash
# Register an existing project (language auto-detected from Cargo.toml etc.)
devctl env add ~/code/my-app

# Or scaffold a new one
devctl env new my-app --lang python

# Jump to any project — frecency-ranked picker
devctl jump

# Define and run per-project tasks (devctl.toml [tasks])
devctl run my-app --init
devctl run my-app test

# Track your dotfiles
devctl sync init git@github.com:you/dotfiles.git
devctl sync add ~/.zshrc ~/.gitconfig
devctl sync push

# Snapshot this machine, restore on another (cross-platform)
devctl snapshot           # writes ~/.devctl/profile.toml
devctl restore            # replays it

# Per-project secret vault
devctl secret set DATABASE_URL "postgres://..."
devctl secret get DATABASE_URL

# Health check
devctl doctor
```

### Shell integration for `jump`

`devctl jump --print` writes the chosen path to stdout. Add this to your
`.zshrc` / `.bashrc` so it actually changes directory:

```bash
j() {
  local dir
  dir="$(devctl jump --print "$@")" && [ -n "$dir" ] && cd "$dir"
}
```

## How it works

### Storage layout

Everything lives under `~/.devctl/` (override with `DEVCTL_HOME`), so the tool is
self-contained and easy to back up or wipe:

```
~/.devctl/
├── config.toml           # global config (dotfile repo, tracked paths)
├── projects.json         # project index + frecency data
├── profile.toml          # latest machine snapshot
├── dotfiles/             # local clone of your dotfiles repo
└── vault/<project>.enc   # encrypted per-project .env vaults
```

> **Note:** the Python version stored the registry in SQLite (`projects.db`). This
> Rust rewrite uses a plain JSON file (`projects.json`) with the identical frecency
> logic — keeping the tool pure-Rust with no native dependencies. The two formats
> are not interchangeable; this is a clean reimplementation, not a drop-in for
> existing `~/.devctl` data.

### Frecency ranking

`jump` and `env ls` order projects by a **frecency** score — `use_count` × a
recency weight that decays in buckets (last hour ×4, last day ×2, last week ×0.5,
older ×0.25), the same idea behind zoxide, autojump, and Firefox's address bar.
A monotonic `seq` field breaks ties deterministically so ordering is stable.

### Encrypted secrets

Each project's vault is a single `<project>.enc` file: `salt(16) || nonce(24) ||
ciphertext`. The 32-byte key is derived with **argon2id** from the master password
and the stored salt; the JSON blob is sealed with **XSalsa20-Poly1305**. The master
password comes from `DEVCTL_MASTER_PASSWORD` or an interactive prompt.

## Tech stack

- **clap** — type-safe CLI parsing
- **comfy-table** + **owo-colors** — terminal tables and color
- **inquire** — interactive fuzzy picker
- **serde / serde_json / toml** — config, registry, and profile serialization
- **argon2** + **crypto_secretbox** — argon2id KDF + XSalsa20-Poly1305 vault
- **git** (subprocess) — dotfile sync, inheriting your git/SSH config

## Development

```bash
cargo test                       # unit + integration tests
cargo clippy --all-targets       # lint
cargo fmt --all -- --check       # formatting
```

CI (GitHub Actions) runs fmt + clippy plus the full suite on Linux, macOS, and Windows.

### Building on Windows

The MSVC target needs the Visual Studio C++ build tools + Windows SDK (for the
linker). On a machine with limited free space, building with reduced parallelism
(`cargo build -j 2`) avoids `STATUS_COMMITMENT_LIMIT` (out-of-virtual-memory) errors
when the page file can't grow.

## License

MIT
