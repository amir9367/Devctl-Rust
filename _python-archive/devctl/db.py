"""Persistent SQLite-backed project registry for devctl.

This is a drop-in replacement for the original db.py.  It keeps the same
public API (`list_projects`, `touch`, `add_project`, `remove_project`,
`get_project`) but makes three performance improvements:

1. Module-level connection reuse
   Opening a SQLite file has overhead (file stat, lock check, page cache
   init).  We open it once per process and reuse the connection object.

2. WAL journal mode
   Write-Ahead Logging lets reads proceed without blocking on a concurrent
   write.  For a CLI tool that may be called from scripts or multiplexers
   that run multiple instances in parallel, this avoids the occasional
   "database is locked" error and speeds up reads.

3. PRAGMA synchronous = NORMAL (instead of FULL)
   The default FULL syncs to disk on every commit.  NORMAL is still safe
   with WAL (you won't get corruption on a crash) but skips the expensive
   fsync on every write.

⚠  If your existing db.py stores data as JSON / TOML rather than SQLite,
   keep your original storage format and apply only the "defer imports"
   pattern from cli.py / jump.py.  The function signatures below are
   inferred from jump.py's usage of db.list_projects() and db.touch().
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import TypedDict

# ── Types ─────────────────────────────────────────────────────────────────────


class Project(TypedDict):
    name: str
    path: str
    lang: str | None
    use_count: int


# ── Frecency scoring ──────────────────────────────────────────────────────────
# "Frecency" = frequency × recency, the ranking behind editor/shell jump tools
# such as zoxide, autojump, and Firefox's address bar.  A project you open often
# AND recently ranks above one you opened once last month.  We use Firefox's
# bucketed recency weights: a recently-touched project gets a large multiplier
# that decays as it ages, multiplied by how many times it has been used.

_HOUR = 3600
_DAY = 86_400
_WEEK = 604_800


def frecency(use_count: int, last_used: float, now: float) -> float:
    """Score a project by frequency × recency (higher = ranks first)."""
    age = now - last_used
    if age < _HOUR:
        weight = 4.0
    elif age < _DAY:
        weight = 2.0
    elif age < _WEEK:
        weight = 0.5
    else:
        weight = 0.25
    return use_count * weight


# ── Connection management ─────────────────────────────────────────────────────

_conn: sqlite3.Connection | None = None


def reset_connection() -> None:
    """Close the cached connection so the next call reopens it.

    Used by the test suite, which points DEVCTL_HOME at a fresh temp dir
    between cases.
    """
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _get_conn() -> sqlite3.Connection:
    """Return the module-level connection, creating it on first call."""
    global _conn
    if _conn is not None:
        return _conn

    # Resolve the DB path through storage so DEVCTL_HOME is honoured and the
    # filename matches what the README documents (~/.devctl/projects.db).
    from .storage import PROJECTS_DB, ensure_dirs

    ensure_dirs()
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row  # allow dict-style row access

    # ── One-time setup pragmas ────────────────────────────────────────────────
    conn.execute("PRAGMA journal_mode=WAL")       # concurrent-friendly
    conn.execute("PRAGMA synchronous=NORMAL")     # safe + faster than FULL
    conn.execute("PRAGMA foreign_keys=ON")

    # ── Schema migration (idempotent) ─────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            name      TEXT NOT NULL PRIMARY KEY,
            path      TEXT NOT NULL,
            lang      TEXT,
            last_used REAL NOT NULL DEFAULT 0,
            seq       INTEGER NOT NULL DEFAULT 0,
            use_count INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    # Backfill older DBs that predate a column.  Each ALTER is guarded so the
    # migration is idempotent and safe to run against a registry created by any
    # earlier devctl version — including ones that predate `last_used`.
    columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()]
    if "lang" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN lang TEXT")
    if "last_used" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN last_used REAL NOT NULL DEFAULT 0")
    if "seq" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
        # Give pre-existing rows distinct, order-preserving seq values so their
        # relative ordering stays stable after the upgrade.
        conn.execute("UPDATE projects SET seq = rowid WHERE seq = 0")
    if "use_count" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN use_count INTEGER NOT NULL DEFAULT 1")
        # Pre-existing rows were registered at least once → baseline of 1.
        conn.execute("UPDATE projects SET use_count = 1 WHERE use_count = 0")

    conn.commit()
    _conn = conn
    return _conn


# ── Public API ────────────────────────────────────────────────────────────────


def _next_seq(conn: sqlite3.Connection) -> int:
    """Return a strictly-increasing ordering token.

    ``last_used`` is wall-clock time, which is great for display but a poor sort
    key: two operations within the same clock tick (common on Windows, whose
    ``time.time()`` resolution is ~16 ms) get identical timestamps, leaving
    ``ORDER BY last_used`` non-deterministic.  ``seq`` is a logical clock that
    increments on every add/touch, so it breaks those ties in true operation
    order.
    """
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM projects").fetchone()
    return int(row[0])


def list_projects() -> list[Project]:
    """Return all registered projects, highest frecency first.

    Ranking is frequency × recency (see :func:`frecency`); ``last_used`` and the
    monotonic ``seq`` break ties deterministically.  The scoring is done in
    Python — the project count is tiny, and it keeps the (testable) ranking
    logic in one place rather than encoded in SQL.
    """
    now = time.time()
    rows = _get_conn().execute(
        "SELECT name, path, lang, last_used, seq, use_count FROM projects "
        "ORDER BY last_used DESC, seq DESC"
    ).fetchall()
    ranked = sorted(
        rows,
        key=lambda r: (frecency(r["use_count"], r["last_used"], now), r["last_used"], r["seq"]),
        reverse=True,
    )
    return [
        {"name": r["name"], "path": r["path"], "lang": r["lang"], "use_count": r["use_count"]}
        for r in ranked
    ]


def get_project(name: str) -> Project | None:
    """Look up a single project by exact name; returns None if not found."""
    row = _get_conn().execute(
        "SELECT name, path, lang, use_count FROM projects WHERE name = ?", (name,)
    ).fetchone()
    return {
        "name": row["name"],
        "path": row["path"],
        "lang": row["lang"],
        "use_count": row["use_count"],
    } if row else None


def add_project(name: str, path: str, lang: str | None = None) -> None:
    """Register a project (upsert).

    A fresh registration starts at ``use_count = 1``; re-registering an existing
    project bumps the count (you interacted with it) and updates its path.
    """
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO projects (name, path, lang, last_used, seq, use_count)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(name) DO UPDATE SET
            path = excluded.path,
            lang = COALESCE(excluded.lang, lang),
            last_used = excluded.last_used,
            seq = excluded.seq,
            use_count = use_count + 1
        """,
        (
            name,
            str(Path(path).expanduser().resolve()),
            lang,
            time.time(),
            _next_seq(conn),
        ),
    )
    conn.commit()


def remove_project(name: str) -> bool:
    """Unregister a project. Returns True if the project existed."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM projects WHERE name = ?", (name,))
    conn.commit()
    return cur.rowcount > 0


def touch(name: str) -> None:
    """Record a use of *name*: bump its frecency (count + recency) to the top."""
    conn = _get_conn()
    conn.execute(
        "UPDATE projects SET last_used = ?, seq = ?, use_count = use_count + 1 WHERE name = ?",
        (time.time(), _next_seq(conn), name),
    )
    conn.commit()