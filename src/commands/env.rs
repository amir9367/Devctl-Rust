//! `devctl env` — scaffold and register projects in the local index.

use std::path::PathBuf;

use anyhow::Result;
use comfy_table::{presets::UTF8_FULL, Cell, Table};

use crate::db;
use crate::ui;
use crate::util;

/// Minimal language-specific scaffolds — kept small on purpose. Each entry is
/// `(relative_path, template)`; `{name}` is substituted in both.
fn scaffolds(lang: &str) -> Option<Vec<(&'static str, &'static str)>> {
    match lang {
        "python" => Some(vec![
            ("README.md", "# {name}\n"),
            (
                "pyproject.toml",
                "[project]\nname = \"{name}\"\nversion = \"0.1.0\"\n",
            ),
            ("src/{name}/__init__.py", ""),
            (".gitignore", "__pycache__/\n.venv/\n*.pyc\n"),
        ]),
        "node" => Some(vec![
            ("README.md", "# {name}\n"),
            (
                "package.json",
                "{\n  \"name\": \"{name}\",\n  \"version\": \"0.1.0\"\n}\n",
            ),
            (".gitignore", "node_modules/\n.env\n"),
        ]),
        "generic" => Some(vec![("README.md", "# {name}\n"), (".gitignore", ".env\n")]),
        _ => None,
    }
}

/// Files that, if present in a directory, reveal its language.
const LANG_MARKERS: &[(&str, &str)] = &[
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("requirements.txt", "python"),
    ("package.json", "node"),
    ("Cargo.toml", "rust"),
    ("go.mod", "go"),
];

fn detect_lang(path: &std::path::Path) -> Option<String> {
    for (marker, lang) in LANG_MARKERS {
        if path.join(marker).exists() {
            return Some((*lang).to_string());
        }
    }
    None
}

pub fn new(name: &str, lang: &str, root: Option<PathBuf>) -> Result<i32> {
    let Some(files) = scaffolds(lang) else {
        println!(
            "{} Choose: python, node, generic",
            ui::red(&format!("Unknown lang '{lang}'."))
        );
        return Ok(1);
    };

    let root = match root {
        Some(r) => r,
        None => std::env::current_dir()?,
    };
    let project_path = root.join(name);
    if project_path.exists() {
        println!(
            "{}",
            ui::red(&format!("{} already exists.", project_path.display()))
        );
        return Ok(1);
    }

    for (rel, template) in files {
        let rel = rel.replace("{name}", name);
        let file_path = project_path.join(&rel);
        if let Some(parent) = file_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&file_path, template.replace("{name}", name))?;
    }

    let project_path = util::resolve_path(&project_path);
    db::add_project(
        name,
        &project_path.to_string_lossy(),
        Some(lang.to_string()),
    )?;
    println!(
        "{} Created and registered {} at {}",
        ui::green("✓"),
        ui::bold(name),
        project_path.display()
    );
    Ok(0)
}

pub fn add(path: PathBuf, name: Option<String>, lang: Option<String>) -> Result<i32> {
    let path = util::resolve_path(&path);
    if !path.is_dir() {
        println!(
            "{}",
            ui::red(&format!("{} is not a directory.", path.display()))
        );
        return Ok(1);
    }
    let resolved_lang = lang.or_else(|| detect_lang(&path));
    let proj_name = name.unwrap_or_else(|| {
        path.file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default()
    });
    db::add_project(&proj_name, &path.to_string_lossy(), resolved_lang.clone())?;
    let tag = match &resolved_lang {
        Some(l) => format!(" {}", ui::magenta(&format!("({l})"))),
        None => String::new(),
    };
    println!(
        "{} Registered {}{}",
        ui::green("✓"),
        ui::bold(&proj_name),
        tag
    );
    Ok(0)
}

pub fn rm(name: &str) -> Result<i32> {
    if db::remove_project(name)? {
        println!("{} Removed {}", ui::green("✓"), ui::bold(name));
    } else {
        println!("{}", ui::yellow(&format!("No project named '{name}'.")));
    }
    Ok(0)
}

pub fn ls() -> Result<i32> {
    let rows = db::list_projects()?;
    if rows.is_empty() {
        println!("{}", ui::dim("No projects yet."));
        return Ok(0);
    }
    let mut table = Table::new();
    table.load_preset(UTF8_FULL);
    table.set_header(vec!["Name", "Lang", "Uses", "Path"]);
    for r in &rows {
        table.add_row(vec![
            Cell::new(&r.name),
            Cell::new(r.lang.as_deref().unwrap_or("-")),
            Cell::new(r.use_count),
            Cell::new(&r.path),
        ]);
    }
    println!("{table}");
    Ok(0)
}
