"""SQLite-backed project index used by `devctl jump` and `devctl env`."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .storage import PROJECTS_DB, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    path        TEXT NOT NULL UNIQUE,
    lang        TEXT,
    last_opened REAL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(PROJECTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_project(name: str, path: Path, lang: Optional[str] = None) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO projects(name, path, lang, last_opened) "
            "VALUES (?, ?, ?, ?)",
            (name, str(path.resolve()), lang, None),
        )


def remove_project(name: str) -> int:
    with connect() as c:
        cur = c.execute("DELETE FROM projects WHERE name = ?", (name,))
        return cur.rowcount


def list_projects() -> list[sqlite3.Row]:
    with connect() as c:
        return list(
            c.execute(
                "SELECT * FROM projects "
                "ORDER BY COALESCE(last_opened, 0) DESC, name ASC"
            )
        )


def touch(name: str) -> None:
    """Bump last_opened so frequently-used projects float to the top."""
    with connect() as c:
        c.execute(
            "UPDATE projects SET last_opened = ? WHERE name = ?",
            (time.time(), name),
        )
