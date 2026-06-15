//! Persistent project registry with frecency ranking.
//!
//! The Python original used SQLite (WAL mode, a monotonic `seq` tie-breaker).
//! This reimplementation keeps the *same observable behavior* — frecency
//! scoring, upsert semantics, deterministic ordering via `seq` — but stores the
//! registry as a single JSON file (`projects.json`). For a tiny, single-writer,
//! per-user index that keeps the whole tool pure-Rust with no native deps.

use std::cmp::Ordering;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::Result;
use serde::{Deserialize, Serialize};

use crate::storage;
use crate::util;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Project {
    pub name: String,
    pub path: String,
    #[serde(default)]
    pub lang: Option<String>,
    #[serde(default)]
    pub last_used: f64,
    #[serde(default)]
    pub seq: i64,
    #[serde(default = "default_use_count")]
    pub use_count: i64,
}

fn default_use_count() -> i64 {
    1
}

#[derive(Serialize, Deserialize, Default)]
struct Registry {
    projects: Vec<Project>,
}

// ── Frecency scoring ────────────────────────────────────────────────────────
// "Frecency" = frequency × recency, the ranking behind editor/shell jump tools
// such as zoxide, autojump, and Firefox's address bar. We use Firefox's
// bucketed recency weights: a recently-touched project gets a large multiplier
// that decays as it ages, multiplied by how many times it has been used.

const HOUR: f64 = 3_600.0;
const DAY: f64 = 86_400.0;
const WEEK: f64 = 604_800.0;

/// Score a project by frequency × recency (higher = ranks first).
pub fn frecency(use_count: i64, last_used: f64, now: f64) -> f64 {
    let age = now - last_used;
    let weight = if age < HOUR {
        4.0
    } else if age < DAY {
        2.0
    } else if age < WEEK {
        0.5
    } else {
        0.25
    };
    use_count as f64 * weight
}

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

// ── Persistence ─────────────────────────────────────────────────────────────

/// Load the registry, returning an empty one if the file is missing.
/// Fails only when the file exists but cannot be read/parsed (used by `doctor`
/// to surface a corrupt registry).
fn load() -> Result<Registry> {
    let path = storage::projects_db();
    if !path.exists() {
        return Ok(Registry::default());
    }
    let text = std::fs::read_to_string(&path)?;
    if text.trim().is_empty() {
        return Ok(Registry::default());
    }
    Ok(serde_json::from_str(&text)?)
}

fn save(reg: &Registry) -> Result<()> {
    storage::ensure_dirs()?;
    let text = serde_json::to_string_pretty(reg)?;
    std::fs::write(storage::projects_db(), text)?;
    Ok(())
}

fn next_seq(reg: &Registry) -> i64 {
    reg.projects.iter().map(|p| p.seq).max().unwrap_or(0) + 1
}

// ── Public API ──────────────────────────────────────────────────────────────

/// Return all registered projects, highest frecency first. `last_used` and the
/// monotonic `seq` break ties deterministically.
pub fn list_projects() -> Result<Vec<Project>> {
    let reg = load()?;
    let now = now();
    let mut projects = reg.projects;
    projects.sort_by(|a, b| {
        let fa = frecency(a.use_count, a.last_used, now);
        let fb = frecency(b.use_count, b.last_used, now);
        fb.partial_cmp(&fa)
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                b.last_used
                    .partial_cmp(&a.last_used)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| b.seq.cmp(&a.seq))
    });
    Ok(projects)
}

/// Look up a single project by exact name.
pub fn get_project(name: &str) -> Result<Option<Project>> {
    let reg = load()?;
    Ok(reg.projects.into_iter().find(|p| p.name == name))
}

/// Register a project (upsert). A fresh registration starts at `use_count = 1`;
/// re-registering bumps the count, refreshes recency, and updates the path. A
/// new `lang` overrides the old one, but `None` keeps the existing tag
/// (the `COALESCE` in the original SQL).
pub fn add_project(name: &str, path: &str, lang: Option<String>) -> Result<()> {
    let mut reg = load()?;
    let resolved = util::resolve_path(Path::new(path))
        .to_string_lossy()
        .to_string();
    let seq = next_seq(&reg);
    let now = now();

    if let Some(p) = reg.projects.iter_mut().find(|p| p.name == name) {
        p.path = resolved;
        if lang.is_some() {
            p.lang = lang;
        }
        p.last_used = now;
        p.seq = seq;
        p.use_count += 1;
    } else {
        reg.projects.push(Project {
            name: name.to_string(),
            path: resolved,
            lang,
            last_used: now,
            seq,
            use_count: 1,
        });
    }
    save(&reg)
}

/// Unregister a project. Returns true if the project existed.
pub fn remove_project(name: &str) -> Result<bool> {
    let mut reg = load()?;
    let before = reg.projects.len();
    reg.projects.retain(|p| p.name != name);
    let removed = reg.projects.len() != before;
    if removed {
        save(&reg)?;
    }
    Ok(removed)
}

/// Record a use of `name`: bump its frecency (count + recency) to the top.
pub fn touch(name: &str) -> Result<()> {
    let mut reg = load()?;
    let seq = next_seq(&reg);
    let now = now();
    if let Some(p) = reg.projects.iter_mut().find(|p| p.name == name) {
        p.last_used = now;
        p.seq = seq;
        p.use_count += 1;
        save(&reg)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frecency_buckets() {
        let now = 1_000_000.0;
        // < 1 hour → ×4
        assert_eq!(frecency(2, now - 60.0, now), 8.0);
        // < 1 day → ×2
        assert_eq!(frecency(2, now - 2.0 * HOUR, now), 4.0);
        // < 1 week → ×0.5
        assert_eq!(frecency(2, now - 2.0 * DAY, now), 1.0);
        // older → ×0.25
        assert_eq!(frecency(2, now - 2.0 * WEEK, now), 0.5);
    }

    #[test]
    fn frecency_prefers_recent_over_frequent() {
        let now = 1_000_000.0;
        // Used once an hour ago (4.0) beats used 5× a month ago (1.25).
        let recent = frecency(1, now - 60.0, now);
        let frequent = frecency(5, now - 30.0 * DAY, now);
        assert!(recent > frequent);
    }
}
