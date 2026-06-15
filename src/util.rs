//! Small cross-cutting helpers: PATH lookup and path resolution.

use std::env;
use std::path::{Path, PathBuf};

/// Locate an executable on `PATH`, mirroring `shutil.which`. On Windows we also
/// try the usual executable extensions so `which("git")` finds `git.exe`.
pub fn which(name: &str) -> Option<PathBuf> {
    let exts: &[&str] = if cfg!(windows) {
        &["", ".exe", ".cmd", ".bat", ".com"]
    } else {
        &[""]
    };
    let path = env::var_os("PATH")?;
    for dir in env::split_paths(&path) {
        for ext in exts {
            let candidate = dir.join(format!("{name}{ext}"));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

/// Expand a leading `~` to the user's home directory.
fn expanduser(p: &Path) -> PathBuf {
    let s = p.to_string_lossy();
    if let Some(rest) = s.strip_prefix("~/").or_else(|| s.strip_prefix("~\\")) {
        if let Some(home) = dirs::home_dir() {
            return home.join(rest);
        }
    } else if s == "~" {
        if let Some(home) = dirs::home_dir() {
            return home;
        }
    }
    p.to_path_buf()
}

#[cfg(windows)]
fn strip_unc(p: PathBuf) -> PathBuf {
    let s = p.to_string_lossy();
    if let Some(rest) = s.strip_prefix(r"\\?\") {
        return PathBuf::from(rest);
    }
    p
}

#[cfg(not(windows))]
fn strip_unc(p: PathBuf) -> PathBuf {
    p
}

/// Expand `~`, then make absolute and canonical — the Rust analogue of
/// `Path(path).expanduser().resolve()`. If the path doesn't exist yet (so
/// `canonicalize` would fail), fall back to a best-effort absolute path.
pub fn resolve_path(p: &Path) -> PathBuf {
    let expanded = expanduser(p);
    match std::fs::canonicalize(&expanded) {
        Ok(c) => strip_unc(c),
        Err(_) => {
            if expanded.is_absolute() {
                expanded
            } else {
                env::current_dir()
                    .map(|d| d.join(&expanded))
                    .unwrap_or(expanded)
            }
        }
    }
}
