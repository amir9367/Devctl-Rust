//! Integration tests driving the real `devctl` binary with `DEVCTL_HOME`
//! pointed at a throwaway temp dir (the Rust analogue of the Python suite's
//! conftest fixture).

use assert_cmd::Command;
use predicates::prelude::*;
use tempfile::TempDir;

/// A `devctl` command with an isolated `DEVCTL_HOME`.
fn devctl(home: &TempDir) -> Command {
    let mut cmd = Command::cargo_bin("devctl").unwrap();
    cmd.env("DEVCTL_HOME", home.path());
    cmd
}

#[test]
fn version_prints_name_and_number() {
    let home = TempDir::new().unwrap();
    devctl(&home)
        .arg("version")
        .assert()
        .success()
        .stdout(predicate::str::contains("devctl 1.0.0"));
}

#[test]
fn jump_with_no_projects_exits_nonzero() {
    let home = TempDir::new().unwrap();
    devctl(&home)
        .arg("jump")
        .assert()
        .failure()
        .stdout(predicate::str::contains("No projects registered"));
}

#[test]
fn env_add_then_ls_lists_project() {
    let home = TempDir::new().unwrap();
    let proj = TempDir::new().unwrap();
    // Make it look like a python project so lang auto-detect fires.
    std::fs::write(proj.path().join("pyproject.toml"), "[project]\n").unwrap();

    devctl(&home)
        .args([
            "env",
            "add",
            proj.path().to_str().unwrap(),
            "--name",
            "myproj",
        ])
        .assert()
        .success()
        .stdout(predicate::str::contains("Registered").and(predicate::str::contains("myproj")));

    devctl(&home)
        .args(["env", "ls"])
        .assert()
        .success()
        .stdout(predicate::str::contains("myproj").and(predicate::str::contains("python")));
}

#[test]
fn env_rm_unknown_warns_but_succeeds() {
    let home = TempDir::new().unwrap();
    devctl(&home)
        .args(["env", "rm", "ghost"])
        .assert()
        .success()
        .stdout(predicate::str::contains("No project named 'ghost'"));
}

#[test]
fn jump_print_emits_bare_path_for_single_match() {
    let home = TempDir::new().unwrap();
    let proj = TempDir::new().unwrap();
    devctl(&home)
        .args([
            "env",
            "add",
            proj.path().to_str().unwrap(),
            "--name",
            "solo",
        ])
        .assert()
        .success();

    // Exactly one project → auto-picked, --print emits just the path.
    devctl(&home)
        .args(["jump", "solo", "--print"])
        .assert()
        .success()
        .stdout(predicate::str::contains("solo").not()) // bare path, not the label
        .stdout(predicate::str::is_empty().not());
}

#[test]
fn jump_no_match_exits_nonzero() {
    let home = TempDir::new().unwrap();
    let proj = TempDir::new().unwrap();
    devctl(&home)
        .args([
            "env",
            "add",
            proj.path().to_str().unwrap(),
            "--name",
            "alpha",
        ])
        .assert()
        .success();

    devctl(&home)
        .args(["jump", "zzz"])
        .assert()
        .failure()
        .stdout(predicate::str::contains("No project matches 'zzz'"));
}

