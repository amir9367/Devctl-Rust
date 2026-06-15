//! `devctl doctor` — diagnose the health of your devctl setup.
//!
//! Runs independent checks and prints a tidy report. Exits non-zero if any
//! check is a hard *error* (so it can gate CI/scripts); *warnings* don't fail.

use std::path::Path;

use anyhow::Result;
use comfy_table::{presets::UTF8_FULL, Cell, Table};

use crate::storage;
use crate::ui;
use crate::util;
use crate::{config, db};

#[derive(Clone, Copy, PartialEq)]
enum Status {
    Ok,
    Warn,
    Error,
}

struct Check {
    status: Status,
    label: String,
    detail: String,
}

impl Check {
    fn new(status: Status, label: &str, detail: impl Into<String>) -> Self {
        Check {
            status,
            label: label.to_string(),
            detail: detail.into(),
        }
    }
}

/// Collect health checks. Pure (no printing) so the logic is easy to follow.
fn run_checks() -> Vec<Check> {
    let mut checks: Vec<Check> = Vec::new();

    // ── devctl version ──────────────────────────────────────────────────────
    checks.push(Check::new(Status::Ok, "devctl", env!("CARGO_PKG_VERSION")));

    // ── git (needed for `sync`) ─────────────────────────────────────────────
    match util::which("git") {
        Some(p) => checks.push(Check::new(Status::Ok, "git", p.display().to_string())),
        None => checks.push(Check::new(
            Status::Warn,
            "git",
            "not found — `devctl sync` will not work",
        )),
    }

    // ── devctl home is writable ─────────────────────────────────────────────
    let dir = storage::devctl_dir();
    match write_probe(&dir) {
        Ok(()) => checks.push(Check::new(
            Status::Ok,
            "devctl home",
            dir.display().to_string(),
        )),
        Err(e) => checks.push(Check::new(
            Status::Error,
            "devctl home",
            format!("not writable: {e}"),
        )),
    }

    // ── config parses ───────────────────────────────────────────────────────
    match config::load() {
        Ok(_) => {
            let where_ = if storage::config_file().exists() {
                storage::config_file().display().to_string()
            } else {
                "defaults (no file yet)".to_string()
            };
            checks.push(Check::new(Status::Ok, "config", where_));
        }
        Err(e) => checks.push(Check::new(
            Status::Error,
            "config",
            format!("failed to load: {e}"),
        )),
    }

    // ── project registry + stale paths ──────────────────────────────────────
    match db::list_projects() {
        Err(e) => checks.push(Check::new(
            Status::Error,
            "registry",
            format!("unreadable: {e}"),
        )),
        Ok(projects) => {
            let stale: Vec<&str> = projects
                .iter()
                .filter(|p| !Path::new(&p.path).exists())
                .map(|p| p.name.as_str())
                .collect();
            if projects.is_empty() {
                checks.push(Check::new(
                    Status::Ok,
                    "registry",
                    "no projects registered yet",
                ));
            } else if !stale.is_empty() {
                let mut shown = stale.iter().take(5).copied().collect::<Vec<_>>().join(", ");
                if stale.len() > 5 {
                    shown.push_str(" …");
                }
                checks.push(Check::new(
                    Status::Warn,
                    "registry",
                    format!(
                        "{} project(s); {} stale path(s): {}",
                        projects.len(),
                        stale.len(),
                        shown
                    ),
                ));
            } else {
                checks.push(Check::new(
                    Status::Ok,
                    "registry",
                    format!("{} project(s), all paths exist", projects.len()),
                ));
            }
        }
    }

    // ── dotfiles repo (only if sync was initialised) ────────────────────────
    if let Ok(cfg) = config::load() {
        if !cfg.sync.repo.is_empty() {
            if storage::dotfiles_dir().join(".git").exists() {
                checks.push(Check::new(
                    Status::Ok,
                    "dotfiles repo",
                    storage::dotfiles_dir().display().to_string(),
                ));
            } else {
                checks.push(Check::new(
                    Status::Warn,
                    "dotfiles repo",
                    "configured but mirror missing — run `devctl sync init`",
                ));
            }
        }
    }

    checks
}

fn write_probe(dir: &Path) -> Result<()> {
    std::fs::create_dir_all(dir)?;
    let probe = dir.join(".devctl-write-probe");
    std::fs::write(&probe, "ok")?;
    std::fs::remove_file(&probe)?;
    Ok(())
}

pub fn doctor() -> Result<i32> {
    let checks = run_checks();

    let mut table = Table::new();
    table.load_preset(UTF8_FULL);
    table.set_header(vec!["", "Check", "Detail"]);
    for c in &checks {
        let glyph = match c.status {
            Status::Ok => ui::green("✓"),
            Status::Warn => ui::yellow("!"),
            Status::Error => ui::red("✗"),
        };
        table.add_row(vec![
            Cell::new(glyph),
            Cell::new(&c.label),
            Cell::new(&c.detail),
        ]);
    }
    println!("{table}");

    let errors = checks.iter().filter(|c| c.status == Status::Error).count();
    let warns = checks.iter().filter(|c| c.status == Status::Warn).count();
    if errors > 0 {
        let mut msg = ui::red(&format!("✗ {errors} error(s)"));
        if warns > 0 {
            msg.push_str(&format!(", {}", ui::yellow(&format!("{warns} warning(s)"))));
        }
        println!("{msg}");
        return Ok(1);
    }
    if warns > 0 {
        println!(
            "{} — everything else looks good.",
            ui::yellow(&format!("! {warns} warning(s)"))
        );
    } else {
        println!("{}", ui::green("✓ All checks passed."));
    }
    Ok(0)
}
