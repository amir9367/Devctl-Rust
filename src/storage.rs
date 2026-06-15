//! Storage paths and shared helpers.
//!
//! Everything devctl writes lives under `~/.devctl/` so the tool is fully
//! self-contained and easy to back up or wipe. The root can be overridden with
//! the `DEVCTL_HOME` environment variable (the test suite relies on this).
//!
//! Unlike the Python version — which resolved these paths once at import time —
//! we resolve them on each call so a per-process `DEVCTL_HOME` is always
//! honoured. That makes the integration tests (which spawn the real binary with
//! a fresh temp `DEVCTL_HOME`) trivially correct.

use std::env;
use std::io;
use std::path::PathBuf;

/// Root directory for all devctl state: `$DEVCTL_HOME` or `~/.devctl`.
pub fn devctl_dir() -> PathBuf {
    if let Some(home) = env::var_os("DEVCTL_HOME") {
        PathBuf::from(home)
    } else {
        dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".devctl")
    }
}

/// Global TOML config (`config.toml`).
pub fn config_file() -> PathBuf {
    devctl_dir().join("config.toml")
}

/// Project registry. The Python version used SQLite (`projects.db`); this
/// reimplementation stores the registry as a plain JSON file instead, keeping
/// the tool dependency-free and pure-Rust.
pub fn projects_db() -> PathBuf {
    devctl_dir().join("projects.json")
}

/// Latest machine snapshot (`profile.toml`).
#[allow(dead_code)] // used by `snapshot`/`restore` (Milestone 2)
pub fn profile_file() -> PathBuf {
    devctl_dir().join("profile.toml")
}

/// Local mirror of the tracked dotfiles git repo.
pub fn dotfiles_dir() -> PathBuf {
    devctl_dir().join("dotfiles")
}

/// Per-project encrypted vaults live here as `<project>.enc`.
pub fn vault_dir() -> PathBuf {
    devctl_dir().join("vault")
}

/// Create the devctl home directory and subfolders on first use.
pub fn ensure_dirs() -> io::Result<()> {
    std::fs::create_dir_all(devctl_dir())?;
    std::fs::create_dir_all(vault_dir())?;
    Ok(())
}
