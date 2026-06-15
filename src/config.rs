//! Global devctl config persisted as TOML at `~/.devctl/config.toml`.

use anyhow::Result;
use serde::{Deserialize, Serialize};

use crate::storage;

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct SyncConfig {
    /// Git remote for the dotfiles repo.
    #[serde(default)]
    pub repo: String,
    /// Absolute paths of tracked dotfiles/dirs.
    #[serde(default)]
    pub tracked: Vec<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct Config {
    #[serde(default)]
    pub sync: SyncConfig,
}

/// Load the config, backfilling defaults for any missing keys. A missing file
/// yields the default config (matching the Python behavior).
pub fn load() -> Result<Config> {
    let path = storage::config_file();
    if !path.exists() {
        return Ok(Config::default());
    }
    let text = std::fs::read_to_string(&path)?;
    let cfg: Config = toml::from_str(&text)?;
    Ok(cfg)
}

/// Persist the config as TOML.
#[allow(dead_code)] // used by `sync` (Milestone 2)
pub fn save(cfg: &Config) -> Result<()> {
    storage::ensure_dirs()?;
    let text = toml::to_string(cfg)?;
    std::fs::write(storage::config_file(), text)?;
    Ok(())
}
