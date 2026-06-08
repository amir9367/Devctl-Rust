# devctl — your personal dev-environment manager

[![CI](https://github.com/amir9367/devctl/actions/workflows/ci.yml/badge.svg)](https://github.com/amir9367/devctl/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Coverage](https://img.shields.io/badge/coverage-88%25-brightgreen.svg)](#development)

A single CLI that is the source of truth for your whole dev setup across machines —
projects, dotfiles, machine snapshots, per-project secrets, and task running.
Think of it as a smaller, developer-focused, **personal** Ansible.

## Why

- New-machine setup takes hours of reinstalling, reconfiguring, re-cloning.
- Dotfiles on the laptop and the desktop drift apart.
- You forget which projects exist, where they live, and how to run them.
- Secrets and env vars end up scattered in plaintext everywhere.

`devctl` puts all of that behind one cohesive, cross-platform tool.

## Demo

> _Add an asciinema/GIF here — e.g. `devctl jump` fuzzy-picking a project, then
> `devctl doctor` printing a green health report._
>
> `![devctl demo](docs/demo.gif)`

## Features

| Command | What it does |
|---|---|
| `devctl jump [query]` | Fuzzy-pick a registered project and `cd` into it — ranked by **frecency** (frequency × recency, like zoxide) |
| `devctl env new\|add\|ls\|rm` | Scaffold / register / list / remove projects (language auto-detected on `add`) |
| `devctl run <project> <task>` | Per-project task runner driven by a `devctl.toml` `[tasks]` table |
| `devctl sync init\|add\|push\|pull\|status` | Track dotfiles in a private Git repo and keep machines in sync |
| `devctl snapshot` / `restore` | Capture & rebuild a machine: packages, VS Code extensions, aliases, env-var names |
| `devctl secret set\|get\|list\|rm` | Per-project encrypted `.env` vault (PyNaCl / argon2id) |
| `devctl doctor` | Diagnose your setup: git, registry, stale paths, dotfiles repo, vault, config |

## Install

```bash
pip install -e .
# or, once published:
pip install devctl
```

Requires Python 3.9+. Tested on Linux, macOS, and Windows.

## Quick start

```bash
# Register an existing project (language auto-detected from pyproject.toml etc.)
devctl env add ~/code/my-app

# Or scaffold a new one
devctl env new my-app --lang python

# Jump to any project — frecency-ranked interactive picker
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
├── projects.db           # SQLite project index (WAL mode)
├── profile.toml          # latest machine snapshot
├── dotfiles/             # local clone of your dotfiles repo
└── vault/<project>.enc   # encrypted per-project .env vaults
```

### Frecency ranking

`jump` and `env ls` order projects by a **frecency** score — `use_count` × a
recency weight that decays in buckets (last hour ×4, last day ×2, last week ×0.5,
older ×0.25), the same idea behind zoxide, autojump, and Firefox's address bar.
A monotonic `seq` column breaks ties deterministically even when the system clock
has coarse resolution (Windows `time.time()` is ~16 ms), so ordering is stable.

### Encrypted secrets

Each project's vault is a single `<project>.enc` file: a random argon2id salt
followed by an XSalsa20-Poly1305 (`nacl.SecretBox`) ciphertext of the JSON blob.
The master password comes from `DEVCTL_MASTER_PASSWORD` or an interactive prompt.

### Architecture

```
devctl/
├── cli.py             # entry point; two-tier lazy command loading
├── storage.py         # path resolution under ~/.devctl
├── config.py          # TOML global config
├── db.py              # SQLite registry + frecency scoring
└── commands/
    ├── jump.py        env.py    run.py
    ├── sync.py        secret.py snapshot.py  doctor.py
```

## Performance

Startup latency is the most-felt cost of a CLI, so devctl loads as little as
possible per invocation:

1. **Two-tier lazy command loading.** `cli.py` inspects `sys.argv` *before*
   importing anything heavy and loads only the one command module you invoked.
   `devctl version` never imports `snapshot`, `secret`, or `sync` — so it stays
   around **~270 ms** (mostly Python + Typer startup) instead of paying for every
   subcommand's dependencies.
2. **Deferred heavy imports.** Inside each command, third-party imports (`rich`,
   `nacl`, `GitPython`) happen in the function body, not at module top. Scripting
   paths skip what they don't need — e.g. `secret get` (which prints a bare value)
   avoids the ~45 ms `rich.table` import entirely.
3. **SQLite tuned for a CLI.** The registry connection is opened once per process
   and reused, with `journal_mode=WAL` + `synchronous=NORMAL` so reads never block
   on a concurrent write and commits skip the per-write fsync (safe under WAL).

## Tech stack

- **Typer** — type-safe CLI
- **Rich** — terminal output
- **SQLite** — local project index
- **PyNaCl** — argon2id + SecretBox secret vault
- **GitPython** — dotfile sync
- **tomli / tomli-w** — TOML config

## Development

```bash
pip install -e ".[dev]"
pytest --cov            # 74 tests, ~88% coverage
ruff check .            # lint
```

CI (GitHub Actions) runs ruff plus the full suite on a matrix of Linux, macOS,
and Windows across Python 3.9–3.12.

## License

MIT
