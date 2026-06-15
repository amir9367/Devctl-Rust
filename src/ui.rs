//! Tiny color helpers — the Rust stand-in for the scattered Rich markup in the
//! Python version. Colors auto-disable when stdout isn't a terminal (e.g. piped
//! into a shell wrapper or captured by the test harness), so output stays plain
//! and matchable in those contexts.

use owo_colors::{OwoColorize, Stream};

macro_rules! painter {
    ($name:ident, $method:ident) => {
        #[allow(dead_code)] // some colors are only used by later commands
        pub fn $name(s: &str) -> String {
            format!("{}", s.if_supports_color(Stream::Stdout, |t| t.$method()))
        }
    };
}

painter!(green, green);
painter!(red, red);
painter!(yellow, yellow);
painter!(cyan, cyan);
painter!(magenta, magenta);
painter!(dim, dimmed);
painter!(bold, bold);
