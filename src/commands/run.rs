//! `devctl run` — per-project task runner.
//!
//! Tasks live in a `devctl.toml` at the project root:
//!
//! ```toml
//! [tasks]
//! test = "pytest -q"
//! dev  = "uvicorn app:main --reload"
//! ```

use std::path::PathBuf;
use std::process::Command;

use anyhow::Result;
use comfy_table::{presets::UTF8_FULL, Cell, Table};

use crate::db;
use crate::ui;

const STARTER_TOML: &str = "\
# devctl tasks - run with `devctl run <project> <task>`
[tasks]
test = \"echo replace me with your test command\"
";

pub fn run(
    project: Option<String>,
    task: Option<String>,
    extra: Vec<String>,
    init: bool,
) -> Result<i32> {
    let project = project.filter(|s| !s.is_empty());
    let task = task.filter(|s| !s.is_empty());

    // ── Resolve the project directory ──────────────────────────────────────
    let (proj_name, proj_dir) = match &project {
        Some(name) => match db::get_project(name)? {
            Some(record) => (record.name, PathBuf::from(record.path)),
            None => {
                println!(
                    "{} Run {} to see projects.",
                    ui::red(&format!("No registered project named '{name}'.")),
                    ui::bold("devctl env ls")
                );
                return Ok(1);
            }
        },
        None => {
            let cwd = std::env::current_dir()?;
            let name = cwd
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            (name, cwd)
        }
    };

    let toml_path = proj_dir.join("devctl.toml");

    // ── --init: scaffold and stop ──────────────────────────────────────────
    if init {
        if toml_path.exists() {
            println!(
                "{}",
                ui::yellow(&format!("{} already exists.", toml_path.display()))
            );
            return Ok(1);
        }
        std::fs::create_dir_all(&proj_dir)?;
        std::fs::write(&toml_path, STARTER_TOML)?;
        println!(
            "{} Wrote starter {}",
            ui::green("OK"),
            ui::bold(&toml_path.display().to_string())
        );
        return Ok(0);
    }

    // ── Load tasks ──────────────────────────────────────────────────────────
    if !toml_path.exists() {
        let hint = match &project {
            Some(p) => format!("devctl run {p} --init"),
            None => "devctl run --init".to_string(),
        };
        println!(
            "{} Create one with {}.",
            ui::red(&format!("No devctl.toml in {}.", proj_dir.display())),
            ui::bold(&hint)
        );
        return Ok(1);
    }

    let text = std::fs::read_to_string(&toml_path)?;
    let value: toml::Value = toml::from_str(&text)?;
    let tasks = value.get("tasks").and_then(|t| t.as_table());
    let tasks = match tasks {
        Some(t) if !t.is_empty() => t,
        _ => {
            println!(
                "{}",
                ui::yellow(&format!("No [tasks] defined in {}.", toml_path.display()))
            );
            return Ok(1);
        }
    };

    // ── No task → list ──────────────────────────────────────────────────────
    let Some(task) = task else {
        let mut table = Table::new();
        table.load_preset(UTF8_FULL);
        table.set_header(vec!["Task", "Command"]);
        for (name, cmd) in tasks {
            table.add_row(vec![Cell::new(name), Cell::new(value_to_string(cmd))]);
        }
        println!("Tasks for {proj_name}");
        println!("{table}");
        return Ok(0);
    };

    // ── Run the task ────────────────────────────────────────────────────────
    let Some(cmd_value) = tasks.get(&task) else {
        let available: Vec<&str> = tasks.keys().map(|s| s.as_str()).collect();
        println!(
            "{} Available: {}",
            ui::red(&format!("No task '{task}' in {}.", toml_path.display())),
            available.join(", ")
        );
        return Ok(1);
    };

    let mut command = value_to_string(cmd_value);
    if !extra.is_empty() {
        command.push(' ');
        command.push_str(&extra.join(" "));
    }

    println!("{}", ui::dim(&format!("> {command}")));
    let status = if cfg!(windows) {
        Command::new("cmd")
            .arg("/C")
            .arg(&command)
            .current_dir(&proj_dir)
            .status()?
    } else {
        Command::new("sh")
            .arg("-c")
            .arg(&command)
            .current_dir(&proj_dir)
            .status()?
    };
    Ok(status.code().unwrap_or(1))
}

/// Render a TOML scalar the way Python's `str(cmd)` would for display/exec.
fn value_to_string(v: &toml::Value) -> String {
    match v {
        toml::Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}