#[test]
fn run_init_then_list_tasks() {
    let home = TempDir::new().unwrap();
    let proj = TempDir::new().unwrap();

    // Run from inside the project dir (no registered project) and scaffold.
    devctl(&home)
        .current_dir(proj.path())
        .args(["run", "--init"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Wrote starter"));

    assert!(proj.path().join("devctl.toml").exists());

    // No task arg → list the starter task.
    devctl(&home)
        .current_dir(proj.path())
        .arg("run")
        .assert()
        .success()
        .stdout(predicate::str::contains("test"));
}

#[test]
fn run_executes_task_and_propagates_output() {
    let home = TempDir::new().unwrap();
    let proj = TempDir::new().unwrap();
    std::fs::write(
        proj.path().join("devctl.toml"),
        "[tasks]\nhello = \"echo hello-from-task\"\n",
    )
    .unwrap();

    devctl(&home)
        .current_dir(proj.path())
        .args(["run", "", "hello"])
        .assert()
        .success()
        .stdout(predicate::str::contains("hello-from-task"));
}

#[test]
fn doctor_reports_and_succeeds_on_clean_home() {
    let home = TempDir::new().unwrap();
    devctl(&home)
        .arg("doctor")
        .assert()
        .success()
        .stdout(predicate::str::contains("devctl").and(predicate::str::contains("registry")));
}

// ── Milestone 2 ──────────────────────────────────────────────────────────────

/// A `devctl` command with isolated `DEVCTL_HOME` and a fixed master password
/// (so the vault is non-interactive in tests).
fn devctl_secret(home: &TempDir) -> Command {
    let mut cmd = devctl(home);
    cmd.env("DEVCTL_MASTER_PASSWORD", "test-password");
    cmd
}

#[test]
fn secret_set_get_roundtrip() {
    let home = TempDir::new().unwrap();
    devctl_secret(&home)
        .args([
            "secret",
            "set",
            "DATABASE_URL",
            "postgres://x",
            "-p",
            "demo",
        ])
        .assert()
        .success()
        .stdout(predicate::str::contains("Saved"));

    devctl_secret(&home)
        .args(["secret", "get", "DATABASE_URL", "-p", "demo"])
        .assert()
        .success()
        .stdout(predicate::str::contains("postgres://x"));
}

#[test]
fn secret_get_missing_key_exits_nonzero() {
    let home = TempDir::new().unwrap();
    devctl_secret(&home)
        .args(["secret", "set", "A", "1", "-p", "demo"])
        .assert()
        .success();
    devctl_secret(&home)
        .args(["secret", "get", "NOPE", "-p", "demo"])
        .assert()
        .failure()
        .stdout(predicate::str::contains("No such key"));
}

#[test]
fn secret_wrong_password_fails_to_decrypt() {
    let home = TempDir::new().unwrap();
    devctl_secret(&home)
        .args(["secret", "set", "A", "1", "-p", "demo"])
        .assert()
        .success();
    // Different password → decryption must fail.
    devctl(&home)
        .env("DEVCTL_MASTER_PASSWORD", "wrong-password")
        .args(["secret", "get", "A", "-p", "demo"])
        .assert()
        .failure()
        .stdout(predicate::str::contains("Failed to decrypt"));
}

#[test]
fn secret_list_masks_values() {
    let home = TempDir::new().unwrap();
    devctl_secret(&home)
        .args(["secret", "set", "TOKEN", "supersecret", "-p", "demo"])
        .assert()
        .success();
    devctl_secret(&home)
        .args(["secret", "list", "-p", "demo"])
        .assert()
        .success()
        .stdout(
            predicate::str::contains("TOKEN").and(predicate::str::contains("supersecret").not()),
        );
}

#[test]
fn secret_rm_removes_key() {
    let home = TempDir::new().unwrap();
    devctl_secret(&home)
        .args(["secret", "set", "A", "1", "-p", "demo"])
        .assert()
        .success();
    devctl_secret(&home)
        .args(["secret", "rm", "A", "-p", "demo"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Removed"));
    devctl_secret(&home)
        .args(["secret", "get", "A", "-p", "demo"])
        .assert()
        .failure();
}

#[test]
fn sync_status_empty_when_nothing_tracked() {
    let home = TempDir::new().unwrap();
    devctl(&home)
        .args(["sync", "status"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Dotfile sync status"));
}

#[test]
fn sync_add_then_status_shows_tracked_file() {
    let home = TempDir::new().unwrap();
    let dir = TempDir::new().unwrap();
    let file = dir.path().join("rcfile");
    std::fs::write(&file, "hello").unwrap();

    devctl(&home)
        .args(["sync", "add", file.to_str().unwrap()])
        .assert()
        .success()
        .stdout(predicate::str::contains("rcfile"));

    // Not pushed yet → "not mirrored".
    devctl(&home)
        .args(["sync", "status"])
        .assert()
        .success()
        .stdout(predicate::str::contains("not mirrored"));
}

#[test]
fn restore_without_profile_exits_nonzero() {
    let home = TempDir::new().unwrap();
    devctl(&home)
        .args(["restore", "-y"])
        .assert()
        .failure()
        .stdout(predicate::str::contains("No profile"));
}
