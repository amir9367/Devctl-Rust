//! `devctl sync` — track dotfiles in a private Git repo.
//!
//! Tracked files are copied into `~/.devctl/dotfiles/`, which is a real Git
//! repo; push/pull operate on that repo. Git is invoked as a subprocess (the
//! Rust analogue of GitPython) so it inherits the user's git/SSH configuration.

use std::io::{self, IsTerminal, Write};
use std::path::{Component, Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, Result};

use crate::config;
use crate::storage;
use crate::ui;
use crate::util;

// ── git helpers ─────────────────────────────────────────────────────────────

/// Run `git` in `dir`, returning Ok(stdout) on success or an error carrying
/// git's stderr on failure.
fn git(dir: &Path, args: &[&str]) -> Result<String> {
    let out = Command::new("git")
        .arg("-C")
        .arg(dir)
        .args(args)
        .output()
        .map_err(|e| anyhow!("failed to run git (is it installed?): {e}"))?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        Err(anyhow!("{}", String::from_utf8_lossy(&out.stderr).trim()))
    }
}

/// Map an absolute source path into the dotfiles mirror, preserving layout.
/// Paths under `$HOME` keep their relative layout; anything else is stored
/// under an `abs/` prefix to avoid collisions.
fn mirror_path(src: &Path) -> PathBuf {
    let resolved = util::resolve_path(src);
    if let Some(home) = dirs::home_dir() {
        if let Ok(rel) = resolved.strip_prefix(&home) {
            return storage::dotfiles_dir().join(rel);
        }
    }
    let tail: PathBuf = resolved
        .components()
        .filter(|c| matches!(c, Component::Normal(_)))
        .collect();
    storage::dotfiles_dir().join("abs").join(tail)
}

// ── commands ────────────────────────────────────────────────────────────────

pub fn init(repo_url: String) -> Result<i32> {
    storage::ensure_dirs()?;
    let dir = storage::dotfiles_dir();
    if dir.join(".git").exists() {
        println!("{}", ui::yellow("Dotfiles repo already initialised."));
    } else {
        std::fs::create_dir_all(&dir)?;
        git(&dir, &["init"])?;
        git(&dir, &["remote", "add", "origin", &repo_url])?;
    }
    let mut cfg = config::load()?;
    cfg.sync.repo = repo_url.clone();
    config::save(&cfg)?;
    println!(
        "{} Tracking dotfiles in {} → {}",
        ui::green("✓"),
        dir.display(),
        repo_url
    );
    Ok(0)
}

pub fn add(paths: Vec<PathBuf>) -> Result<i32> {
    let mut cfg = config::load()?;
    let mut tracked: std::collections::BTreeSet<String> =
        cfg.sync.tracked.iter().cloned().collect();
    for p in &paths {
        let absolute = util::resolve_path(p).to_string_lossy().to_string();
        println!("{} {}", ui::green("+"), absolute);
        tracked.insert(absolute);
    }
    cfg.sync.tracked = tracked.into_iter().collect(); // BTreeSet → sorted, deduped
    config::save(&cfg)?;
    Ok(0)
}

pub fn push(message: String) -> Result<i32> {
    let dir = storage::dotfiles_dir();
    materialise(true)?;

    git(&dir, &["add", "-A"])?;
    if git(&dir, &["status", "--porcelain"])?.trim().is_empty() {
        println!("{}", ui::dim("Nothing to commit."));
        return Ok(0);
    }
    git(&dir, &["commit", "-m", &message])?;
    match git(&dir, &["push", "origin", "HEAD:main"]) {
        Ok(_) => println!("{}", ui::green("✓ Pushed")),
        Err(e) => println!("{} {e}", ui::red("Push failed:")),
    }
    Ok(0)
}

