//! devctl — your personal dev-environment manager.
//!
//! A compiled binary has none of Python's per-invocation import latency, so the
//! original's two-tier lazy command loading (`cli.py`) and per-command deferred
//! imports simply don't exist here — one clean clap command tree, plain modules.

mod config;
mod db;
mod storage;
mod ui;
mod util;

mod commands {
    pub mod doctor;
    pub mod env;
    pub mod jump;
    pub mod run;
    pub mod secret;
    pub mod snapshot;
    pub mod sync;
}

use std::path::PathBuf;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(
    name = "devctl",
    version,
    about = "Your personal dev environment manager — dotfiles, projects, snapshots, secrets.",
    arg_required_else_help = true
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Fuzzy-search registered projects and jump to one.
    Jump {
        /// Optional substring to pre-filter.
        query: Option<String>,
        /// Print only the chosen path (for a shell wrapper).
        #[arg(long = "print")]
        print_path: bool,
    },
    /// Manage your project registry.
    Env {
        #[command(subcommand)]
        cmd: EnvCmd,
    },
    /// Run a task defined in a project's devctl.toml.
    Run {
        /// Registered project name. Omit to use the current directory.
        project: Option<String>,
        /// Task to run. Omit to list available tasks.
        task: Option<String>,
        /// Extra args appended to the command (use -- to separate).
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        extra: Vec<String>,
        /// Create a starter devctl.toml in the project root.
        #[arg(long)]
        init: bool,
    },
    /// Diagnose your devctl setup and report any problems.
    Doctor,
    /// Per-project encrypted .env vault.
    Secret {
        #[command(subcommand)]
        cmd: SecretCmd,
    },
    /// Dotfile manager backed by a private Git repo.
    Sync {
        #[command(subcommand)]
        cmd: SyncCmd,
    },
    /// Capture installed packages, extensions, aliases, and env key names.
    Snapshot,
    /// Replay a profile: install packages and VS Code extensions.
    Restore {
        /// Skip confirmation prompts.
        #[arg(short = 'y', long)]
        yes: bool,
    },
    /// Print the devctl version.
    Version,
}

#[derive(Subcommand)]
enum SecretCmd {
    /// Store or update a secret.
    Set {
        key: String,
        value: String,
        #[arg(short = 'p', long)]
        project: Option<String>,
    },
    /// Print a single secret value (plain stdout, scripting-friendly).
    Get {
        key: String,
        #[arg(short = 'p', long)]
        project: Option<String>,
    },
    /// List all keys in the vault (values masked).
    List {
        #[arg(short = 'p', long)]
        project: Option<String>,
    },
    /// Delete a secret.
    Rm {
        key: String,
        #[arg(short = 'p', long)]
        project: Option<String>,
    },
}

#[derive(Subcommand)]
enum SyncCmd {
    /// Initialise the local mirror and set the remote.
    Init { repo_url: String },
    /// Start tracking one or more dotfiles or directories.
    Add { paths: Vec<PathBuf> },
    /// Copy tracked files into the mirror, commit, and push.
    Push {
        #[arg(short = 'm', long = "message", default_value = "devctl sync")]
        message: String,
    },
    /// Pull the remote repo and apply changes back to live dotfile locations.
    Pull,
    /// Diff view: which tracked files are out of sync with the mirror.
    Status,
}

#[derive(Subcommand)]
enum EnvCmd {
    /// Scaffold a new project folder and auto-register it.
    New {
        name: String,
        /// python | node | generic
        #[arg(long, default_value = "generic")]
        lang: String,
        /// Parent directory to create the project in.
        #[arg(long)]
        root: Option<PathBuf>,
    },
    /// Register an existing folder as a project (language auto-detected).
    Add {
        path: PathBuf,
        /// Defaults to folder name.
        #[arg(long)]
        name: Option<String>,
        /// Optional language tag (auto-detected if omitted).
        #[arg(long)]
        lang: Option<String>,
    },
    /// Remove a project from the registry (does NOT delete files).
    Rm { name: String },
    /// List all registered projects, ranked by frecency.
    Ls,
}

fn main() {
    let cli = Cli::parse();
    let result = match cli.command {
        Commands::Jump { query, print_path } => commands::jump::jump(query, print_path),
        Commands::Env { cmd } => match cmd {
            EnvCmd::New { name, lang, root } => commands::env::new(&name, &lang, root),
            EnvCmd::Add { path, name, lang } => commands::env::add(path, name, lang),
            EnvCmd::Rm { name } => commands::env::rm(&name),
            EnvCmd::Ls => commands::env::ls(),
        },
        Commands::Run {
            project,
            task,
            extra,
            init,
        } => commands::run::run(project, task, extra, init),
        Commands::Doctor => commands::doctor::doctor(),
        Commands::Secret { cmd } => match cmd {
            SecretCmd::Set {
                key,
                value,
                project,
            } => commands::secret::set(key, value, project),
            SecretCmd::Get { key, project } => commands::secret::get(key, project),
            SecretCmd::List { project } => commands::secret::list(project),
            SecretCmd::Rm { key, project } => commands::secret::rm(key, project),
        },
        Commands::Sync { cmd } => match cmd {
            SyncCmd::Init { repo_url } => commands::sync::init(repo_url),
            SyncCmd::Add { paths } => commands::sync::add(paths),
            SyncCmd::Push { message } => commands::sync::push(message),
            SyncCmd::Pull => commands::sync::pull(),
            SyncCmd::Status => commands::sync::status(),
        },
        Commands::Snapshot => commands::snapshot::snapshot(),
        Commands::Restore { yes } => commands::snapshot::restore(yes),
        Commands::Version => {
            println!("devctl {}", env!("CARGO_PKG_VERSION"));
            Ok(0)
        }
    };

    match result {
        Ok(code) => std::process::exit(code),
        Err(e) => {
            eprintln!("{}: {e:#}", ui::red("error"));
            std::process::exit(1);
        }
    }
}
