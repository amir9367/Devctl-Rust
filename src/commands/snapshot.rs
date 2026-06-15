//! `devctl snapshot` and `devctl restore` — portable machine profile.
//!
//! Cross-platform: captures packages from Homebrew, apt, pip and the Windows
//! managers scoop / Chocolatey / winget, plus VS Code extensions, shell aliases
//! (bash/zsh and PowerShell) and env-var *names* (never values).

use std::collections::BTreeMap;
use std::path::Path;
use std::process::Command;

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};

use crate::storage;
use crate::ui;
use crate::util;

#[derive(Serialize, Deserialize, Default)]
struct Profile {
    // Arrays first, then the `packages` table — TOML requires tables last.
    #[serde(default)]
    vscode_extensions: Vec<String>,
    #[serde(default)]
    aliases: Vec<String>,
    #[serde(default)]
    powershell_aliases: Vec<String>,
    #[serde(default)]
    env_keys: Vec<String>,
    #[serde(default)]
    packages: BTreeMap<String, Vec<String>>,
}

/// Run a command and return its stdout, or "" if the binary is missing.
fn run(cmd: &[&str]) -> String {
    match Command::new(cmd[0]).args(&cmd[1..]).output() {
        Ok(out) => String::from_utf8_lossy(&out.stdout).into_owned(),
        Err(_) => String::new(),
    }
}

fn lines(s: &str) -> Vec<String> {
    s.lines()
        .map(|l| l.trim_end())
        .filter(|l| !l.is_empty())
        .map(|l| l.to_string())
        .collect()
}

// ── Package capture (per manager) ───────────────────────────────────────────

fn capture_scoop() -> Vec<String> {
    let raw = run(&["scoop", "export"]);
    let raw = raw.trim();
    if raw.is_empty() {
        return Vec::new();
    }
    // Newer scoop emits JSON from `export`; older emits plain lines.
    if let Ok(value) = serde_json::from_str::<serde_json::Value>(raw) {
        let apps = if value.is_object() {
            value
                .get("apps")
                .cloned()
                .unwrap_or(serde_json::Value::Null)
        } else {
            value
        };
        if let Some(arr) = apps.as_array() {
            return arr
                .iter()
                .filter_map(|a| {
                    if let Some(name) = a.get("Name").and_then(|n| n.as_str()) {
                        Some(name.to_string())
                    } else {
                        a.as_str().map(|s| s.to_string())
                    }
                })
                .filter(|s| !s.is_empty())
                .collect();
        }
    }
    raw.lines()
        .filter_map(|l| l.split_whitespace().next().map(|s| s.to_string()))
        .collect()
}

fn capture_choco() -> Vec<String> {
    run(&["choco", "list", "--local-only", "--limit-output"])
        .lines()
        .filter(|l| l.contains('|'))
        .filter_map(|l| l.split('|').next().map(|s| s.to_string()))
        .collect()
}

fn capture_winget() -> Vec<String> {
    let tmp = std::env::temp_dir().join("devctl-winget-export.json");
    let tmp_str = tmp.to_string_lossy().to_string();
    run(&[
        "winget",
        "export",
        "-o",
        &tmp_str,
        "--accept-source-agreements",
    ]);
    if !tmp.exists() {
        return Vec::new();
    }
    let text = std::fs::read_to_string(&tmp).unwrap_or_default();
    let _ = std::fs::remove_file(&tmp);
    let Ok(data) = serde_json::from_str::<serde_json::Value>(&text) else {
        return Vec::new();
    };
    let mut ids = Vec::new();
    if let Some(sources) = data.get("Sources").and_then(|s| s.as_array()) {
        for source in sources {
            if let Some(pkgs) = source.get("Packages").and_then(|p| p.as_array()) {
                for pkg in pkgs {
                    if let Some(id) = pkg.get("PackageIdentifier").and_then(|i| i.as_str()) {
                        ids.push(id.to_string());
                    }
                }
            }
        }
    }
    ids
}

fn capture_packages() -> BTreeMap<String, Vec<String>> {
    let mut pkgs: BTreeMap<String, Vec<String>> = BTreeMap::new();
    if util::which("brew").is_some() {
        pkgs.insert("brew".into(), lines(&run(&["brew", "leaves"])));
    }
    if util::which("apt").is_some() {
        let raw = run(&["dpkg", "--get-selections"]);
        let names = raw
            .lines()
            .filter_map(|l| l.split_whitespace().next().map(|s| s.to_string()))
            .collect();
        pkgs.insert("apt".into(), names);
    }
    if util::which("scoop").is_some() {
        pkgs.insert("scoop".into(), capture_scoop());
    }
    if util::which("choco").is_some() {
        pkgs.insert("choco".into(), capture_choco());
    }
    if util::which("winget").is_some() {
        pkgs.insert("winget".into(), capture_winget());
    }
    if util::which("pip").is_some() {
        let raw = run(&["pip", "freeze"]);
        let freeze = raw
            .lines()
            .filter(|l| !l.is_empty() && !l.starts_with("-e "))
            .map(|l| l.to_string())
            .collect();
        pkgs.insert("pip".into(), freeze);
    }
    // Drop managers that returned nothing so the profile stays tidy.
    pkgs.retain(|_, v| !v.is_empty());
    pkgs
}

fn capture_vscode() -> Vec<String> {
    if util::which("code").is_none() {
        return Vec::new();
    }
    lines(&run(&["code", "--list-extensions"]))
}