pub fn pull() -> Result<i32> {
    let dir = storage::dotfiles_dir();
    if let Err(e) = git(&dir, &["pull", "origin", "main"]) {
        println!("{} {e}", ui::red("Pull failed:"));
        return Ok(1);
    }
    let cfg = config::load()?;
    for src in &cfg.sync.tracked {
        let src_path = PathBuf::from(src);
        let mirror = mirror_path(&src_path);
        if !mirror.exists() {
            continue;
        }
        if src_path.exists() && same(&src_path, &mirror) {
            continue;
        }
        if src_path.exists() && !confirm(&format!("Overwrite local {}?", src_path.display()), false)
        {
            continue;
        }
        if let Some(parent) = src_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        copy(&mirror, &src_path)?;
        println!("{} {}", ui::green("↓"), src_path.display());
    }
    Ok(0)
}

pub fn status() -> Result<i32> {
    use comfy_table::{presets::UTF8_FULL, Cell, Table};

    let cfg = config::load()?;
    let mut table = Table::new();
    table.load_preset(UTF8_FULL);
    table.set_header(vec!["Path", "State"]);
    for src in &cfg.sync.tracked {
        let src_path = PathBuf::from(src);
        let mirror = mirror_path(&src_path);
        let state = if !src_path.exists() {
            "missing locally"
        } else if !mirror.exists() {
            "not mirrored (run push)"
        } else if same(&src_path, &mirror) {
            "in sync"
        } else {
            "changed"
        };
        table.add_row(vec![Cell::new(src), Cell::new(state)]);
    }
    println!("Dotfile sync status");
    println!("{table}");
    Ok(0)
}

// ── helpers ─────────────────────────────────────────────────────────────────

/// Copy each tracked source into the dotfiles mirror.
fn materialise(verbose: bool) -> Result<()> {
    let cfg = config::load()?;
    for src in &cfg.sync.tracked {
        let src_path = PathBuf::from(src);
        if !src_path.exists() {
            if verbose {
                println!("{}", ui::dim(&format!("skip (missing): {src}")));
            }
            continue;
        }
        let dest = mirror_path(&src_path);
        if let Some(parent) = dest.parent() {
            std::fs::create_dir_all(parent)?;
        }
        copy(&src_path, &dest)?;
        if verbose {
            println!("{} {src}", ui::green("↑"));
        }
    }
    Ok(())
}

fn copy(src: &Path, dst: &Path) -> Result<()> {
    if src.is_dir() {
        if dst.exists() {
            std::fs::remove_dir_all(dst)?;
        }
        copy_dir_all(src, dst)?;
    } else {
        if let Some(parent) = dst.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::copy(src, dst)?;
    }
    Ok(())
}

fn copy_dir_all(src: &Path, dst: &Path) -> Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_all(&from, &to)?;
        } else {
            std::fs::copy(&from, &to)?;
        }
    }
    Ok(())
}

/// True if `a` and `b` have identical content (recursively for directories).
fn same(a: &Path, b: &Path) -> bool {
    let (a_dir, b_dir) = (a.is_dir(), b.is_dir());
    if a_dir != b_dir {
        return false;
    }
    if a_dir {
        dirs_equal(a, b)
    } else {
        match (std::fs::read(a), std::fs::read(b)) {
            (Ok(x), Ok(y)) => x == y,
            _ => false,
        }
    }
}

fn dirs_equal(a: &Path, b: &Path) -> bool {
    let mut a_names = entry_names(a);
    let mut b_names = entry_names(b);
    a_names.sort();
    b_names.sort();
    if a_names != b_names {
        return false;
    }
    for name in a_names {
        if !same(&a.join(&name), &b.join(&name)) {
            return false;
        }
    }
    true
}

fn entry_names(dir: &Path) -> Vec<std::ffi::OsString> {
    std::fs::read_dir(dir)
        .map(|rd| rd.flatten().map(|e| e.file_name()).collect())
        .unwrap_or_default()
}

/// Yes/no prompt. Returns `default` when stdin isn't a terminal.
fn confirm(prompt: &str, default: bool) -> bool {
    if !io::stdin().is_terminal() {
        return default;
    }
    print!("{prompt} [{}] ", if default { "Y/n" } else { "y/N" });
    let _ = io::stdout().flush();
    let mut line = String::new();
    if io::stdin().read_line(&mut line).is_err() {
        return default;
    }
    match line.trim().to_lowercase().as_str() {
        "" => default,
        "y" | "yes" => true,
        _ => false,
    }
}
