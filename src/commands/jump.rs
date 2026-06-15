//! `devctl jump` — fuzzy-pick a registered project and print its path.

use anyhow::Result;
use inquire::Select;

use crate::db::{self, Project};
use crate::ui;

pub fn jump(query: Option<String>, print_path: bool) -> Result<i32> {
    let mut projects = db::list_projects()?;
    if projects.is_empty() {
        println!(
            "{} Try `devctl env add <path>`.",
            ui::yellow("No projects registered.")
        );
        return Ok(1);
    }

    if let Some(q) = query.as_deref().filter(|s| !s.is_empty()) {
        let q_lower = q.to_lowercase();
        projects.retain(|p| p.name.to_lowercase().contains(&q_lower));
        if projects.is_empty() {
            println!("{}", ui::red(&format!("No project matches '{q}'.")));
            return Ok(1);
        }
    }

    let chosen = if projects.len() == 1 {
        projects.into_iter().next().unwrap()
    } else {
        match pick(&projects)? {
            Some(p) => p,
            None => return Ok(1),
        }
    };

    db::touch(&chosen.name)?;

    if print_path {
        // Plain stdout so a shell function can do: cd "$(devctl jump --print)"
        println!("{}", chosen.path);
    } else {
        println!("{} {}", ui::green("→"), chosen.path);
    }
    Ok(0)
}

/// Interactive picker (replaces the Python `questionary` menu).
fn pick(projects: &[Project]) -> Result<Option<Project>> {
    let labels: Vec<String> = projects
        .iter()
        .map(|p| format!("{} — {}", p.name, p.path))
        .collect();
    match Select::new("Jump to:", labels).raw_prompt() {
        Ok(choice) => Ok(Some(projects[choice.index].clone())),
        // Cancelled (Esc/Ctrl-C) or no TTY — treat as "no selection".
        Err(_) => Ok(None),
    }
}
