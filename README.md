# devctl — Your Personal Dev Environment Manager

A CLI tool that acts as the single source of truth for your entire dev setup across machines.
Think of it as a smarter, developer-focused version of Ansible — but just for you.

## Why

- New machine setup takes hours of reinstalling, reconfiguring, re-cloning.
- Dotfiles on laptop vs desktop drift apart.
- You forget which projects exist, where they live, and how to run them.
- Secrets and env vars are scattered everywhere.

`devctl` fixes all of that with one cohesive tool.

## Features

| Command | What it does |
|---|---|
| `devctl jump` | Fuzzy-search registered projects and `cd` into one instantly |
| `devctl env new <name>` | Scaffold a new project folder and auto-register it |
| `devctl sync push/pull/status` | Push/pull tracked dotfiles to a private Git repo |
| `devctl snapshot` | Capture installed packages, VS Code extensions, aliases, env keys |
| `devctl restore` | Rebuild your environment on a fresh machine from a profile |
| `devctl secret set/get/list` | Per-project encrypted `.env` vault (PyNaCl) |

## Install

```bash
pip install -e .
# or once published:
pip install devctl
```

Requires Python 3.9+.

## Quick start

```bash
# Register an existing project
devctl env add ~/code/my-app

# Or scaffold a new one
devctl env new my-app --lang python

# Jump to any project (interactive fuzzy picker)
devctl jump

# Track your dotfiles
devctl sync init git@github.com:you/dotfiles.git
devctl sync add ~/.zshrc ~/.vimrc ~/.config/nvim
devctl sync push

# Snapshot this machine, restore on another
devctl snapshot           # writes ~/.devctl/profile.toml
devctl restore            # reads it back

# Per-project secret vault
devctl secret set DATABASE_URL "postgres://..."
devctl secret get DATABASE_URL
devctl secret list
```

### Shell integration for `jump`

`devctl jump` prints the chosen path. Add this to your `.zshrc` / `.bashrc`
so it actually changes directory:

```bash
j() {
  local dir
  dir="$(devctl jump --print "$@")" && [ -n "$dir" ] && cd "$dir"
}
```

## Storage layout

Everything lives under `~/.devctl/`:

```
~/.devctl/
├── config.toml           # global config (dotfile repo, tracked paths)
├── projects.db           # SQLite project index
├── profile.toml          # latest snapshot
├── dotfiles/             # local clone of your dotfiles repo
└── vault/<project>.enc   # encrypted per-project .env vaults
```

## Tech stack

- **Typer** — type-safe CLI
- **Rich** — gorgeous terminal output
- **SQLite** — local project index
- **PyNaCl** — secret vault encryption
- **GitPython** — dotfile sync
- **tomli / tomli-w** — TOML config

## Roadmap

- [x] Week 1 — scaffold + `jump`
- [x] Week 2 — `sync` (dotfile manager)
- [x] Week 3 — `snapshot` + `restore`
- [x] Week 4 — `secret` vault + polish
- [ ] Publish to PyPI, tag `v1.0.0`, demo GIF

## License

MIT
