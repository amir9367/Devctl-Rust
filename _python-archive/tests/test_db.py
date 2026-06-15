"""Tests for the SQLite project registry."""
from __future__ import annotations

import sqlite3

from devctl import db, storage


def test_add_and_get(tmp_path):
    db.add_project("alpha", str(tmp_path), "python")
    rec = db.get_project("alpha")
    assert rec is not None
    assert rec["name"] == "alpha"
    assert rec["lang"] == "python"
    assert rec["path"] == str(tmp_path.resolve())


def test_get_missing_returns_none():
    assert db.get_project("nope") is None


def test_list_orders_by_last_used(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    db.add_project("a", str(a))
    db.add_project("b", str(b))  # added second -> more recent -> first
    names = [p["name"] for p in db.list_projects()]
    assert names[0] == "b"
    db.touch("a")  # now 'a' is most recent
    assert db.list_projects()[0]["name"] == "a"


def test_upsert_updates_path(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    db.add_project("proj", str(first))
    db.add_project("proj", str(second))
    assert db.get_project("proj")["path"] == str(second.resolve())
    assert len(db.list_projects()) == 1


def test_remove(tmp_path):
    db.add_project("gone", str(tmp_path))
    assert db.remove_project("gone") is True
    assert db.get_project("gone") is None
    assert db.remove_project("gone") is False


def test_ordering_is_stable_under_identical_timestamps(tmp_path, monkeypatch):
    """Regression: rapid ops sharing one clock tick must still order correctly.

    On low-resolution clocks (e.g. Windows ~16 ms) several add/touch calls land
    on the same ``time.time()`` value. The monotonic ``seq`` tiebreaker must keep
    most-recently-used-first ordering deterministic regardless.
    """
    monkeypatch.setattr(db.time, "time", lambda: 1000.0)  # freeze the clock

    for name in ("a", "b", "c"):
        d = tmp_path / name
        d.mkdir()
        db.add_project(name, str(d))

    # Most recent insert ('c') first, despite all three sharing a timestamp.
    assert [p["name"] for p in db.list_projects()] == ["c", "b", "a"]

    db.touch("a")  # same frozen timestamp, but newer seq → floats to top
    assert [p["name"] for p in db.list_projects()] == ["a", "c", "b"]


# ── Frecency ──────────────────────────────────────────────────────────────────


def test_frecency_rewards_frequency_and_recency():
    now = 1_000_000.0
    # More uses ranks higher when recency is equal.
    assert db.frecency(10, now, now) > db.frecency(1, now, now)
    # More recent ranks higher when frequency is equal.
    assert db.frecency(1, now, now) > db.frecency(1, now - db._WEEK * 2, now)


def test_use_count_increments_on_touch_and_readd(tmp_path):
    db.add_project("p", str(tmp_path))
    assert db.get_project("p")["use_count"] == 1
    db.touch("p")
    assert db.get_project("p")["use_count"] == 2
    db.add_project("p", str(tmp_path))  # re-registering counts as a use
    assert db.get_project("p")["use_count"] == 3


def test_list_ranks_by_frecency_not_just_recency(tmp_path, monkeypatch):
    """A frequently-used project beats a more-recently-added one-off."""
    monkeypatch.setattr(db.time, "time", lambda: 1000.0)  # equal recency for all
    (tmp_path / "frequent").mkdir()
    (tmp_path / "rare").mkdir()

    db.add_project("frequent", str(tmp_path / "frequent"))
    for _ in range(5):
        db.touch("frequent")
    db.add_project("rare", str(tmp_path / "rare"))  # newest insertion, single use

    names = [p["name"] for p in db.list_projects()]
    assert names[0] == "frequent"  # frequency wins over insertion recency


# ── Schema migration from legacy databases ────────────────────────────────────


def test_migrates_legacy_db_without_last_used():
    """A registry created before last_used/seq/use_count must auto-migrate.

    Regression for `OperationalError: no such column: last_used` seen when
    running against a projects.db from an early devctl version.
    """
    db.reset_connection()
    storage.ensure_dirs()
    # Build a legacy-schema DB: only name + path, like the earliest devctl.
    legacy = sqlite3.connect(storage.PROJECTS_DB)
    legacy.execute("CREATE TABLE projects (name TEXT PRIMARY KEY, path TEXT NOT NULL)")
    legacy.execute("INSERT INTO projects (name, path) VALUES ('old', '/tmp/old')")
    legacy.commit()
    legacy.close()
    db.reset_connection()  # force reopen → triggers the migration

    rows = db.list_projects()
    assert [r["name"] for r in rows] == ["old"]
    assert rows[0]["use_count"] == 1  # backfilled baseline
    # The migrated DB still supports the full API.
    db.touch("old")
    assert db.get_project("old")["use_count"] == 2
