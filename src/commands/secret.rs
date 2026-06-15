//! `devctl secret` — per-project encrypted .env vault.
//!
//! The vault is a single file per project at `~/.devctl/vault/<project>.enc`.
//! Key derivation: argon2id(master_password, salt) → 32-byte key; the JSON blob
//! is sealed with XSalsa20-Poly1305 (the same primitive as NaCl's SecretBox).
//!
//! On-disk layout (clean reimplementation — not byte-compatible with the Python
//! PyNaCl version): `salt(16) || nonce(24) || ciphertext`.

use std::collections::BTreeMap;
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use crypto_secretbox::{
    aead::{Aead, KeyInit},
    Key, Nonce, XSalsa20Poly1305,
};

use crate::storage;
use crate::ui;

const SALT_LEN: usize = 16;
const NONCE_LEN: usize = 24;

type Vault = BTreeMap<String, String>;

fn project_name(explicit: Option<String>) -> String {
    explicit.unwrap_or_else(|| {
        std::env::current_dir()
            .ok()
            .and_then(|d| d.file_name().map(|n| n.to_string_lossy().to_string()))
            .unwrap_or_default()
    })
}

fn vault_path(project: &str) -> Result<PathBuf> {
    storage::ensure_dirs()?;
    Ok(storage::vault_dir().join(format!("{project}.enc")))
}

/// Read the master password from the environment or prompt for it.
fn password() -> Result<Vec<u8>> {
    if let Ok(env) = std::env::var("DEVCTL_MASTER_PASSWORD") {
        if !env.is_empty() {
            return Ok(env.into_bytes());
        }
    }
    let pw = rpassword::prompt_password("Master password: ")?;
    Ok(pw.into_bytes())
}

fn derive_key(password: &[u8], salt: &[u8]) -> Result<[u8; 32]> {
    let mut key = [0u8; 32];
    argon2::Argon2::default()
        .hash_password_into(password, salt, &mut key)
        .map_err(|e| anyhow!("key derivation failed: {e}"))?;
    Ok(key)
}

fn load(project: &str, password: &[u8]) -> Result<Vault> {
    let path = vault_path(project)?;
    if !path.exists() {
        return Ok(Vault::new());
    }
    let blob = std::fs::read(&path)?;
    if blob.len() < SALT_LEN + NONCE_LEN {
        return Err(anyhow!("vault file is corrupt"));
    }
    let salt = &blob[..SALT_LEN];
    let nonce = &blob[SALT_LEN..SALT_LEN + NONCE_LEN];
    let ciphertext = &blob[SALT_LEN + NONCE_LEN..];

    let key = derive_key(password, salt)?;
    let cipher = XSalsa20Poly1305::new(Key::from_slice(&key));
    let plaintext = cipher
        .decrypt(Nonce::from_slice(nonce), ciphertext)
        .map_err(|_| anyhow!("Failed to decrypt — wrong password?"))?;
    Ok(serde_json::from_slice(&plaintext)?)
}

fn save(project: &str, password: &[u8], data: &Vault) -> Result<()> {
    let path = vault_path(project)?;
    // Reuse the existing salt so the same password keeps unlocking the vault.
    let mut salt = [0u8; SALT_LEN];
    if path.exists() {
        let existing = std::fs::read(&path)?;
        if existing.len() >= SALT_LEN {
            salt.copy_from_slice(&existing[..SALT_LEN]);
        } else {
            getrandom::getrandom(&mut salt).map_err(|e| anyhow!("randomness failed: {e}"))?;
        }
    } else {
        getrandom::getrandom(&mut salt).map_err(|e| anyhow!("randomness failed: {e}"))?;
    }

    let mut nonce = [0u8; NONCE_LEN];
    getrandom::getrandom(&mut nonce).map_err(|e| anyhow!("randomness failed: {e}"))?;

    let key = derive_key(password, &salt)?;
    let cipher = XSalsa20Poly1305::new(Key::from_slice(&key));
    let plaintext = serde_json::to_vec(data)?;
    let ciphertext = cipher
        .encrypt(Nonce::from_slice(&nonce), plaintext.as_ref())
        .map_err(|e| anyhow!("encryption failed: {e}"))?;

    let mut out = Vec::with_capacity(SALT_LEN + NONCE_LEN + ciphertext.len());
    out.extend_from_slice(&salt);
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&ciphertext);
    std::fs::write(&path, out)?;
    Ok(())
}

/// Load, or print the (styled) error and signal exit-1 to the caller.
fn load_or_report(project: &str, password: &[u8]) -> Result<Option<Vault>> {
    match load(project, password) {
        Ok(v) => Ok(Some(v)),
        Err(e) => {
            println!("{}", ui::red(&e.to_string()));
            Ok(None)
        }
    }
}

pub fn set(key: String, value: String, project: Option<String>) -> Result<i32> {
    let proj = project_name(project);
    let pw = password()?;
    let Some(mut data) = load_or_report(&proj, &pw)? else {
        return Ok(1);
    };
    data.insert(key.clone(), value);
    save(&proj, &pw, &data)?;
    println!(
        "{} Saved {} in vault '{}'",
        ui::green("✓"),
        ui::bold(&key),
        proj
    );
    Ok(0)
}

pub fn get(key: String, project: Option<String>) -> Result<i32> {
    let proj = project_name(project);
    let pw = password()?;
    let Some(data) = load_or_report(&proj, &pw)? else {
        return Ok(1);
    };
    match data.get(&key) {
        Some(v) => {
            // Bare stdout — scripting-friendly.
            println!("{v}");
            Ok(0)
        }
        None => {
            println!(
                "{}",
                ui::red(&format!("No such key '{key}' in vault '{proj}'."))
            );
            Ok(1)
        }
    }
}

pub fn list(project: Option<String>) -> Result<i32> {
    use comfy_table::{presets::UTF8_FULL, Cell, Table};

    let proj = project_name(project);
    let pw = password()?;
    let Some(data) = load_or_report(&proj, &pw)? else {
        return Ok(1);
    };
    if data.is_empty() {
        println!("{}", ui::dim(&format!("Vault '{proj}' is empty.")));
        return Ok(0);
    }
    let mut table = Table::new();
    table.load_preset(UTF8_FULL);
    table.set_header(vec!["Key", "Value"]);
    for (k, v) in &data {
        let masked = "•".repeat(v.chars().count().min(12));
        table.add_row(vec![Cell::new(k), Cell::new(masked)]);
    }
    println!("Vault: {proj}");
    println!("{table}");
    Ok(0)
}

pub fn rm(key: String, project: Option<String>) -> Result<i32> {
    let proj = project_name(project);
    let pw = password()?;
    let Some(mut data) = load_or_report(&proj, &pw)? else {
        return Ok(1);
    };
    if data.remove(&key).is_none() {
        println!("{}", ui::yellow(&format!("No such key '{key}'.")));
        return Ok(0);
    }
    save(&proj, &pw, &data)?;
    println!("{} Removed {}", ui::green("✓"), ui::bold(&key));
    Ok(0)
}