fn capture_aliases() -> Vec<String> {
    let shell = std::env::var("SHELL").unwrap_or_default();
    let base = Path::new(&shell)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();
    let rc = match base.as_str() {
        "zsh" => "~/.zshrc",
        "bash" => "~/.bashrc",
        _ => return Vec::new(),
    };
    let expanded = util::resolve_path(Path::new(rc));
    if !expanded.exists() {
        return Vec::new();
    }
    let cmd = format!("source {} 2>/dev/null; alias", expanded.display());
    run(&[&shell, "-i", "-c", &cmd])
        .lines()
        .filter(|l| l.starts_with("alias ") || l.contains('='))
        .map(|l| l.to_string())
        .collect()
}

fn capture_powershell_aliases() -> Vec<String> {
    let shell = if util::which("pwsh").is_some() {
        "pwsh"
    } else if util::which("powershell").is_some() {
        "powershell"
    } else {
        return Vec::new();
    };
    let script = "Get-Alias | ForEach-Object { \"$($_.Name)=$($_.Definition)\" }";
    run(&[shell, "-Command", script])
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| l.contains('='))
        .collect()
}

fn capture_env_keys() -> Vec<String> {
    let mut keys: Vec<String> = std::env::vars().map(|(k, _)| k).collect();
    keys.sort();
    keys
}

pub fn snapshot() -> Result<i32> {
    storage::ensure_dirs()?;
    eprintln!("{}", ui::dim("Capturing machine profile…"));
    let profile = Profile {
        vscode_extensions: capture_vscode(),
        aliases: capture_aliases(),
        powershell_aliases: capture_powershell_aliases(),
        env_keys: capture_env_keys(),
        packages: capture_packages(),
    };
    let text = toml::to_string(&profile)?;
    std::fs::write(storage::profile_file(), text)?;
    println!(
        "{} Wrote profile → {}",
        ui::green("✓"),
        storage::profile_file().display()
    );
    Ok(0)
}

/// Turn a captured profile into an ordered list of (label, command) steps,
/// skipping managers/tools that aren't present on the current machine.
fn build_plan(profile: &Profile) -> Vec<(String, Vec<String>)> {
    let mut plan: Vec<(String, Vec<String>)> = Vec::new();
    let p = &profile.packages;

    let has = |name: &str| util::which(name).is_some();
    let get = |name: &str| p.get(name).filter(|v| !v.is_empty());

    if let Some(items) = get("brew") {
        if has("brew") {
            let mut cmd = vec!["brew".into(), "install".into()];
            cmd.extend(items.iter().cloned());
            plan.push(("brew".into(), cmd));
        }
    }
    if let Some(items) = get("apt") {
        if has("apt") {
            let mut cmd = vec!["sudo".into(), "apt".into(), "install".into(), "-y".into()];
            cmd.extend(items.iter().cloned());
            plan.push(("apt".into(), cmd));
        }
    }
    if let Some(items) = get("scoop") {
        if has("scoop") {
            let mut cmd = vec!["scoop".into(), "install".into()];
            cmd.extend(items.iter().cloned());
            plan.push(("scoop".into(), cmd));
        }
    }
    if let Some(items) = get("choco") {
        if has("choco") {
            let mut cmd = vec!["choco".into(), "install".into(), "-y".into()];
            cmd.extend(items.iter().cloned());
            plan.push(("choco".into(), cmd));
        }
    }
    if let Some(items) = get("winget") {
        if has("winget") {
            for pid in items {
                plan.push((
                    format!("winget:{pid}"),
                    vec![
                        "winget".into(),
                        "install".into(),
                        "--id".into(),
                        pid.clone(),
                        "-e".into(),
                        "--accept-package-agreements".into(),
                        "--accept-source-agreements".into(),
                    ],
                ));
            }
        }
    }
    if let Some(items) = get("pip") {
        if has("pip") {
            let mut cmd = vec!["pip".into(), "install".into()];
            cmd.extend(items.iter().cloned());
            plan.push(("pip".into(), cmd));
        }
    }
    if !profile.vscode_extensions.is_empty() && has("code") {
        for ext in &profile.vscode_extensions {
            plan.push((
                format!("vscode:{ext}"),
                vec!["code".into(), "--install-extension".into(), ext.clone()],
            ));
        }
    }
    plan
}

pub fn restore(yes: bool) -> Result<i32> {
    let path = storage::profile_file();
    if !path.exists() {
        println!(
            "{} Run snapshot first.",
            ui::red(&format!("No profile at {}.", path.display()))
        );
        return Ok(1);
    }
    let text = std::fs::read_to_string(&path)?;
    let profile: Profile = toml::from_str(&text).map_err(|e| anyhow!("bad profile: {e}"))?;

    let plan = build_plan(&profile);
    if plan.is_empty() {
        println!("{}", ui::yellow("Nothing to install on this machine."));
        return Ok(0);
    }

    println!("{} {} step(s)", ui::bold("Plan:"), plan.len());
    if !yes && !confirm("Proceed?", true) {
        return Ok(0);
    }

    for (label, cmd) in &plan {
        println!("{}", ui::cyan(&format!("→ {label}")));
        let _ = Command::new(&cmd[0]).args(&cmd[1..]).status();
    }

    if !profile.env_keys.is_empty() {
        let shown: Vec<&str> = profile
            .env_keys
            .iter()
            .take(10)
            .map(|s| s.as_str())
            .collect();
        let ellipsis = if profile.env_keys.len() > 10 {
            " …"
        } else {
            ""
        };
        println!(
            "\n{} {}{}",
            ui::dim("Env keys captured (values not stored):"),
            shown.join(", "),
            ellipsis
        );
    }
    println!("{}", ui::green("✓ Restore complete."));
    Ok(0)
}

/// Yes/no prompt; returns `default` when stdin isn't a terminal.
fn confirm(prompt: &str, default: bool) -> bool {
    use std::io::{self, IsTerminal, Write};
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
